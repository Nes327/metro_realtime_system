# realtime.py
import threading
import time
import json
from typing import List, Optional, Dict, Tuple
from flask_sock import Sock

sock = Sock()

# 已连接的 WebSocket 客户端
clients = set()

# 运行中的模拟列车：train_id -> (thread, stop_event)
running_trains: Dict[str, Tuple[threading.Thread, threading.Event]] = {}

def init_realtime(app):
    sock.init_app(app)

    @sock.route('/ws')
    def ws_route(ws):
        clients.add(ws)
        ws.send("hello from server (train realtime ready)")
        try:
            while True:
                msg = ws.receive()
                if msg is None:
                    break
                # 简单 echo
                ws.send(f"echo: {msg}")
        finally:
            clients.discard(ws)

# ============= 广播工具 =============
def broadcast(message: dict):
    data = json.dumps(message, ensure_ascii=False)
    dead = []
    for ws in list(clients):
        try:
            ws.send(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)

# ============= 启动 / 停止模拟列车 =============
def start_train(train_id: str,
                path_names: List[str],
                per_edge_seconds: Optional[List[float]] = None,
                loop: bool = True,
                ping_interval: float = 1.0):
    """
    启动一个后台线程，沿给定 path 往返运行并广播位置。
    - path_names: 站名序列，例如 ["KLCC","Pasar Seni (KJL)","Kajang"]
    - per_edge_seconds: 每段区间的秒数（len= len(path_names)-1）；None 则默认每段 8 秒
    - loop: True 表示到终点后再反向继续
    - ping_interval: 每隔多少秒广播一次进度
    """

    # 如果已存在同名列车，先停止
    stop_train(train_id)

    if not path_names or len(path_names) < 2:
        raise ValueError("path_names must contain at least 2 stations")

    if per_edge_seconds is None:
        per_edge_seconds = [8.0] * (len(path_names) - 1)
    else:
        if len(per_edge_seconds) != len(path_names) - 1:
            raise ValueError("per_edge_seconds length mismatch")

    stop_event = threading.Event()

    def _runner():
        forward = True
        idx = 0
        # 先广播一次“准备出发”
        broadcast({
            "type": "train_status",
            "train_id": train_id,
            "status": "started",
            "path": path_names
        })
        try:
            while not stop_event.is_set():
                if forward:
                    nxt = idx + 1
                    if nxt >= len(path_names):
                        if not loop:
                            break
                        forward = False
                        idx -= 1
                        continue
                else:
                    nxt = idx - 1
                    if nxt < 0:
                        if not loop:
                            break
                        forward = True
                        idx += 1
                        continue

                origin = path_names[idx]
                dest   = path_names[nxt]
                seg_seconds = max(0.1, float(per_edge_seconds[min(idx, nxt)]))
                steps = max(1, int(seg_seconds / ping_interval))

                # 每段里按进度广播
                for s in range(steps + 1):
                    if stop_event.is_set():
                        break
                    progress = s / steps
                    broadcast({
                        "type": "train_tick",
                        "train_id": train_id,
                        "origin": origin,
                        "dest": dest,
                        "progress": round(progress, 4),
                        "timestamp": time.time()
                    })
                    time.sleep(ping_interval)

                if stop_event.is_set():
                    break
                idx = nxt
        finally:
            broadcast({
                "type": "train_status",
                "train_id": train_id,
                "status": "stopped"
            })

    th = threading.Thread(target=_runner, daemon=True)
    running_trains[train_id] = (th, stop_event)
    th.start()

def stop_train(train_id: str) -> bool:
    info = running_trains.pop(train_id, None)
    if not info:
        return False
    th, ev = info
    ev.set()
    return True

def list_trains() -> List[str]:
    return list(running_trains.keys())
