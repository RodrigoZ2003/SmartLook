// mobile/lib/features/cambios/presentation/cambios_tienda_screen.dart
//
// NUEVO (Fase 2 - CU05 / CU06, igual que web pos/cambios-prenda): cambio de
// prenda por talla o color. Tres pestañas:
//   - Seguimiento: solicitudes de los clientes (delivery). El encargado, el
//     administrador o el SUPER_ADMIN asigna repartidor y fecha de visita
//     (máximo 48 h) o la rechaza; se ve el avance hasta "Completado".
//   - Registrar en tienda: busca la venta o el pedido, elige la prenda, el
//     motivo y la nueva talla/color; se completa en el momento.
//   - Consulta del mes (CU06): totales por estado, motivo, modalidad,
//     sucursal y prendas más cambiadas, con la lista de cambios del mes.
// El cajero registra en tienda y consulta; aprobar y rechazar es del
// encargado, el administrador o el SUPER_ADMIN.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../../../shared/widgets/gestion_dialogs.dart';
import '../data/cambios_service.dart';

class CambiosTiendaScreen extends StatefulWidget {
  const CambiosTiendaScreen({super.key});

  @override
  State<CambiosTiendaScreen> createState() => _CambiosTiendaScreenState();
}

class _CambiosTiendaScreenState extends State<CambiosTiendaScreen> {
  static const List<String> _rolesGestion = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];
  static const List<List<String>> _estados = [
    ['SOLICITADO', 'Por aprobar'],
    ['PROGRAMADO', 'Programados'],
    ['EN_CAMINO', 'En camino'],
    ['COMPLETADO', 'Completados'],
    ['RECHAZADO', 'Rechazados'],
    ['', 'Todos'],
  ];

  late final CambiosService _service;
  late final bool _esGestor;
  final DateFormat _fmt = DateFormat('dd/MM/yyyy HH:mm');

  String? _mensaje;
  String? _error;

  // ---- Seguimiento
  String _filtroEstado = 'SOLICITADO';
  String _filtroModalidad = '';
  List<Map<String, dynamic>> _cambios = [];
  bool _cargando = false;
  List<Map<String, dynamic>> _repartidores = [];
  int? _procesando;

  // ---- Registrar en tienda
  final TextEditingController _numeroCtrl = TextEditingController();
  final TextEditingController _observacionCtrl = TextEditingController();
  String _tipoCompra = 'VENTA';
  bool _buscando = false;
  Map<String, dynamic>? _compra;
  Map<String, dynamic>? _itemSel;
  Map<String, dynamic>? _opciones;
  bool _cargandoOpciones = false;
  String _motivo = 'NO_LE_QUEDA';
  int? _idVariante;
  int _cantidad = 1;
  bool _condicionesOk = false;
  bool _registrando = false;

  // ---- Consulta del mes (CU06)
  DateTime _mes = DateTime(DateTime.now().year, DateTime.now().month);
  Map<String, dynamic>? _resumen;
  List<Map<String, dynamic>> _cambiosMes = [];
  bool _cargandoMes = false;

  @override
  void initState() {
    super.initState();
    _service = CambiosService(apiClient: context.read<ApiClient>());
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
        _cambios = lista;
        _cargando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _cambios = [];
        _cargando = false;
        _error = CambiosService.textoError(e, 'No se pudieron cargar los cambios.');
      });
    }
  }

  Future<void> _aprobar(Map<String, dynamic> c) async {
    setState(_limpiarAvisos);
    final nota = c['motivo'] == 'ERROR_TIENDA'
        ? 'Al aprobar se corrige el inventario: se descuenta ${c['prenda_devuelta']}, que salió por error.'
        : 'Al aprobar se aparta ${c['prenda_entregada']} (se descuenta del stock).';
    final datos = await pedirAprobacion(
      context,
      titulo: 'Aprobar y asignar repartidor',
      etiquetaFecha: 'Fecha y hora de la visita (máximo 48 h)',
      repartidores: _repartidores,
      nota: nota,
    );
    if (datos == null) return;
    final id = c['id_cambio'] as int;
    setState(() => _procesando = id);
    try {
      final actualizado = await _service.aprobar(id, datos.$1, datos.$2);
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _mensaje = 'Cambio ${actualizado['numero_nota']} programado con ${actualizado['repartidor']}.';
      });
      _cargarSeguimiento();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _error = CambiosService.textoError(e, 'No se pudo aprobar el cambio.');
      });
    }
  }

  Future<void> _rechazar(Map<String, dynamic> c) async {
    setState(_limpiarAvisos);
    final motivo = await pedirMotivoRechazo(
      context,
      nota: c['estado'] != 'SOLICITADO' ? 'Lo que se descontó al aprobar vuelve al stock.' : null,
    );
    if (motivo == null) return;
    final id = c['id_cambio'] as int;
    setState(() => _procesando = id);
    try {
      final actualizado = await _service.rechazar(id, motivo);
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _mensaje = 'Cambio ${actualizado['numero_nota']} rechazado.';
      });
      _cargarSeguimiento();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _procesando = null;
        _error = CambiosService.textoError(e, 'No se pudo rechazar el cambio.');
      });
    }
  }

  void _verNota(Map<String, dynamic> n) {
    final cliente = n['cliente'] as Map?;
    final origen = n['origen'] as Map?;
    mostrarNota(context, 'Nota de devolución ${n['numero_nota']}', [
      ('Estado', '${n['estado_display'] ?? ''}'),
      ('Origen', '${origen?['etiqueta'] ?? ''} · ${n['sucursal'] ?? ''}'),
      ('Cliente', '${cliente?['nombre'] ?? 'Sin cliente'}'),
      ('Motivo', '${n['motivo_display'] ?? ''}'),
      ('Modalidad', '${n['modalidad_display'] ?? ''}'),
      ('Prenda devuelta', '${n['prenda_devuelta']} (${n['cantidad']} u.)'),
      ('Prenda entregada', '${n['prenda_entregada']} · Bs ${n['precio']}'),
      ('Condiciones', n['condiciones_verificadas'] == true ? 'Sin uso y con etiqueta (verificado)' : 'Sin verificar'),
      ('Solicitado', '${_fecha(n['fecha_solicitud'])} · ${n['solicitado_por'] ?? '-'}'),
      if (n['aprobado_por'] != null) ('Aprobado', '${_fecha(n['fecha_aprobacion'])} · ${n['aprobado_por']}'),
      if (n['repartidor'] != null) ('Repartidor', '${n['repartidor']}'),
      if (n['completado_por'] != null) ('Completado', '${_fecha(n['fecha_completado'])} · ${n['completado_por']}'),
      if (n['observacion'] != null) ('Observación', '${n['observacion']}'),
      if (n['motivo_rechazo'] != null) ('Rechazo', '${n['motivo_rechazo']}'),
    ]);
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
      _itemSel = null;
      _opciones = null;
    });
    try {
      final compra = await _service.buscarCompra(_tipoCompra, numero);
      if (!mounted) return;
      setState(() {
        _compra = compra;
        _buscando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _compra = null;
        _buscando = false;
        _error = CambiosService.textoError(e, 'No se encontró la compra.');
      });
    }
  }

  Future<void> _elegirItem(Map<String, dynamic> item) async {
    if (item['motivo_no_elegible'] != null) return;
    setState(() {
      _itemSel = item;
      _opciones = null;
      _error = null;
      _motivo = 'NO_LE_QUEDA';
      _idVariante = null;
      _cantidad = 1;
      _condicionesOk = false;
      _observacionCtrl.clear();
      _cargandoOpciones = true;
    });
    try {
      final opciones = await _service.opciones(
        idVentaItem: item['id_venta_item'] as int?,
        idOrdenItem: item['id_orden_item'] as int?,
      );
      if (!mounted) return;
      setState(() {
        _opciones = opciones;
        _cargandoOpciones = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _cargandoOpciones = false;
        _error = CambiosService.textoError(e, 'No se pudieron cargar las tallas y colores.');
      });
    }
  }

  List<Map<String, dynamic>> get _alternativasValidas {
    final lista = ((_opciones?['alternativas'] ?? []) as List<dynamic>)
        .map((a) => Map<String, dynamic>.from(a as Map))
        .toList();
    if (_motivo == 'ERROR_TIENDA') return lista;
    return lista.where((a) => a['mismo_precio'] == true && ((a['stock'] ?? 0) as int) > 0).toList();
  }

  Future<void> _registrar() async {
    if (_itemSel == null || _idVariante == null) {
      setState(() => _error = _motivo == 'ERROR_TIENDA'
          ? 'Elige la talla o el color que se entregó por error.'
          : 'Elige la nueva talla o color.');
      return;
    }
    if (!_condicionesOk) {
      setState(() => _error = 'Confirma que la prenda devuelta está sin uso y con etiqueta.');
      return;
    }
    setState(() {
      _registrando = true;
      _error = null;
    });
    try {
      final cambio = await _service.registrarTienda(
        idVentaItem: _itemSel!['id_venta_item'] as int?,
        idOrdenItem: _itemSel!['id_orden_item'] as int?,
        motivo: _motivo,
        idVariante: _idVariante!,
        cantidad: _cantidad,
        observacion: _observacionCtrl.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _registrando = false;
        _itemSel = null;
        _opciones = null;
        _mensaje = 'Cambio ${cambio['numero_nota']} registrado: el cliente devolvió '
            '${cambio['prenda_devuelta']} y recibió ${cambio['prenda_entregada']}.';
      });
      _verNota(cambio);
      _buscarCompra(limpiarMensaje: false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _registrando = false;
        _error = CambiosService.textoError(e, 'No se pudo registrar el cambio.');
      });
    }
  }

  // ---------------------------------------------------------------- consulta del mes (CU06)
  Future<void> _cargarMes() async {
    setState(() => _cargandoMes = true);
    try {
      final resumen = await _service.resumenMes(_mesTexto);
      if (mounted) setState(() => _resumen = resumen);
    } catch (e) {
      if (mounted) {
        setState(() {
          _resumen = null;
          _error = CambiosService.textoError(e, 'No se pudo cargar el resumen del mes.');
        });
      }
    }
    try {
      final lista = await _service.listar({'mes': _mesTexto, 'page_size': 100});
      if (mounted) setState(() => _cambiosMes = lista);
    } catch (_) {
      if (mounted) setState(() => _cambiosMes = []);
    }
    if (mounted) setState(() => _cargandoMes = false);
  }

  void _moverMes(int delta) {
    setState(() => _mes = DateTime(_mes.year, _mes.month + delta));
    _cargarMes();
  }

  int _cantidadDe(dynamic mapa, String clave) => (mapa is Map ? (mapa[clave] ?? 0) : 0) as int;

  // ---------------------------------------------------------------- interfaz
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Cambios de prenda'),
          bottom: const TabBar(
            isScrollable: true,
            tabs: [
              Tab(text: 'Seguimiento'),
              Tab(text: 'Registrar en tienda'),
              Tab(text: 'Consulta del mes'),
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
          const Text('Cambio por talla o color dentro de los 7 días, con nota de devolución.',
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
              DropdownMenuItem(value: '', child: Text('Tienda y delivery')),
              DropdownMenuItem(value: 'DELIVERY', child: Text('Solo delivery')),
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
          else if (_cambios.isEmpty)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: Text('No hay cambios en esta lista.')),
            )
          else
            for (final c in _cambios) _tarjetaCambio(c),
        ],
      ),
    );
  }

  Widget _tarjetaCambio(Map<String, dynamic> c) {
    final estado = '${c['estado']}';
    final (fondo, color) = coloresEstadoGestion(estado);
    final cliente = c['cliente'] as Map?;
    final entrega = c['entrega'] as Map?;
    final origen = c['origen'] as Map?;
    final ocupado = _procesando == c['id_cambio'];
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: c['atrasado'] == true ? AppColors.danger : AppColors.greyLight),
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
                      Text('${c['numero_nota']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text('${origen?['etiqueta'] ?? ''} · ${c['sucursal'] ?? ''} · ${c['modalidad_display'] ?? ''}',
                          style: const TextStyle(fontSize: 12, color: AppColors.grey)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                  child: Text('${c['estado_display'] ?? estado}',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color)),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text('Cliente: ${cliente?['nombre'] ?? 'Sin cliente'}'
                '${cliente?['telefono'] != null ? ' · Tel. ${cliente!['telefono']}' : ''}'),
            Text('Motivo: ${c['motivo_display'] ?? ''}'),
            Text('Devuelve: ${c['prenda_devuelta']} → Recibe: ${c['prenda_entregada']} (${c['cantidad']} u.)',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            if (entrega != null)
              Text('Dirección: ${entrega['direccion']}'
                  '${entrega['referencia'] != null && '${entrega['referencia']}'.isNotEmpty ? ' (${entrega['referencia']})' : ''}'),
            if (c['observacion'] != null) Text('Observación: ${c['observacion']}'),
            if (c['repartidor'] != null)
              Text('Repartidor: ${c['repartidor']} · visita ${_fecha(c['fecha_programada'])} · '
                  'límite ${_fecha(c['fecha_limite'])}${c['atrasado'] == true ? ' · ATRASADO' : ''}'),
            if (c['motivo_rechazo'] != null)
              Text('Rechazado: ${c['motivo_rechazo']}', style: const TextStyle(color: AppColors.danger)),
            Text('Solicitado el ${_fecha(c['fecha_solicitud'])}'
                '${c['solicitado_por'] != null ? ' por ${c['solicitado_por']}' : ''}',
                style: const TextStyle(fontSize: 12, color: AppColors.grey)),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                if (estado == 'COMPLETADO')
                  OutlinedButton(onPressed: () => _verNota(c), child: const Text('Ver nota de devolución')),
                if (_esGestor && estado == 'SOLICITADO')
                  ElevatedButton(
                    onPressed: ocupado ? null : () => _aprobar(c),
                    child: const Text('Aprobar y asignar repartidor'),
                  ),
                if (_esGestor && (estado == 'SOLICITADO' || estado == 'PROGRAMADO' || estado == 'EN_CAMINO'))
                  OutlinedButton(
                    onPressed: ocupado ? null : () => _rechazar(c),
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
                decoration: const InputDecoration(labelText: 'Número (ej.: 120)', border: OutlineInputBorder()),
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
        if (_compra != null) ...[
          const SizedBox(height: 16),
          _tarjetaCompra(_compra!),
        ],
        if (_itemSel != null) ...[
          const SizedBox(height: 16),
          _formulario(),
        ],
      ],
    );
  }

  Widget _tarjetaCompra(Map<String, dynamic> compra) {
    final items = (compra['items'] ?? []) as List<dynamic>;
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
              '${cliente != null ? ' · Cliente: ${cliente['nombre']}' : ''}',
              style: const TextStyle(fontSize: 12, color: AppColors.grey),
            ),
            const SizedBox(height: 8),
            for (final raw in items) _filaItem(Map<String, dynamic>.from(raw as Map)),
          ],
        ),
      ),
    );
  }

  Widget _filaItem(Map<String, dynamic> i) {
    final noElegible = i['motivo_no_elegible'];
    final seleccionada = _itemSel != null &&
        _itemSel!['id_venta_item'] == i['id_venta_item'] &&
        _itemSel!['id_orden_item'] == i['id_orden_item'];
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
      decoration: BoxDecoration(
        color: seleccionada ? const Color(0xFFF5F5FA) : null,
        border: const Border(top: BorderSide(color: Color(0xFFF0F0F0))),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${i['prenda']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                Text('${i['cantidad']} u. · Bs ${i['precio']} · hasta ${_fecha(i['vence'])}',
                    style: const TextStyle(fontSize: 12, color: AppColors.grey)),
                if (noElegible != null)
                  Text('$noElegible', style: const TextStyle(fontSize: 12, color: AppColors.danger)),
              ],
            ),
          ),
          if (noElegible == null)
            OutlinedButton(onPressed: () => _elegirItem(i), child: const Text('Cambiar')),
        ],
      ),
    );
  }

  Widget _formulario() {
    final item = _itemSel!;
    final cantidadMax = (item['cantidad'] ?? 1) as int;
    if (_cargandoOpciones) {
      return const Padding(
        padding: EdgeInsets.all(12),
        child: Center(child: Text('Cargando tallas y colores...')),
      );
    }
    if (_opciones == null) return const SizedBox.shrink();
    final alternativas = _alternativasValidas;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Cambiar: ${item['prenda']}', style: const TextStyle(fontWeight: FontWeight.w700)),
            RadioListTile<String>(
              contentPadding: EdgeInsets.zero,
              value: 'NO_LE_QUEDA',
              groupValue: _motivo,
              title: const Text('No le quedó: quiere otra talla o color (mismo precio)'),
              onChanged: (v) => setState(() {
                _motivo = v ?? _motivo;
                _idVariante = null;
              }),
            ),
            RadioListTile<String>(
              contentPadding: EdgeInsets.zero,
              value: 'ERROR_TIENDA',
              groupValue: _motivo,
              title: const Text('Error de la tienda: se le entregó otra talla o color'),
              onChanged: (v) => setState(() {
                _motivo = v ?? _motivo;
                _idVariante = null;
              }),
            ),
            DropdownButtonFormField<int>(
              key: ValueKey('alternativas-$_motivo'),
              value: alternativas.any((a) => a['id_variante'] == _idVariante) ? _idVariante : null,
              isExpanded: true,
              decoration: InputDecoration(
                labelText: _motivo == 'ERROR_TIENDA'
                    ? '¿Qué talla/color se le entregó por error?'
                    : '¿Por cuál la cambia?',
                border: const OutlineInputBorder(),
              ),
              items: alternativas
                  .map((a) => DropdownMenuItem<int>(
                        value: a['id_variante'] as int,
                        child: Text('Talla ${a['talla']} · ${a['color']} · Bs ${a['precio']} · stock ${a['stock']}'),
                      ))
                  .toList(),
              onChanged: (v) => setState(() => _idVariante = v),
            ),
            if (_motivo == 'NO_LE_QUEDA' && alternativas.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  'No hay otra talla o color al mismo precio con stock en ${_opciones!['sucursal'] ?? 'la sucursal'}.',
                  style: const TextStyle(fontSize: 12, color: AppColors.danger),
                ),
              ),
            if (_motivo == 'ERROR_TIENDA')
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  'El cliente devuelve la que se le entregó por error y recibe ${item['prenda']}.',
                  style: const TextStyle(fontSize: 12, color: AppColors.grey),
                ),
              ),
            if (cantidadMax > 1)
              Row(
                children: [
                  const Text('Cantidad'),
                  IconButton(
                    icon: const Icon(Icons.remove_circle_outline),
                    onPressed: _cantidad <= 1 ? null : () => setState(() => _cantidad--),
                  ),
                  Text('$_cantidad'),
                  IconButton(
                    icon: const Icon(Icons.add_circle_outline),
                    onPressed: _cantidad >= cantidadMax ? null : () => setState(() => _cantidad++),
                  ),
                ],
              ),
            const SizedBox(height: 8),
            TextField(
              controller: _observacionCtrl,
              decoration: const InputDecoration(
                labelText: 'Observación (opcional)',
                hintText: 'Ej.: le quedaba ajustada',
                border: OutlineInputBorder(),
              ),
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _condicionesOk,
              title: const Text('La prenda devuelta está sin uso y con etiqueta'),
              onChanged: (v) => setState(() => _condicionesOk = v ?? false),
            ),
            ElevatedButton(
              onPressed: _registrando ? null : _registrar,
              style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 48)),
              child: Text(_registrando ? 'Registrando...' : 'Registrar cambio'),
            ),
            TextButton(
              onPressed: _registrando
                  ? null
                  : () => setState(() {
                        _itemSel = null;
                        _opciones = null;
                      }),
              child: const Text('Cancelar'),
            ),
          ],
        ),
      ),
    );
  }

  // ---- Pestaña Consulta del mes (CU06)
  Widget _tabMes() {
    final r = _resumen;
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
          if (r != null) ...[
            Row(
              children: [
                _tarjetaNumero('${r['total'] ?? 0}', 'Cambios del mes', AppColors.light, AppColors.textDark),
                const SizedBox(width: 6),
                _tarjetaNumero('${r['completados'] ?? 0}', 'Completados', const Color(0xFFE8F8F0), const Color(0xFF1B7F4B)),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                _tarjetaNumero('${r['en_proceso'] ?? 0}', 'En proceso', const Color(0xFFE3F2FD), const Color(0xFF0D47A1)),
                const SizedBox(width: 6),
                _tarjetaNumero('${r['rechazados'] ?? 0}', 'Rechazados', const Color(0xFFFDECEA), const Color(0xFFC0392B)),
              ],
            ),
            const SizedBox(height: 12),
            _bloque('Por motivo', [
              'Error de la tienda: ${_cantidadDe(r['por_motivo'], 'ERROR_TIENDA')}',
              'No le quedó: ${_cantidadDe(r['por_motivo'], 'NO_LE_QUEDA')}',
            ]),
            _bloque('Por modalidad', [
              'En tienda: ${_cantidadDe(r['por_modalidad'], 'TIENDA')}',
              'Con delivery: ${_cantidadDe(r['por_modalidad'], 'DELIVERY')}',
            ]),
            _bloque('Por sucursal', [
              for (final s in (r['por_sucursal'] ?? []) as List) '${s['sucursal']}: ${s['total']}',
              if (((r['por_sucursal'] ?? []) as List).isEmpty) 'Sin cambios.',
            ]),
            _bloque('Prendas más cambiadas', [
              for (final p in (r['prendas_mas_cambiadas'] ?? []) as List) '${p['prenda']}: ${p['total']}',
              if (((r['prendas_mas_cambiadas'] ?? []) as List).isEmpty) 'Sin cambios.',
            ]),
          ],
          const SizedBox(height: 8),
          if (_cargandoMes)
            const Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()))
          else if (_cambiosMes.isEmpty)
            const Padding(padding: EdgeInsets.all(16), child: Center(child: Text('No hay cambios en este mes.')))
          else
            for (final c in _cambiosMes)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  title: Text('${c['numero_nota']} · ${c['sucursal'] ?? ''}'),
                  subtitle: Text(
                    '${_fecha(c['fecha_solicitud'])}\n${c['prenda_devuelta']} → ${c['prenda_entregada']}\n'
                    '${c['motivo_display'] ?? ''} · ${c['estado_display'] ?? ''}',
                  ),
                  isThreeLine: true,
                  trailing: TextButton(onPressed: () => _verNota(c), child: const Text('Ver')),
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
            Text(numero, style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: color)),
            Text(etiqueta, textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: color)),
          ],
        ),
      ),
    );
  }

  Widget _bloque(String titulo, List<String> lineas) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(titulo, style: const TextStyle(fontWeight: FontWeight.w700)),
            for (final l in lineas) Text(l, style: const TextStyle(fontSize: 13)),
          ],
        ),
      ),
    );
  }
}