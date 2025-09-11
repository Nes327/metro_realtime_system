# realtime.py
import json
import threading
import time
import random
from typing import Dict, Any, List
from flask import current_app
from flask_sock import Sock

sock = Sock()

# Connected WebSocket clients
_clients_lock = threading.Lock()
_clients: List[Any] = []

def init_realtime(app):
    """
    Initialize WebSocket route /ws
    - Frontend or data_generator.py connects to this endpoint
    - Server broadcasts train updates from the built-in simulator or external scripts
    """
    sock.init_app(app)

    @sock.route('/ws')
    def ws_handler(ws):
        # Register client
        with _clients_lock:
            _clients.append(ws)
        try:
            # Greet on connect
            ws.send(json.dumps({"type": "hello", "msg": "hello from server (train realtime ready)"}))
            while True:
                # Wait for client message (plain echo or train_update from data_generator.py)
                msg = ws.receive()
                if msg is None:
                    break
                # Try parse JSON if it's plain text
                try:
                    js = json.loads(msg)
                    # Broadcast if it is the generic format: type = "train_update"
                    if isinstance(js, dict) and js.get("type") == "train_update":
                        _broadcast(js)  # broadcast to all clients (including frontend)
                    else:
                        # Echo for debugging
                        ws.send(msg)
                except Exception:
                    # Non-JSON, echo back
                    ws.send(msg)
        finally:
            # Unregister client
            with _clients_lock:
                if ws in _clients:
                    _clients.remove(ws)

    return sock


def _broadcast(obj: Dict[str, Any]):
    """Broadcast object to all online ws clients (auto JSON)"""
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


# ---------------- Built-in background train simulator (kept as-is; emits train_tick) ----------------
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
            # Notify start
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
    # Stop same-named train
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
