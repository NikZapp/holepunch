import argparse
import socket
import threading
import time
#import rudp

MAX_MSG_SIZE = 65536
PUNCH_MESSAGE = b"THIS_IS_A_UNIQUE_MESSAGE_5348y2dhjkg"

def punch_and_monitor(ext_sock, relay_addr, session, state, punch_timeout=5.0):
    print("Registering with relay...")

    # blast register packets short term to create NAT mapping
    for _ in range(6):
        ext_sock.sendto(f"REGISTER {session}\n".encode(), relay_addr)
        time.sleep(0.1)

    # Wait for peer info
    print("Waiting for peer info from relay...")
    wait_deadline = time.time() + 15.0
    while time.time() < wait_deadline and not state.get('remote_peer'):
        time.sleep(0.2)

    if not state.get('remote_peer'):
        print("Remote peer not found.")
        exit(0)

    peer = state["remote_peer"]
    print(f"Peer discovered: {peer}")

    # Try punching
    print("Hole punching attempt...")
    punch_deadline = time.time() + punch_timeout
    while time.time() < punch_deadline:# and not state.get('connected'):
        try:
            ext_sock.sendto(PUNCH_MESSAGE, peer)
        except:
            pass
        time.sleep(0.1)

    if state.get('connected'):
        print("Holepunch established!")
    else:
        print("Holepunch failed ∑:{")
        exit(0)

def packet_loop(ext_sock, tcp_sock, relay_addr, session, state):
    # Listen for messages
    while True:
        data, addr = ext_sock.recvfrom(MAX_MSG_SIZE)
        #print("GOT", addr, data)
        # We might receive raw forwarded payloads or control messages from relay
        if addr == relay_addr:
            t = data.decode(errors="ignore").strip().split()
            if len(t) >= 3 and t[0] == "PEER":
                peer_ip = t[1]; peer_port = int(t[2])
                #print(f"[client] received remote_peer {peer_ip}:{peer_port}")
                state['remote_peer'] = (peer_ip, peer_port)
            else:
                # ignore other control messages
                pass
        elif addr == state.get("remote_peer"):
            # Transfer to local_peer
            if data != PUNCH_MESSAGE:
                print("GOT", addr, data)
                if state.get("tcp"):
                    if "tcp_conn" in state:
                        state["tcp_conn"].sendto(data, state['local_peer'])
                    else:
                        print("Trying to send response to TCP socket, but its not alive")
                else:
                    ext_sock.sendto(data, state['local_peer'])
            else:
                state['connected'] = True
        elif addr[0].startswith("127."):
            print("OUT", addr, data)
            # Local to remote_peer
            state["local_peer"] = addr
            
            ext_sock.sendto(data, state['remote_peer'])


# A --> B
# a on
# create tcp socket
# listen, send stuff to B
# b on
# create tcp socket
# connect to local peer!
# tcp:listen, send stuff to A
def tcp_bridge(ext_sock, tcp_sock, state):
    if "tcp_conn" not in state:
        print("TCP socket not connected, accepting a connection...")
        conn, addr = tcp_sock.accept()
        state["tcp_conn"] = conn
        state["local_peer"] = addr
        print("TCP socket got a connection!")
    try:
        while True:
            try:
                data = state["tcp_conn"].recv(MAX_MSG_SIZE)
                if data:
                    print("TCP", data)
                    ext_sock.sendto(data, state['remote_peer'])
            except BlockingIOError:
                time.sleep(0.01)
    except OSError as e:
        print(e)
        print("Socket closed, exiting thread")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--relay", required=True)
    p.add_argument("--relay-port", type=int, default=50000)
    p.add_argument("--session", required=True)
    p.add_argument("--external-port", type=int, required=True)
    p.add_argument("--local-default", type=int)
    p.add_argument("--tcp", action="store_true")
    args = p.parse_args()

    relay_addr = (args.relay, args.relay_port)
    session = args.session
    

    # External socket bound to the port used for NAT mapping/hole punching
    ext_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ext_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        ext_sock.bind(('0.0.0.0', args.external_port))
    except Exception as e:
        print(f"Failed to bind external port {args.external_port}: {e}")
        return
    
    state = {
        'local_peer': None if not args.local_default else ("127.0.0.1", args.local_default),
        'remote_peer': None,
        'connected': False,
        'tcp': args.tcp
    }

    tcp_sock = None
    if args.tcp:
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_sock.bind(("0.0.0.0", args.external_port))
        tcp_sock.listen()
        if args.local_default:
            print("Connecting to default TCP socket")
            local_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            local_conn.connect(("127.0.0.1", args.local_default))
            print("Connected!")
            state["tcp_conn"] = local_conn
    
    
    # Background thread for receiving packets
    threading.Thread(
        target=packet_loop,
        args=(ext_sock, tcp_sock, relay_addr, session, state),
        daemon=True
    ).start()
    
    if args.tcp:
        threading.Thread(
            target=tcp_bridge,
            args=(ext_sock, tcp_sock, state),
            daemon=True
        ).start()
    
    
    punch_and_monitor(ext_sock, relay_addr, session, state, punch_timeout=5.0)

    print("[client] running. Ctrl+C to quit.")
    try:
        while True:
            # Keep NAT mapping + relay aware
            ext_sock.sendto(f"REGISTER {session}\n".encode(), relay_addr)

            # Only send PUNCH if peer known
            remote_peer = state.get('remote_peer')
            if remote_peer:
                try:
                    ext_sock.sendto(PUNCH_MESSAGE, remote_peer)
                except:
                    pass

            time.sleep(1.0)
    except KeyboardInterrupt:
        if args.tcp:
            print("Closing tcp")
            tcp_sock.shutdown(socket.SHUT_RDWR)
            tcp_sock.close()
        print("bye!")


if __name__ == "__main__":
    main()
