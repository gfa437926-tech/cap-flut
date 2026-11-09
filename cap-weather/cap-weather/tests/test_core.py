import os
import sys
import tempfile
import unittest

# قاعدة بيانات مؤقتة قبل استيراد التطبيق
os.environ["CAPW_DATA_DIR"] = tempfile.mkdtemp()
os.environ["ADMIN_PASSWORD"] = "test-pass"
os.environ["CAP_API_TOKEN"] = "test-token"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cap  # noqa: E402
import geo  # noqa: E402
from app import app  # noqa: E402

SQUARE = [[36.0, 33.0], [37.0, 33.0], [37.0, 34.0], [36.0, 34.0]]  # lon,lat حول دمشق (36.27, 33.51)


def cap_xml(ident="x-1", msg="Alert", refs="", expires="2999-01-01T00:00:00+00:00", status="Actual"):
    ref = f"<references>{refs}</references>" if refs else ""
    return f"""<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
<identifier>{ident}</identifier><sender>met.test</sender><sent>2026-11-09T00:00:00+03:00</sent>
<status>{status}</status><msgType>{msg}</msgType><scope>Public</scope>{ref}
<info><language>en</language><category>Met</category><event>Heavy Rain</event><urgency>Expected</urgency>
<severity>Severe</severity><certainty>Likely</certainty><expires>{expires}</expires>
<headline>Heavy rain</headline>
<area><areaDesc>Test</areaDesc><polygon>33,36 33,37 34,37 34,36 33,36</polygon></area></info>
</alert>"""


class GeoTests(unittest.TestCase):
    def test_pip(self):
        ring = SQUARE + [SQUARE[0]]
        self.assertTrue(geo.point_in_ring(36.5, 33.5, ring))
        self.assertFalse(geo.point_in_ring(38, 33.5, ring))

    def test_hole(self):
        outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
        self.assertFalse(geo.point_in_polygon(5, 5, [outer, hole]))
        self.assertTrue(geo.point_in_polygon(1, 1, [outer, hole]))

    def test_circle(self):
        ring = geo.circle_to_ring(36.0, 33.0, 10)
        self.assertTrue(geo.point_in_ring(36.0, 33.0, ring))
        self.assertAlmostEqual(geo.haversine_km(36.0, 33.0, ring[0][0], ring[0][1]), 10, delta=0.1)

    def test_invalid_ring(self):
        self.assertFalse(geo.valid_ring([[0, 0], [1, 1]]))
        self.assertFalse(geo.valid_ring([[0, 0], [200, 1], [1, 5]]))


class CapTests(unittest.TestCase):
    def test_parse(self):
        a = cap.parse_cap(cap_xml())
        self.assertEqual(a["identifier"], "x-1")
        self.assertEqual(a["sent"], "2025-11-08T21:00:00Z".replace("2025", "2026"))
        info = a["infos"][0]
        self.assertEqual(info["severity"], "Severe")
        self.assertEqual(info["areas"][0]["polygons"][0][0], [36.0, 33.0])

    def test_bad(self):
        with self.assertRaises(cap.CapError):
            cap.parse_cap("<alert>")
        with self.assertRaises(cap.CapError):
            cap.parse_cap("<foo/>")
        with self.assertRaises(cap.CapError):
            cap.parse_cap('<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>a</identifier></alert>')

    def test_xxe_not_resolved(self):
        evil = '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><alert><identifier>&x;</identifier></alert>'
        with self.assertRaises(cap.CapError):
            cap.parse_cap(evil)

    def test_roundtrip(self):
        a = cap.make_alert(sender="s", sender_name="n", event="e", severity="Severe", urgency="Expected",
                           certainty="Likely", category="Met", headline="h", description="d<&>", instruction="i",
                           polygons=[SQUARE], area_desc="a")
        b = cap.parse_cap(cap.build_cap_xml(a))
        self.assertEqual(b["infos"][0]["description"], "d<&>")
        self.assertEqual(len(b["infos"][0]["areas"][0]["polygons"][0]), 5)

    def test_expiry_before_start(self):
        with self.assertRaises(cap.CapError):
            cap.make_alert(sender="s", sender_name="n", event="e", severity="Severe", urgency="Expected",
                           certainty="Likely", category="Met", headline="h", description="", instruction="",
                           polygons=[SQUARE], area_desc="a",
                           effective="2026-01-02T00:00:00Z", expires="2026-01-01T00:00:00Z")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.c = app.test_client()

    def login(self):
        r = self.c.post("/admin/login", data={"password": "test-pass"})
        self.assertEqual(r.status_code, 302)

    def post_cap(self, xml, token="test-token"):
        return self.c.post("/api/cap", data=xml.encode(), headers={"Authorization": f"Bearer {token}"})

    def test_01_auth(self):
        self.assertEqual(self.c.get("/admin/api/alerts").status_code, 401)
        self.assertEqual(self.c.get("/admin").status_code, 302)
        self.assertEqual(self.c.post("/api/cap", data=cap_xml()).status_code, 401)
        self.assertEqual(self.post_cap(cap_xml(), "wrong").status_code, 401)
        bad = self.c.post("/admin/login", data={"password": "nope"})
        self.assertEqual(bad.status_code, 200)

    def test_02_ingest_and_query(self):
        r = self.post_cap(cap_xml("ing-1"))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.get_json()["new"], 1)
        self.assertEqual(self.post_cap(cap_xml("ing-1")).get_json()["duplicate"], 1)  # تكرار
        fc = self.c.get("/api/alerts").get_json()
        ids = [f["id"] for f in fc["features"]]
        self.assertIn("ing-1", ids)
        f = [f for f in fc["features"] if f["id"] == "ing-1"][0]
        self.assertEqual(f["geometry"]["type"], "MultiPolygon")
        self.assertEqual(f["properties"]["severity"], "Severe")
        inside = self.c.get("/api/alerts/at?lat=33.5&lon=36.5").get_json()
        outside = self.c.get("/api/alerts/at?lat=36.2&lon=37.1").get_json()
        self.assertIn("ing-1", [a["id"] for a in inside["alerts"]])
        self.assertNotIn("ing-1", [a["id"] for a in outside["alerts"]])
        self.assertEqual(self.c.get("/api/alerts/at?lat=abc&lon=1").status_code, 400)
        marked = self.c.get("/api/alerts?lat=33.5&lon=36.5").get_json()["features"]
        self.assertTrue([m for m in marked if m["id"] == "ing-1"][0]["properties"]["affectsPoint"])
        self.assertEqual(self.c.get("/api/alerts/ing-1/cap.xml").status_code, 200)

    def test_03_update_cancel_expired_test(self):
        self.post_cap(cap_xml("u-1"))
        self.post_cap(cap_xml("u-2", "Update", "met.test,u-1,2026-11-09T00:00:00+03:00"))
        ids = [f["id"] for f in self.c.get("/api/alerts").get_json()["features"]]
        self.assertNotIn("u-1", ids)   # استُبدل
        self.assertIn("u-2", ids)
        self.post_cap(cap_xml("u-3", "Cancel", "met.test,u-2,2026-11-09T00:00:00+03:00"))
        ids = [f["id"] for f in self.c.get("/api/alerts").get_json()["features"]]
        self.assertNotIn("u-2", ids)
        self.assertNotIn("u-3", ids)
        self.post_cap(cap_xml("e-1", expires="2020-01-01T00:00:00Z"))
        self.post_cap(cap_xml("t-1", status="Test"))
        ids = [f["id"] for f in self.c.get("/api/alerts").get_json()["features"]]
        self.assertNotIn("e-1", ids)   # منتهٍ
        self.assertNotIn("t-1", ids)   # تجريبي لا يظهر للجمهور

    def test_04_bad_cap(self):
        self.assertEqual(self.post_cap("<alert>").status_code, 400)
        self.assertEqual(self.post_cap("<x/>").status_code, 400)

    def test_05_admin_create_cancel(self):
        self.login()
        body = {"event": "عاصفة رعدية", "severity": "Extreme", "urgency": "Immediate", "certainty": "Observed",
                "headline": "h", "description": "d", "instruction": "i", "areaDesc": "دمشق",
                "polygons": [SQUARE], "hoursValid": 3}
        r = self.c.post("/admin/api/alerts", json=body)
        self.assertEqual(r.status_code, 201, r.data)
        ident = r.get_json()["id"]
        active = {f["id"]: f for f in self.c.get("/api/alerts").get_json()["features"]}
        self.assertIn(ident, active)
        self.assertEqual(active[ident]["properties"]["event"], "عاصفة رعدية")
        # مضلع غير صالح ومنطقة مفقودة وخطورة غير صالحة
        self.assertEqual(self.c.post("/admin/api/alerts", json={**body, "polygons": []}).status_code, 400)
        self.assertEqual(self.c.post("/admin/api/alerts", json={**body, "polygons": [[[0, 0], [1, 1]]]}).status_code, 400)
        self.assertEqual(self.c.post("/admin/api/alerts", json={**body, "severity": "Bogus"}).status_code, 400)
        self.assertEqual(self.c.post("/admin/api/alerts", json={**body, "event": " "}).status_code, 400)
        # تحديث
        r2 = self.c.post("/admin/api/alerts", json={**body, "severity": "Severe", "replaces": ident})
        self.assertEqual(r2.status_code, 201)
        ids = [f["id"] for f in self.c.get("/api/alerts").get_json()["features"]]
        self.assertNotIn(ident, ids)
        self.assertIn(r2.get_json()["id"], ids)
        # إلغاء
        self.assertEqual(self.c.post(f"/admin/api/alerts/{r2.get_json()['id']}/cancel").status_code, 200)
        ids = [f["id"] for f in self.c.get("/api/alerts").get_json()["features"]]
        self.assertNotIn(r2.get_json()["id"], ids)

    def test_06_settings_layers(self):
        self.login()
        cfg = self.c.get("/api/config").get_json()
        self.assertEqual([l["id"] for l in cfg["layers"]], ["radar"])  # طبقات OWM مخفية بلا مفتاح
        self.c.put("/admin/api/settings", json={"owm_key": "abc"})
        for lid in ("owm_wind",):
            self.c.patch(f"/admin/api/layers/{lid}", json={"enabled": True})
        cfg = self.c.get("/api/config").get_json()
        self.assertIn("owm_wind", [l["id"] for l in cfg["layers"]])
        self.assertEqual(self.c.post("/admin/api/layers", json={"name": "x", "url": "http://a/{z}/{x}/{y}"}).status_code, 400)

    def test_08_cors_openapi(self):
        r = self.c.get("/api/alerts", headers={"Origin": "http://localhost:5555"})
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "*")
        spec = self.c.get("/api/openapi.json").get_json()
        self.assertEqual(spec["openapi"], "3.0.3")
        self.assertIn("/api/alerts/at", spec["paths"])
        # لا CORS على لوحة الإدارة
        self.assertIsNone(self.c.get("/admin/login", headers={"Origin": "http://x"}).headers.get("Access-Control-Allow-Origin"))

    def test_07_pages(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.get("/api/places").status_code, 200)
        self.login()
        self.assertEqual(self.c.get("/admin").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
