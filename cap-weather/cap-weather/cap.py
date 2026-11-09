"""قراءة وتوليد رسائل CAP (Common Alerting Protocol) إصدار 1.2 (مع تسامح مع 1.0/1.1)."""
import uuid
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape

from lxml import etree

from geo import circle_to_ring, close_ring, valid_ring

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"

SEVERITIES = ["Extreme", "Severe", "Moderate", "Minor", "Unknown"]
URGENCIES = ["Immediate", "Expected", "Future", "Past", "Unknown"]
CERTAINTIES = ["Observed", "Likely", "Possible", "Unlikely", "Unknown"]
CATEGORIES = ["Met", "Geo", "Safety", "Security", "Rescue", "Fire", "Health", "Env",
              "Transport", "Infra", "CBRNE", "Other"]
RESPONSE_TYPES = ["Shelter", "Evacuate", "Prepare", "Execute", "Avoid", "Monitor",
                  "Assess", "AllClear", "None"]
STATUSES = ["Actual", "Exercise", "System", "Test", "Draft"]
MSG_TYPES = ["Alert", "Update", "Cancel", "Ack", "Error"]


class CapError(ValueError):
    pass


def now_utc():
    return datetime.now(timezone.utc)


def parse_time(s):
    """يقبل ISO8601 بأي إزاحة، ويعيد datetime بتوقيت UTC (أو None)."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise CapError(f"صيغة وقت غير صالحة: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _local(tag):
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _text(el, name, default=None):
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip() or default
    return default


def _parse_polygon(text):
    ring = []
    for pair in text.split():
        try:
            lat, lon = pair.split(",")[:2]
            ring.append([float(lon), float(lat)])
        except ValueError:
            raise CapError(f"مضلع غير صالح: {pair}")
    return close_ring(ring)


def _parse_circle(text):
    try:
        center, radius = text.strip().rsplit(" ", 1)
        lat, lon = center.split(",")
        return float(lon), float(lat), float(radius)
    except ValueError:
        raise CapError(f"دائرة غير صالحة: {text}")


def _parse_area(area_el):
    area = {"desc": _text(area_el, "areaDesc", ""), "polygons": [], "circles": [], "geocodes": []}
    for p in _children(area_el, "polygon"):
        ring = _parse_polygon(p.text or "")
        if not valid_ring(ring):
            raise CapError("مضلع غير صالح (نقاط غير كافية أو إحداثيات خارج النطاق)")
        area["polygons"].append(ring)
    for c in _children(area_el, "circle"):
        lon, lat, r = _parse_circle(c.text or "")
        area["circles"].append({"lon": lon, "lat": lat, "radius_km": r})
    for g in _children(area_el, "geocode"):
        area["geocodes"].append({"name": _text(g, "valueName", ""), "value": _text(g, "value", "")})
    return area


def _parse_info(info_el):
    info = {
        "language": _text(info_el, "language", "en-US"),
        "categories": [(c.text or "").strip() for c in _children(info_el, "category")],
        "event": _text(info_el, "event", ""),
        "responseTypes": [(c.text or "").strip() for c in _children(info_el, "responseType")],
        "urgency": _text(info_el, "urgency", "Unknown"),
        "severity": _text(info_el, "severity", "Unknown"),
        "certainty": _text(info_el, "certainty", "Unknown"),
        "effective": iso(parse_time(_text(info_el, "effective"))),
        "onset": iso(parse_time(_text(info_el, "onset"))),
        "expires": iso(parse_time(_text(info_el, "expires"))),
        "senderName": _text(info_el, "senderName", ""),
        "headline": _text(info_el, "headline", ""),
        "description": _text(info_el, "description", ""),
        "instruction": _text(info_el, "instruction", ""),
        "web": _text(info_el, "web", ""),
        "contact": _text(info_el, "contact", ""),
        "areas": [_parse_area(a) for a in _children(info_el, "area")],
    }
    return info


def parse_cap(xml_bytes):
    """يحلل رسالة CAP واحدة ويعيد dict. يرفع CapError عند الخطأ."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        root = etree.fromstring(xml_bytes, parser)
    except etree.XMLSyntaxError as e:
        raise CapError(f"XML غير صالح: {e}")
    if _local(root.tag) != "alert":
        raise CapError("العنصر الجذر ليس alert")
    return parse_alert_element(root)


def parse_alert_element(root):
    ident = _text(root, "identifier")
    sender = _text(root, "sender")
    sent = _text(root, "sent")
    if not (ident and sender and sent):
        raise CapError("الحقول identifier وsender وsent مطلوبة")
    status = _text(root, "status", "Actual")
    msg_type = _text(root, "msgType", "Alert")
    refs = []
    r = _text(root, "references")
    if r:
        for token in r.split():
            parts = token.split(",")
            if len(parts) >= 2:
                refs.append({"sender": parts[0], "identifier": parts[1], "sent": parts[2] if len(parts) > 2 else None})
    alert = {
        "identifier": ident,
        "sender": sender,
        "sent": iso(parse_time(sent)),
        "status": status,
        "msgType": msg_type,
        "scope": _text(root, "scope", "Public"),
        "references": refs,
        "infos": [_parse_info(i) for i in _children(root, "info")],
    }
    return alert


def pick_info(alert, lang_pref=("ar", "en")):
    """يختار كتلة info الأنسب حسب اللغة."""
    infos = alert.get("infos") or []
    if not infos:
        return None
    for lang in lang_pref:
        for i in infos:
            if (i.get("language") or "").lower().startswith(lang):
                return i
    return infos[0]


def alert_features(alert, info=None):
    """يحوّل مناطق التحذير إلى قائمة حلقات GeoJSON (مضلعات + دوائر مقرّبة)."""
    info = info or pick_info(alert)
    polys = []
    if not info:
        return polys
    for area in info["areas"]:
        for ring in area["polygons"]:
            polys.append([ring])
        for c in area["circles"]:
            polys.append([circle_to_ring(c["lon"], c["lat"], c["radius_km"])])
    return polys


# ---------- التوليد ----------

def new_identifier(sender="local"):
    safe = "".join(ch for ch in sender if ch.isalnum() or ch in ".-_") or "local"
    return f"{safe}-{now_utc().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def build_cap_xml(alert):
    """يبني XML بصيغة CAP 1.2 من dict (نفس بنية parse_cap)."""
    def tag(name, value):
        return f"<{name}>{escape(str(value))}</{name}>" if value not in (None, "") else ""

    out = ['<?xml version="1.0" encoding="UTF-8"?>', f'<alert xmlns="{CAP_NS}">']
    out.append(tag("identifier", alert["identifier"]))
    out.append(tag("sender", alert["sender"]))
    out.append(tag("sent", alert["sent"]))
    out.append(tag("status", alert.get("status", "Actual")))
    out.append(tag("msgType", alert.get("msgType", "Alert")))
    out.append(tag("scope", alert.get("scope", "Public")))
    if alert.get("references"):
        out.append(tag("references", " ".join(
            f'{r["sender"]},{r["identifier"]},{r.get("sent") or ""}' for r in alert["references"])))
    for info in alert.get("infos", []):
        out.append("<info>")
        out.append(tag("language", info.get("language", "ar")))
        for c in info.get("categories") or ["Met"]:
            out.append(tag("category", c))
        out.append(tag("event", info.get("event")))
        for rt in info.get("responseTypes", []):
            out.append(tag("responseType", rt))
        out.append(tag("urgency", info.get("urgency", "Unknown")))
        out.append(tag("severity", info.get("severity", "Unknown")))
        out.append(tag("certainty", info.get("certainty", "Unknown")))
        out.append(tag("effective", info.get("effective")))
        out.append(tag("onset", info.get("onset")))
        out.append(tag("expires", info.get("expires")))
        out.append(tag("senderName", info.get("senderName")))
        out.append(tag("headline", info.get("headline")))
        out.append(tag("description", info.get("description")))
        out.append(tag("instruction", info.get("instruction")))
        out.append(tag("web", info.get("web")))
        out.append(tag("contact", info.get("contact")))
        for area in info.get("areas", []):
            out.append("<area>")
            out.append(tag("areaDesc", area.get("desc") or "—"))
            for ring in area.get("polygons", []):
                out.append(tag("polygon", " ".join(f"{y},{x}" for x, y in ring)))
            for c in area.get("circles", []):
                out.append(tag("circle", f'{c["lat"]},{c["lon"]} {c["radius_km"]}'))
            for g in area.get("geocodes", []):
                out.append(f'<geocode>{tag("valueName", g["name"])}{tag("value", g["value"])}</geocode>')
            out.append("</area>")
        out.append("</info>")
    out.append("</alert>")
    return "\n".join(x for x in out if x)


def make_alert(*, sender, sender_name, event, severity, urgency, certainty, category,
               headline, description, instruction, polygons, area_desc,
               effective=None, expires=None, hours_valid=6, status="Actual",
               msg_type="Alert", references=None, identifier=None, language="ar"):
    """ينشئ dict لتحذير من إدخال لوحة الإدارة. polygons = [[[lon,lat],...], ...]."""
    eff = parse_time(effective) if effective else now_utc()
    exp = parse_time(expires) if expires else eff + timedelta(hours=hours_valid)
    if exp <= eff:
        raise CapError("وقت الانتهاء يجب أن يكون بعد وقت البدء")
    rings = []
    for p in polygons:
        p = close_ring([[float(x), float(y)] for x, y in p])
        if not valid_ring(p):
            raise CapError("مضلع غير صالح")
        rings.append(p)
    if msg_type != "Cancel" and not rings:
        raise CapError("يجب رسم منطقة واحدة على الأقل")
    if severity not in SEVERITIES or urgency not in URGENCIES or certainty not in CERTAINTIES:
        raise CapError("قيمة severity/urgency/certainty غير صالحة")
    return {
        "identifier": identifier or new_identifier(sender),
        "sender": sender,
        "sent": iso(now_utc()),
        "status": status,
        "msgType": msg_type,
        "scope": "Public",
        "references": references or [],
        "infos": [{
            "language": language,
            "categories": [category],
            "event": event,
            "responseTypes": [],
            "urgency": urgency, "severity": severity, "certainty": certainty,
            "effective": iso(eff), "onset": iso(eff), "expires": iso(exp),
            "senderName": sender_name, "headline": headline,
            "description": description, "instruction": instruction,
            "web": "", "contact": "",
            "areas": [{"desc": area_desc, "polygons": rings, "circles": [], "geocodes": []}],
        }],
    }
