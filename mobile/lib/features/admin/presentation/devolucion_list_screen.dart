// mobile/lib/features/admin/presentation/devolucion_list_screen.dart
//
// Lista de devoluciones para administración/encargados.
// MODIFICADO (Fase 2 - CU12, igual que la web): muestra la nota, el origen
// (pedido o venta POS), el cliente, las prendas con su motivo, el reembolso
// (y lo retenido) y el estado, con filtro por sucursal.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';

class DevolucionListScreen extends StatefulWidget {
  const DevolucionListScreen({super.key});

  @override
  State<DevolucionListScreen> createState() => _DevolucionListScreenState();
}

class _DevolucionListScreenState extends State<DevolucionListScreen> {
  late final ApiClient _api;
  List<dynamic> _devoluciones = [];
  List<dynamic> _sucursales = [];
  int? _sucursalSeleccionada;
  bool _cargando = true;
  final _formatoFecha = DateFormat('dd/MM/yyyy HH:mm');

  @override
  void initState() {
    super.initState();
    _api = context.read<ApiClient>();
    _cargarSucursales();
    _cargar();
  }

  Future<void> _cargarSucursales() async {
    try {
      final response = await _api.dio.get('/catalog/sucursales/');
      final data = response.data;
      if (!mounted) return;
      setState(() => _sucursales = (data is Map ? (data['results'] ?? []) : data) as List);
    } catch (_) {
      if (mounted) setState(() => _sucursales = []);
    }
  }

  Future<void> _cargar() async {
    setState(() => _cargando = true);
    try {
      final response = await _api.dio.get(
        '/sales/devoluciones/',
        queryParameters: _sucursalSeleccionada != null ? {'sucursal': _sucursalSeleccionada} : null,
      );
      final data = response.data;
      final lista = (data is Map ? (data['results'] ?? []) : data) as List;
      if (!mounted) return;
      setState(() {
        _devoluciones = lista;
        _cargando = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _devoluciones = [];
        _cargando = false;
      });
    }
  }

  String _formatearFecha(dynamic iso) {
    final dt = DateTime.tryParse('${iso ?? ''}')?.toLocal();
    return dt == null ? '' : _formatoFecha.format(dt);
  }

  (Color, Color) _coloresEstado(String estado) {
    switch (estado) {
      case 'SOLICITADA':
        return (const Color(0xFFFFF8E1), const Color(0xFF8A6D00));
      case 'PROGRAMADA':
      case 'EN_CAMINO':
        return (const Color(0xFFE3F2FD), const Color(0xFF0D47A1));
      case 'RECHAZADA':
        return (const Color(0xFFFDECEA), const Color(0xFFC0392B));
      default:
        return (const Color(0xFFE8F8F0), const Color(0xFF1B7F4B));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Devoluciones')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: DropdownButtonFormField<int?>(
              value: _sucursalSeleccionada,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Sucursal', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem<int?>(value: null, child: Text('Todas las sucursales')),
                ..._sucursales.map((s) => DropdownMenuItem<int?>(
                      value: s['id_sucursal'] as int,
                      child: Text('${s['nombre']}'),
                    )),
              ],
              onChanged: (v) {
                setState(() => _sucursalSeleccionada = v);
                _cargar();
              },
            ),
          ),
          Expanded(
            child: _cargando
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: _cargar,
                    child: _devoluciones.isEmpty
                        ? ListView(
                            children: const [
                              Padding(
                                padding: EdgeInsets.all(32),
                                child: Center(child: Text('No hay devoluciones registradas todavía.')),
                              ),
                            ],
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.all(16),
                            itemCount: _devoluciones.length,
                            itemBuilder: (context, index) =>
                                _tarjeta(Map<String, dynamic>.from(_devoluciones[index] as Map)),
                          ),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _tarjeta(Map<String, dynamic> d) {
    final items = (d['items'] ?? []) as List;
    final estado = '${d['estado'] ?? ''}';
    final (fondo, texto) = _coloresEstado(estado);
    final retenido = double.tryParse('${d['monto_retenido'] ?? ''}') ?? 0;
    final origen = d['origen'] as Map?;
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${d['numero_nota'] ?? ''} · ${origen?['etiqueta'] ?? ''}',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                  decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                  child: Text(
                    '${d['estado_display'] ?? estado}',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: texto),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '${_formatearFecha(d['fecha_creacion'])} · ${d['sucursal'] ?? ''}',
              style: const TextStyle(fontSize: 12, color: AppColors.grey),
            ),
            Text('Cliente: ${d['cliente'] ?? 'Sin cliente'}', style: const TextStyle(fontSize: 13)),
            const SizedBox(height: 6),
            for (final i in items)
              Text(
                '${i['cantidad']} x ${i['variante']} (${i['motivo_display']})',
                style: const TextStyle(fontSize: 13),
              ),
            const SizedBox(height: 6),
            if (d['es_anterior'] == true)
              const Text('Reembolso: -', style: TextStyle(fontSize: 13))
            else ...[
              Text('Reembolso: Bs ${d['monto_reembolso']}',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
              if (retenido > 0)
                Text('Retenido Bs ${d['monto_retenido']}',
                    style: const TextStyle(fontSize: 12, color: Color(0xFFC0392B))),
            ],
          ],
        ),
      ),
    );
  }
}