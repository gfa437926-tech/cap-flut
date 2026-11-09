"""منصة عرض التحذيرات الجوية (CAP) على الخرائط التفاعلية — تطبيق Flask.

التشغيل:  python app.py        ثم افتح http://127.0.0.1:5000  (الإدارة: /admin)
"""
import hmac
import json
import logging
import os
import re
import secrets
import time
from functools import wraps

from flask import (Flask, Response, abort, jsonify, redirect, render_template, request,
                   session, url_for)

import cap as capmod
import db
import ingest
from geo import haversine_km

app = Flask(__name__)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  MAX_CONTENT_LENGTH=3 * 1024 * 1024, JSON_AS_ASCII=False)
app.json.ensure_ascii = False


def _persist_secret(name, env, nbytes=24):
    """يقرأ السر من متغير البيئة، وإلا ينشئ ويحفظ واحداً في data/."""
    if os.environ.get(env):
        return os.environ[env], False
    os.makedirs(db.DATA_DIR, exist_ok=True)
    path = os.path.join(db.DATA_DIR, name)
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip(), False
    val = secrets.token_urlsafe(nbytes)
    with open(path, "w", encoding="utf-8") as f:
        f.write(val)
    os.chmod(path, 0o600)
    return val, True


db.init()
app.secret_key, _ = _persist_secret("secret_key.txt", "CAPW_SECRET_KEY", 32)
ADMIN_PASSWORD, _new_pw = _persist_secret("admin_password.txt", "ADMIN_PASSWORD", 12)
API_TOKEN, _new_tok = _persist_secret("api_token.txt", "CAP_API_TOKEN", 24)

SEV_ORDER = {s: i for i, s in enumerate(capmod.SEVERITIES)}
_login_fail = {}


# ======================= أدوات =======================

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            if request.path.startswith("/admin/api/"):
                return jsonify(error="غير مصرّح"), 401
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


def api_error(msg, code=400):
    return jsonify(error=msg), code


def alert_properties(item, lang_pref=("ar", "en")):
    row, alert = item["row"], item["alert"]
    info = capmod.pick_info(alert, lang_pref) or {}
    areas = ", ".join(a["desc"] for a in info.get("areas", []) if a.get("desc"))
    return {
        "id": row["identifier"],
        "sender": row["sender"],
        "senderName": info.get("senderName") or row["sender"],
        "sent": row["sent"],
        "status": row["status"],
        "msgType": row["msg_type"],
        "event": info.get("event"),
        "category": (info.get("categories") or [None])[0],
        "severity": info.get("severity", "Unknown"),
        "urgency": info.get("urgency", "Unknown"),
        "certainty": info.get("certainty", "Unknown"),
        "effective": info.get("effective") or info.get("onset") or row["sent"],
        "expires": info.get("expires"),
        "headline": info.get("headline"),
        "description": info.get("description"),
        "instruction": info.get("instruction"),
        "web": info.get("web"),
        "areaDesc": areas,
        "state": db.alert_state(row),
        "origin": row["origin"],
    }


def feature(item, lang_pref):
    return {"type": "Feature", "id": item["row"]["identifier"],
            "geometry": db.alert_geometry(item["alert"]),
            "properties": alert_properties(item, lang_pref)}


def sort_key(feat):
    p = feat["properties"]
    return (SEV_ORDER.get(p["severity"], 9), p["expires"] or "")


def lang_pref():
    lang = request.args.get("lang", "ar")
    return (lang, "en") if lang != "en" else ("en", "ar")


def parse_latlon():
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except (KeyError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


# ======================= الواجهة العامة =======================

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def api_config():
    s = db.get_settings()
    layers = []
    for l in db.rows("SELECT * FROM layers WHERE enabled=1 ORDER BY sort, name"):
        url = l["url"] or ""
        if "{key}" in url:
            if not s.get("owm_key"):
                continue
            url = url.replace("{key}", s["owm_key"])
        layers.append({"id": l["id"], "name": l["name"], "kind": l["kind"], "url": url,
                       "opacity": l["opacity"], "maxZoom": l["max_zoom"], "attribution": l["attribution"]})
    return jsonify(center=[float(s["map_lat"]), float(s["map_lon"])], zoom=int(s["map_zoom"]), layers=layers)


@app.get("/api/places")
def api_places():
    return jsonify(db.rows("SELECT id,name,name_en,lat,lon FROM places ORDER BY name"))


@app.get("/api/alerts")
def api_alerts():
    """GeoJSON FeatureCollection للتحذيرات النشطة. اختياري: lat/lon لتعليم التحذيرات التي تؤثر على النقطة."""
    include_future = request.args.get("future") == "1"
    include_tests = db.get_settings().get("show_tests") == "1"
    items = db.list_alerts(active_only=True, include_tests=include_tests, include_future=include_future)
    feats = [feature(i, lang_pref()) for i in items if i["alert"]["infos"]]
    ll = parse_latlon()
    by_id = {i["row"]["identifier"]: i for i in items}
    if ll:
        lat, lon = ll
        for f in feats:
            f["properties"]["affectsPoint"] = db.alert_affects_point(by_id[f["id"]]["alert"], lon, lat)
    sev = request.args.get("severity")
    if sev:
        wanted = set(sev.split(","))
        feats = [f for f in feats if f["properties"]["severity"] in wanted]
    feats.sort(key=sort_key)
    return jsonify(type="FeatureCollection", features=feats, generatedAt=capmod.iso(capmod.now_utc()))


@app.get("/api/alerts/at")
def api_alerts_at():
    ll = parse_latlon()
    if not ll:
        return api_error("lat/lon مطلوبان وصالحان")
    lat, lon = ll
    include_tests = db.get_settings().get("show_tests") == "1"
    out = []
    for i in db.list_alerts(True, include_tests):
        if i["alert"]["infos"] and db.alert_affects_point(i["alert"], lon, lat):
            out.append(alert_properties(i, lang_pref()))
    out.sort(key=lambda p: (SEV_ORDER.get(p["severity"], 9), p["expires"] or ""))
    return jsonify(lat=lat, lon=lon, count=len(out), alerts=out)


@app.get("/api/alerts/<path:ident>/cap.xml")
def api_alert_xml(ident):
    item = db.get_alert(ident)
    if not item or item["row"]["status"] in ("Draft", "System"):
        abort(404)
    return Response(item["row"]["cap_xml"], mimetype="application/cap+xml")


@app.get("/api/alerts/<path:ident>")
def api_alert_one(ident):
    item = db.get_alert(ident)
    if not item or item["row"]["status"] in ("Draft", "System"):
        abort(404)
    return jsonify(feature(item, lang_pref()))


# ======================= استقبال CAP عبر API =======================

@app.post("/api/cap")
def api_cap_ingest():
    """استقبال رسالة CAP (أو خلاصة) عبر POST. الرأس: Authorization: Bearer <token> أو X-API-Key."""
    token = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, API_TOKEN):
        return api_error("رمز API غير صالح", 401)
    try:
        stats = ingest.ingest_bytes(request.get_data(), origin="api")
    except capmod.CapError as e:
        return api_error(str(e))
    return jsonify(stats), (200 if not stats["errors"] or stats["new"] or stats["duplicate"] else 422)


# ======================= الإدارة =======================

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        fails = [t for t in _login_fail.get(ip, []) if time.time() - t < 600]
        if len(fails) >= 8:
            err = "محاولات كثيرة، حاول بعد عدة دقائق"
        elif hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin"))
        else:
            fails.append(time.time())
            _login_fail[ip] = fails
            err = "كلمة المرور غير صحيحة"
    return render_template("login.html", error=err)


@app.get("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.get("/admin")
@admin_required
def admin():
    return render_template("admin.html", api_token=API_TOKEN, enums={
        "severities": capmod.SEVERITIES, "urgencies": capmod.URGENCIES,
        "certainties": capmod.CERTAINTIES, "categories": capmod.CATEGORIES})


@app.get("/admin/api/alerts")
@admin_required
def admin_alerts():
    out = []
    for r in db.rows("SELECT * FROM alerts ORDER BY sent DESC LIMIT 300"):
        out.append(alert_properties({"row": r, "alert": json.loads(r["data"])}))
    return jsonify(out)


@app.get("/admin/api/alerts/<path:ident>")
@admin_required
def admin_alert_one(ident):
    item = db.get_alert(ident)
    if not item:
        abort(404)
    return jsonify(feature(item, ("ar", "en")))


@app.post("/admin/api/alerts")
@admin_required
def admin_create_alert():
    """ينشئ تحذيراً من مضلعات مرسومة على الخريطة. إن وُجد replaces فهو تحديث (Update) لتحذير سابق."""
    d = request.get_json(silent=True) or {}
    s = db.get_settings()
    try:
        polygons = [[[float(x), float(y)] for x, y in p] for p in d.get("polygons", [])]
        refs, msg_type = [], "Alert"
        if d.get("replaces"):
            old = db.get_alert(d["replaces"])
            if not old:
                return api_error("التحذير المراد تحديثه غير موجود", 404)
            refs = [{"sender": old["row"]["sender"], "identifier": old["row"]["identifier"], "sent": old["row"]["sent"]}]
            msg_type = "Update"
        alert = capmod.make_alert(
            sender=s["sender_id"], sender_name=d.get("senderName") or s["sender_name"],
            event=(d.get("event") or "").strip(), severity=d.get("severity", "Moderate"),
            urgency=d.get("urgency", "Expected"), certainty=d.get("certainty", "Likely"),
            category=d.get("category", "Met"),
            headline=(d.get("headline") or d.get("event") or "").strip(),
            description=(d.get("description") or "").strip(), instruction=(d.get("instruction") or "").strip(),
            polygons=polygons, area_desc=(d.get("areaDesc") or "المنطقة المحددة").strip(),
            effective=d.get("effective") or None, expires=d.get("expires") or None,
            hours_valid=float(d.get("hoursValid") or 6), status=d.get("status", "Actual"),
            msg_type=msg_type, references=refs, language=d.get("language", "ar"))
        if not alert["infos"][0]["event"]:
            return api_error("اسم الحدث مطلوب")
    except (capmod.CapError, ValueError, TypeError) as e:
        return api_error(str(e))
    ident, st = db.save_alert(alert, origin="admin")
    return jsonify(id=ident, status=st), 201


@app.post("/admin/api/alerts/<path:ident>/cancel")
@admin_required
def admin_cancel(ident):
    """إلغاء: يُنشئ رسالة Cancel رسمية ويعلّم الأصل ملغى."""
    old = db.get_alert(ident)
    if not old:
        abort(404)
    s = db.get_settings()
    info = capmod.pick_info(old["alert"]) or {}
    now = capmod.now_utc()
    cancel = {
        "identifier": capmod.new_identifier(s["sender_id"]), "sender": s["sender_id"],
        "sent": capmod.iso(now), "status": old["row"]["status"], "msgType": "Cancel", "scope": "Public",
        "references": [{"sender": old["row"]["sender"], "identifier": ident, "sent": old["row"]["sent"]}],
        "infos": [{"language": info.get("language", "ar"), "categories": info.get("categories") or ["Met"],
                   "event": info.get("event", ""), "responseTypes": [], "urgency": "Past",
                   "severity": info.get("severity", "Unknown"), "certainty": info.get("certainty", "Unknown"),
                   "effective": capmod.iso(now), "onset": None, "expires": None,
                   "senderName": s["sender_name"], "headline": "إلغاء: " + (info.get("headline") or ""),
                   "description": "", "instruction": "", "web": "", "contact": "", "areas": []}],
    }
    db.save_alert(cancel, origin="admin")
    db.cancel_alert(ident)
    return jsonify(ok=True)


@app.delete("/admin/api/alerts/<path:ident>")
@admin_required
def admin_delete(ident):
    return jsonify(ok=db.delete_alert(ident))


@app.post("/admin/api/upload")
@admin_required
def admin_upload():
    f = request.files.get("file")
    if not f:
        return api_error("لم يُرفع ملف")
    try:
        stats = ingest.ingest_bytes(f.read(), origin="admin")
    except capmod.CapError as e:
        return api_error(str(e))
    return jsonify(stats)


# ---- المصادر ----

@app.get("/admin/api/sources")
@admin_required
def sources_list():
    return jsonify(db.rows("SELECT * FROM sources ORDER BY id"))


@app.post("/admin/api/sources")
@admin_required
def sources_add():
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return api_error("الرابط يجب أن يبدأ بـ http:// أو https://")
    interval = max(60, int(d.get("interval_s") or 300))
    sid = db.execute("INSERT INTO sources(name,url,interval_s) VALUES (?,?,?)",
                     ((d.get("name") or url)[:100], url, interval))
    return jsonify(id=sid), 201


@app.patch("/admin/api/sources/<int:sid>")
@admin_required
def sources_toggle(sid):
    d = request.get_json(silent=True) or {}
    db.execute("UPDATE sources SET enabled=? WHERE id=?", (1 if d.get("enabled") else 0, sid))
    return jsonify(ok=True)


@app.delete("/admin/api/sources/<int:sid>")
@admin_required
def sources_del(sid):
    db.execute("DELETE FROM sources WHERE id=?", (sid,))
    return jsonify(ok=True)


@app.post("/admin/api/sources/<int:sid>/poll")
@admin_required
def sources_poll(sid):
    rows = db.rows("SELECT * FROM sources WHERE id=?", (sid,))
    if not rows:
        abort(404)
    return jsonify(status=ingest.poll_source(rows[0]))


# ---- الأماكن ----

@app.post("/admin/api/places")
@admin_required
def places_add():
    d = request.get_json(silent=True) or {}
    try:
        lat, lon = float(d["lat"]), float(d["lon"])
        assert -90 <= lat <= 90 and -180 <= lon <= 180 and d.get("name", "").strip()
    except (KeyError, ValueError, TypeError, AssertionError):
        return api_error("اسم وإحداثيات صالحة مطلوبة")
    pid = db.execute("INSERT INTO places(name,name_en,lat,lon) VALUES (?,?,?,?)",
                     (d["name"].strip(), (d.get("name_en") or "").strip(), lat, lon))
    return jsonify(id=pid), 201


@app.delete("/admin/api/places/<int:pid>")
@admin_required
def places_del(pid):
    db.execute("DELETE FROM places WHERE id=?", (pid,))
    return jsonify(ok=True)


# ---- الطبقات والإعدادات ----

@app.get("/admin/api/layers")
@admin_required
def layers_list():
    return jsonify(db.rows("SELECT * FROM layers ORDER BY sort, name"))


@app.post("/admin/api/layers")
@admin_required
def layers_add():
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()
    if not re.match(r"^https://.*\{z\}.*\{x\}.*\{y\}", url):
        return api_error("قالب البلاطات يجب أن يكون https ويحتوي {z}/{x}/{y}")
    lid = "custom_" + secrets.token_hex(3)
    db.execute("INSERT INTO layers VALUES (?,?,?,?,?,?,?,1,99)",
               (lid, (d.get("name") or lid)[:80], "tile", url, float(d.get("opacity") or 0.6),
                int(d.get("max_zoom") or 18), (d.get("attribution") or "")[:120]))
    return jsonify(id=lid), 201


@app.patch("/admin/api/layers/<lid>")
@admin_required
def layers_toggle(lid):
    d = request.get_json(silent=True) or {}
    if "enabled" in d:
        db.execute("UPDATE layers SET enabled=? WHERE id=?", (1 if d["enabled"] else 0, lid))
    if "opacity" in d:
        db.execute("UPDATE layers SET opacity=? WHERE id=?", (min(1, max(0.1, float(d["opacity"]))), lid))
    return jsonify(ok=True)


@app.delete("/admin/api/layers/<lid>")
@admin_required
def layers_del(lid):
    if lid.startswith("custom_"):
        db.execute("DELETE FROM layers WHERE id=?", (lid,))
    return jsonify(ok=True)


@app.get("/admin/api/settings")
@admin_required
def settings_get():
    return jsonify(db.get_settings())


@app.put("/admin/api/settings")
@admin_required
def settings_put():
    d = request.get_json(silent=True) or {}
    allowed = {"sender_id", "sender_name", "owm_key", "map_lat", "map_lon", "map_zoom", "show_tests"}
    clean = {k: str(v).strip() for k, v in d.items() if k in allowed}
    for k in ("map_lat", "map_lon", "map_zoom"):
        if k in clean:
            try:
                float(clean[k])
            except ValueError:
                return api_error(f"قيمة {k} غير صالحة")
    db.set_settings(clean)
    return jsonify(ok=True)


@app.get("/api/openapi.json")
def api_openapi():
    from openapi import SPEC
    return jsonify(SPEC)


# CORS لواجهة القراءة العامة فقط (يلزم لتطبيق فلاتر ويب). قيّد الأصول عبر CAPW_CORS_ORIGINS.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CAPW_CORS_ORIGINS", "*").split(",") if o.strip()]


@app.after_request
def headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.method == "GET" and request.path.startswith("/api/"):
        origin = request.headers.get("Origin", "")
        if "*" in CORS_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = "*"
        elif origin in CORS_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
    return resp


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if _new_pw or _new_tok:
        print("\n=== أسرار تم توليدها (محفوظة في مجلد data/) ===")
        print(f"كلمة مرور الإدارة : {ADMIN_PASSWORD}")
        print(f"رمز API لاستقبال CAP: {API_TOKEN}\n")
    ingest.start_background()
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
