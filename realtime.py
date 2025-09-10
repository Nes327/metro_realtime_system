# realtime.py
import time
import threading
from flask_socketio import SocketIO, emit

socketio = SocketIO()   # 用这个替代 Sock

# ========== 模拟列车逻辑 ==========
_trains = {}  # train_id -> thread 控制

def start_train(train_id, path_names, per_edge_seconds, loop=True, ping_interval=1.0):
    """后台线程，逐段发送进度"""
    if train_id in _trains:
        return

    def run():
        try:
            while True:
                for i in range(len(path_names) - 1):
                    origin = path_names[i]
                    dest = path_names[i+1]
                    sec = per_edge_seconds[i]
                    steps = int(sec / ping_interval)
                    for step in range(steps + 1):
                        progress = step / max(1, steps)
                        msg = {
                            "type": "train_tick",
                            "train_id": train_id,
                            "origin": origin,
                            "dest": dest,
                            "progress": progress,
                            "timestamp": time.time()
                        }
                        socketio.emit("train_update", msg)  # 广播
                        time.sleep(ping_interval)
                if not loop:
                    break
        finally:
            _trains.pop(train_id, None)

    t = threading.Thread(target=run, daemon=True)
    _trains[train_id] = t
    t.start()

def stop_train(train_id):
    # 简单处理：目前只能等线程自己退出
    return _trains.pop(train_id, None) is not None

def list_trains():
    return list(_trains.keys())

# ========== 初始化 ==========
def init_realtime(app):
    socketio.init_app(app, cors_allowed_origins="*")
    return socketio
