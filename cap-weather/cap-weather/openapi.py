"""وثيقة OpenAPI 3.0 لواجهة القراءة العامة التي تستهلكها تطبيقات فلاتر (موبايل / ويب / سطح مكتب)."""

_lat = {"name": "lat", "in": "query", "schema": {"type": "number", "minimum": -90, "maximum": 90}}
_lon = {"name": "lon", "in": "query", "schema": {"type": "number", "minimum": -180, "maximum": 180}}
_lang = {"name": "lang", "in": "query", "schema": {"type": "string", "enum": ["ar", "en"], "default": "ar"}}

SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Weather Warnings API",
        "version": "1.0.0",
        "description": "واجهة قراءة التحذيرات الجوية (CAP 1.2). المناطق بصيغة GeoJSON [lon,lat].",
    },
    "paths": {
        "/api/alerts": {"get": {
            "summary": "التحذيرات النشطة كـ GeoJSON FeatureCollection",
            "parameters": [
                _lat, _lon, _lang,
                {"name": "future", "in": "query", "description": "1 = تضمين المجدولة", "schema": {"type": "string", "enum": ["0", "1"]}},
                {"name": "severity", "in": "query", "description": "قائمة مفصولة بفواصل: Extreme,Severe,...", "schema": {"type": "string"}},
            ],
            "responses": {"200": {"description": "FeatureCollection", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/FeatureCollection"}}}}}}},
        "/api/alerts/at": {"get": {
            "summary": "التحذيرات التي تتقاطع مع نقطة (موقع المستخدم)",
            "parameters": [dict(_lat, required=True), dict(_lon, required=True), _lang],
            "responses": {"200": {"description": "قائمة خصائص بدون هندسة"}, "400": {"description": "إحداثيات غير صالحة"}}}},
        "/api/alerts/{id}": {"get": {
            "summary": "تفاصيل تحذير (Feature)",
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}, _lang],
            "responses": {"200": {"description": "Feature"}, "404": {"description": "غير موجود"}}}},
        "/api/alerts/{id}/cap.xml": {"get": {
            "summary": "رسالة CAP الأصلية",
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "application/cap+xml"}}}},
        "/api/places": {"get": {"summary": "قائمة المدن", "responses": {"200": {"description": "مصفوفة مدن"}}}},
        "/api/config": {"get": {"summary": "إعدادات الخريطة وطبقات الطقس المفعّلة", "responses": {"200": {"description": "إعدادات"}}}},
        "/api/cap": {"post": {
            "summary": "استقبال رسالة/خلاصة CAP (يتطلب رمزاً)",
            "security": [{"bearer": []}],
            "requestBody": {"content": {"application/xml": {"schema": {"type": "string"}}}},
            "responses": {"200": {"description": "إحصاءات الاستيراد"}, "401": {"description": "رمز غير صالح"}}}},
    },
    "components": {
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        "schemas": {
            "FeatureCollection": {"type": "object", "properties": {
                "type": {"type": "string"}, "generatedAt": {"type": "string", "format": "date-time"},
                "features": {"type": "array", "items": {"$ref": "#/components/schemas/Feature"}}}},
            "Feature": {"type": "object", "properties": {
                "id": {"type": "string"}, "type": {"type": "string"},
                "geometry": {"type": "object", "description": "MultiPolygon: [polygon][ring][[lon,lat]]"},
                "properties": {"$ref": "#/components/schemas/AlertProperties"}}},
            "AlertProperties": {"type": "object", "properties": {
                "id": {"type": "string"}, "event": {"type": "string"}, "headline": {"type": "string"},
                "description": {"type": "string"}, "instruction": {"type": "string"},
                "severity": {"type": "string", "enum": ["Extreme", "Severe", "Moderate", "Minor", "Unknown"]},
                "urgency": {"type": "string"}, "certainty": {"type": "string"},
                "state": {"type": "string", "enum": ["active", "scheduled", "expired", "cancelled"]},
                "sent": {"type": "string", "format": "date-time"}, "effective": {"type": "string", "format": "date-time"},
                "expires": {"type": "string", "format": "date-time"},
                "areaDesc": {"type": "string"}, "senderName": {"type": "string"},
                "affectsPoint": {"type": "boolean", "description": "يظهر عند تمرير lat/lon"}}},
        },
    },
}
