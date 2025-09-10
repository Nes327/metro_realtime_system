# realtime.py
import json
import threading
import time
import random
from typing import Dict, Any, List
from flask import current_app
from flask_sock import Sock

sock = Sock()

# 维护连接的 WebSocket 客户端
_clients_lock = threading.Lock()
_clients: List[Any] = []

def init_realtime(app):
    """
    初始化 WebSocket 路由 /ws
    - 前端或 data_generator.py 连接此地址
    - 服务端会广播来自后台模拟器或外部脚本的 train 更新
    """
    sock.init_app(app)

    @sock.route('/ws')
    def ws_handler(ws):
        # 注册
        with _clients_lock:
            _clients.append(ws)
        try:
            # 告知客户端已连接
            ws.send(json.dumps({"type": "hello", "msg": "hello from server (train realtime ready)"}))
            while True:
                # 等待客户端消息（可能是普通 echo，也可能是 data_generator.py 发来的 train_update）
                msg = ws.receive()
                if msg is None:
                    break
                # 如果是纯文本，尽量解析 JSON
                try:
                    js = json.loads(msg)
                    # 若是 data_generator.py 推送的通用格式： type = "train_update"
                    if isinstance(js, dict) and js.get("type") == "train_update":
                        _broadcast(js)  # 直接广播给所有连接（包括前端）
                    else:
                        # 其他消息就原样 echo 回去，便于调试
                        ws.send(msg)
                except Exception:
                    # 非 JSON，原样 echo
                    ws.send(msg)
        finally:
            # 注销
            with _clients_lock:
                if ws in _clients:
                    _clients.remove(ws)

    return sock


def _broadcast(obj: Dict[str, Any]):
    """将对象广播给所有在线 ws 客户端（自动转 JSON）"""
    data = json.dumps(obj)
    with _clients_lock:
        dead = []
        for w in _clients:
            try:
                w.send(data)
            except Exception:
                dead.append(w)
        for w in dead:
            try:
                _clients.remove(w)
            except Exception:
                pass


# ---------------- 后台内置列车模拟（你之前就有的逻辑，这里保持；会定期发 train_tick） ----------------
class TrainThread(threading.Thread):
    def __init__(self, train_id: str, path_names: List[str], per_edge_seconds: List[float], loop=True, ping_interval=1.0):
        super().__init__(daemon=True)
        self.train_id = train_id
        self.path = path_names
        self.edge_secs = per_edge_seconds
        self.loop = loop
        self.ping_interval = max(0.2, float(ping_interval))
        self._stop = threading.Event()

    def run(self):
        try:
            # 通知启动
            _broadcast({"type": "train_status", "train_id": self.train_id, "status": "started"})
            while not self._stop.is_set():
                for idx in range(len(self.path) - 1):
                    origin = self.path[idx]
                    dest   = self.path[idx + 1]
                    dur    = max(1.0, float(self.edge_secs[idx] if idx < len(self.edge_secs) else 8.0))
                    start  = time.time()
                    while not self._stop.is_set():
                        t = time.time() - start
                        progress = min(1.0, t / dur)
                        _broadcast({
                            "type": "train_tick",
                            "train_id": self.train_id,
                            "origin": origin,
                            "dest": dest,
                            "progress": progress
                        })
                        if progress >= 1.0:
                            break
                        time.sleep(self.ping_interval)
                if not self.loop:
                    break
        finally:
            _broadcast({"type": "train_status", "train_id": self.train_id, "status": "stopped"})

    def stop(self):
        self._stop.set()


_trains: Dict[str, TrainThread] = {}

def start_train(train_id: str, path_names: List[str], per_edge_seconds: List[float], loop=True, ping_interval=1.0):
    # 停掉同名
    if train_id in _trains:
        try:
            _trains[train_id].stop()
        except Exception:
            pass
    t = TrainThread(train_id, path_names, per_edge_seconds, loop=loop, ping_interval=ping_interval)
    _trains[train_id] = t
    t.start()

def stop_train(train_id: str) -> bool:
    if train_id in _trains:
        try:
            _trains[train_id].stop()
            return True
        finally:
            _trains.pop(train_id, None)
    return False

def list_trains():
    return list(_trains.keys())
