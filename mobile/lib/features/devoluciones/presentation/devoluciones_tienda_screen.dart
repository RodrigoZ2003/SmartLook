// mobile/lib/features/devoluciones/presentation/devoluciones_tienda_screen.dart
//
// NUEVO (Fase 2 - CU12, igual que web pos/devoluciones-tienda): devolución de
// prendas con reembolso y nota de devolución. Tres pestañas:
//   - Seguimiento: solicitudes de los clientes (con recojo). El encargado, el
//     administrador o el SUPER_ADMIN asigna repartidor y fecha de recojo
//     (máximo 48 h) o la rechaza.
//   - Registrar en tienda: busca la venta o el pedido, elige prendas, cantidad
//     y motivo, ve el reembolso y la registra (se completa en el momento).
//   - Historial del mes: devoluciones del mes con lo reembolsado y retenido.
// El cajero registra en tienda y consulta; aprobar y rechazar es del
// encargado, el administrador o el SUPER_ADMIN.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../../../shared/widgets/gestion_dialogs.dart';
import '../../admin/presentation/devolucion_list_screen.dart';
import '../data/devoluciones_service.dart';

class DevolucionesTiendaScreen extends StatefulWidget {
  const DevolucionesTiendaScreen({super.key});

  @override
  State<DevolucionesTiendaScreen> createState() => _DevolucionesTiendaScreenState();
}

class _DevolucionesTiendaScreenState extends State<DevolucionesTiendaScreen> {
  static const List<String> _rolesGestion = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];
  static const List<List<String>> _estados = [
    ['SOLICITADA', 'Por aprobar'],
    ['PROGRAMADA', 'Recojo programado'],
    ['EN_CAMINO', 'En camino'],
    ['COMPLETADA', 'Completadas'],
    ['RECHAZADA', 'Rechazadas'],
    ['', 'Todas'],
  ];

  late final DevolucionesService _service;
  late final bool _esGestor;
  final DateFormat _fmt = DateFormat('dd/MM/yyyy HH:mm');

  String? _mensaje;
  String? _error;

  // ---- Seguimiento
  String _filtroEstado = 'SOLICITADA';
  String _filtroModalidad = '';
  List<Map<String, dynamic>> _devoluciones = [];
  bool _cargando = false;
  List<Map<String, dynamic>> _repartidores = [];
  int? _procesando;

  // ---- Registrar en tienda
  final TextEditingController _numeroCtrl = TextEditingController();
  final TextEditingController _observacionCtrl = TextEditingController();
  String _tipoCompra = 'VENTA';
  bool _buscando = false;
  Map<String, dynamic>? _compra;
  final Map<int, Map<String, dynamic>> _seleccion = {};
  Map<String, dynamic>? _montos;
  bool _calculando = false;
  int _calculoId = 0;
  bool _condicionesOk = false;
  bool _registrando = false;

  // ---- Historial del mes
  DateTime _mes = DateTime(DateTime.now().year, DateTime.now().month);
  List<Map<String, dynamic>> _devolucionesMes = [];
  bool _cargandoMes = false;

  @override
  void initState() {
    super.initState();
    _service = DevolucionesService(apiClient: context.read<ApiClient>());
    final usuario = context.read<AuthService>().currentUser;
    _esGestor = _rolesGestion.any((r) => usuario?.hasRole(r) ?? false);
    if (_esGestor) {
      _service.repartidores().then((r) {
        if (mounted) setState(() => _repartidores = r);
      }).catchError((_) {});
    }
    _cargarSeguimiento();
    _cargarMes();
  }

  @override
  void dispose() {
    _numeroCtrl.dispose();
    _observacionCtrl.dispose();
    super.dispose();
  }

  String _fecha(dynamic iso) {
    final dt = DateTime.tryParse('${iso ?? ''}')?.toLocal();
    return dt == null ? '' : _fmt.format(dt);
  }

  double _num(dynamic v) => double.tryParse('${v ?? ''}') ?? 0;

  String get _mesTexto =>
      '${_mes.year.toString().padLeft(4, '0')}-${_mes.month.toString().padLeft(2, '0')}';

  void _limpiarAvisos() {
    _mensaje = null;
    _error = null;
  }

  // ---------------------------------------------------------------- seguimiento
  Future<void> _cargarSeguimiento() async {
    setState(() => _cargando = true);
    try {
      final lista = await _service.listar({
        'estado': _filtroEstado,
        'modalidad': _filtroModalidad,
        'page_size': 50,
      });
      if (!mounted) return;
      setState(() {
        _devoluciones = lista;
        _cargando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _devoluciones = [];
        _cargando = false;
        _error = DevolucionesService.textoError(e, 'No se pudieron cargar las devoluciones.');
      });
    }
  }

  Future<void> _aprobar(Map<String, dynamic> d) async {
    setState(_limpiarAvisos);
    final datos = await pedirAprobacion(
      context,
      titulo: 'Aprobar y asignar repartidor',
      etiquetaFecha: 'Fecha y hora del recojo (máximo 48 h)',
      repartidores: _repartidores,
      nota: 'El reembolso y la reposición del stock se hacen cuando el repartidor complete el recojo.',
    );
    if (datos == null) return;
    final id = d['id_devolucion'] as int;
    setState(() => _procesando = id);
    try {
      final actualizada = await _service.aprobar(id, datos.$1, datos.$2);
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _mensaje = 'Devolución ${actualizada['numero_nota']} con recojo programado con ${actualizada['repartidor']}.';
      });
      _cargarSeguimiento();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _error = DevolucionesService.textoError(e, 'No se pudo aprobar la devolución.');
      });
    }
  }

  Future<void> _rechazar(Map<String, dynamic> d) async {
    setState(_limpiarAvisos);
    final motivo = await pedirMotivoRechazo(context);
    if (motivo == null) return;
    final id = d['id_devolucion'] as int;
    setState(() => _procesando = id);
    try {
      final actualizada = await _service.rechazar(id, motivo);
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _mensaje = 'Devolución ${actualizada['numero_nota']} rechazada.';
      });
      _cargarSeguimiento();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _error = DevolucionesService.textoError(e, 'No se pudo rechazar la devolución.');
      });
    }
  }

  void _verNota(Map<String, dynamic> n) {
    final origen = n['origen'] as Map?;
    final items = (n['items'] ?? []) as List;
    mostrarNota(
      context,
      'Nota de devolución ${n['numero_nota']}',
      [
        ('Estado', '${n['estado_display'] ?? ''}'),
        ('Origen', '${origen?['etiqueta'] ?? ''} · ${n['sucursal'] ?? ''}'),
        ('Cliente', '${n['cliente'] ?? 'Sin cliente'}'),
        ('Modalidad', '${n['modalidad_display'] ?? 'Anterior'}'),
        ('Solicitada', '${_fecha(n['fecha_creacion'])} · ${n['solicitado_por'] ?? '-'}'),
        if (n['aprobado_por'] != null) ('Aprobada', '${_fecha(n['fecha_aprobacion'])} · ${n['aprobado_por']}'),
        if (n['repartidor'] != null) ('Repartidor', '${n['repartidor']}'),
        if (n['completado_por'] != null) ('Completada', '${_fecha(n['fecha_completado'])} · ${n['completado_por']}'),
        if (n['observacion'] != null) ('Observación', '${n['observacion']}'),
        if (n['motivo_rechazo'] != null) ('Rechazo', '${n['motivo_rechazo']}'),
      ],
      extra: [
        const SizedBox(height: 10),
        const Text('Prendas', style: TextStyle(fontWeight: FontWeight.w700)),
        for (final i in items)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              '${i['cantidad']} x ${i['variante']} (${i['motivo_display']})'
              '${i['repone_stock'] == false ? ' · no vuelve al stock' : ''}\n'
              'Pagado ${i['subtotal'] != null ? 'Bs ${i['subtotal']}' : '-'} · '
              'Retenido ${i['monto_retenido'] != null ? 'Bs ${i['monto_retenido']}' : '-'} · '
              'Devuelve ${i['monto_reembolso'] != null ? 'Bs ${i['monto_reembolso']}' : '-'}',
              style: const TextStyle(fontSize: 13),
            ),
          ),
        if (n['es_anterior'] != true) ...[
          const SizedBox(height: 10),
          Text('Prendas devueltas: Bs ${n['monto_prendas']}'),
          if (_num(n['monto_retenido']) > 0) Text('La empresa retiene el 10%: - Bs ${n['monto_retenido']}'),
          if (_num(n['monto_envio']) > 0) Text('Envío devuelto: + Bs ${n['monto_envio']}'),
          Text('Se devuelve: Bs ${n['monto_reembolso']} (${n['metodo_reembolso_display'] ?? ''})',
              style: const TextStyle(fontWeight: FontWeight.w700)),
        ],
      ],
    );
  }

  // ---------------------------------------------------------------- registrar en tienda
  Future<void> _buscarCompra({bool limpiarMensaje = true}) async {
    final numero = int.tryParse(_numeroCtrl.text.trim());
    if (numero == null || numero < 1) {
      setState(() => _error = 'Escribe el número de la venta o del pedido.');
      return;
    }
    setState(() {
      _buscando = true;
      _error = null;
      if (limpiarMensaje) _mensaje = null;
      _montos = null;
      _condicionesOk = false;
      _observacionCtrl.clear();
    });
    try {
      final compra = await _service.buscarCompra(_tipoCompra, numero);
      if (!mounted) return;
      setState(() {
        _compra = compra;
        _seleccion.clear();
        for (final raw in (compra['items'] ?? []) as List) {
          final i = Map<String, dynamic>.from(raw as Map);
          _seleccion[i['id_item'] as int] = {'incluir': false, 'cantidad': 1, 'motivo': 'PRODUCTO_DANADO'};
        }
        _buscando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _compra = null;
        _buscando = false;
        _error = DevolucionesService.textoError(e, 'No se encontró la compra.');
      });
    }
  }

  List<Map<String, dynamic>> get _itemsElegidos => _seleccion.entries
      .where((e) => e.value['incluir'] == true)
      .map((e) => {'id_item': e.key, 'cantidad': e.value['cantidad'], 'motivo': e.value['motivo']})
      .toList();

  Future<void> _recalcular() async {
    final compra = _compra;
    final items = _itemsElegidos;
    final id = ++_calculoId;
    if (compra == null || items.isEmpty) {
      setState(() {
        _montos = null;
        _calculando = false;
      });
      return;
    }
    setState(() => _calculando = true);
    try {
      final montos = await _service.calcular('${compra['tipo']}', compra['numero'] as int, items);
      if (!mounted || id != _calculoId) return;
      setState(() {
        _montos = montos;
        _calculando = false;
      });
    } catch (e) {
      if (!mounted || id != _calculoId) return;
      setState(() {
        _montos = null;
        _calculando = false;
        _error = DevolucionesService.textoError(e, 'No se pudo calcular el reembolso.');
      });
    }
  }

  void _cambiarSeleccion(int idItem, String campo, dynamic valor) {
    setState(() => _seleccion[idItem]![campo] = valor);
    _recalcular();
  }

  Future<void> _registrar() async {
    final compra = _compra;
    final items = _itemsElegidos;
    if (compra == null || items.isEmpty) {
      setState(() => _error = 'Elige al menos una prenda.');
      return;
    }
    if (!_condicionesOk) {
      setState(() => _error = 'Confirma que revisaste la prenda.');
      return;
    }
    setState(() {
      _registrando = true;
      _error = null;
    });
    try {
      final devolucion = await _service.registrarTienda(
        tipo: '${compra['tipo']}',
        numero: compra['numero'] as int,
        items: items,
        observacion: _observacionCtrl.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _registrando = false;
        _mensaje = 'Devolución ${devolucion['numero_nota']} registrada: se devuelve Bs '
            '${devolucion['monto_reembolso']} (${devolucion['metodo_reembolso_display'] ?? ''}).';
      });
      _verNota(devolucion);
      _buscarCompra(limpiarMensaje: false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _registrando = false;
        _error = DevolucionesService.textoError(e, 'No se pudo registrar la devolución.');
      });
    }
  }

  // ---------------------------------------------------------------- historial del mes
  Future<void> _cargarMes() async {
    setState(() => _cargandoMes = true);
    try {
      final lista = await _service.listar({'mes': _mesTexto, 'page_size': 100});
      if (!mounted) return;
      setState(() {
        _devolucionesMes = lista;
        _cargandoMes = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _devolucionesMes = [];
        _cargandoMes = false;
        _error = DevolucionesService.textoError(e, 'No se pudieron cargar las devoluciones del mes.');
      });
    }
  }

  void _moverMes(int delta) {
    setState(() => _mes = DateTime(_mes.year, _mes.month + delta));
    _cargarMes();
  }

  double _sumaCompletadas(String campo) => _devolucionesMes
      .where((d) => d['estado'] == 'COMPLETADA' && d['es_anterior'] != true)
      .fold(0.0, (t, d) => t + _num(d[campo]));

  // ---------------------------------------------------------------- interfaz
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Devoluciones'),
          actions: [
            if (_esGestor)
              IconButton(
                tooltip: 'Lista de devoluciones',
                icon: const Icon(Icons.list_alt),
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const DevolucionListScreen()),
                ),
              ),
          ],
          bottom: const TabBar(
            isScrollable: true,
            tabs: [
              Tab(text: 'Seguimiento'),
              Tab(text: 'Registrar en tienda'),
              Tab(text: 'Historial del mes'),
            ],
          ),
        ),
        body: Column(
          children: [
            if (_mensaje != null) _aviso(_mensaje!, const Color(0xFFE8F5E9), const Color(0xFF1B5E20)),
            if (_error != null) _aviso(_error!, AppColors.dangerBg, AppColors.danger),
            Expanded(
              child: TabBarView(
                children: [
                  _tabSeguimiento(),
                  _tabTienda(),
                  _tabMes(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _aviso(String texto, Color fondo, Color color) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 10, 16, 0),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(6)),
      child: Row(
        children: [
          Expanded(child: Text(texto, style: TextStyle(color: color))),
          InkWell(onTap: () => setState(_limpiarAvisos), child: Icon(Icons.close, size: 18, color: color)),
        ],
      ),
    );
  }

  // ---- Pestaña Seguimiento
  Widget _tabSeguimiento() {
    return RefreshIndicator(
      onRefresh: _cargarSeguimiento,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Devolución dentro de los 7 días con reembolso y nota de devolución.',
              style: TextStyle(fontSize: 13, color: AppColors.grey)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final e in _estados)
                ChoiceChip(
                  label: Text(e[1]),
                  selected: _filtroEstado == e[0],
                  onSelected: (_) {
                    setState(() => _filtroEstado = e[0]);
                    _cargarSeguimiento();
                  },
                ),
            ],
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            value: _filtroModalidad,
            decoration: const InputDecoration(labelText: 'Modalidad', border: OutlineInputBorder()),
            items: const [
              DropdownMenuItem(value: '', child: Text('Tienda y recojo')),
              DropdownMenuItem(value: 'DELIVERY', child: Text('Solo con recojo')),
              DropdownMenuItem(value: 'TIENDA', child: Text('Solo en tienda')),
            ],
            onChanged: (v) {
              setState(() => _filtroModalidad = v ?? '');
              _cargarSeguimiento();
            },
          ),
          const SizedBox(height: 12),
          if (_cargando)
            const Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()))
          else if (_devoluciones.isEmpty)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: Text('No hay devoluciones en esta lista.')),
            )
          else
            for (final d in _devoluciones) _tarjetaDevolucion(d),
        ],
      ),
    );
  }

  Widget _tarjetaDevolucion(Map<String, dynamic> d) {
    final estado = '${d['estado']}';
    final (fondo, color) = coloresEstadoGestion(estado);
    final contacto = d['cliente_contacto'] as Map?;
    final entrega = d['entrega'] as Map?;
    final origen = d['origen'] as Map?;
    final items = (d['items'] ?? []) as List;
    final ocupado = _procesando == d['id_devolucion'];
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: d['atrasado'] == true ? AppColors.danger : AppColors.greyLight),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${d['numero_nota']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text('${origen?['etiqueta'] ?? ''} · ${d['sucursal'] ?? ''} · ${d['modalidad_display'] ?? 'Anterior'}',
                          style: const TextStyle(fontSize: 12, color: AppColors.grey)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                  child: Text('${d['estado_display'] ?? estado}',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color)),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text('Cliente: ${d['cliente'] ?? 'Sin cliente'}'
                '${contacto?['telefono'] != null ? ' · Tel. ${contacto!['telefono']}' : ''}'),
            for (final i in items)
              Text('• ${i['cantidad']} x ${i['variante']} (${i['motivo_display']})'
                  '${i['monto_reembolso'] != null ? ' · devuelve Bs ${i['monto_reembolso']}' : ''}'),
            if (d['es_anterior'] != true && d['resumen_reembolso'] != null)
              Text('${d['resumen_reembolso']}', style: const TextStyle(fontWeight: FontWeight.w600)),
            if (entrega != null)
              Text('Dirección: ${entrega['direccion']}'
                  '${entrega['referencia'] != null && '${entrega['referencia']}'.isNotEmpty ? ' (${entrega['referencia']})' : ''}'),
            if (d['observacion'] != null) Text('Observación: ${d['observacion']}'),
            if (d['repartidor'] != null)
              Text('Repartidor: ${d['repartidor']} · recojo ${_fecha(d['fecha_programada'])} · '
                  'límite ${_fecha(d['fecha_limite'])}${d['atrasado'] == true ? ' · ATRASADO' : ''}'),
            if (d['motivo_rechazo'] != null)
              Text('Rechazada: ${d['motivo_rechazo']}', style: const TextStyle(color: AppColors.danger)),
            Text('Solicitada el ${_fecha(d['fecha_creacion'])}'
                '${d['solicitado_por'] != null ? ' por ${d['solicitado_por']}' : ''}',
                style: const TextStyle(fontSize: 12, color: AppColors.grey)),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                OutlinedButton(onPressed: () => _verNota(d), child: const Text('Ver nota de devolución')),
                if (_esGestor && estado == 'SOLICITADA')
                  ElevatedButton(
                    onPressed: ocupado ? null : () => _aprobar(d),
                    child: const Text('Aprobar y asignar repartidor'),
                  ),
                if (_esGestor && (estado == 'SOLICITADA' || estado == 'PROGRAMADA' || estado == 'EN_CAMINO'))
                  OutlinedButton(
                    onPressed: ocupado ? null : () => _rechazar(d),
                    style: OutlinedButton.styleFrom(foregroundColor: AppColors.danger),
                    child: const Text('Rechazar'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // ---- Pestaña Registrar en tienda
  Widget _tabTienda() {
    final compra = _compra;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        DropdownButtonFormField<String>(
          value: _tipoCompra,
          decoration: const InputDecoration(labelText: 'Tipo de compra', border: OutlineInputBorder()),
          items: const [
            DropdownMenuItem(value: 'VENTA', child: Text('Venta en tienda (POS)')),
            DropdownMenuItem(value: 'PEDIDO', child: Text('Pedido en línea')),
          ],
          onChanged: (v) => setState(() => _tipoCompra = v ?? 'VENTA'),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _numeroCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Número (ej.: 14)', border: OutlineInputBorder()),
                onSubmitted: (_) => _buscarCompra(),
              ),
            ),
            const SizedBox(width: 8),
            ElevatedButton(
              onPressed: _buscando ? null : _buscarCompra,
              child: Text(_buscando ? 'Buscando...' : 'Buscar'),
            ),
          ],
        ),
        if (compra != null) ...[
          const SizedBox(height: 16),
          _tarjetaCompra(compra),
          if (_itemsElegidos.isNotEmpty) ...[
            const SizedBox(height: 12),
            _formularioReembolso(),
          ],
        ],
      ],
    );
  }

  Widget _tarjetaCompra(Map<String, dynamic> compra) {
    final items = (compra['items'] ?? []) as List;
    final cliente = compra['cliente'] as Map?;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${compra['etiqueta']} · ${compra['sucursal'] ?? ''}',
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
            Text(
              '${_fecha(compra['fecha'])} · ${compra['entrega'] ?? ''}'
              '${cliente != null ? ' · Cliente: ${cliente['nombre']}' : ''}'
              ' · Plazo hasta el ${_fecha(compra['vence'])}',
              style: const TextStyle(fontSize: 12, color: AppColors.grey),
            ),
            if (compra['motivo_no_elegible'] != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('${compra['motivo_no_elegible']}', style: const TextStyle(color: AppColors.danger)),
              ),
            const SizedBox(height: 6),
            for (final raw in items) _filaItem(Map<String, dynamic>.from(raw as Map)),
            const SizedBox(height: 6),
            const Text(
              'Dañada u otra prenda: se devuelve el 100% (y el envío, si fue con delivery). Ya no la quiere: se devuelve el 90%.',
              style: TextStyle(fontSize: 12, color: AppColors.grey),
            ),
          ],
        ),
      ),
    );
  }

  Widget _filaItem(Map<String, dynamic> i) {
    final id = i['id_item'] as int;
    final noElegible = i['motivo_no_elegible'];
    final sel = _seleccion[id]!;
    final disponible = (i['disponible'] ?? 0) as int;
    final incluir = sel['incluir'] == true;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Color(0xFFF0F0F0)))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: incluir && noElegible == null,
            title: Text('${i['prenda']}'),
            subtitle: Text(
              noElegible != null
                  ? '$noElegible'
                  : 'Bs ${i['precio_unitario']} · se puede devolver $disponible de ${i['cantidad']}',
              style: TextStyle(fontSize: 12, color: noElegible != null ? AppColors.danger : AppColors.grey),
            ),
            onChanged: noElegible != null ? null : (v) => _cambiarSeleccion(id, 'incluir', v ?? false),
          ),
          if (incluir && noElegible == null)
            Row(
              children: [
                if (disponible > 1) ...[
                  IconButton(
                    icon: const Icon(Icons.remove_circle_outline),
                    onPressed: (sel['cantidad'] as int) <= 1
                        ? null
                        : () => _cambiarSeleccion(id, 'cantidad', (sel['cantidad'] as int) - 1),
                  ),
                  Text('${sel['cantidad']}'),
                  IconButton(
                    icon: const Icon(Icons.add_circle_outline),
                    onPressed: (sel['cantidad'] as int) >= disponible
                        ? null
                        : () => _cambiarSeleccion(id, 'cantidad', (sel['cantidad'] as int) + 1),
                  ),
                ] else
                  const Padding(padding: EdgeInsets.only(right: 12), child: Text('1 u.')),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    value: sel['motivo'] as String,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Motivo', border: OutlineInputBorder()),
                    items: motivosDevolucionTienda
                        .map((m) => DropdownMenuItem(value: m['valor'], child: Text(m['texto']!)))
                        .toList(),
                    onChanged: (v) => _cambiarSeleccion(id, 'motivo', v ?? sel['motivo']),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _formularioReembolso() {
    final m = _montos;
    Widget fila(String a, String b, {bool fuerte = false, Color? color}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            children: [
              Expanded(child: Text(a, style: TextStyle(color: color))),
              Text(b, style: TextStyle(fontWeight: fuerte ? FontWeight.bold : FontWeight.w600, color: color)),
            ],
          ),
        );
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Reembolso', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
            if (_calculando) const Padding(padding: EdgeInsets.all(8), child: Text('Calculando...')),
            if (m != null && !_calculando) ...[
              fila('Prendas devueltas', 'Bs ${m['monto_prendas']}'),
              if (_num(m['monto_retenido']) > 0)
                fila('La empresa retiene el 10% (ya no la quiere)', '- Bs ${m['monto_retenido']}',
                    color: AppColors.danger),
              if (_num(m['monto_envio']) > 0) fila('Envío devuelto', '+ Bs ${m['monto_envio']}'),
              const Divider(),
              fila('Se le devuelve', 'Bs ${m['monto_reembolso']}', fuerte: true, color: AppColors.success),
              Text(
                m['metodo_reembolso'] == 'EFECTIVO'
                    ? 'Se paga en efectivo desde la caja.'
                    : m['metodo_reembolso'] == 'STRIPE'
                        ? 'Se reembolsa automáticamente a la tarjeta del cliente.'
                        : 'El pago no fue con Stripe: el reembolso se registra manualmente.',
                style: const TextStyle(fontSize: 12, color: AppColors.grey),
              ),
            ],
            const SizedBox(height: 8),
            TextField(
              controller: _observacionCtrl,
              decoration: const InputDecoration(
                labelText: 'Observación (opcional)',
                hintText: 'Ej.: costura abierta en la manga',
                border: OutlineInputBorder(),
              ),
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _condicionesOk,
              title: const Text('Revisé la prenda: sin uso y con etiqueta (si está dañada, el defecto no es por mal uso)'),
              onChanged: (v) => setState(() => _condicionesOk = v ?? false),
            ),
            ElevatedButton(
              onPressed: (_registrando || _calculando || m == null) ? null : _registrar,
              style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 48)),
              child: Text(_registrando ? 'Registrando...' : 'Registrar devolución'),
            ),
          ],
        ),
      ),
    );
  }

  // ---- Pestaña Historial del mes
  Widget _tabMes() {
    final completadas = _devolucionesMes.where((d) => d['estado'] == 'COMPLETADA').length;
    final enProceso = _devolucionesMes
        .where((d) => ['SOLICITADA', 'PROGRAMADA', 'EN_CAMINO'].contains(d['estado']))
        .length;
    return RefreshIndicator(
      onRefresh: _cargarMes,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton(icon: const Icon(Icons.chevron_left), onPressed: () => _moverMes(-1)),
              Text('Mes: ${_mes.month.toString().padLeft(2, '0')}/${_mes.year}',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
              IconButton(icon: const Icon(Icons.chevron_right), onPressed: () => _moverMes(1)),
            ],
          ),
          Row(
            children: [
              _tarjetaNumero('${_devolucionesMes.length}', 'Devoluciones del mes', AppColors.light, AppColors.textDark),
              const SizedBox(width: 6),
              _tarjetaNumero('$completadas', 'Completadas', const Color(0xFFE8F8F0), const Color(0xFF1B7F4B)),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              _tarjetaNumero('$enProceso', 'En proceso', const Color(0xFFE3F2FD), const Color(0xFF0D47A1)),
              const SizedBox(width: 6),
              _tarjetaNumero(
                'Bs ${_sumaCompletadas('monto_reembolso').toStringAsFixed(2)}',
                'Reembolsado (retenido Bs ${_sumaCompletadas('monto_retenido').toStringAsFixed(2)})',
                const Color(0xFFFFF8E1),
                const Color(0xFF8A6D00),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (_cargandoMes)
            const Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()))
          else if (_devolucionesMes.isEmpty)
            const Padding(padding: EdgeInsets.all(16), child: Center(child: Text('No hay devoluciones en este mes.')))
          else
            for (final d in _devolucionesMes)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  title: Text('${d['numero_nota']} · ${(d['origen'] as Map?)?['etiqueta'] ?? ''}'),
                  subtitle: Text(
                    '${_fecha(d['fecha_creacion'])} · ${d['sucursal'] ?? ''}\n'
                    '${d['es_anterior'] == true ? '-' : 'Bs ${d['monto_reembolso']}'} · ${d['estado_display'] ?? ''}',
                  ),
                  isThreeLine: true,
                  trailing: TextButton(onPressed: () => _verNota(d), child: const Text('Ver')),
                ),
              ),
        ],
      ),
    );
  }

  Widget _tarjetaNumero(String numero, String etiqueta, Color fondo, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(8)),
        child: Column(
          children: [
            Text(numero,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: color)),
            Text(etiqueta, textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: color)),
          ],
        ),
      ),
    );
  }
}