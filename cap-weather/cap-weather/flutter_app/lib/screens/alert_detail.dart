import 'package:flutter/material.dart';

import '../models/warning_alert.dart';
import '../widgets/severity.dart';

/// صفحة التفاصيل — تُستخدم كصفحة كاملة على الموبايل وكنافذة سفلية على الشاشات الكبيرة.
class AlertDetailView extends StatelessWidget {
  final WarningAlert alert;
  final ScrollController? controller;
  const AlertDetailView({super.key, required this.alert, this.controller});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final s = sevOf(alert.severity);

    Widget block(String title, String? body) => (body == null || body.isEmpty)
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: t.labelLarge?.copyWith(color: Theme.of(context).hintColor)),
              const SizedBox(height: 4),
              SelectableText(body, style: t.bodyLarge),
            ]),
          );

    Widget kv(String k, String v) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: 92, child: Text(k, style: TextStyle(color: Theme.of(context).hintColor))),
            Expanded(child: Text(v)),
          ]),
        );

    return ListView(
      controller: controller,
      padding: const EdgeInsets.all(18),
      children: [
        Container(height: 6, decoration: BoxDecoration(color: s.color, borderRadius: BorderRadius.circular(3))),
        const SizedBox(height: 12),
        Wrap(spacing: 8, children: [
          SeverityBadge(alert.severity),
          if (alert.isScheduled) const Chip(label: Text('مجدول'), visualDensity: VisualDensity.compact),
        ]),
        const SizedBox(height: 8),
        Text(alert.title, style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
        if (alert.event != null) Text(alert.event!, style: t.bodyMedium?.copyWith(color: Theme.of(context).hintColor)),
        const SizedBox(height: 14),
        kv('المنطقة', alert.areaDesc.isEmpty ? '—' : alert.areaDesc),
        kv('تبدأ', fmtTime(alert.effective)),
        kv('تنتهي', '${fmtTime(alert.expires)}  (${remaining(alert.expires)})'),
        kv('الإلحاح', urgencyAr[alert.urgency] ?? alert.urgency),
        kv('اليقين', certaintyAr[alert.certainty] ?? alert.certainty),
        kv('المصدر', alert.senderName),
        kv('وقت الإصدار', fmtTime(alert.sent)),
        block('الوصف', alert.description),
        block('التعليمات والإرشادات', alert.instruction),
      ],
    );
  }
}

class AlertDetailPage extends StatelessWidget {
  final WarningAlert alert;
  const AlertDetailPage({super.key, required this.alert});

  @override
  Widget build(BuildContext context) =>
      Scaffold(appBar: AppBar(title: const Text('تفاصيل التحذير')), body: AlertDetailView(alert: alert));
}
