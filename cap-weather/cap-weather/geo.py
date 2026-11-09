"""أدوات جغرافية بدون اعتماد على shapely: نقطة داخل مضلع، تحويل دائرة إلى مضلع، صندوق إحاطة."""
import math

EARTH_R_KM = 6371.0088


def point_in_ring(lon, lat, ring):
    """Ray casting. ring = [[lon,lat], ...] (مغلقة أو غير مغلقة)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lon, lat, rings):
    """rings[0] الحلقة الخارجية، والباقي ثقوب (GeoJSON)."""
    if not rings or not point_in_ring(lon, lat, rings[0]):
        return False
    return not any(point_in_ring(lon, lat, hole) for hole in rings[1:])


def haversine_km(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def circle_to_ring(lon, lat, radius_km, steps=48):
    """تقريب دائرة CAP إلى مضلع GeoJSON مغلق."""
    ring = []
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    d = radius_km / EARTH_R_KM
    for k in range(steps):
        brg = 2 * math.pi * k / steps
        lat2 = math.asin(math.sin(lat_r) * math.cos(d) + math.cos(lat_r) * math.sin(d) * math.cos(brg))
        lon2 = lon_r + math.atan2(math.sin(brg) * math.sin(d) * math.cos(lat_r),
                                  math.cos(d) - math.sin(lat_r) * math.sin(lat2))
        ring.append([round(math.degrees(lon2), 6), round(math.degrees(lat2), 6)])
    ring.append(ring[0])
    return ring


def close_ring(ring):
    if ring and ring[0] != ring[-1]:
        return ring + [ring[0]]
    return ring


def bbox_of_rings(rings_list):
    xs, ys = [], []
    for rings in rings_list:
        for ring in rings:
            for x, y in ring:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def valid_ring(ring):
    """تحقق أساسي: 4 نقاط على الأقل (مغلقة)، إحداثيات ضمن النطاق."""
    ring = close_ring(ring)
    if len(ring) < 4:
        return False
    for x, y in ring:
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            return False
    return True
