"""تخزين SQLite: التحذيرات، الأماكن، مصادر CAP، طبقات الخرائط، الإعدادات."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

import cap as capmod
from geo import bbox_of_rings, haversine_km, point_in_polygon

DATA_DIR = os.environ.get("CAPW_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "capweather.db")
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    identifier   TEXT PRIMARY KEY,
    sender       TEXT NOT NULL,
    sent         TEXT NOT NULL,
    status       TEXT NOT NULL,
    msg_type     TEXT NOT NULL,
    event        TEXT, severity TEXT, urgency TEXT, certainty TEXT, category TEXT,
    effective    TEXT, expires TEXT,
    headline     TEXT,
    bbox         TEXT,
    origin       TEXT,              -- admin | api | feed:<id>
    cancelled    INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT,
    data         TEXT NOT NULL,     -- JSON كامل
    cap_xml      TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_exp ON alerts(expires);
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, name_en TEXT, lat REAL NOT NULL, lon REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, url TEXT NOT NULL,
    interval_s INTEGER NOT NULL DEFAULT 300,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run TEXT, last_status TEXT
);
CREATE TABLE IF NOT EXISTS layers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,             -- rainviewer | tile
    url TEXT,                       -- قالب XYZ، ويدعم {key}
    opacity REAL NOT NULL DEFAULT 0.6,
    max_zoom INTEGER NOT NULL DEFAULT 18,
    attribution TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_PLACES = [
    ("دمشق", "Damascus", 33.5138, 36.2765),
    ("حلب", "Aleppo", 36.2021, 37.1343),
    ("حمص", "Homs", 34.7324, 36.7137),
    ("حماة", "Hama", 35.1318, 36.7578),
    ("اللاذقية", "Latakia", 35.5317, 35.7915),
    ("طرطوس", "Tartus", 34.8890, 35.8866),
    ("دير الزور", "Deir ez-Zor", 35.3359, 40.1408),
    ("درعا", "Daraa", 32.6189, 36.1021),
    ("السويداء", "As-Suwayda", 32.7089, 36.5695),
    ("إدلب", "Idlib", 35.9306, 36.6339),
    ("الحسكة", "Al-Hasakah", 36.5024, 40.7477),
    ("الرقة", "Raqqa", 35.9528, 39.0079),
]

DEFAULT_LAYERS = [
    # id, name, kind, url, opacity, max_zoom, attribution, enabled, sort
    ("radar", "رادار الأمطار (RainViewer)", "rainviewer", None, 0.65, 7, "© RainViewer", 1, 1),
    ("owm_precip", "هطول الأمطار (OpenWeatherMap)", "tile",
     "https://tile.openweathermap.org/map/precipitation_new/{z}/{x}/{y}.png?appid={key}", 0.7, 18, "© OpenWeatherMap", 0, 2),
    ("owm_wind", "الرياح (OpenWeatherMap)", "tile",
     "https://tile.openweathermap.org/map/wind_new/{z}/{x}/{y}.png?appid={key}", 0.7, 18, "© OpenWeatherMap", 0, 3),
    ("owm_clouds", "الغيوم (OpenWeatherMap)", "tile",
     "https://tile.openweathermap.org/map/clouds_new/{z}/{x}/{y}.png?appid={key}", 0.6, 18, "© OpenWeatherMap", 0, 4),
    ("owm_pressure", "الضغط الجوي (OpenWeatherMap)", "tile",
     "https://tile.openweathermap.org/map/pressure_new/{z}/{x}/{y}.png?appid={key}", 0.6, 18, "© OpenWeatherMap", 0, 5),
]


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init():
    os.makedirs(DATA_DIR, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        if not c.execute("SELECT 1 FROM places LIMIT 1").fetchone():
            c.executemany("INSERT INTO places(name,name_en,lat,lon) VALUES (?,?,?,?)", DEFAULT_PLACES)
        if not c.execute("SELECT 1 FROM layers LIMIT 1").fetchone():
            c.executemany("INSERT INTO layers VALUES (?,?,?,?,?,?,?,?,?)", DEFAULT_LAYERS)
        defaults = {"sender_id": "weather.local", "sender_name": "هيئة الأرصاد",
                    "owm_key": "", "map_lat": "34.8", "map_lon": "38.5", "map_zoom": "6",
                    "show_tests": "0"}
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k, v))


# ---------- الإعدادات ----------

def get_settings():
    with conn() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings")}


def set_settings(d):
    with conn() as c:
        for k, v in d.items():
            c.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (k, str(v)))


# ---------- التحذيرات ----------

def save_alert(alert, origin="api", xml=None):
    """يحفظ تحذيراً ويطبّق منطق Update/Cancel. يعيد (identifier, 'new'|'duplicate')."""
    info = capmod.pick_info(alert)
    polys = capmod.alert_features(alert, info)
    bbox = bbox_of_rings(polys)
    if xml is None:
        xml = capmod.build_cap_xml(alert)
    with conn() as c:
        if c.execute("SELECT 1 FROM alerts WHERE identifier=?", (alert["identifier"],)).fetchone():
            return alert["identifier"], "duplicate"
        c.execute(
            """INSERT INTO alerts(identifier,sender,sent,status,msg_type,event,severity,urgency,certainty,
               category,effective,expires,headline,bbox,origin,data,cap_xml,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (alert["identifier"], alert["sender"], alert["sent"], alert["status"], alert["msgType"],
             info and info["event"], info and info["severity"], info and info["urgency"],
             info and info["certainty"], info and (info["categories"] or ["Met"])[0],
             info and (info["effective"] or info["onset"] or alert["sent"]), info and info["expires"],
             info and info["headline"], json.dumps(bbox), origin,
             json.dumps(alert, ensure_ascii=False), xml, capmod.iso(capmod.now_utc())))
        # Update/Cancel: الرسائل المشار إليها تُلغى/تُستبدل
        if alert["msgType"] in ("Update", "Cancel"):
            for ref in alert.get("references", []):
                c.execute("UPDATE alerts SET cancelled=1, superseded_by=? WHERE identifier=? AND sender=?",
                          (alert["identifier"], ref["identifier"], ref["sender"]))
    return alert["identifier"], "new"


def cancel_alert(identifier):
    with conn() as c:
        cur = c.execute("UPDATE alerts SET cancelled=1 WHERE identifier=?", (identifier,))
        return cur.rowcount > 0


def delete_alert(identifier):
    with conn() as c:
        cur = c.execute("DELETE FROM alerts WHERE identifier=?", (identifier,))
        return cur.rowcount > 0


def _row_to_alert(row):
    data = json.loads(row["data"])
    return {"row": dict(row), "alert": data}


def is_active(row, now_iso, include_tests=False):
    if row["cancelled"] or row["msg_type"] in ("Cancel", "Ack", "Error"):
        return False
    if row["status"] != "Actual" and not (include_tests and row["status"] in ("Test", "Exercise")):
        return False
    if row["status"] == "Draft" or row["status"] == "System":
        return False
    if row["effective"] and row["effective"] > now_iso:
        return False
    if row["expires"] and row["expires"] <= now_iso:
        return False
    return True


def list_alerts(active_only=True, include_tests=False, include_future=False, limit=500):
    now_iso = capmod.iso(capmod.now_utc())
    with conn() as c:
        rows = c.execute("SELECT * FROM alerts ORDER BY sent DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        if active_only:
            if include_future:
                # نشط أو مجدول لاحقاً
                if r["cancelled"] or r["msg_type"] in ("Cancel", "Ack", "Error") or \
                        (r["expires"] and r["expires"] <= now_iso) or \
                        (r["status"] != "Actual" and not (include_tests and r["status"] in ("Test", "Exercise"))):
                    continue
            elif not is_active(r, now_iso, include_tests):
                continue
        out.append(_row_to_alert(r))
    return out


def get_alert(identifier):
    with conn() as c:
        r = c.execute("SELECT * FROM alerts WHERE identifier=?", (identifier,)).fetchone()
    return _row_to_alert(r) if r else None


def alert_state(row):
    now_iso = capmod.iso(capmod.now_utc())
    if row["cancelled"]:
        return "cancelled"
    if row["expires"] and row["expires"] <= now_iso:
        return "expired"
    if row["effective"] and row["effective"] > now_iso:
        return "scheduled"
    return "active"


def alert_geometry(alert):
    """MultiPolygon بصيغة GeoJSON من مناطق التحذير."""
    polys = capmod.alert_features(alert)
    if not polys:
        return None
    return {"type": "MultiPolygon", "coordinates": polys}


def alert_affects_point(alert, lon, lat):
    for rings in capmod.alert_features(alert):
        if point_in_polygon(lon, lat, rings):
            return True
    return False


# ---------- الأماكن والمصادر والطبقات ----------

def rows(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def execute(sql, args=()):
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid
