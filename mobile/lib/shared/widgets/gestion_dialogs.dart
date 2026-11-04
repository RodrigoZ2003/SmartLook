// mobile/lib/shared/widgets/gestion_dialogs.dart
//
// NUEVO (Fase 2 - CU05 / CU12): diálogos compartidos para aprobar (repartidor
// y fecha/hora de la visita, máximo 48 h) y rechazar (motivo) un cambio de
// prenda o una devolución, igual que los paneles de la web.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../theme/app_colors.dart';

const int plazoVisitaHoras = 48;

/// Pide repartidor y fecha de visita. Devuelve (idRepartidor, fecha) o null.
Future<(int, DateTime)?> pedirAprobacion(
  BuildContext context, {
  required String titulo,
  required String etiquetaFecha,
  required List<Map<String, dynamic>> repartidores,
  String? nota,
}) {
  int? repartidor = repartidores.length == 1 ? repartidores.first['id_usuario'] as int : null;
  DateTime fecha = DateTime.now().add(const Duration(hours: 2));
  String? error;
  final fmt = DateFormat('dd/MM/yyyy HH:mm');

  return showDialog<(int, DateTime)>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setLocal) {
        Future<void> elegirFecha() async {
          final ahora = DateTime.now();
          final limite = ahora.add(const Duration(hours: plazoVisitaHoras));
          final dia = await showDatePicker(
            context: ctx,
            initialDate: fecha,
            firstDate: DateTime(ahora.year, ahora.month, ahora.day),
            lastDate: limite,
          );
          if (dia == null || !ctx.mounted) return;
          final hora = await showTimePicker(context: ctx, initialTime: TimeOfDay.fromDateTime(fecha));
          if (hora == null) return;
          setLocal(() => fecha = DateTime(dia.year, dia.month, dia.day, hora.hour, hora.minute));
        }

        return AlertDialog(
          title: Text(titulo),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DropdownButtonFormField<int>(
                value: repartidor,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Repartidor', border: OutlineInputBorder()),
                items: repartidores
                    .map((r) => DropdownMenuItem<int>(
                          value: r['id_usuario'] as int,
                          child: Text('${r['nombre']}'),
                        ))
                    .toList(),
                onChanged: (v) => setLocal(() => repartidor = v),
              ),
              const SizedBox(height: 10),
              Text(etiquetaFecha, style: const TextStyle(fontSize: 12, color: AppColors.grey)),
              OutlinedButton(onPressed: elegirFecha, child: Text(fmt.format(fecha))),
              if (nota != null) ...[
                const SizedBox(height: 8),
                Text(nota, style: const TextStyle(fontSize: 12, color: AppColors.grey)),
              ],
              if (error != null) ...[
                const SizedBox(height: 8),
                Text(error!, style: const TextStyle(color: AppColors.danger, fontSize: 13)),
              ],
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
            TextButton(
              onPressed: () {
                final ahora = DateTime.now();
                if (repartidor == null) {
                  setLocal(() => error = 'Elige el repartidor y la fecha de la visita.');
                  return;
                }
                if (fecha.isBefore(ahora) ||
                    fecha.isAfter(ahora.add(const Duration(hours: plazoVisitaHoras)))) {
                  setLocal(() => error = 'La fecha debe estar dentro de las próximas $plazoVisitaHoras horas.');
                  return;
                }
                Navigator.pop(ctx, (repartidor!, fecha));
              },
              child: const Text('Confirmar'),
            ),
          ],
        );
      },
    ),
  );
}

/// Pide el motivo del rechazo. Devuelve el texto o null.
Future<String?> pedirMotivoRechazo(BuildContext context, {String? nota}) {
  final ctrl = TextEditingController();
  String? error;
  return showDialog<String>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setLocal) => AlertDialog(
        title: const Text('Motivo del rechazo'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: ctrl,
              decoration: const InputDecoration(
                hintText: 'Ej.: la prenda tiene uso / fuera de plazo',
                border: OutlineInputBorder(),
              ),
            ),
            if (nota != null) ...[
              const SizedBox(height: 8),
              Text(nota, style: const TextStyle(fontSize: 12, color: AppColors.grey)),
            ],
            if (error != null) ...[
              const SizedBox(height: 8),
              Text(error!, style: const TextStyle(color: AppColors.danger, fontSize: 13)),
            ],
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
          TextButton(
            onPressed: () {
              if (ctrl.text.trim().isEmpty) {
                setLocal(() => error = 'Escribe el motivo del rechazo.');
                return;
              }
              Navigator.pop(ctx, ctrl.text.trim());
            },
            child: const Text('Confirmar rechazo', style: TextStyle(color: AppColors.danger)),
          ),
        ],
      ),
    ),
  );
}

/// Hoja con filas "etiqueta: valor" (nota de devolución).
Future<void> mostrarNota(BuildContext context, String titulo, List<(String, String)> filas,
    {List<Widget> extra = const []}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.7,
      builder: (ctx, scroll) => ListView(
        controller: scroll,
        padding: const EdgeInsets.all(16),
        children: [
          Text(titulo, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
          const SizedBox(height: 10),
          for (final (etiqueta, valor) in filas)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 120,
                    child: Text(etiqueta, style: const TextStyle(color: AppColors.grey, fontSize: 13)),
                  ),
                  Expanded(child: Text(valor, style: const TextStyle(fontSize: 13))),
                ],
              ),
            ),
          ...extra,
          const SizedBox(height: 12),
          ElevatedButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cerrar')),
        ],
      ),
    ),
  );
}

/// Colores (fondo, texto) por estado de cambio o devolución.
(Color, Color) coloresEstadoGestion(String estado) {
  switch (estado) {
    case 'SOLICITADO':
    case 'SOLICITADA':
      return (const Color(0xFFFFF8E1), const Color(0xFF8A6D00));
    case 'PROGRAMADO':
    case 'PROGRAMADA':
    case 'EN_CAMINO':
      return (const Color(0xFFE3F2FD), const Color(0xFF0D47A1));
    case 'RECHAZADO':
    case 'RECHAZADA':
      return (const Color(0xFFFDECEA), const Color(0xFFC0392B));
    default:
      return (const Color(0xFFE8F8F0), const Color(0xFF1B7F4B));
  }
}