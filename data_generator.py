# data_generator.py  —— Socket.IO 版本
import time
import json
import random
import sqlite3
import socketio  # pip install "python-socketio[client]"

DB_PATH = "metro.db"
SIO_URL = "http://127.0.0.1:5000"

sio = socketio.Client(reconnection=True, reconnection_attempts=999)

def get_stations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT station_id, name, latitude, longitude FROM stations ORDER BY station_id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@sio.event
def connect():
    print("✅ connected to Socket.IO server")

@sio.event
def disconnect():
    print("❌ disconnected from Socket.IO server")

def run_train(train_id, stations):
    """简单来回跑两两相邻站：每 2–5 秒推一次进度"""
    idx = random.randint(0, max(0, len(stations) - 2))
    direction = 1
    while True:
        origin = stations[idx]
        dest   = stations[idx + direction]

        # 0.0 → 1.0 分 10 步（可调）
        for step in range(11):
            progress = step / 10
            data = {
                "type": "train_update",         # 前端也兼容 train_tick
                "train_id": train_id,
                "from": origin["name"],        # 注意：Socket.IO 前端会转成 origin/dest 使用
                "to": dest["name"],
                "progress": float(progress),
                "timestamp": time.time()
            }
            try:
                sio.emit("train_update", data)  # 直接发事件给服务端
                print(f"📡 {train_id}: {origin['name']} → {dest['name']} {int(progress*100)}%")
            except Exception as e:
                print("⚠️ emit failed:", e)

            time.sleep(random.randint(2, 5))   # 每 2–5 秒一次

        # 到头换向
        idx += direction
        if idx <= 0 or idx >= len(stations) - 2:
            direction *= -1

def main():
    stations = get_stations()
    if len(stations) < 2:
        print("⚠️ 站点不足，请先初始化数据库")
        return

    # 连接到 Socket.IO 服务器
    sio.connect(SIO_URL)

    # 启动多列车
    try:
        run_train("GEN-1", stations)
        # 如需多列车，可开多个线程或进程分别调用 run_train("GEN-2", ...)
    finally:
        sio.disconnect()

if __name__ == "__main__":
    main()
