import 'package:latlong2/latlong.dart';

/// منطقة واحدة: حلقة خارجية + ثقوب اختيارية (GeoJSON تخزّن [lon, lat]).
class AlertShape {
  final List<LatLng> outer;
  final List<List<LatLng>> holes;
  const AlertShape(this.outer, this.holes);
}

class WarningAlert {
  final String id;
  final String? event, headline, description, instruction, web;
  final String senderName, areaDesc;
  final String severity, urgency, certainty, state;
  final DateTime? sent, effective, expires;
  final List<AlertShape> shapes;
  final bool affectsPoint;

  const WarningAlert({
    required this.id,
    required this.severity,
    required this.urgency,
    required this.certainty,
    required this.state,
    required this.senderName,
    required this.areaDesc,
    required this.shapes,
    this.event,
    this.headline,
    this.description,
    this.instruction,
    this.web,
    this.sent,
    this.effective,
    this.expires,
    this.affectsPoint = false,
  });

  String get title => (headline?.isNotEmpty ?? false) ? headline! : (event ?? '');
  bool get isScheduled => state == 'scheduled';

  static DateTime? _dt(dynamic v) => v is String ? DateTime.tryParse(v)?.toLocal() : null;

  static List<LatLng> _ring(dynamic r) => [
        for (final p in (r as List)) LatLng((p[1] as num).toDouble(), (p[0] as num).toDouble()),
      ];

  factory WarningAlert.fromFeature(Map<String, dynamic> f) {
    final p = (f['properties'] as Map).cast<String, dynamic>();
    final shapes = <AlertShape>[];
    final g = f['geometry'];
    if (g is Map && g['type'] == 'MultiPolygon') {
      for (final poly in (g['coordinates'] as List)) {
        final rings = poly as List;
        if (rings.isEmpty) continue;
        shapes.add(AlertShape(_ring(rings.first), [for (final h in rings.skip(1)) _ring(h)]));
      }
    }
    return WarningAlert(
      id: p['id'] as String,
      event: p['event'] as String?,
      headline: p['headline'] as String?,
      description: p['description'] as String?,
      instruction: p['instruction'] as String?,
      web: p['web'] as String?,
      senderName: (p['senderName'] ?? '') as String,
      areaDesc: (p['areaDesc'] ?? '') as String,
      severity: (p['severity'] ?? 'Unknown') as String,
      urgency: (p['urgency'] ?? 'Unknown') as String,
      certainty: (p['certainty'] ?? 'Unknown') as String,
      state: (p['state'] ?? 'active') as String,
      sent: _dt(p['sent']),
      effective: _dt(p['effective']),
      expires: _dt(p['expires']),
      shapes: shapes,
      affectsPoint: p['affectsPoint'] == true,
    );
  }
}

class Place {
  final int id;
  final String name;
  final LatLng location;
  const Place(this.id, this.name, this.location);

  factory Place.fromJson(Map<String, dynamic> j) =>
      Place(j['id'] as int, j['name'] as String, LatLng((j['lat'] as num).toDouble(), (j['lon'] as num).toDouble()));
}

class MapConfig {
  final LatLng center;
  final double zoom;
  const MapConfig(this.center, this.zoom);
}
