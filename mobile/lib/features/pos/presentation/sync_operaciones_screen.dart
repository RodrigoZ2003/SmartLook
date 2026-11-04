// mobile/lib/features/pos/presentation/sync_operaciones_screen.dart
//
// NUEVO (Fase 2 - CU08, igual que web sync-operaciones): historial de las
// ventas POS hechas sin conexión (sincronizadas, en conflicto y rechazadas)
// con resumen, filtros y paginación, y resolución de los conflictos por el
// encargado, el administrador de la empresa o el SUPER_ADMIN:
//   - Confirmar: la venta queda válida (si faltó stock, se ajusta el inventario).
//   - Devolver efectivo: la venta se anula, se repone lo descontado y se
//     genera la nota de devolución.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/pos_sale_service.dart';

class SyncOperacionesScreen extends StatefulWidget {
  const SyncOperacionesScreen({super.key});

  @override
  State<SyncOperacionesScreen> createState() => _SyncOperacionesScreenState();
}

class _SyncOperacionesScreenState extends State<SyncOperacionesScreen> {
  final DateFormat _fmt = DateFormat('dd/MM/yyyy HH:mm');
  final DateFormat _fmtDia = DateFormat('yyyy-MM-dd');
  late final PosSaleService _service;
  late final bool _esSuperAdmin;

  // Filtros
  String _estado = '';
  bool _pendientes = false;
  String _tipoConflicto = '';
  int? _sucursal;
  DateTime? _desde;
  DateTime? _hasta;
  String? _empresa;

  List<Map<String, dynamic>> _operaciones = [];
  Map<String, dynamic>? _resumen;
  int _total = 0;
  int _pagina = 1;
  bool _hayAnterior = false;
  bool _haySiguiente = false;
  bool _cargando = false;
  String? _error;
  String? _mensaje;

  List<dynamic> _empresas = [];
  List<dynamic> _sucursales = [];

  int? _abierta;
  final Map<int, TextEditingController> _notas = {};
  bool _resolviendo = false;

  @override
  void initState() {
    super.initState();
    _service = PosSaleService(apiClient: context.read<ApiClient>());
    _esSuperAdmin = context.read<AuthService>().currentUser?.hasRole('SUPER_ADMIN') ?? false;
    if (_esSuperAdmin) {
      _service.listarEmpresas().then((e) {
        if (mounted) setState(() => _empresas = e);
      }).catchError((_) {});
    }
    _cargarSucursales();
    _buscar();
  }

  @override
  void dispose() {
    for (final c in _notas.values) {
      c.dispose();
    }
    super.dispose();
  }

  String _fecha(dynamic iso) {
    final dt = DateTime.tryParse('${iso ?? ''}')?.toLocal();
    return dt == null ? '-' : _fmt.format(dt);
  }

  String _textoError(Object e, String fallback) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map && data['error'] != null) return data['error'].toString();
      if (data is Map && data['detail'] != null) return data['detail'].toString();
    } catch (_) {}
    return fallback;
  }

  Future<void> _cargarSucursales() async {
    try {
      final s = await _service.listarSucursales(empresa: _empresa);
      if (mounted) setState(() => _sucursales = s);
    } catch (_) {
      if (mounted) setState(() => _sucursales = []);
    }
  }

  Future<void> _buscar({int pagina = 1}) async {
    setState(() {
      _pagina = pagina;
      _cargando = true;
      _error = null;
    });
    try {
      final data = await _service.listarOperaciones({
        'estado': _estado,
        'pendientes': _pendientes ? 1 : null,
        'tipo_conflicto': _tipoConflicto,
        'sucursal': _sucursal,
        'desde': _desde != null ? _fmtDia.format(_desde!) : null,
        'hasta': _hasta != null ? _fmtDia.format(_hasta!) : null,
        'empresa': _empresa,
        'page': pagina,
      });
      final lista = ((data['results'] ?? []) as List<dynamic>)
          .map((o) => Map<String, dynamic>.from(o as Map))
          .toList();
      if (!mounted) return;
      setState(() {
        _operaciones = lista;
        _total = (data['count'] as int?) ?? lista.length;
        _hayAnterior = data['previous'] != null;
        _haySiguiente = data['next'] != null;
        _cargando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _cargando = false;
        _operaciones = [];
        _error = _textoError(e, 'No se pudo cargar el historial.');
      });
    }
    _cargarResumen();
  }

  Future<void> _cargarResumen() async {
    try {
      final r = await _service.resumenOperaciones(empresa: _empresa);
      if (mounted) setState(() => _resumen = r);
    } catch (_) {
      if (mounted) setState(() => _resumen = null);
    }
  }

  void _filtrarPorEstado(String estado, {bool pendientes = false}) {
    setState(() {
      _estado = estado;
      _pendientes = pendientes;
    });
    _buscar();
  }

  void _limpiar() {
    setState(() {
      _estado = '';
      _pendientes = false;
      _tipoConflicto = '';
      _sucursal = null;
      _desde = null;
      _hasta = null;
      _empresa = null;
    });
    _cargarSucursales();
    _buscar();
  }

  Future<void> _elegirFecha(bool desde) async {
    final hoy = DateTime.now();
    final elegida = await showDatePicker(
      context: context,
      initialDate: (desde ? _desde : _hasta) ?? hoy,
      firstDate: DateTime(hoy.year - 2),
      lastDate: hoy,
    );
    if (elegida == null) return;
    setState(() => desde ? _desde = elegida : _hasta = elegida);
  }

  bool _tieneConflictoDeStock(Map op) =>
      ((op['detalle_conflicto'] ?? []) as List).any((c) => c['tipo'] == 'STOCK');

  String _textoConfirmar(Map op) =>
      _tieneConflictoDeStock(op) ? 'Confirmar y ajustar stock' : 'Marcar como revisada';

  String _textoEstado(Map op) {
    if (op['estado'] == 'EN_CONFLICTO' && op['resolucion'] != null) {
      return 'Conflicto resuelto · ${op['resolucion_display'] ?? ''}';
    }
    if (op['estado'] == 'EN_CONFLICTO') {
      return 'En conflicto · ${op['tipo_conflicto_display'] ?? ''}';
    }
    return '${op['estado_display'] ?? op['estado'] ?? ''}';
  }

  (Color, Color) _coloresEstado(Map op) {
    if (op['estado'] == 'EN_CONFLICTO' && op['resolucion'] != null) {
      return (const Color(0xFFE3F2FD), const Color(0xFF0D47A1));
    }
    switch (op['estado']) {
      case 'SINCRONIZADA':
        return (const Color(0xFFE8F5E9), const Color(0xFF1B5E20));
      case 'EN_CONFLICTO':
        return (const Color(0xFFFFF8E1), const Color(0xFF8A6D00));
      case 'RECHAZADA':
        return (const Color(0xFFFDECEA), const Color(0xFFC0392B));
      default:
        return (AppColors.light, AppColors.grey);
    }
  }

  Future<void> _resolver(Map<String, dynamic> op, String accion) async {
    final venta = op['venta'] as Map?;
    final explicacion = accion == 'CONFIRMAR'
        ? (_tieneConflictoDeStock(op)
            ? 'La venta queda válida y el stock de las prendas sin stock se ajusta restando lo vendido.'
            : 'La venta queda válida con el precio cobrado sin conexión.')
        : 'Se anula la venta #${op['id_venta']}, se devuelven Bs ${venta?['total'] ?? ''} al cliente, '
            'las prendas vuelven al stock y se genera la nota de devolución.';
    final seguir = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(accion == 'CONFIRMAR' ? _textoConfirmar(op) : 'Devolver efectivo'),
        content: Text(explicacion),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Sí, continuar')),
        ],
      ),
    );
    if (seguir != true) return;
    final id = op['id_operacion'] as int;
    final nota = _notas[id]?.text.trim();
    setState(() {
      _resolviendo = true;
      _error = null;
      _mensaje = null;
    });
    try {
      final actualizada = await _service.resolverOperacion(id, accion, (nota == null || nota.isEmpty) ? null : nota);
      if (!mounted) return;
      setState(() {
        _resolviendo = false;
        final i = _operaciones.indexWhere((o) => o['id_operacion'] == id);
        if (i >= 0) _operaciones[i] = actualizada;
        _mensaje = accion == 'DEVOLVER'
            ? 'Venta #${actualizada['id_venta']} anulada: se devolvió Bs '
                '${(actualizada['nota_devolucion'] as Map?)?['monto_devuelto'] ?? ''} y se generó la nota de devolución.'
            : 'Venta #${actualizada['id_venta']} confirmada.';
      });
      _cargarResumen();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _resolviendo = false;
        _error = _textoError(e, 'No se pudo resolver la operación.');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Operaciones sin conexión')),
      body: RefreshIndicator(
        onRefresh: () => _buscar(pagina: _pagina),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              'Ventas del POS hechas sin internet y su resultado al sincronizar.',
              style: TextStyle(fontSize: 13, color: AppColors.grey),
            ),
            const SizedBox(height: 12),
            if (_resumen != null) _tarjetasResumen(_resumen!),
            const SizedBox(height: 12),
            _filtros(),
            if (_mensaje != null) _aviso(_mensaje!, const Color(0xFFE8F5E9), const Color(0xFF1B5E20)),
            if (_error != null) _aviso(_error!, AppColors.dangerBg, AppColors.danger),
            if (_cargando)
              const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
            else if (_operaciones.isEmpty && _error == null)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: Text('No hay operaciones con esos filtros.')),
              )
            else if (_operaciones.isNotEmpty) ...[
              Text('$_total operación(es)', style: const TextStyle(color: AppColors.grey)),
              const SizedBox(height: 8),
              for (final op in _operaciones) _tarjetaOperacion(op),
              if (_hayAnterior || _haySiguiente)
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    OutlinedButton(
                      onPressed: _hayAnterior ? () => _buscar(pagina: _pagina - 1) : null,
                      child: const Text('Anterior'),
                    ),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Text('Página $_pagina'),
                    ),
                    OutlinedButton(
                      onPressed: _haySiguiente ? () => _buscar(pagina: _pagina + 1) : null,
                      child: const Text('Siguiente'),
                    ),
                  ],
                ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _aviso(String texto, Color fondo, Color color) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(6)),
      child: Text(texto, style: TextStyle(color: color)),
    );
  }

  Widget _tarjetasResumen(Map<String, dynamic> r) {
    Widget tarjeta(String numero, String etiqueta, Color fondo, Color color, VoidCallback onTap,
        {String? extra}) {
      return Expanded(
        child: InkWell(
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(8)),
            child: Column(
              children: [
                Text(numero, style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: color)),
                Text(etiqueta, textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: color)),
                if (extra != null) Text(extra, style: TextStyle(fontSize: 11, color: color)),
              ],
            ),
          ),
        ),
      );
    }

    return Row(
      children: [
        tarjeta('${r['SINCRONIZADA'] ?? 0}', 'Sincronizadas', const Color(0xFFE8F5E9),
            const Color(0xFF1B5E20), () => _filtrarPorEstado('SINCRONIZADA')),
        const SizedBox(width: 8),
        tarjeta('${r['pendientes'] ?? 0}', 'Conflictos pendientes', const Color(0xFFFFF8E1),
            const Color(0xFF8A6D00), () => _filtrarPorEstado('EN_CONFLICTO', pendientes: true),
            extra: '${r['EN_CONFLICTO'] ?? 0} en total'),
        const SizedBox(width: 8),
        tarjeta('${r['RECHAZADA'] ?? 0}', 'Rechazadas', const Color(0xFFFDECEA),
            const Color(0xFFC0392B), () => _filtrarPorEstado('RECHAZADA')),
      ],
    );
  }

  Widget _filtros() {
    return Card(
      child: ExpansionTile(
        title: const Text('Filtros', style: TextStyle(fontWeight: FontWeight.w600)),
        childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        children: [
          if (_esSuperAdmin) ...[
            DropdownButtonFormField<String?>(
              value: _empresa,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Empresa', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem<String?>(value: null, child: Text('Todas')),
                ..._empresas.map((e) => DropdownMenuItem<String?>(
                      value: '${e['slug']}',
                      child: Text('${e['nombre']}'),
                    )),
              ],
              onChanged: (v) {
                setState(() {
                  _empresa = v;
                  _sucursal = null;
                });
                _cargarSucursales();
                _buscar();
              },
            ),
            const SizedBox(height: 8),
          ],
          DropdownButtonFormField<String>(
            value: _estado,
            decoration: const InputDecoration(labelText: 'Estado', border: OutlineInputBorder()),
            items: const [
              DropdownMenuItem(value: '', child: Text('Todos')),
              DropdownMenuItem(value: 'SINCRONIZADA', child: Text('Sincronizada')),
              DropdownMenuItem(value: 'EN_CONFLICTO', child: Text('En conflicto')),
              DropdownMenuItem(value: 'RECHAZADA', child: Text('Rechazada')),
            ],
            onChanged: (v) => setState(() => _estado = v ?? ''),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            value: _tipoConflicto,
            decoration: const InputDecoration(labelText: 'Tipo de conflicto', border: OutlineInputBorder()),
            items: const [
              DropdownMenuItem(value: '', child: Text('Todos')),
              DropdownMenuItem(value: 'PRECIO', child: Text('Precio distinto')),
              DropdownMenuItem(value: 'STOCK', child: Text('Sin stock suficiente')),
              DropdownMenuItem(value: 'PRECIO_Y_STOCK', child: Text('Precio y stock')),
            ],
            onChanged: (v) => setState(() => _tipoConflicto = v ?? ''),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<int?>(
            value: _sucursales.any((s) => s['id_sucursal'] == _sucursal) ? _sucursal : null,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Sucursal', border: OutlineInputBorder()),
            items: [
              const DropdownMenuItem<int?>(value: null, child: Text('Todas')),
              ..._sucursales.map((s) => DropdownMenuItem<int?>(
                    value: s['id_sucursal'] as int,
                    child: Text('${s['nombre']}'),
                  )),
            ],
            onChanged: (v) => setState(() => _sucursal = v),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _elegirFecha(true),
                  child: Text(_desde == null ? 'Desde' : 'Desde ${DateFormat('dd/MM/yyyy').format(_desde!)}'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _elegirFecha(false),
                  child: Text(_hasta == null ? 'Hasta' : 'Hasta ${DateFormat('dd/MM/yyyy').format(_hasta!)}'),
                ),
              ),
            ],
          ),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: _pendientes,
            title: const Text('Solo conflictos sin resolver'),
            onChanged: (v) => setState(() => _pendientes = v ?? false),
          ),
          Row(
            children: [
              Expanded(child: ElevatedButton(onPressed: () => _buscar(), child: const Text('Filtrar'))),
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton(onPressed: _limpiar, child: const Text('Limpiar'))),
            ],
          ),
        ],
      ),
    );
  }

  Widget _tarjetaOperacion(Map<String, dynamic> op) {
    final id = op['id_operacion'] as int;
    final abierta = _abierta == id;
    final venta = op['venta'] as Map?;
    final cliente = venta?['cliente'] as Map?;
    final (fondo, color) = _coloresEstado(op);
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: op['puede_resolver'] == true ? const Color(0xFFFFC107) : AppColors.greyLight),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: () => setState(() => _abierta = abierta ? null : id),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text('${op['sucursal'] ?? 'Sin sucursal'}',
                            style: const TextStyle(fontWeight: FontWeight.w700)),
                      ),
                      Flexible(
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                          child: Text(_textoEstado(op),
                              textAlign: TextAlign.center,
                              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color)),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Hecha sin conexión: ${_fecha(op['fecha_operacion'] ?? op['fecha_recepcion'])}'
                    ' · Recibida: ${_fecha(op['fecha_recepcion'])}',
                    style: const TextStyle(fontSize: 12, color: Color(0xFF555555)),
                  ),
                  Text(
                    'Cajero: ${op['usuario'] ?? '-'}'
                    '${op['id_venta'] != null ? ' · Venta #${op['id_venta']} · Bs ${venta?['total'] ?? ''}' : ''}'
                    '${cliente != null ? ' · Cliente: ${cliente['nombre']}' : ''}',
                    style: const TextStyle(fontSize: 12, color: Color(0xFF555555)),
                  ),
                ],
              ),
            ),
          ),
          if (abierta) _detalle(op),
        ],
      ),
    );
  }

  Widget _detalle(Map<String, dynamic> op) {
    final id = op['id_operacion'] as int;
    final venta = op['venta'] as Map?;
    final conflictos = (op['detalle_conflicto'] ?? []) as List;
    final nota = op['nota_devolucion'] as Map?;
    final items = (venta?['items'] ?? []) as List;
    final prendas = items.fold<int>(0, (s, i) => s + ((i['cantidad'] ?? 0) as int));
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Divider(),
          if (op['mensaje'] != null) Text('${op['mensaje']}', style: const TextStyle(fontSize: 13)),
          // Detalle del conflicto por prenda.
          for (final c in conflictos)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                c['tipo'] == 'PRECIO'
                    ? 'Precio distinto · ${c['prenda']} (${c['cantidad']}): cobrado Bs ${c['precio_offline']} · '
                        'actual Bs ${c['precio_servidor']} · diferencia Bs ${c['diferencia']}'
                    : 'Sin stock · ${c['prenda']} (${c['cantidad']}): quedaban ${c['stock_disponible']} en la sucursal',
                style: const TextStyle(fontSize: 12, color: Color(0xFF8A6D00)),
              ),
            ),
          // Prendas de la venta registrada.
          if (venta != null) ...[
            const SizedBox(height: 8),
            Text('Venta #${venta['id_venta']} · ${venta['estado_display'] ?? ''} · $prendas prenda(s)',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            for (final i in items)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  '${i['cantidad']} x ${i['variante']}${i['sin_stock'] == true ? ' (sin stock)' : ''} · '
                  'cobrado Bs ${i['precio_unitario']} · actual ${i['precio_lista'] != null ? 'Bs ${i['precio_lista']}' : '-'} · '
                  'subtotal Bs ${i['subtotal']}',
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            Text('Total cobrado: Bs ${venta['total']} (${venta['metodo_pago'] ?? ''})',
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ],
          // Resolución ya hecha.
          if (op['resolucion'] != null) ...[
            const SizedBox(height: 8),
            Text(
              '${op['resolucion_display'] ?? op['resolucion']} por ${op['revisada_por'] ?? '-'} el ${_fecha(op['fecha_revision'])}'
              '${op['nota_revision'] != null ? ' · Nota: ${op['nota_revision']}' : ''}',
              style: const TextStyle(fontSize: 13, color: Color(0xFF0D47A1)),
            ),
          ],
          if (nota != null) ...[
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: AppColors.light, borderRadius: BorderRadius.circular(6)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Nota de devolución #${nota['id_nota']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text('Monto devuelto: Bs ${nota['monto_devuelto']}'),
                  Text('Motivo: ${nota['motivo'] ?? ''}'),
                  Text('Emitida por ${nota['usuario'] ?? '-'} el ${_fecha(nota['fecha_creacion'])}',
                      style: const TextStyle(fontSize: 12, color: AppColors.grey)),
                  for (final d in (nota['detalle'] ?? []) as List)
                    Text(
                      '${d['cantidad']} x ${d['prenda']} (Bs ${d['subtotal']}) · '
                      '${d['vuelve_al_stock'] == true ? 'volvió al stock' : 'no había descontado stock'}',
                      style: const TextStyle(fontSize: 12),
                    ),
                ],
              ),
            ),
          ],
          // Resolver el conflicto.
          if (op['puede_resolver'] == true) ...[
            const SizedBox(height: 10),
            TextField(
              controller: _notas.putIfAbsent(id, () => TextEditingController()),
              maxLines: 2,
              decoration: const InputDecoration(
                labelText: 'Nota (opcional)',
                hintText: 'Ej.: la prenda estaba en tienda / se devolvió el efectivo al cliente',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton(
                    onPressed: _resolviendo ? null : () => _resolver(op, 'CONFIRMAR'),
                    child: Text(_textoConfirmar(op), textAlign: TextAlign.center),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: _resolviendo ? null : () => _resolver(op, 'DEVOLVER'),
                    style: OutlinedButton.styleFrom(foregroundColor: AppColors.danger),
                    child: const Text('Devolver efectivo'),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}