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
    """统一站名：去括号、合并空白、lower、统一撇号"""
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

# ---------------- 小工具 ----------------
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

# ---------------- 表结构 ----------------
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

# ---------------- 读取 CSV 辅助 ----------------
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

# ---------------- 导入：车站 ----------------
def import_stations(conn: sqlite3.Connection, data_dir: str) -> int:
    fare_csv = _csv_path(data_dir, "Fare.csv")
    names: Set[str] = set()

    # 从 Fare.csv 的首列/表头收集站名
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

    # 兜底：从 Route/Time 的表头补站名
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

# ---------------- 导入：票价（矩阵） ----------------
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

# ---------------- 导入：路线（Route.csv + Time.csv） ----------------
def import_routes(conn: sqlite3.Connection, data_dir: str) -> int:
    """
    读取 Route.csv（线路站序列表）并连成相邻边；用 Time.csv（矩阵）填每段 travel_time_min。

    Route.csv 支持两种“序列”写法：
    - 逗号分隔的一整行：Gombak,Taman Melati,Wangsa Maju,...,KLCC,...
    - 或含括号/箭头：KJL [ Taman Melati > Wangsa Maju > ... > KLCC > ... ]

    Time.csv 假设是“矩阵”：
    - 第一行是列目的地站名（第一格常为空），首列是行起点站名
    - 单元格为分钟（可含空白/“-”表示无值）
    """
    route_csv = _csv_path(data_dir, "Route.csv")
    if not route_csv or not os.path.exists(route_csv):
        print("[routes] Route.csv not found, skip.")
        return 0

    time_csv = _csv_path(data_dir, "Time.csv")

    # ---- 站名 -> id（归一化） ----
    name_to_id: Dict[str, int] = {}
    for r in conn.execute("SELECT station_id, name FROM stations"):
        name_to_id[_name_key(r["name"])] = int(r["station_id"])

    def id_of(nm: str) -> Optional[int]:
        return name_to_id.get(_name_key(nm))

    # ---- 解析 Route.csv：每行一条线路的站序，连相邻边（双向）----
    edges: Set[Tuple[int, int]] = set()

    with open(route_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for raw_row in reader:
            row_text = " ".join(c for c in raw_row if c).strip()
            seq: List[str] = []
            if not row_text:
                continue

            # 1) 兼容  [ A > B > ... ] 形式
            m = re.search(r"\[(.+?)\]", row_text)
            if m and ">" in m.group(1):
                seq = [p.strip() for p in m.group(1).split(">") if p.strip()]
            else:
                # 2) 否则按逗号分隔的整行
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

    # ---- 如果有 Time.csv：建立 (origin_key, dest_key) -> 分钟 的映射 ----
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

    # ---- 写入 routes ----
    rows = []
    DEFAULT_MIN = 1.0  # 查不到分钟时的默认值（仅用于 Dijkstra 权重）
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

# ---------------- 一键初始化 ----------------
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

# ---------------- 查询 ----------------
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

# ---------------- 路线规划：最短站数 / 最短时间 ----------------
def get_route_shortest(conn: sqlite3.Connection, origin_id: int, destination_id: int, mode: str = "stops"):
    """
    mode = 'stops' 使用 BFS（每条边权重=1）
    mode = 'time'  使用 Dijkstra（边权重=travel_time_min；若为NULL/<=0，按1）
    返回: dict(path_ids=[...], path_names=[...], total_stops=int, total_time=float|None)
    """
    # 读取图
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

    # BFS（最少站数）
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
        # 回溯路径
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

    # Dijkstra（最短时间）
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
        # 回溯路径
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

    # 未知模式
    return None
