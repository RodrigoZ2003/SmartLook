// mobile/lib/features/orders/presentation/orders_screen.dart
//
// CU21: "Mis pedidos" del cliente. Lista sus órdenes pagadas y, si son con
// delivery, muestra la línea de tiempo del envío. Se actualiza cada 10 s.
// NUEVO (devoluciones): botón "Solicitar devolución" en pedidos DELIVERY
// ya ENTREGADA, badge "Devuelto"/"Entregado (devolución parcial)" usando
// los campos devuelto/tiene_devolucion que ahora manda OrderSerializer.
// MODIFICADO (Fase 2 - CU12, igual que la web): el botón depende de
// puede_solicitar_devolucion (plazo de 7 días desde la entrega) y cada
// pedido muestra sus devoluciones con nota, estado y reembolso.
// MODIFICADO (Fase 2 - CU05): cada prenda de un pedido con delivery
// entregado se puede cambiar por otra talla o color (puede_solicitar_cambio)
// y muestra el estado de su último cambio.
// MODIFICADO (Fase 3 - CU18, igual que la web): arriba de la lista, la tarjeta
// "Tu descuento por fidelidad" con el progreso del mes por tienda (compras de
// N, barra y mensaje). Se carga al abrir y al deslizar para recargar.

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';
import '../../cambios/presentation/cambio_solicitud_screen.dart';
import '../../fidelidad/data/fidelidad_service.dart';
import 'devolucion_form_screen.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late final ApiClient _api;
  late final FidelidadService _fidelidadService;
  // CU18: progreso del descuento por fidelidad (null si no cargó).
  Map<String, dynamic>? _fidelidad;
  List<Map<String, dynamic>> _pedidos = [];
  bool _cargando = true;
  String? _error;
  Timer? _timer;

  static const List<String> _claves = ['PENDIENTE', 'EN_PREPARACION', 'EN_CAMINO', 'ENTREGADO'];
  static const List<String> _textos = ['Recibido', 'Preparando', 'En camino', 'Entregado'];

  @override
  void initState() {
    super.initState();
    _api = context.read<ApiClient>();
    _fidelidadService = FidelidadService(apiClient: _api);
    _cargar();
    _cargarFidelidad();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _cargar());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _cargar() async {
    try {
      final response = await _api.dio.get('/sales/ordenes/');
      final data = response.data;
      final lista = (data is Map ? (data['results'] ?? []) : data) as List;
      if (!mounted) return;
      setState(() {
        // Las órdenes PENDIENTE son pagos que nunca se completaron: no se muestran.
        _pedidos = lista
            .map((e) => Map<String, dynamic>.from(e as Map))
            .where((o) => o['estado'] != 'PENDIENTE')
            .toList();
        _cargando = false;
        _error = null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _cargando = false;
        if (_pedidos.isEmpty) _error = 'No se pudieron cargar tus pedidos.';
      });
    }
  }

  /// NUEVO (CU18): progreso del mes por tienda. Un fallo no se muestra.
  Future<void> _cargarFidelidad() async {
    try {
      final datos = await _fidelidadService.miProgreso();
      if (!mounted) return;
      setState(() => _fidelidad = datos);
    } catch (_) {
      if (!mounted) return;
      setState(() => _fidelidad = null);
    }
  }

  /// Al deslizar hacia abajo se recargan los pedidos y el progreso.
  Future<void> _recargarTodo() async {
    await Future.wait([_cargar(), _cargarFidelidad()]);
  }

  /// NUEVO (CU18): la tarjeta se muestra si la regla está activa o hay tiendas (como la web).
  bool get _mostrarFidelidad {
    final datos = _fidelidad;
    if (datos == null) return false;
    final regla = (datos['regla'] ?? {}) as Map;
    return regla['activa'] == true || FidelidadService.empresas(datos).isNotEmpty;
  }

  int _indicePaso(Map<String, dynamic> o) {
    final estado = (o['delivery'] as Map?)?['estado'];
    final i = _claves.indexOf('$estado');
    return i < 0 ? 0 : i;
  }

  bool _devuelto(Map<String, dynamic> o) => o['devuelto'] == true;
  bool _tieneDevolucion(Map<String, dynamic> o) => o['tiene_devolucion'] == true;

  String _textoEstado(Map<String, dynamic> o) {
    if (o['estado'] == 'CANCELADA') return 'Cancelado';
    if (_devuelto(o)) return 'Devuelto';
    if (_tieneDevolucion(o)) return 'Entregado (devolución parcial)';
    if (o['tipo_entrega'] == 'DELIVERY' && o['delivery'] != null) {
      return _textos[_indicePaso(o)];
    }
    return o['estado'] == 'ENTREGADA' ? 'Entregado' : 'Pagado';
  }

  Color _colorEstado(Map<String, dynamic> o) {
    if (o['estado'] == 'CANCELADA') return const Color(0xFFC62828);
    if (_devuelto(o)) return const Color(0xFF6A1B9A);
    if (_tieneDevolucion(o)) return const Color(0xFFE65100);
    final entregado = o['estado'] == 'ENTREGADA' ||
        (o['delivery'] as Map?)?['estado'] == 'ENTREGADO';
    return entregado ? const Color(0xFF1B7F4B) : AppColors.primary;
  }

  // Fase 2: el backend decide (entregado, dentro de los 7 días y con prendas por devolver).
  bool _puedeDevolver(Map<String, dynamic> o) => o['puede_solicitar_devolucion'] == true;

  // Fase 2 (CU05): la prenda se puede cambiar si el pedido está en plazo y no
  // tiene un cambio en curso (uno rechazado no cuenta).
  bool _puedeCambiar(Map<String, dynamic> o, Map item) {
    if (o['puede_solicitar_cambio'] != true) return false;
    final cambio = item['cambio'] as Map?;
    return cambio == null || cambio['estado'] == 'RECHAZADO';
  }

  String _fecha(dynamic iso) {
    final dt = DateTime.tryParse('$iso')?.toLocal();
    return dt == null ? '' : DateFormat('dd/MM/yyyy HH:mm').format(dt);
  }

  Future<void> _abrirDevolucion(Map<String, dynamic> pedido) async {
    final devolucion = await Navigator.push<Map<String, dynamic>>(
      context,
      MaterialPageRoute(builder: (context) => DevolucionFormScreen(pedido: pedido)),
    );
    if (devolucion == null || !mounted) return;
    await _mostrarResultado(
      'Devolución solicitada',
      devolucion['numero_nota'],
      [devolucion['mensaje_cliente'], devolucion['resumen_reembolso']],
    );
  }

  Future<void> _abrirCambio(Map item) async {
    final cambio = await Navigator.push<Map<String, dynamic>>(
      context,
      MaterialPageRoute(
        builder: (context) => CambioSolicitudScreen(
          idOrdenItem: item['id_item'] as int,
          prenda: '${item['variante']}',
        ),
      ),
    );
    if (cambio == null || !mounted) return;
    await _mostrarResultado(
      'Cambio solicitado',
      cambio['numero_nota'],
      [
        '${cambio['prenda_devuelta']} → ${cambio['prenda_entregada']}',
        cambio['mensaje_cliente'],
      ],
    );
  }

  Future<void> _mostrarResultado(String titulo, dynamic nota, List<dynamic> lineas) async {
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(titulo),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (nota != null) Text('Nota $nota', style: const TextStyle(fontWeight: FontWeight.bold)),
            for (final l in lineas)
              if (l != null && '$l'.isNotEmpty)
                Padding(padding: const EdgeInsets.only(top: 6), child: Text('$l')),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cerrar')),
        ],
      ),
    );
    _cargar();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mis pedidos')),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _recargarTodo,
              child: _pedidos.isEmpty
                  ? ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(16),
                      children: [
                        if (_mostrarFidelidad) _tarjetaFidelidad(),
                        const SizedBox(height: 120),
                        Center(
                          child: Text(
                            _error ?? 'Todavía no tienes pedidos.',
                            style: const TextStyle(color: AppColors.grey),
                          ),
                        ),
                      ],
                    )
                  : Builder(builder: (context) {
                      // CU18: la tarjeta de fidelidad ocupa la primera posición.
                      final extra = _mostrarFidelidad ? 1 : 0;
                      return ListView.builder(
                        physics: const AlwaysScrollableScrollPhysics(),
                        padding: const EdgeInsets.all(16),
                        itemCount: _pedidos.length + extra,
                        itemBuilder: (context, index) {
                          if (index < extra) return _tarjetaFidelidad();
                          return _tarjeta(_pedidos[index - extra]);
                        },
                      );
                    }),
            ),
    );
  }

  /// NUEVO (CU18): "Tu descuento por fidelidad" (textos de la web).
  Widget _tarjetaFidelidad() {
    final datos = _fidelidad!;
    final regla = Map<String, dynamic>.from((datos['regla'] ?? {}) as Map);
    final activa = regla['activa'] == true;
    final empresas = FidelidadService.empresas(datos);
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Tu descuento por fidelidad',
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: Color(0xFF1A1A2E)),
          ),
          const SizedBox(height: 4),
          Text(
            activa
                ? 'Compra ${regla['compras_requeridas']} veces en una misma tienda este mes y tu '
                    'siguiente compra sin reservas tendrá '
                    '${FidelidadService.porcentajeTexto(regla['porcentaje'])}% de descuento en las '
                    'prendas. Se reinicia cada mes.'
                : 'El descuento por fidelidad no está activo en este momento.',
            style: const TextStyle(fontSize: 13, color: Color(0xFF6B6459)),
          ),
          const SizedBox(height: 8),
          for (final e in empresas) _filaFidelidad(e, datos['vence'], activa),
        ],
      ),
    );
  }

  /// Una tienda: nombre, "X de N compras", barra de progreso y mensaje según el estado.
  Widget _filaFidelidad(Map<String, dynamic> e, dynamic vence, bool activa) {
    final lista = e['disponible'] == true;
    final porcentaje = FidelidadService.porcentajeTexto(e['porcentaje']);
    final faltan = FidelidadService.numero(e['faltan']).toInt();
    String? mensaje;
    switch (e['estado']) {
      case 'DISPONIBLE':
        mensaje = '¡Tienes $porcentaje% de descuento en tu próxima compra sin reservas! '
            'Válido hasta el ${FidelidadService.fecha(vence)}.';
        break;
      case 'USADO':
        mensaje = 'Usaste tu descuento este mes en ${e['uso'] ?? ''} '
            '(−Bs ${FidelidadService.numero(e['monto_descuento']).toStringAsFixed(2)}).';
        break;
      case 'EN_PROGRESO':
        if (activa) {
          mensaje = 'Te ${faltan == 1 ? 'falta 1 compra' : 'faltan $faltan compras'} '
              'para ganar el descuento.';
        }
        break;
    }
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        boxShadow: const [BoxShadow(color: Color(0x0F000000), blurRadius: 8, offset: Offset(0, 2))],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: Container(
          decoration: BoxDecoration(
            border: Border(
              left: BorderSide(
                color: lista ? const Color(0xFF16A085) : const Color(0xFFE2E5EC),
                width: 4,
              ),
            ),
          ),
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${e['empresa'] ?? ''}',
                      style: const TextStyle(fontWeight: FontWeight.w700, color: Color(0xFF1A1A2E)),
                    ),
                  ),
                  Text(
                    '${e['compras']} de ${e['requeridas']} compras',
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFF0F3460),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: LinearProgressIndicator(
                  value: FidelidadService.avance(e['compras'], e['requeridas']),
                  minHeight: 8,
                  backgroundColor: const Color(0xFFEEF0F4),
                  valueColor: const AlwaysStoppedAnimation<Color>(Color(0xFF16A085)),
                ),
              ),
              if (mensaje != null) ...[
                const SizedBox(height: 6),
                Text(
                  mensaje,
                  style: TextStyle(
                    fontSize: 13,
                    color: lista ? const Color(0xFF1E6B3A) : const Color(0xFF1A1A2E),
                    fontWeight: lista ? FontWeight.w600 : FontWeight.w400,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _tarjeta(Map<String, dynamic> o) {
    final delivery = o['delivery'] as Map?;
    final esDelivery = o['tipo_entrega'] == 'DELIVERY' && delivery != null;
    final items = (o['items'] ?? []) as List;
    final devoluciones = (o['devoluciones'] ?? []) as List;
    final color = _colorEstado(o);

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Pedido #${o['id_orden']}',
                          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                      Text(_fecha(o['fecha_creacion']),
                          style: const TextStyle(color: AppColors.grey, fontSize: 12)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    _textoEstado(o),
                    style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            for (final i in items) _filaItem(o, i as Map),
            const Divider(height: 20),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(esDelivery ? 'Envío: Bs ${o['costo_envio']}' : ''),
                Text('Total: Bs ${o['total']}',
                    style: const TextStyle(fontWeight: FontWeight.w700)),
              ],
            ),
            if (esDelivery) ...[
              const SizedBox(height: 10),
              Text(
                'Entrega en: ${delivery['direccion']}'
                '${(delivery['referencia'] ?? '').toString().isNotEmpty ? ' (${delivery['referencia']})' : ''}',
                style: const TextStyle(fontSize: 13),
              ),
              if (delivery['repartidor'] != null) ...[
                const SizedBox(height: 2),
                Text('Repartidor: ${delivery['repartidor']}',
                    style: const TextStyle(fontSize: 13)),
              ],
              const SizedBox(height: 12),
              _lineaTiempo(_indicePaso(o)),
            ] else ...[
              const SizedBox(height: 8),
              Text('Retiro en sucursal: ${o['sucursal']}', style: const TextStyle(fontSize: 13)),
            ],
            if (o['puede_solicitar_cambio'] == true && o['cambio_vence'] != null) ...[
              const SizedBox(height: 8),
              Text('Puedes cambiar talla o color hasta el ${_fecha(o['cambio_vence'])}.',
                  style: const TextStyle(fontSize: 12, color: AppColors.grey)),
            ],
            // NUEVO (Fase 2 - CU12): devoluciones del pedido con su nota y reembolso.
            for (final d in devoluciones) _filaDevolucion(Map<String, dynamic>.from(d as Map)),
            if (_puedeDevolver(o)) ...[
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      o['devolucion_vence'] != null
                          ? 'Puedes pedir una devolución hasta el ${_fecha(o['devolucion_vence'])}.'
                          : '',
                      style: const TextStyle(fontSize: 12, color: AppColors.grey),
                    ),
                  ),
                  TextButton(
                    onPressed: () => _abrirDevolucion(o),
                    child: const Text('Solicitar devolución'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _filaItem(Map<String, dynamic> o, Map i) {
    final cambio = i['cambio'] as Map?;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(child: Text('${i['cantidad']} x ${i['variante']}')),
              Text('Bs ${i['subtotal']}'),
            ],
          ),
          if (cambio != null)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(top: 4),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFFE3F2FD),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Cambio ${cambio['numero_nota'] ?? ''} · ${cambio['estado_display'] ?? cambio['estado'] ?? ''}',
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFF0D47A1)),
                  ),
                  if (cambio['mensaje_cliente'] != null)
                    Text('${cambio['mensaje_cliente']}',
                        style: const TextStyle(fontSize: 12, color: Color(0xFF555555))),
                ],
              ),
            ),
          if (_puedeCambiar(o, i))
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => _abrirCambio(i),
                child: const Text('Cambiar talla o color'),
              ),
            ),
        ],
      ),
    );
  }

  Widget _filaDevolucion(Map<String, dynamic> d) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFF3E5F5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Devolución ${d['numero_nota'] ?? ''} · ${d['estado_display'] ?? d['estado'] ?? ''}',
            style: const TextStyle(fontWeight: FontWeight.w700, color: Color(0xFF6A1B9A)),
          ),
          if (d['es_anterior'] != true && d['monto_reembolso'] != null)
            Text('Reembolso: Bs ${d['monto_reembolso']}', style: const TextStyle(fontSize: 13)),
          if (d['mensaje_cliente'] != null)
            Text('${d['mensaje_cliente']}', style: const TextStyle(fontSize: 12, color: Color(0xFF555555))),
        ],
      ),
    );
  }

  Widget _lineaTiempo(int actual) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < _textos.length; i++) ...[
          if (i > 0)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Container(
                  height: 2,
                  color: i <= actual ? AppColors.primary : Colors.grey.shade300,
                ),
              ),
            ),
          Column(
            children: [
              Container(
                width: 14,
                height: 14,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: i <= actual ? AppColors.primary : Colors.grey.shade300,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                _textos[i],
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: i == actual ? FontWeight.w700 : FontWeight.w400,
                  color: i <= actual ? AppColors.primary : AppColors.grey,
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}