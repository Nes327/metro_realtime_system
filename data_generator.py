import json
import random
import time
from websocket import create_connection

WS_URL = "ws://127.0.0.1:5000/ws"

# Demo route station sequence
ROUTE = [
    ("KLCC", "Kampung Baru"),
    ("Kampung Baru", "Dang Wangi"),
    ("Dang Wangi", "Masjid Jamek (KJL)"),
    ("Masjid Jamek (KJL)", "Pasar Seni (SBK)"),
    ("Pasar Seni (SBK)", "Merdeka"),
    ("Merdeka", "Bukit Bintang"),
    ("Bukit Bintang", "Tun Razak Exchange (TRX)"),
    ("Tun Razak Exchange (TRX)", "Cochrane"),
]

def main():
    print(f"[generator] connecting to {WS_URL} ...")
    ws = create_connection(WS_URL)
    print("[generator] connected.")

    # Generate a train ID
    train_id = f"Train-{int(time.time())}"
    print(f"[generator] simulate {train_id}")

    try:
        # start moving
        forward = True
        idx = 0
        progress = 0.0
        while True:
            # Decide the direction to move
            if forward:
                origin, dest = ROUTE[idx]
            else:
                origin, dest = ROUTE[len(ROUTE) - 1 - idx][1], ROUTE[len(ROUTE) - 1 - idx][0]

            # Progress increases in random steps
            step = random.uniform(0.15, 0.35)
            progress += step
            if progress >= 1.0:
                progress = 1.0

            # Build message for WebSocket
            payload = {
                "type": "train_update",
                "train_id": train_id,
                "from": origin,
                "to": dest,
                "progress": progress
            }
            ws.send(json.dumps(payload))
            print("[generator] sent:", payload)

            # If segment is complete, move to next
            if progress >= 1.0:
                progress = 0.0
                idx += 1
                if idx >= len(ROUTE):
                    idx = 0
                    forward = not forward 

            # Update every 2–5 seconds
            time.sleep(random.uniform(2.0, 5.0))
    finally:
        ws.close()

if __name__ == "__main__":
    main()
