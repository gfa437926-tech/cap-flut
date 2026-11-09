import 'package:flutter_test/flutter_test.dart';
import 'package:weather_warnings/models/warning_alert.dart';

void main() {
  test('يحوّل Feature من الـ API إلى WarningAlert مع ترتيب [lon,lat] الصحيح', () {
    final a = WarningAlert.fromFeature({
      'type': 'Feature',
      'id': 'x',
      'geometry': {
        'type': 'MultiPolygon',
        'coordinates': [
          [
            [
              [36.0, 33.0],
              [37.0, 33.0],
              [37.0, 34.0],
              [36.0, 33.0]
            ]
          ]
        ]
      },
      'properties': {
        'id': 'x',
        'event': 'أمطار',
        'severity': 'Severe',
        'state': 'active',
        'expires': '2999-01-01T00:00:00Z',
        'affectsPoint': true,
      },
    });
    expect(a.shapes.single.outer.first.latitude, 33.0);
    expect(a.shapes.single.outer.first.longitude, 36.0);
    expect(a.affectsPoint, isTrue);
    expect(a.severity, 'Severe');
  });
}
