import argparse
import socket
import threading
import time

MAX_MSG_SIZE = 65536
PUNCH_MESSAGE = b"THIS_IS_A_UNIQUE_MESSAGE_5348y2dhjkg"

def punch_and_monitor(ext_sock, relay_addr, session, state, punch_timeout=5.0):
    print("Registering with relay...")

    # blast register packets short term to create NAT mapping
    for _ in range(6):
        send_register(ext_sock, relay_addr, session)
        time.sleep(0.5)

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

    if state.get('direct_ok'):
        print("Holepunch established!")
        state['connected'] = True
    else:
        print("Holepunch failed ∑:{")
        exit(0)

def packet_loop(ext_sock, relay_addr, session, state):
    # Listen for messages
    while True:
        data, addr = ext_sock.recvfrom(MAX_MSG_SIZE)
        print("GOT", addr, data)
        # We might receive raw forwarded payloads or control messages from relay
        if addr == relay_addr:
            t = data.decode(errors="ignore").strip().split()
            if len(t) >= 3 and t[0] == "PEER":
                peer_ip = t[1]; peer_port = int(t[2])
                print(f"[client] received remote_peer {peer_ip}:{peer_port}")
                state['remote_peer'] = (peer_ip, peer_port)
            else:
                # ignore other control messages
                pass
        elif addr == state.get("remote_peer"):
            # Transfer to local_peer
            if data != PUNCH_MESSAGE:
                ext_sock.sendto(data, ('127.0.0.1', state['local_peer']))
        elif addr[0].startswith("127."):
            # Local to remote_peer
            state["local_peer"] = addr
            
            ext_sock.sendto(data, ('127.0.0.1', state['remote_peer']))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--relay", required=True)
    p.add_argument("--relay-port", type=int, default=50000)
    p.add_argument("--session", required=True)
    p.add_argument("--external-port", type=int, required=True)
    p.add_argument("--local-default", type=int)
    args = p.parse_args()

    relay_addr = (args.relay, args.relay_port)
    session = args.session
    

    # External socket bound to the port used for NAT mapping/hole punching
    ext_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ext_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        ext_sock.bind(('', args.external_port))
    except Exception as e:
        print(f"Failed to bind external port {args.external_port}: {e}")
        return

    state = {
        'local_peer': None if not args.local_default else ("127.0.0.1", args.local_default),
        'remote_peer': None,
        'connected': False
    }

    ext_sock.sendto(f"REGISTER {session}\n".encode(), relay_addr)
    
    # Background thread for receiving packets
    threading.Thread(
        target=packet_loop,
        args=(ext_sock, relay_addr, session, state),
        daemon=True
    ).start()
    
    
    punch_and_monitor(ext_sock, relay_addr, session, state, punch_timeout=5.0)

    # Start local->remote forwarder (stays same)
    threading.Thread(
        target=local_to_remote_loop,
        args=(local_sock, ext_sock, relay_addr, session, state),
        daemon=True
    ).start()

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
        print("bye!")


if __name__ == "__main__":
    main()
