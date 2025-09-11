# database.py
import csv
import os
import sqlite3
import heapq
from collections import deque, defaultdict
from contextlib import contextmanager
from typing import Dict, Iterable, Optional, Set, List, Tuple

import re
PAREN = re.compile(r"\s*\([^)]*\)\s*")

def _name_key(s: str) -> str:
    """Normalize station name: drop parentheses, collapse spaces, lower, unify apostrophe"""
    if s is None:
        return ""
    s = PAREN.sub("", str(s))
    s = s.replace("’", "'")
    return re.sub(r"\s+", " ", s).strip().lower()

@contextmanager
def get_conn(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

# ---------------- Utilities ----------------
def _norm(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_")

def _find_col(header: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    if not header:
        return None
    norm_map = {_norm(h): h for h in header}
    for c in candidates:
        key = _norm(c)
        if key in norm_map:
            return norm_map[key]
    for raw in header:
        if any(_norm(c) in _norm(raw) for c in candidates):
            return raw
    return None

_num = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
def _to_float(x) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "")
    m = _num.search(s)
    return float(m.group(0)) if m else None

def _ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

# ---------------- DDL ----------------
DDL = """
CREATE TABLE IF NOT EXISTS stations (
    station_id   INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    latitude     REAL,
    longitude    REAL
);

CREATE TABLE IF NOT EXISTS fares (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_id      INTEGER NOT NULL,
    destination_id INTEGER NOT NULL,
    price          REAL NOT NULL,
    UNIQUE(origin_id, destination_id)
);

CREATE INDEX IF NOT EXISTS idx_fares_pair ON fares(origin_id, destination_id);

CREATE TABLE IF NOT EXISTS routes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id          INTEGER NOT NULL,
    to_id            INTEGER NOT NULL,
    travel_time_min  REAL,
    UNIQUE(from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_routes_from ON routes(from_id);
CREATE INDEX IF NOT EXISTS idx_routes_to   ON routes(to_id);
"""

def _create_tables(conn: sqlite3.Connection):
    conn.executescript(DDL)

# ---------------- CSV helpers ----------------
def _csv_path(data_dir: str, filename: str) -> Optional[str]:
    p = os.path.join(data_dir, filename)
    return p if os.path.exists(p) else None

def _read_header_row_only(path: str) -> Optional[list]:
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return None
        header = [h.strip() for h in header if h and h.strip()]
        return header

# ---------------- Import: stations ----------------
def import_stations(conn: sqlite3.Connection, data_dir: str) -> int:
    fare_csv = _csv_path(data_dir, "Fare.csv")
    names: Set[str] = set()

    # Collect station names from Fare.csv first column/header
    if fare_csv and os.path.exists(fare_csv):
        with open(fare_csv, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            for line in reader:
                if line and line[0].strip():
                    names.add(line[0].strip())
            for h in header[1:]:
                if h.strip():
                    names.add(h.strip())

    # Fallback: add names from headers of Route/Time
    if not names:
        for alt in ("Route.csv", "Time.csv"):
            hdr = _read_header_row_only(_csv_path(data_dir, alt))
            if hdr:
                for h in hdr:
                    names.add(h)

    rows = []
    for i, name in enumerate(sorted(names), start=1):
        rows.append((i, name, None, None))

    conn.executemany(
        "INSERT OR IGNORE INTO stations(station_id, name, latitude, longitude) VALUES (?,?,?,?)",
        rows
    )
    return len(rows)

# ---------------- Import: fares (matrix) ----------------
def import_fares(conn: sqlite3.Connection, data_dir: str) -> int:
    fare_csv = _csv_path(data_dir, "Fare.csv")
    if not fare_csv:
        print("[fares] Fare.csv not found, skip.")
        return 0

    # name -> id
    name_to_id: Dict[str, int] = {}
    for r in conn.execute("SELECT station_id, name FROM stations"):
        name_to_id[_name_key(r["name"])] = int(r["station_id"])
        
    def id_of(name: str) -> Optional[int]:
        return name_to_id.get(_name_key(name))

    rows = []
    with open(fare_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        dest_names = [h.strip() for h in header[1:] if h.strip()]

        for line in reader:
            if not line:
                continue
            origin_name = line[0].strip()
            if not origin_name:
                continue
            o = id_of(origin_name)
            if not o:
                continue
            for j, dest_name in enumerate(dest_names, start=1):
                if j >= len(line):
                    continue
                cell = str(line[j]).strip()
                if not cell or cell in {"-", "NA", "N/A"}:
                    continue
                price = _to_float(cell)
                if price is None:
                    continue
                d = id_of(dest_name)
                if not d:
                    continue
                rows.append((o, d, price))

    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO fares(origin_id, destination_id, price) VALUES (?,?,?)",
            rows
        )
    print(f"[fares] imported rows: {len(rows)}")
    return len(rows)

# ---------------- Import: routes (Route.csv + Time.csv) ----------------
def import_routes(conn: sqlite3.Connection, data_dir: str) -> int:
    """
    Use only the first row of Route.csv as the full line sequence and connect adjacent pairs (bidirectional);
    use Time.csv (matrix) to fill travel_time_min for each segment.
    """
    route_csv = _csv_path(data_dir, "Route.csv")
    if not route_csv or not os.path.exists(route_csv):
        print("[routes] Route.csv not found, skip.")
        return 0

    time_csv = _csv_path(data_dir, "Time.csv")

    # name -> id (normalized)
    name_to_id: Dict[str, int] = {}
    for r in conn.execute("SELECT station_id, name FROM stations"):
        name_to_id[_name_key(r["name"])] = int(r["station_id"])

    def id_of(nm: str) -> Optional[int]:
        return name_to_id.get(_name_key(nm))

    # ---------- read only first row ----------
    with open(route_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        first_row = next(reader, [])
        seq = [c.strip() for c in first_row if c and c.strip()]
    if len(seq) < 2:
        print("[routes] Route.csv first row too short.")
        return 0

    # Build adjacent edges (bidirectional)
    edges: Set[Tuple[int, int]] = set()
    for a, b in zip(seq, seq[1:]):
        u, v = id_of(a), id_of(b)
        if not u or not v:
            # print("[routes] name not found in first row:", a, b)
            continue
        edges.add((u, v))
        edges.add((v, u))

    if not edges:
        print("[routes] No edges from first row.")
        return 0

    # ---------- If Time.csv exists: build (origin_key, dest_key) -> minutes map ----------
    time_map: Dict[Tuple[str, str], float] = {}
    if time_csv and os.path.exists(time_csv):
        with open(time_csv, "r", encoding="utf-8-sig", newline="") as tf:
            treader = csv.reader(tf)
            theader = next(treader, [])
            dest_names = [h.strip() for h in theader[1:] if h and h.strip()]
            dest_keys  = [_name_key(h) for h in dest_names]
            for row in treader:
                if not row:
                    continue
                oname = (row[0] or "").strip()
                if not oname:
                    continue
                okey = _name_key(oname)
                for j, dkey in enumerate(dest_keys, start=1):
                    if j >= len(row):
                        continue
                    cell = str(row[j]).strip()
                    if not cell or cell in {"-", "NA", "N/A"}:
                        continue
                    try:
                        t = float(cell)
                    except ValueError:
                        continue
                    time_map[(okey, dkey)] = t

    # ---------- write into routes ----------
    rows = []
    DEFAULT_MIN = 1.0  # fallback minutes when missing, used by Dijkstra weight only
    sel_name = "SELECT name FROM stations WHERE station_id=?"
    for u, v in edges:
        on = conn.execute(sel_name, (u,)).fetchone()["name"]
        dn = conn.execute(sel_name, (v,)).fetchone()["name"]
        tmin = time_map.get((_name_key(on), _name_key(dn)))
        w = float(tmin) if (tmin is not None and tmin > 0) else DEFAULT_MIN
        rows.append((u, v, w))

    conn.executemany(
        "INSERT OR REPLACE INTO routes(from_id, to_id, travel_time_min) VALUES (?,?,?)",
        rows
    )
    print(f"[routes] imported edges from first row (directed): {len(rows)}")
    return len(rows)
    """
    Read Route.csv (line sequences) and connect adjacent pairs; fill each segment's travel_time_min using Time.csv (matrix).

    Route.csv supports two sequence formats:
    - A whole comma-separated row: Gombak,Taman Melati,Wangsa Maju,...,KLCC,...
    - Or a bracket/arrow form: KJL [ Taman Melati > Wangsa Maju > ... > KLCC > ... ]

    Time.csv is assumed a matrix:
    - First row = destination column headers (first cell often blank), first column = origin station names
    - Cell = minutes (blank/"-" means missing)
    """
    route_csv = _csv_path(data_dir, "Route.csv")
    if not route_csv or not os.path.exists(route_csv):
        print("[routes] Route.csv not found, skip.")
        return 0

    time_csv = _csv_path(data_dir, "Time.csv")

    # ---- name -> id (normalized) ----
    name_to_id: Dict[str, int] = {}
    for r in conn.execute("SELECT station_id, name FROM stations"):
        name_to_id[_name_key(r["name"])] = int(r["station_id"])

    def id_of(nm: str) -> Optional[int]:
        return name_to_id.get(_name_key(nm))

    # ---- Parse Route.csv: each row is a line sequence; connect adjacent edges (bidirectional) ----
    edges: Set[Tuple[int, int]] = set()

    with open(route_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for raw_row in reader:
            row_text = " ".join(c for c in raw_row if c).strip()
            seq: List[str] = []
            if not row_text:
                continue

            # 1) Support [ A > B > ... ] form
            m = re.search(r"\[(.+?)\]", row_text)
            if m and ">" in m.group(1):
                seq = [p.strip() for p in m.group(1).split(">") if p.strip()]
            else:
                # 2) Else treat as a comma-separated row
                seq = [c.strip() for c in raw_row if c and c.strip()]

            if len(seq) < 2:
                continue

            for a, b in zip(seq, seq[1:]):
                u, v = id_of(a), id_of(b)
                if not u or not v:
                    # print("[routes] name not found in Route.csv:", a, b)
                    continue
                edges.add((u, v))
                edges.add((v, u))

    if not edges:
        print("[routes] No edges parsed from Route.csv.")
        return 0

    # ---- If Time.csv exists: build (origin_key, dest_key) -> minutes ----
    time_map: Dict[Tuple[str, str], float] = {}
    if time_csv and os.path.exists(time_csv):
        with open(time_csv, "r", encoding="utf-8-sig", newline="") as tf:
            treader = csv.reader(tf)
            theader = next(treader, [])
            dest_names = [h.strip() for h in theader[1:] if h and h.strip()]
            dest_keys  = [_name_key(h) for h in dest_names]
            for row in treader:
                if not row:
                    continue
                oname = (row[0] or "").strip()
                if not oname:
                    continue
                okey = _name_key(oname)
                for j, dkey in enumerate(dest_keys, start=1):
                    if j >= len(row):
                        continue
                    cell = str(row[j]).strip()
                    if not cell or cell in {"-", "NA", "N/A"}:
                        continue
                    try:
                        t = float(cell)
                    except ValueError:
                        continue
                    time_map[(okey, dkey)] = t

    # ---- Write into routes ----
    rows = []
    DEFAULT_MIN = 1.0  # default minutes when not found (for Dijkstra weight only)
    select_name = "SELECT name FROM stations WHERE station_id=?"

    for u, v in edges:
        on = conn.execute(select_name, (u,)).fetchone()["name"]
        dn = conn.execute(select_name, (v,)).fetchone()["name"]
        tmin = time_map.get((_name_key(on), _name_key(dn)))
        w = float(tmin) if (tmin is not None and tmin > 0) else DEFAULT_MIN
        rows.append((u, v, w))

    conn.executemany(
        "INSERT OR REPLACE INTO routes(from_id, to_id, travel_time_min) VALUES (?,?,?)",
        rows
    )
    print(f"[routes] imported edges (sequence mode, directed): {len(rows)}")
    return len(rows)

# ---------------- DB init (one-shot) ----------------
def init_db(db_path: str, data_dir: str):
    _ensure_dir(os.path.dirname(db_path) or ".")
    _ensure_dir(data_dir)
    with get_conn(db_path) as conn:
        _create_tables(conn)

        c = conn.execute("SELECT COUNT(*) AS c FROM stations").fetchone()["c"]
        if c == 0:
            inserted = import_stations(conn, data_dir)
            print(f"[stations] inserted: {inserted}")
        else:
            print(f"[stations] already has {c} rows")

        f = conn.execute("SELECT COUNT(*) AS c FROM fares").fetchone()["c"]
        if f == 0:
            imported = import_fares(conn, data_dir)
            print(f"[fares] total imported: {imported}")
        else:
            print(f"[fares] already has {f} rows")

        r = conn.execute("SELECT COUNT(*) AS c FROM routes").fetchone()["c"]
        if r == 0:
            imported_r = import_routes(conn, data_dir)
            print(f"[routes] total imported: {imported_r}")
        else:
            print(f"[routes] already has {r} rows")
                # Finally: try importing station coordinates if files exist
        try:
            _ = update_station_coords_from_files(conn, data_dir)
        except Exception as e:
            print("[coords] import failed:", e)


# ---------------- Queries ----------------
def get_all_stations(conn: sqlite3.Connection):
    cur = conn.execute("SELECT station_id, name, latitude, longitude FROM stations ORDER BY station_id")
    return [dict(r) for r in cur.fetchall()]

def get_fare_between(conn: sqlite3.Connection, origin_id: int, destination_id: int) -> Optional[float]:
    cur = conn.execute(
        "SELECT price FROM fares WHERE origin_id=? AND destination_id=?",
        (origin_id, destination_id)
    )
    row = cur.fetchone()
    return float(row["price"]) if row else None

# ---------------- Routing: min stops / min time ----------------
def get_route_shortest(conn: sqlite3.Connection, origin_id: int, destination_id: int, mode: str = "stops"):
    """
    mode = 'stops' -> BFS (edge weight = 1)
    mode = 'time'  -> Dijkstra (edge weight = travel_time_min; if NULL/<=0, use 1)
    Return: dict(path_ids=[...], path_names=[...], total_stops=int, total_time=float|None)
    """
    # Build graph
    adj: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    cur = conn.execute("SELECT from_id, to_id, COALESCE(travel_time_min, 1) AS w FROM routes")
    for row in cur.fetchall():
        u, v, w = int(row["from_id"]), int(row["to_id"]), float(row["w"])
        if w <= 0:
            w = 1.0
        adj[u].append((v, w))

    # station_id -> name
    id2name = {int(r["station_id"]): str(r["name"]) for r in conn.execute("SELECT station_id, name FROM stations")}
    if origin_id not in id2name or destination_id not in id2name:
        return None

    # BFS (min stops)
    if mode == "stops":
        q = deque([origin_id])
        prev = {origin_id: None}
        while q:
            u = q.popleft()
            if u == destination_id:
                break
            for v, _ in adj.get(u, []):
                if v not in prev:
                    prev[v] = u
                    q.append(v)
        if destination_id not in prev:
            return None
        # Reconstruct path
        path = []
        x = destination_id
        while x is not None:
            path.append(x)
            x = prev[x]
        path.reverse()
        return {
            "path_ids": path,
            "path_names": [id2name[i] for i in path],
            "total_stops": max(0, len(path) - 1),
            "total_time": None
        }

    # Dijkstra (min time)
    if mode == "time":
        dist = {origin_id: 0.0}
        prev = {origin_id: None}
        pq = [(0.0, origin_id)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == destination_id:
                break
            if d > dist.get(u, float("inf")):
                continue
            for v, w in adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

        if destination_id not in prev and destination_id != origin_id:
            return None
        # Reconstruct path
        path = []
        x = destination_id
        while x is not None:
            path.append(x)
            x = prev.get(x)
        path.reverse()
        return {
            "path_ids": path,
            "path_names": [id2name[i] for i in path],
            "total_stops": max(0, len(path) - 1),
            "total_time": float(dist.get(destination_id, 0.0))
        }

    # Unknown mode
    return None

# === Coordinate import: CSV or XLSX ===
def update_station_coords_from_files(conn: sqlite3.Connection, data_dir: str) -> int:
    """
    Look for either of the following files under data_dir and import coordinates:
      - stations_coords.csv (headers: name, latitude, longitude)
      - Station.xlsx        (Sheet1 or first sheet; same headers)
    Match by 'name' (normalized via _name_key), update stations.latitude/longitude.
    Return number of updated rows.
    """
    import_path_csv  = os.path.join(data_dir, "stations_coords.csv")
    import_path_xlsx = os.path.join(data_dir, "Station.xlsx")

    rows = []
    src  = None

    if os.path.exists(import_path_csv):
        # Read CSV
        with open(import_path_csv, "r", encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                name = (row.get("name") or "").strip()
                lat  = row.get("latitude")
                lng  = row.get("longitude")
                if not name or lat in (None, "") or lng in (None, ""):
                    continue
                try:
                    rows.append((_name_key(name), float(lat), float(lng)))
                except ValueError:
                    pass
        src = "csv"

    elif os.path.exists(import_path_xlsx):
        # Read XLSX (requires pandas+openpyxl)
        try:
            import pandas as pd
            df = pd.read_excel(import_path_xlsx)
            # Tolerate header case/spacing
            cols = {c.strip().lower(): c for c in df.columns if isinstance(c, str)}
            need = ("name", "latitude", "longitude")
            if not all(k in cols for k in need):
                print("[coords] Station.xlsx missing headers name/latitude/longitude, skip")
                return 0
            for _, r in df.iterrows():
                name = str(r[cols["name"]]).strip() if pd.notna(r[cols["name"]]) else ""
                lat  = r[cols["latitude"]]
                lng  = r[cols["longitude"]]
                if not name or pd.isna(lat) or pd.isna(lng):
                    continue
                try:
                    rows.append((_name_key(name), float(lat), float(lng)))
                except Exception:
                    pass
            src = "xlsx"
        except Exception as e:
            print("[coords] failed to read Station.xlsx:", e)
            return 0
    else:
        # No file found; silently return
        return 0

    if not rows:
        print(f"[coords] no valid rows in {src} file")
        return 0

    # Build (key -> station_id) index from stations
    name_to_id = {}
    for r in conn.execute("SELECT station_id, name FROM stations"):
        name_to_id[_name_key(r["name"])] = int(r["station_id"])

    updated = 0
    for k, lat, lng in rows:
        sid = name_to_id.get(k)
        if not sid:
            # Not matched; could log if needed
            # print("[coords] station name not matched:", k)
            continue
        conn.execute(
            "UPDATE stations SET latitude=?, longitude=? WHERE station_id=?",
            (lat, lng, sid)
        )
        updated += 1
    print(f"[coords] updated rows: {updated} (from {src})")
    return updated
