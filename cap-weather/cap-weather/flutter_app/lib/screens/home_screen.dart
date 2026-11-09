import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import '../config.dart';
import '../models/warning_alert.dart';
import '../services/api_client.dart';
import '../widgets/severity.dart';
import 'alert_detail.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _api = ApiClient();
  final _map = MapController();
  Timer? _timer;

  List<WarningAlert> _alerts = [];
  List<Place> _places = [];
  LatLng? _point;
  String? _pointName;
  String? _error;
  bool _loading = true;
  bool _radar = false;
  String? _radarUrl;
  LatLng _center = const LatLng(34.8, 38.5);
  double _zoom = 6;

  @override
  void initState() {
    super.initState();
    _init();
    _timer = Timer.periodic(const Duration(seconds: kRefreshSeconds), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _init() async {
    try {
      final cfg = await _api.mapConfig();
      _center = cfg.center;
      _zoom = cfg.zoom;
      _map.move(_center, _zoom);
      _places = await _api.places();
    } on ApiException catch (e) {
      _error = e.message;
    }
    await _load();
  }

  Future<void> _load() async {
    try {
      final a = await _api.alerts(point: _point);
      if (!mounted) return;
      setState(() {
        _alerts = a;
        _error = null;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    }
  }

  void _setPoint(LatLng p, {String? name, bool move = true}) {
    setState(() {
      _point = p;
      _pointName = name;
    });
    if (move) _map.move(p, _map.camera.zoom < 8 ? 8 : _map.camera.zoom);
    _load();
  }

  Future<void> _locate() async {
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
        throw 'denied';
      }
      final pos = await Geolocator.getCurrentPosition();
      _setPoint(LatLng(pos.latitude, pos.longitude), name: 'موقعك الحالي');
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('تعذّر تحديد موقعك. اختر مدينة أو المس الخريطة.')));
    }
  }

  /// RainViewer: آخر إطار رادار (بلا مفتاح). أقصى تقريب أصلي 7.
  Future<void> _toggleRadar(bool on) async {
    if (!on) return setState(() => _radar = false);
    try {
      final r = await http.get(Uri.parse('https://api.rainviewer.com/public/weather-maps.json'));
      final j = jsonDecode(r.body) as Map<String, dynamic>;
      final past = (j['radar']['past'] as List);
      final url = '${j['host']}${past.last['path']}/256/{z}/{x}/{y}/2/1_1.png';
      setState(() {
        _radarUrl = url;
        _radar = true;
      });
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('تعذّر تحميل رادار الأمطار')));
    }
  }

  void _open(WarningAlert a, bool wide) {
    if (a.shapes.isNotEmpty) {
      final pts = [for (final s in a.shapes) ...s.outer];
      _map.fitCamera(CameraFit.coordinates(coordinates: pts, padding: const EdgeInsets.all(40), maxZoom: 9));
    }
    if (wide) {
      showModalBottomSheet(
        context: context,
        isScrollControlled: true,
        builder: (_) => DraggableScrollableSheet(
          expand: false,
          initialChildSize: .7,
          builder: (_, c) => AlertDetailView(alert: a, controller: c),
        ),
      );
    } else {
      Navigator.push(context, MaterialPageRoute(builder: (_) => AlertDetailPage(alert: a)));
    }
  }

  // ---------- الواجهة ----------
  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      final wide = c.maxWidth >= 900;
      final panel = _buildPanel(wide);
      final map = _buildMap(wide);
      return Scaffold(
        appBar: AppBar(
          title: const Text('التحذيرات الجوية'),
          actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh), tooltip: 'تحديث')],
        ),
        body: wide
            ? Row(children: [SizedBox(width: 400, child: panel), Expanded(child: map)])
            : Column(children: [Expanded(flex: 5, child: map), Expanded(flex: 5, child: panel)]),
      );
    });
  }

  Widget _buildMap(bool wide) {
    final polygons = <Polygon>[];
    final order = ['Unknown', 'Minor', 'Moderate', 'Severe', 'Extreme']; // الأخطر فوق
    final sorted = [..._alerts]..sort((a, b) => order.indexOf(a.severity).compareTo(order.indexOf(b.severity)));
    for (final a in sorted) {
      final col = sevOf(a.severity).color;
      for (final s in a.shapes) {
        polygons.add(Polygon(
          points: s.outer,
          holePointsList: s.holes,
          color: col.withOpacity(a.isScheduled ? 0.08 : 0.28),
          borderColor: col,
          borderStrokeWidth: 2,
          isFilled: true,
        ));
      }
    }
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Stack(children: [
      FlutterMap(
        mapController: _map,
        options: MapOptions(
          initialCenter: _center,
          initialZoom: _zoom,
          onTap: (_, p) => _setPoint(p, move: false),
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://{s}.basemaps.cartocdn.com/${dark ? 'dark' : 'light'}_all/{z}/{x}/{y}{r}.png',
            subdomains: const ['a', 'b', 'c', 'd'],
            userAgentPackageName: 'com.example.weather_warnings',
          ),
          if (_radar && _radarUrl != null)
            Opacity(
              opacity: .65,
              child: TileLayer(urlTemplate: _radarUrl!, maxNativeZoom: 7, userAgentPackageName: 'com.example.weather_warnings'),
            ),
          PolygonLayer(polygons: polygons),
          if (_point != null)
            MarkerLayer(markers: [
              Marker(
                point: _point!,
                width: 36,
                height: 36,
                child: const Icon(Icons.location_on, size: 36, color: Color(0xFF1D5FD1)),
              ),
            ]),
          const RichAttributionWidget(attributions: [
            TextSourceAttribution('© OpenStreetMap © CARTO'),
            TextSourceAttribution('الرادار: RainViewer'),
          ]),
        ],
      ),
      PositionedDirectional(
        top: 10,
        start: 10,
        child: Card(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Switch(value: _radar, onChanged: _toggleRadar),
              const Text('رادار الأمطار'),
              const SizedBox(width: 6),
            ]),
          ),
        ),
      ),
      PositionedDirectional(
        bottom: 24,
        start: 10,
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              for (final s in legendSeverities)
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.circle, size: 11, color: s.color),
                  const SizedBox(width: 6),
                  Text(s.label, style: const TextStyle(fontSize: 12)),
                ]),
            ]),
          ),
        ),
      ),
    ]);
  }

  Widget _buildPanel(bool wide) {
    final here = _alerts.where((a) => a.affectsPoint && !a.isScheduled).toList();
    return Material(
      color: Theme.of(context).colorScheme.surface,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        Row(children: [
          Expanded(
            child: DropdownButtonFormField<Place>(
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'اختر مدينة', border: OutlineInputBorder(), isDense: true),
              items: [for (final p in _places) DropdownMenuItem(value: p, child: Text(p.name))],
              onChanged: (p) => p == null ? null : _setPoint(p.location, name: p.name),
            ),
          ),
          const SizedBox(width: 8),
          FilledButton.tonalIcon(onPressed: _locate, icon: const Icon(Icons.my_location), label: const Text('موقعي')),
        ]),
        if (_point != null) ...[
          const SizedBox(height: 12),
          Text(_pointName ?? 'النقطة المحددة', style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          if (here.isEmpty)
            const _Empty('✓ لا توجد تحذيرات نشطة في هذا الموقع')
          else
            ...here.map((a) => _AlertTile(a, () => _open(a, wide))),
        ],
        const Divider(height: 28),
        Text('كل التحذيرات النشطة (${_alerts.length})', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        if (_loading)
          const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
        else if (_error != null)
          _Empty(_error!)
        else if (_alerts.isEmpty)
          const _Empty('لا توجد تحذيرات نشطة حالياً ✓')
        else
          ..._alerts.map((a) => _AlertTile(a, () => _open(a, wide))),
      ]),
    );
  }
}

class _Empty extends StatelessWidget {
  final String text;
  const _Empty(this.text);
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(14),
        alignment: Alignment.center,
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(8)),
        child: Text(text, textAlign: TextAlign.center),
      );
}

class _AlertTile extends StatelessWidget {
  final WarningAlert a;
  final VoidCallback onTap;
  const _AlertTile(this.a, this.onTap);

  @override
  Widget build(BuildContext context) {
    final s = sevOf(a.severity);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(border: BorderDirectional(start: BorderSide(color: s.color, width: 5))),
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text(a.event ?? a.title, style: const TextStyle(fontWeight: FontWeight.w700)),
              SeverityBadge(a.severity),
              if (a.isScheduled) const Text('مجدول', style: TextStyle(fontSize: 12)),
            ]),
            if (a.areaDesc.isNotEmpty) Text(a.areaDesc, style: TextStyle(fontSize: 13, color: Theme.of(context).hintColor)),
            Text(a.isScheduled ? 'تبدأ ${fmtTime(a.effective)}' : remaining(a.expires),
                style: TextStyle(fontSize: 12.5, color: Theme.of(context).hintColor)),
          ]),
        ),
      ),
    );
  }
}
