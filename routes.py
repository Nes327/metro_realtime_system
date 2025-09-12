from flask import Blueprint, jsonify, request, current_app
from database import get_conn, get_all_stations, get_fare_between, get_route_shortest
from realtime import start_train, stop_train, list_trains
from database import _name_key
import time

def _name_to_id_map(conn):
    rows = conn.execute("SELECT station_id, name FROM stations").fetchall()
    return {_name_key(r["name"]): int(r["station_id"]) for r in rows}

api_bp = Blueprint("api", __name__)

# Health check
@api_bp.get("/health")
def health():
    """Simple endpoint to verify API is alive."""
    return jsonify(status="ok")

# Stations
@api_bp.get("/stations")
def stations():
    """Return full station list with metadata."""
    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        data = get_all_stations(conn)
    return jsonify(count=len(data), data=data)

# Fare endpoints
@api_bp.get("/fare")
def fare():
    """Query fare by numeric station IDs."""
    from_id = request.args.get("from", type=int)
    to_id = request.args.get("to", type=int)
    if from_id is None or to_id is None:
        return jsonify(error="missing query: from & to (int)"), 400
    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        price = get_fare_between(conn, from_id, to_id)
    if price is None:
        return jsonify({"from_id": from_id, "to_id": to_id, "price": None, "message": "fare not found"}), 404
    return jsonify({"from_id": from_id, "to_id": to_id, "price": price})

@api_bp.get("/fare_by_name")
def fare_by_name():
    """Query fare by station names (case-insensitive)."""
    from_name = (request.args.get("from") or "").strip().lower()
    to_name   = (request.args.get("to") or "").strip().lower()
    if not from_name or not to_name:
        return jsonify(error="missing query: from & to (station names)"), 400
    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        n2i = _name_to_id_map(conn)
        from_id = n2i.get(from_name)
        to_id   = n2i.get(to_name)
        if from_id is None or to_id is None:
            return jsonify({"error": "station name not found", "from_name": from_name, "to_name": to_name}), 404
        price = get_fare_between(conn, from_id, to_id)
    if price is None:
        return jsonify({"from": from_name, "to": to_name, "price": None, "message": "fare not found"}), 404
    return jsonify({"from": from_name, "to": to_name, "price": price, "from_id": from_id, "to_id": to_id})

# Station search
@api_bp.get("/search_station")
def search_station():
    """Search stations by substring in name."""
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify(error="missing q"), 400
    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT station_id, name FROM stations WHERE lower(name) LIKE ?", (f"%{q}%",)
        ).fetchall()
    return jsonify(results=[dict(r) for r in rows])

# Route endpoints
@api_bp.get("/route")
def route_by_id():
    """Compute route using station IDs (supports 'stops' or 'time' mode)."""
    from_id = request.args.get("from", type=int)
    to_id   = request.args.get("to", type=int)
    mode    = (request.args.get("mode") or "stops").strip().lower()
    if from_id is None or to_id is None:
        return jsonify(error="missing query: from & to (int)"), 400
    if mode not in {"stops", "time"}:
        return jsonify(error="mode must be 'stops' or 'time'"), 400
    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        res = get_route_shortest(conn, from_id, to_id, mode=mode)
    if not res:
        return jsonify({"from_id": from_id, "to_id": to_id, "mode": mode, "message": "route not found"}), 404
    return jsonify({
        "from_id": from_id, "to_id": to_id, "mode": mode,
        "path_ids": res["path_ids"], "path_names": res["path_names"],
        "total_stops": res["total_stops"], "total_time": res["total_time"]
    })

@api_bp.get("/route_by_name")
def route_by_name():
    """Compute route using station names (supports 'stops' or 'time' mode)."""
    from_name = (request.args.get("from") or "").strip().lower()
    to_name   = (request.args.get("to") or "").strip().lower()
    mode      = (request.args.get("mode") or "stops").strip().lower()
    if not from_name or not to_name:
        return jsonify(error="missing query: from & to (station names)"), 400
    if mode not in {"stops", "time"}:
        return jsonify(error="mode must be 'stops' or 'time'"), 400
    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        n2i = _name_to_id_map(conn)
        from_id = n2i.get(from_name)
        to_id   = n2i.get(to_name)
        if from_id is None or to_id is None:
            return jsonify({"error": "station name not found", "from_name": from_name, "to_name": to_name}), 404
        res = get_route_shortest(conn, from_id, to_id, mode=mode)
    if not res:
        return jsonify({"from": from_name, "to": to_name, "mode": mode, "message": "route not found"}), 404
    return jsonify({
        "from": from_name, "to": to_name, "mode": mode,
        "path_ids": res["path_ids"], "path_names": res["path_names"],
        "total_stops": res["total_stops"], "total_time": res["total_time"]
    })

# Train simulation endpoints
@api_bp.post("/simulate_train")
def simulate_train():
    """
    Start a simulated train journey.
    Reads travel_time_min per edge from DB and emits progress via WebSocket.
    """
    data = request.get_json(silent=True) or {}
    from_name = (data.get("from") or "").strip().lower()
    to_name   = (data.get("to") or "").strip().lower()
    mode      = (data.get("mode") or "time").strip().lower()
    train_id  = (data.get("train_id") or f"Train-{int(time.time())}")
    speed     = float(data.get("speed") or 1.0)
    loop_flag = bool(data.get("loop", True))
    ping_int  = float(data.get("ping_interval") or 1.0)

    if not from_name or not to_name:
        return jsonify(error="missing 'from' / 'to'"), 400
    if mode not in {"stops", "time"}:
        return jsonify(error="mode must be 'stops' or 'time'"), 400
    if speed <= 0:
        return jsonify(error="speed must be > 0"), 400

    db_path = current_app.config["DB_PATH"]

    with get_conn(db_path) as conn:
        # Convert names to IDs
        n2i = _name_to_id_map(conn)
        from_id = n2i.get(from_name)
        to_id   = n2i.get(to_name)
        if from_id is None or to_id is None:
            return jsonify(error="station name not found"), 404

        # Compute route
        res = get_route_shortest(conn, from_id, to_id, mode=mode)
        if not res:
            return jsonify(error="route not found"), 404
        path_names = res["path_names"]
        path_ids   = res["path_ids"]

        # Calculate travel seconds
        per_edge_seconds = []
        DEFAULT_EDGE_SEC = 8.0
        for i in range(len(path_ids) - 1):
            a, b = int(path_ids[i]), int(path_ids[i+1])
            row = conn.execute(
                "SELECT travel_time_min FROM routes WHERE from_id=? AND to_id=?",
                (a, b)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT travel_time_min FROM routes WHERE from_id=? AND to_id=?",
                    (b, a)
                ).fetchone()

            t_min = float(row["travel_time_min"]) if (row and row["travel_time_min"] is not None) else None

            if t_min is None or t_min <= 0:
                sec = DEFAULT_EDGE_SEC
            else:
                sec = max(1.0, (t_min * 60.0) / max(0.1, speed))

            per_edge_seconds.append(sec)

    # Start background thread to simulate train
    start_train(
        train_id,
        path_names,
        per_edge_seconds=per_edge_seconds,
        loop=loop_flag,
        ping_interval=ping_int
    )

    return jsonify(ok=True, train_id=train_id, path=path_names, per_edge_seconds=per_edge_seconds)

@api_bp.get("/trains")
def trains_list():
    """Return IDs of active simulated trains."""
    return jsonify(trains=list_trains())

@api_bp.delete("/trains/<train_id>")
def trains_stop(train_id):
    """Stop a simulated train by ID."""
    ok = stop_train(train_id)
    return jsonify(ok=ok, train_id=train_id)

# Debug utilities
@api_bp.get("/edge_times_by_name")
def edge_times_by_name():
    """
    Debug endpoint: return per-segment travel_time_min along a route.
    Useful for verifying Time.csv import.
    """
    from_name = (request.args.get("from") or "").strip().lower()
    to_name   = (request.args.get("to") or "").strip().lower()
    mode      = (request.args.get("mode") or "time").strip().lower()
    if not from_name or not to_name:
        return jsonify(error="missing 'from' / 'to'"), 400
    if mode not in {"stops", "time"}:
        return jsonify(error="mode must be 'stops' or 'time'"), 400

    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        n2i = _name_to_id_map(conn)
        from_id = n2i.get(from_name)
        to_id   = n2i.get(to_name)
        if from_id is None or to_id is None:
            return jsonify(error="station name not found"), 404

        res = get_route_shortest(conn, from_id, to_id, mode=mode)
        if not res:
            return jsonify(error="route not found"), 404

        path_ids   = res["path_ids"]
        path_names = res["path_names"]

        segs = []
        for i in range(len(path_ids)-1):
            a, b = int(path_ids[i]), int(path_ids[i+1])
            row = conn.execute(
                "SELECT travel_time_min FROM routes WHERE from_id=? AND to_id=?",
                (a, b)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT travel_time_min FROM routes WHERE from_id=? AND to_id=?",
                    (b, a)
                ).fetchone()
            t_min = float(row["travel_time_min"]) if (row and row["travel_time_min"] is not None) else None
            segs.append({
                "from": path_names[i],
                "to": path_names[i+1],
                "travel_time_min": t_min
            })

    return jsonify(path=path_names, segments=segs)

@api_bp.get("/debug/neighbors")
def debug_neighbors():
    """Debug endpoint: list neighbor stations and travel times for a given station."""
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify(error="missing name"), 400
    db_path = current_app.config["DB_PATH"]
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT station_id FROM stations WHERE lower(name)=lower(?)", (name,)).fetchone()
        if not row:
            return jsonify(error="station not found"), 404
        sid = int(row["station_id"])
        q = """
        SELECT s2.name AS neighbor, r.travel_time_min
        FROM routes r
        JOIN stations s2 ON s2.station_id = r.to_id
        WHERE r.from_id = ?
        ORDER BY s2.name
        """
        res = [dict(r) for r in conn.execute(q, (sid,)).fetchall()]
    return jsonify(station=name, neighbors=res)
