# منصة التحذيرات الجوية (CAP)

محرك بايثون يستقبل رسائل **CAP 1.2** ويديرها، مع لوحة إدارة لرسم مناطق التحذير على الخريطة،
وواجهة API عامة (JSON/GeoJSON) يستهلكها تطبيق **فلاتر** واحد للموبايل والويب وسطح المكتب.

```
backend (بايثون/Flask)                          عملاء
├─ لوحة الإدارة  /admin  (رسم المناطق)           ├─ flutter_app/   موبايل + ويب + سطح مكتب
├─ استقبال CAP   POST /api/cap  + مصادر دورية    └─ templates/index.html  واجهة ويب خفيفة مدمجة
└─ API عامة      GET /api/...   (+ OpenAPI)
```

## التشغيل (الخادم)
```bash
pip install -r requirements.txt
python app.py              # http://127.0.0.1:5000   الإدارة: /admin
python -m unittest discover -s tests -v
```
عند أول تشغيل تُولَّد كلمة مرور الإدارة ورمز API وتُحفظ في `data/` (مستبعد من git) وتُطبع في الطرفية.
يمكن تحديدها بـ `ADMIN_PASSWORD` و`CAP_API_TOKEN`. متغيرات أخرى: `HOST`، `PORT`، `CAPW_CORS_ORIGINS`
(أصول مفصولة بفواصل لنسخة فلاتر ويب؛ الافتراضي `*` للقراءة العامة فقط).

> للإنتاج: شغّل خلف gunicorn/وكيل عكسي بـ HTTPS. أبقِ عملية واحدة (أو انقل المُجمِّع الدوري `ingest.py` إلى خدمة منفصلة).

## واجهة API (القراءة العامة)
التوثيق التفاعلي: `GET /api/openapi.json`

| المسار | الوصف |
|---|---|
| `GET /api/alerts?lat&lon&future=1&severity=` | التحذيرات النشطة كـ GeoJSON، مع `affectsPoint` عند تمرير الإحداثيات |
| `GET /api/alerts/at?lat&lon` | التحذيرات التي تتقاطع مع نقطة |
| `GET /api/alerts/{id}` و `/cap.xml` | التفاصيل / رسالة CAP الأصلية |
| `GET /api/places` · `GET /api/config` | المدن · مركز الخريطة وطبقات الطقس |
| `POST /api/cap` | استقبال CAP (رمز Bearer مطلوب) |

القيم الجغرافية بترتيب GeoJSON: `[lon, lat]` (بينما CAP نفسه يكتب `lat,lon`؛ التحويل تلقائي).

## تطبيق فلاتر
مجلد `flutter_app/` يحتوي كود Dart (`lib/`) فقط. ولّد مجلدات المنصات مرة واحدة:
```bash
cd flutter_app
flutter create --platforms=android,ios,web,windows,macos,linux --project-name weather_warnings .
flutter pub get
flutter run --dart-define=API_BASE=https://your-server        # موبايل/سطح مكتب
flutter run -d chrome --dart-define=API_BASE=http://127.0.0.1:5000   # ويب
```
- **أندرويد:** أضف إلى `AndroidManifest.xml` صلاحيتي `ACCESS_FINE_LOCATION` و`ACCESS_COARSE_LOCATION` والإنترنت؛ مُحاكي أندرويد يصل للخادم عبر `http://10.0.2.2:5000`.
- **iOS:** أضف `NSLocationWhenInUseUsageDescription` في `Info.plist`.
- استخدم **https** في الإنتاج (http الصريح محظور افتراضياً على الموبايل).

## حدود هذه المرحلة (بصراحة)
منفّذ ومختبَر: تحليل/توليد CAP، Update/Cancel، منع التكرار، المطابقة الجغرافية، رسم المناطق، مصادر CAP دورية، API، CORS.
**غير منفّذ بعد:** حسابات موظفين وأدوار، دورة مراجعة/اعتماد/جدولة، سجل تدقيق، إشعارات دفع، تقارير، PostGIS، تحديد معدل الطلبات.
الكود الخاص بفلاتر **لم يُترجَم ولم يُشغَّل** هنا (لا يتوفر Flutter SDK في بيئة العمل) — جرّبه بـ `flutter analyze` و`flutter test`.
