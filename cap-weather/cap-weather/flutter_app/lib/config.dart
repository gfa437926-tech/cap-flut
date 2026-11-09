/// عنوان الخادم. غيّره عند البناء:
///   flutter run --dart-define=API_BASE=https://warnings.example.com
/// ملاحظات:
///  - مُحاكي أندرويد يصل إلى جهازك عبر http://10.0.2.2:5000
///  - على الإنتاج استخدم https (أندرويد/iOS يمنعان http الصريح افتراضياً).
const String kApiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://127.0.0.1:5000');

const int kRefreshSeconds = 60;
