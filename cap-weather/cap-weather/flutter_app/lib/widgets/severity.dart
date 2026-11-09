import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

class Sev {
  final Color color;
  final String label;
  const Sev(this.color, this.label);
}

const _sev = {
  'Extreme': Sev(Color(0xFFB91C1C), 'شديدة الخطورة'),
  'Severe': Sev(Color(0xFFEA580C), 'خطيرة'),
  'Moderate': Sev(Color(0xFFCA8A04), 'متوسطة'),
  'Minor': Sev(Color(0xFF0284C7), 'طفيفة'),
  'Unknown': Sev(Color(0xFF6B7280), 'غير محددة'),
};

Sev sevOf(String s) => _sev[s] ?? _sev['Unknown']!;
List<Sev> get legendSeverities => [_sev['Extreme']!, _sev['Severe']!, _sev['Moderate']!, _sev['Minor']!];

const urgencyAr = {'Immediate': 'فوري', 'Expected': 'متوقع', 'Future': 'قادم', 'Past': 'منتهٍ', 'Unknown': 'غير محدد'};
const certaintyAr = {'Observed': 'مرصود', 'Likely': 'مرجّح', 'Possible': 'محتمل', 'Unlikely': 'غير مرجّح', 'Unknown': 'غير محدد'};

String fmtTime(DateTime? d) => d == null ? '—' : DateFormat('d MMM، HH:mm', 'ar').format(d);

String remaining(DateTime? exp) {
  if (exp == null) return '';
  final m = exp.difference(DateTime.now()).inMinutes;
  if (m <= 0) return 'انتهى';
  if (m < 60) return 'تنتهي بعد $m دقيقة';
  final h = m ~/ 60;
  return h < 48 ? 'تنتهي بعد $h ساعة' : 'تنتهي بعد ${h ~/ 24} يوماً';
}

class SeverityBadge extends StatelessWidget {
  final String severity;
  const SeverityBadge(this.severity, {super.key});

  @override
  Widget build(BuildContext context) {
    final s = sevOf(severity);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(color: s.color, borderRadius: BorderRadius.circular(99)),
      child: Text(s.label, style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700)),
    );
  }
}
