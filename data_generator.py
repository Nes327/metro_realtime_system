# data_generator.py
import json
import random
import time
from websocket import create_connection

WS_URL = "ws://127.0.0.1:5000/ws"

# Demo route segments (you can change these to any stations or a longer loop)
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
    # Connect to WebSocket (/ws exposed by Flask backend)
    print(f"[generator] connecting to {WS_URL} ...")
    ws = create_connection(WS_URL)
    print("[generator] connected.")

    train_id = f"Train-{int(time.time())}"
    print(f"[generator] simulate {train_id}")

    try:
        # Ping-pong loop (forward/backward)
        forward = True
        idx = 0
        progress = 0.0
        while True:
            if forward:
                origin, dest = ROUTE[idx]
            else:
                origin, dest = ROUTE[len(ROUTE) - 1 - idx][1], ROUTE[len(ROUTE) - 1 - idx][0]

            # Within a segment, move from 0->1 with random step every 2–5 seconds
            step = random.uniform(0.15, 0.35)
            progress += step
            if progress >= 1.0:
                progress = 1.0

            payload = {
                "type": "train_update",   # recognized and broadcast by the backend
                "train_id": train_id,
                "from": origin,
                "to": dest,
                # No lat/lng here; if stations table has latitude/longitude,
                # the frontend will render markers/polyline using those.
                "progress": progress
            }
            ws.send(json.dumps(payload))
            print("[generator] sent:", payload)

            if progress >= 1.0:
                # Move to next segment
                progress = 0.0
                idx += 1
                if idx >= len(ROUTE):
                    idx = 0
                    forward = not forward

            # Send every 2–5 seconds
            time.sleep(random.uniform(2.0, 5.0))
    finally:
        ws.close()

if __name__ == "__main__":
    main()
