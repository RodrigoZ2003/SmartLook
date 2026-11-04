// mobile/lib/features/notificaciones/presentation/notificaciones_screen.dart
//
// NUEVO (Fase 2 - CU16): lista de avisos del usuario. Tocar uno lo marca como
// leído y abre la pantalla relacionada (onAbrir recibe el "enlace" de la web:
// /reservations, /orders, /deliveries, /pos/operaciones). "Marcar todas como
// leídas" deja el contador en cero.
// También define CampanaNotificaciones: el icono con el contador.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/notificaciones/notificaciones_service.dart';
import '../../../shared/theme/app_colors.dart';

/// Icono de campana con la cantidad de avisos sin leer.
class CampanaNotificaciones extends StatelessWidget {
  final NotificacionesService service;
  final Color? color;

  const CampanaNotificaciones({super.key, required this.service, this.color});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: service,
      builder: (context, _) {
        final n = service.noLeidas;
        return Badge(
          isLabelVisible: n > 0,
          label: Text(n > 99 ? '99+' : '$n'),
          backgroundColor: AppColors.danger,
          child: Icon(n > 0 ? Icons.notifications : Icons.notifications_none, color: color),
        );
      },
    );
  }
}

class NotificacionesScreen extends StatefulWidget {
  final NotificacionesService service;
  final void Function(String enlace) onAbrir;

  /// false cuando la lista es una pestaña (sin botón "atrás").
  final bool comoPantalla;

  const NotificacionesScreen({
    super.key,
    required this.service,
    required this.onAbrir,
    this.comoPantalla = true,
  });

  @override
  State<NotificacionesScreen> createState() => NotificacionesScreenState();
}

class NotificacionesScreenState extends State<NotificacionesScreen> {
  final DateFormat _fmt = DateFormat('dd/MM/yyyy HH:mm');
  List<Map<String, dynamic>> _avisos = [];
  bool _cargando = true;
  bool _marcando = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    recargar();
  }

  /// Vuelve a pedir la lista (también al entrar a la pestaña).
  Future<void> recargar() async {
    setState(() {
      _cargando = _avisos.isEmpty;
      _error = null;
    });
    try {
      final avisos = await widget.service.listar();
      widget.service.actualizarContador();
      if (!mounted) return;
      setState(() {
        _avisos = avisos;
        _cargando = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _cargando = false;
        _error = 'No se pudieron cargar los avisos. Revisa tu conexión.';
      });
    }
  }

  bool get _hayNoLeidas => _avisos.any((a) => a['leida'] != true);

  Future<void> _tocar(Map<String, dynamic> aviso) async {
    if (aviso['leida'] != true) {
      try {
        await widget.service.leer(aviso['id_notificacion'] as int);
        if (mounted) setState(() => aviso['leida'] = true);
      } catch (_) {}
    }
    final enlace = aviso['enlace'];
    if (enlace != null && '$enlace'.isNotEmpty) widget.onAbrir('$enlace');
  }

  Future<void> _leerTodas() async {
    setState(() => _marcando = true);
    try {
      await widget.service.leerTodas();
      if (!mounted) return;
      setState(() {
        for (final a in _avisos) {
          a['leida'] = true;
        }
      });
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No se pudieron marcar los avisos como leídos.')),
        );
      }
    } finally {
      if (mounted) setState(() => _marcando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: widget.comoPantalla,
        title: const Text('Notificaciones'),
        actions: [
          TextButton(
            onPressed: (_marcando || !_hayNoLeidas) ? null : _leerTodas,
            child: const Text('Marcar todas como leídas'),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: recargar,
        child: _cargando
            ? ListView(children: const [
                SizedBox(height: 120),
                Center(child: CircularProgressIndicator()),
              ])
            : _avisos.isEmpty
                ? ListView(children: [
                    const SizedBox(height: 120),
                    Center(
                      child: Text(_error ?? 'No tienes notificaciones.',
                          style: const TextStyle(color: AppColors.grey)),
                    ),
                  ])
                : ListView.separated(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    itemCount: _avisos.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) => _fila(_avisos[index]),
                  ),
      ),
    );
  }

  Widget _fila(Map<String, dynamic> a) {
    final leida = a['leida'] == true;
    final fecha = DateTime.tryParse('${a['fecha_creacion'] ?? ''}')?.toLocal();
    return Material(
      color: leida ? Colors.white : const Color(0xFFFBF3E8),
      child: InkWell(
        onTap: () => _tocar(a),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 6, right: 10),
                child: Icon(Icons.circle, size: 9, color: leida ? Colors.transparent : AppColors.primary),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${a['titulo'] ?? ''}',
                      style: TextStyle(fontWeight: leida ? FontWeight.w500 : FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text('${a['mensaje'] ?? ''}', style: const TextStyle(fontSize: 13, color: Color(0xFF555555))),
                    const SizedBox(height: 4),
                    Text(
                      '${a['tipo_display'] ?? ''}${fecha != null ? ' · ${_fmt.format(fecha)}' : ''}',
                      style: const TextStyle(fontSize: 11, color: AppColors.grey),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}