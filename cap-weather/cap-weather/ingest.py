"""استقبال CAP من مصادر خارجية: ملف CAP مباشر، أو خلاصة Atom/RSS تشير إلى ملفات CAP."""
import logging
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from lxml import etree

import cap as capmod
import db

log = logging.getLogger("ingest")
UA = "CAP-Weather-Warnings/1.0"
MAX_BYTES = 2_000_000


def _fetch(url):
    r = requests.get(url, timeout=20, headers={"User-Agent": UA}, stream=True)
    r.raise_for_status()
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(data) > MAX_BYTES:
        raise capmod.CapError("الاستجابة أكبر من الحد المسموح")
    return data


def _local(tag):
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def ingest_bytes(data, origin):
    """يعالج بايتات قد تكون alert واحداً أو خلاصة. يعيد dict بالإحصاءات."""
    stats = {"new": 0, "duplicate": 0, "errors": []}
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as e:
        raise capmod.CapError(f"XML غير صالح: {e}")
    name = _local(root.tag)
    if name == "alert":
        _save(root, origin, stats)
    elif name in ("feed", "rss", "RDF"):
        _ingest_feed(root, origin, stats)
    else:
        raise capmod.CapError(f"نوع جذر غير مدعوم: {name}")
    return stats


def _save(alert_el, origin, stats):
    try:
        alert = capmod.parse_alert_element(alert_el)
        xml = etree.tostring(alert_el, encoding="unicode")
        _, st = db.save_alert(alert, origin=origin, xml=xml)
        stats[st] += 1
    except capmod.CapError as e:
        stats["errors"].append(str(e))


def _ingest_feed(root, origin, stats, base_url=""):
    links = []
    for el in root.iter():
        n = _local(el.tag)
        if n == "alert":  # CAP مضمّن داخل الخلاصة
            _save(el, origin, stats)
        elif n == "link":
            href = el.get("href") or (el.text or "").strip()
            typ = (el.get("type") or "").lower()
            if href and (("cap" in typ) or href.lower().endswith((".xml", ".cap"))) and el.get("rel") != "self":
                links.append(urljoin(base_url, href))
    for url in links[:100]:
        try:
            _save(etree.fromstring(_fetch(url), etree.XMLParser(resolve_entities=False, no_network=True)), origin, stats)
        except Exception as e:  # noqa: BLE001
            stats["errors"].append(f"{url}: {e}")


def poll_source(src):
    origin = f"feed:{src['id']}"
    status = "ok"
    try:
        data = _fetch(src["url"])
        stats = ingest_bytes(data, origin)
        status = f"ok: {stats['new']} جديد، {stats['duplicate']} مكرر"
        if stats["errors"]:
            status += f"، {len(stats['errors'])} خطأ: {stats['errors'][0][:120]}"
    except Exception as e:  # noqa: BLE001
        status = f"فشل: {str(e)[:200]}"
        log.warning("source %s failed: %s", src["id"], e)
    db.execute("UPDATE sources SET last_run=?, last_status=? WHERE id=?",
               (capmod.iso(capmod.now_utc()), status, src["id"]))
    return status


def _loop(stop):
    while not stop.is_set():
        try:
            now = datetime.now(timezone.utc)
            for src in db.rows("SELECT * FROM sources WHERE enabled=1"):
                last = capmod.parse_time(src["last_run"]) if src["last_run"] else None
                if not last or (now - last).total_seconds() >= src["interval_s"]:
                    poll_source(src)
        except Exception:  # noqa: BLE001
            log.exception("ingest loop error")
        stop.wait(15)


def start_background():
    stop = threading.Event()
    t = threading.Thread(target=_loop, args=(stop,), daemon=True, name="cap-ingest")
    t.start()
    return stop
