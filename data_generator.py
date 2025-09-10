# data_generator.py
import json
import random
import time
from websocket import create_connection

WS_URL = "ws://127.0.0.1:5000/ws"

# 你可以改成任意两个站，或循环更多站。这里为了演示简单取 KLCC ↔ Cochrane
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
    # 连接 WebSocket（你的 Flask 后端 realtime.py 暴露的 /ws）
    print(f"[generator] connecting to {WS_URL} ...")
    ws = create_connection(WS_URL)
    print("[generator] connected.")

    train_id = f"Train-{int(time.time())}"
    print(f"[generator] simulate {train_id}")

    try:
        # 循环往返
        forward = True
        idx = 0
        progress = 0.0
        while True:
            if forward:
                origin, dest = ROUTE[idx]
            else:
                origin, dest = ROUTE[len(ROUTE) - 1 - idx][1], ROUTE[len(ROUTE) - 1 - idx][0]

            # 每个区段内，从 0~1 慢慢前进，步长随机（2~5秒一次）
            step = random.uniform(0.15, 0.35)
            progress += step
            if progress >= 1.0:
                progress = 1.0

            payload = {
                "type": "train_update",   # 后端会识别并广播
                "train_id": train_id,
                "from": origin,
                "to": dest,
                # 这里没有用经纬度，因为你的 CSV 暂时没有坐标。
                # 如果你后续在 stations 表里补了 latitude/longitude，
                # 前端会用它们绘制 marker 和 polyline。
                "progress": progress
            }
            ws.send(json.dumps(payload))
            print("[generator] sent:", payload)

            if progress >= 1.0:
                # 切到下一个区段
                progress = 0.0
                idx += 1
                if idx >= len(ROUTE):
                    idx = 0
                    forward = not forward

            # 每 2~5 秒发一次
            time.sleep(random.uniform(2.0, 5.0))
    finally:
        ws.close()

if __name__ == "__main__":
    main()
