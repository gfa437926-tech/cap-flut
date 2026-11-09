import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import '../config.dart';
import '../models/warning_alert.dart';

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

class ApiClient {
  final String base;
  final http.Client _http;
  ApiClient({String? base, http.Client? client})
      : base = base ?? kApiBase,
        _http = client ?? http.Client();

  Future<dynamic> _get(String path, [Map<String, String>? q]) async {
    final uri = Uri.parse('$base$path').replace(queryParameters: q);
    try {
      final r = await _http.get(uri).timeout(const Duration(seconds: 15));
      if (r.statusCode != 200) throw ApiException('خطأ من الخادم (${r.statusCode})');
      return jsonDecode(utf8.decode(r.bodyBytes));
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException('تعذّر الاتصال بالخادم');
    }
  }

  /// التحذيرات النشطة (+ المجدولة). عند تمرير [point] تُعلَّم affectsPoint.
  Future<List<WarningAlert>> alerts({LatLng? point, bool includeScheduled = true}) async {
    final q = <String, String>{'lang': 'ar', if (includeScheduled) 'future': '1'};
    if (point != null) {
      q['lat'] = point.latitude.toString();
      q['lon'] = point.longitude.toString();
    }
    final j = await _get('/api/alerts', q) as Map<String, dynamic>;
    return [
      for (final f in (j['features'] as List)) WarningAlert.fromFeature((f as Map).cast<String, dynamic>()),
    ];
  }

  Future<List<Place>> places() async {
    final j = await _get('/api/places') as List;
    return [for (final p in j) Place.fromJson((p as Map).cast<String, dynamic>())];
  }

  Future<MapConfig> mapConfig() async {
    final j = await _get('/api/config') as Map<String, dynamic>;
    final c = (j['center'] as List).cast<num>();
    return MapConfig(LatLng(c[0].toDouble(), c[1].toDouble()), (j['zoom'] as num).toDouble());
  }
}
