// mobile/lib/features/pos/presentation/pos_cart_screen.dart
//
// MODIFICADO (SaaS - 6.2): POS sin conexión (igual que la web).
// - Sin internet, la venta en efectivo se guarda en SQLite como
//   "Registrada localmente" y se muestra un comprobante provisional.
// - Al volver la conexión las ventas por enviar se envían solas (también
//   "Sincronizar ahora"); las rechazadas se muestran con su motivo.
// - La búsqueda y las sucursales usan la copia local sin conexión, con la
//   fecha de esa copia (puede estar desactualizada).
// - Sin conexión solo se aceptan ventas al contado en efectivo.
// MODIFICADO (Fase 2 - reservas con anticipo): se listan las reservas
// confirmadas (pagadas) de la sucursal; al agregar una, se cobra solo su
// saldo y se retira completa (todas sus prendas). Con reservas en la venta
// no se puede vender sin conexión.
// MODIFICADO (Fase 2 - CU08, igual que la web): cliente opcional por correo
// (en línea y sin conexión), ventas "En conflicto" en la cola con su detalle
// y acceso a "Operaciones sin conexión" (con la cantidad de conflictos sin
// resolver) para SUPER_ADMIN, ADMIN_EMPRESA y ENCARGADO_SUCURSAL.
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../../admin/data/inventory_service.dart';
import '../data/pos_offline_service.dart';
import '../data/pos_sale_service.dart';
import 'sync_operaciones_screen.dart';

class ItemVenta {
  final int idVariante;
  final String nombre;
  final double precio;
  int cantidad;

  ItemVenta({required this.idVariante, required this.nombre, required this.precio, this.cantidad = 1});
}

/// NUEVO (Fase 2): reserva confirmada que se retira en caja (se cobra solo el saldo).
class ReservaVenta {
  final int idReserva;
  final String cliente;
  final List<Map<String, dynamic>> prendas;
  final double total;
  final double pagado;
  final double saldo;

  ReservaVenta({
    required this.idReserva,
    required this.cliente,
    required this.prendas,
    required this.total,
    required this.pagado,
    required this.saldo,
  });

  factory ReservaVenta.desdeJson(Map<String, dynamic> r) {
    double numero(dynamic v) => double.tryParse('${v ?? ''}') ?? 0;
    final prendas = ((r['items'] ?? []) as List<dynamic>)
        .map((i) => Map<String, dynamic>.from(i as Map))
        .where((i) => i['estado'] == null || i['estado'] == 'PENDIENTE')
        .toList();
    return ReservaVenta(
      idReserva: r['id_reserva'] as int,
      cliente: '${r['cliente'] ?? ''}',
      prendas: prendas,
      total: numero(r['monto_total']),
      pagado: numero(r['monto_pagado']),
      saldo: numero(r['saldo']),
    );
  }
}

class PosCartScreen extends StatefulWidget {
  const PosCartScreen({super.key});

  @override
  State<PosCartScreen> createState() => _PosCartScreenState();
}

class _PosCartScreenState extends State<PosCartScreen> {
  static const Color _naranja = Color(0xFFE65100);
  static const Color _fondoNaranja = Color(0xFFFFF3E0);
  static const String _errorReservasOffline =
      'Sin conexión no se pueden cobrar reservas. Quítalas de la venta o espera a recuperar internet.';
  static final RegExp _patronCorreo = RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$');
  static const List<String> _rolesGestionConflictos = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];

  late final InventoryService _inventoryService;
  late final PosSaleService _posSaleService;
  late final PosOfflineService _offline;
  late final bool _esGestor;
  final DateFormat _fmt = DateFormat('dd/MM/yyyy HH:mm');

  final TextEditingController _busquedaController = TextEditingController();
  final TextEditingController _correoController = TextEditingController();
  List<dynamic> _resultados = [];
  bool _buscando = false;
  bool _busquedaLocal = false;

  final List<ItemVenta> _items = [];
  List<dynamic> _sucursales = [];
  int? _sucursalSeleccionada;
  String _metodoPago = 'EFECTIVO';

  // NUEVO (Fase 2): reservas por retirar de la sucursal y las agregadas a la venta.
  List<ReservaVenta> _reservasDisponibles = [];
  final List<ReservaVenta> _reservasVenta = [];
  bool _cargandoReservas = false;

  // NUEVO (CU08): conflictos sin resolver de la empresa (solo encargado/administrador).
  int _conflictosPendientes = 0;

  bool _registrando = false;
  String? _error;
  Map<String, dynamic>? _ventaConfirmada;
  VentaLocal? _ventaOffline;
  bool _enLineaAnterior = true;

  @override
  void initState() {
    super.initState();
    final apiClient = context.read<ApiClient>();
    final usuario = context.read<AuthService>().currentUser;
    _esGestor = _rolesGestionConflictos.any((r) => usuario?.hasRole(r) ?? false);
    _inventoryService = InventoryService(apiClient: apiClient);
    _posSaleService = PosSaleService(apiClient: apiClient);
    _offline = context.read<PosOfflineService>();
    _enLineaAnterior = _offline.enLinea;
    _offline.addListener(_alCambiarConexion);
    _offline.recargar();
    _cargarSucursales();
    _offline.prepararCatalogo();
    // Si quedaron ventas pendientes de otra vez, se intentan enviar al entrar.
    _offline.sincronizar();
    _cargarConflictosPendientes();
  }

  @override
  void dispose() {
    _offline.removeListener(_alCambiarConexion);
    _busquedaController.dispose();
    _correoController.dispose();
    super.dispose();
  }

  void _alCambiarConexion() {
    final enLinea = _offline.enLinea;
    if (enLinea == _enLineaAnterior) return;
    _enLineaAnterior = enLinea;
    if (!mounted) return;
    if (!enLinea && _metodoPago != 'EFECTIVO') {
      setState(() => _metodoPago = 'EFECTIVO');
    }
    if (enLinea) {
      _cargarSucursales();
      _cargarReservas();
      _cargarConflictosPendientes();
    }
  }

  // ---- Conflictos (CU08) ----

  Future<void> _cargarConflictosPendientes() async {
    if (!_esGestor || !_offline.enLinea) return;
    try {
      final resumen = await _posSaleService.resumenOperaciones();
      if (!mounted) return;
      setState(() => _conflictosPendientes = (resumen['pendientes'] as int?) ?? 0);
    } catch (_) {}
  }

  Future<void> _abrirOperaciones() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (context) => const SyncOperacionesScreen()),
    );
    _cargarConflictosPendientes();
  }

  // ---- Sucursales ----

  Future<void> _cargarSucursales() async {
    if (!_offline.enLinea) {
      await _cargarSucursalesLocales();
      return;
    }
    try {
      final sucursales = await _inventoryService.getSucursales();
      if (!mounted) return;
      setState(() => _sucursales = sucursales);
      _offline.guardarSucursales(sucursales);
    } catch (e) {
      if (_offline.esErrorDeRed(e)) _offline.marcarSinConexion();
      await _cargarSucursalesLocales();
    }
  }

  Future<void> _cargarSucursalesLocales() async {
    final locales = await _offline.sucursalesLocales();
    if (!mounted) return;
    setState(() => _sucursales = locales);
  }

  void _onCambioSucursal(int? value) {
    setState(() {
      _sucursalSeleccionada = value;
      // Las reservas son de una sucursal: al cambiarla se quitan de la venta.
      _reservasVenta.clear();
      _reservasDisponibles = [];
    });
    _cargarReservas();
  }

  // ---- Reservas por retirar (Fase 2) ----

  Future<void> _cargarReservas() async {
    final idSucursal = _sucursalSeleccionada;
    if (idSucursal == null || !_offline.enLinea) return;
    setState(() => _cargandoReservas = true);
    try {
      final lista = await _posSaleService.reservasPorRetirar(idSucursal);
      if (!mounted || idSucursal != _sucursalSeleccionada) return;
      setState(() {
        _reservasDisponibles = lista
            .map((r) => ReservaVenta.desdeJson(Map<String, dynamic>.from(r as Map)))
            .where((r) => r.prendas.isNotEmpty)
            .toList();
        _cargandoReservas = false;
      });
    } catch (e) {
      if (_offline.esErrorDeRed(e)) _offline.marcarSinConexion();
      if (mounted) setState(() => _cargandoReservas = false);
    }
  }

  bool _reservaAgregada(ReservaVenta r) => _reservasVenta.any((x) => x.idReserva == r.idReserva);

  void _agregarReserva(ReservaVenta r) {
    if (_reservaAgregada(r)) return;
    setState(() {
      _reservasVenta.add(r);
      _error = null;
    });
  }

  void _quitarReserva(ReservaVenta r) {
    setState(() => _reservasVenta.removeWhere((x) => x.idReserva == r.idReserva));
  }

  // ---- Búsqueda ----

  Future<void> _buscar() async {
    final termino = _busquedaController.text.trim();
    if (termino.isEmpty) {
      setState(() => _resultados = []);
      return;
    }
    if (!_offline.enLinea) {
      await _buscarEnCatalogoLocal(termino);
      return;
    }
    setState(() {
      _buscando = true;
      _busquedaLocal = false;
    });
    try {
      final resultados = await _inventoryService.getVariantes(busqueda: termino);
      if (!mounted) return;
      setState(() {
        _resultados = resultados;
        _buscando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _buscando = false);
      if (_offline.esErrorDeRed(e)) {
        _offline.marcarSinConexion();
        await _buscarEnCatalogoLocal(termino);
      } else {
        setState(() => _resultados = []);
      }
    }
  }

  Future<void> _buscarEnCatalogoLocal(String termino) async {
    final locales = await _offline.buscarLocal(termino);
    if (!mounted) return;
    setState(() {
      _busquedaLocal = true;
      _resultados = locales;
    });
  }

  // ---- Venta en curso ----

  void _agregarItem(Map<String, dynamic> variante) {
    final idVariante = variante['id_variante'] as int;
    final existente = _items.where((i) => i.idVariante == idVariante).firstOrNull;
    if (existente != null) {
      setState(() => existente.cantidad += 1);
    } else {
      setState(() {
        _items.add(ItemVenta(
          idVariante: idVariante,
          nombre: variante['nombre_completo'].toString(),
          precio: double.parse(variante['precio'].toString()),
        ));
      });
    }
  }

  void _incrementar(ItemVenta item) => setState(() => item.cantidad += 1);

  void _decrementar(ItemVenta item) {
    if (item.cantidad <= 1) {
      _quitar(item);
      return;
    }
    setState(() => item.cantidad -= 1);
  }

  void _quitar(ItemVenta item) => setState(() => _items.remove(item));

  double get _totalPrendas => _items.fold(0.0, (acc, item) => acc + item.precio * item.cantidad);

  double get _totalSaldos => _reservasVenta.fold(0.0, (acc, r) => acc + r.saldo);

  double get _total => _totalPrendas + _totalSaldos;

  bool get _ventaVacia => _items.isEmpty && _reservasVenta.isEmpty;

  String get _correo => _correoController.text.trim();

  String get _qrData =>
      'SmartLook - Pago QR\nTotal: Bs ${_total.toStringAsFixed(2)}\nReferencia: SL-${DateTime.now().millisecondsSinceEpoch}';

  // ---- Registro ----

  List<Map<String, dynamic>> get _itemsPayload => [
        ..._items.map((i) => {'id_variante': i.idVariante, 'cantidad': i.cantidad}),
        // Fase 2: la reserva se retira completa (todas sus prendas pendientes).
        for (final r in _reservasVenta)
          for (final p in r.prendas) {'id_reserva_item': p['id_item'], 'cantidad': 1},
      ];

  Future<void> _registrarVenta() async {
    if (_ventaVacia) {
      setState(() => _error = 'Agrega al menos una prenda a la venta.');
      return;
    }
    if (_sucursalSeleccionada == null) {
      setState(() => _error = 'Selecciona la sucursal.');
      return;
    }
    if (_correo.isNotEmpty && !_patronCorreo.hasMatch(_correo)) {
      setState(() => _error = 'El correo del cliente no es válido (o déjalo vacío).');
      return;
    }
    setState(() => _error = null);
    if (!_offline.enLinea) {
      if (_reservasVenta.isNotEmpty) {
        setState(() => _error = _errorReservasOffline);
        return;
      }
      await _guardarSinConexion();
      return;
    }

    setState(() => _registrando = true);
    try {
      final venta = await _posSaleService.registrarVenta(
        idSucursal: _sucursalSeleccionada!,
        metodoPago: _metodoPago,
        items: _itemsPayload,
        correoCliente: _correo.isEmpty ? null : _correo,
      );
      if (!mounted) return;
      setState(() {
        _ventaConfirmada = venta;
        _registrando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _registrando = false);
      // Se cortó la conexión justo al registrar: la venta pasa a la cola local
      // (salvo que tenga reservas: esas solo se cobran en línea).
      if (_offline.esErrorDeRed(e)) {
        _offline.marcarSinConexion();
        if (_reservasVenta.isNotEmpty) {
          setState(() => _error = _errorReservasOffline);
          return;
        }
        await _guardarSinConexion();
        return;
      }
      String mensaje = 'No se pudo registrar la venta. Intenta nuevamente.';
      try {
        final data = (e as dynamic).response?.data;
        if (data is Map && data['error'] != null) {
          mensaje = data['error'].toString();
        } else if (data is Map && data['detail'] != null) {
          mensaje = data['detail'].toString();
        }
      } catch (_) {}
      setState(() => _error = mensaje);
    }
  }

  Future<void> _guardarSinConexion() async {
    if (_metodoPago != 'EFECTIVO') {
      setState(() => _error = 'Sin conexión solo se pueden registrar ventas al contado en efectivo.');
      return;
    }
    final items = _items
        .map((i) => ItemVentaLocal(
              idVariante: i.idVariante,
              nombre: i.nombre,
              precio: i.precio,
              cantidad: i.cantidad,
            ))
        .toList();
    String sucursal = '';
    for (final s in _sucursales) {
      if (s['id_sucursal'] == _sucursalSeleccionada) sucursal = '${s['nombre']}';
    }
    setState(() => _registrando = true);
    try {
      final faltante = await _offline.validarStockLocal(items);
      if (faltante != null) {
        if (mounted) setState(() => _error = faltante);
        return;
      }
      final venta = await _offline.guardarVenta(
        idSucursal: _sucursalSeleccionada!,
        sucursal: sucursal,
        metodoPago: _metodoPago,
        items: items,
        correoCliente: _correo,
      );
      if (mounted) setState(() => _ventaOffline = venta);
    } catch (_) {
      if (mounted) setState(() => _error = 'No se pudo guardar la venta en este dispositivo.');
    } finally {
      if (mounted) setState(() => _registrando = false);
    }
  }

  void _nuevaVenta() {
    setState(() {
      _items.clear();
      _reservasVenta.clear();
      _reservasDisponibles = [];
      _busquedaController.clear();
      _correoController.clear();
      _resultados = [];
      _busquedaLocal = false;
      _sucursalSeleccionada = null;
      _metodoPago = 'EFECTIVO';
      _ventaConfirmada = null;
      _ventaOffline = null;
      _error = null;
    });
    _cargarConflictosPendientes();
  }

  Future<void> _descartar(VentaLocal venta) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        content: const Text('¿Descartar esta venta rechazada? Se borrará de este dispositivo.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Descartar', style: TextStyle(color: AppColors.danger)),
          ),
        ],
      ),
    );
    if (confirmar == true) await _offline.descartar(venta);
  }

  String _textoEstado(VentaLocal venta) {
    switch (venta.estado) {
      case EstadoVentaLocal.confirmada:
        return venta.idVenta != null ? 'Confirmada · Venta #${venta.idVenta}' : 'Confirmada';
      case EstadoVentaLocal.enConflicto:
        return venta.idVenta != null ? 'En conflicto · Venta #${venta.idVenta}' : 'En conflicto';
      case EstadoVentaLocal.rechazada:
        return 'Rechazada';
      case EstadoVentaLocal.enviada:
        return 'Enviada';
      default:
        return 'Registrada localmente';
    }
  }

  (Color, Color) _coloresEstado(String estado) {
    switch (estado) {
      case EstadoVentaLocal.enviada:
        return (const Color(0xFFE3F2FD), const Color(0xFF0D47A1));
      case EstadoVentaLocal.confirmada:
        return (const Color(0xFFE8F5E9), const Color(0xFF1B5E20));
      case EstadoVentaLocal.enConflicto:
        return (const Color(0xFFFFF8E1), const Color(0xFF8A6D00));
      case EstadoVentaLocal.rechazada:
        return (const Color(0xFFFDECEA), const Color(0xFFC0392B));
      default:
        return (_fondoNaranja, _naranja);
    }
  }

  // ---- Interfaz ----

  @override
  Widget build(BuildContext context) {
    final offline = context.watch<PosOfflineService>();

    if (_ventaConfirmada != null) return _comprobanteEnLinea();
    if (_ventaOffline != null) return _comprobanteOffline(_ventaOffline!);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Punto de Venta'),
        actions: [
          if (_esGestor)
            IconButton(
              tooltip: 'Operaciones sin conexión',
              onPressed: _abrirOperaciones,
              icon: Badge(
                isLabelVisible: _conflictosPendientes > 0,
                label: Text('$_conflictosPendientes'),
                child: const Icon(Icons.sync_problem),
              ),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _bannerConexion(offline),
          if (_esGestor && _conflictosPendientes > 0) ...[
            const SizedBox(height: 8),
            InkWell(
              onTap: _abrirOperaciones,
              child: Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: const Color(0xFFFFF8E1), borderRadius: BorderRadius.circular(8)),
                child: Text(
                  'Operaciones sin conexión: $_conflictosPendientes en conflicto por revisar. Toca para verlas.',
                  style: const TextStyle(color: Color(0xFF8A6D00), fontWeight: FontWeight.w600),
                ),
              ),
            ),
          ],
          const SizedBox(height: 16),
          const Text('Buscar prenda (código o nombre)', style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _busquedaController,
                  decoration: const InputDecoration(
                    hintText: 'Ej: CAM-001 o Camisa Oxford',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _buscar(),
                ),
              ),
              const SizedBox(width: 8),
              ElevatedButton(onPressed: _buscar, child: const Text('Buscar')),
            ],
          ),
          if (_busquedaLocal && !_buscando)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                'Resultados del catálogo guardado en este dispositivo.',
                style: TextStyle(fontSize: 12, color: _naranja),
              ),
            ),
          if (_buscando) const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator())),
          ..._resultados.map((r) => Card(
                margin: const EdgeInsets.only(top: 8),
                child: ListTile(
                  title: Text(r['nombre_completo'].toString()),
                  subtitle: Text('Bs ${r['precio']} - Stock: ${r['cantidad']}'),
                  trailing: ElevatedButton(
                    onPressed: () => _agregarItem(Map<String, dynamic>.from(r as Map)),
                    child: const Text('Agregar'),
                  ),
                ),
              )),

          const SizedBox(height: 20),
          DropdownButtonFormField<int>(
            value: _sucursales.any((s) => s['id_sucursal'] == _sucursalSeleccionada)
                ? _sucursalSeleccionada
                : null,
            decoration: const InputDecoration(labelText: 'Sucursal', border: OutlineInputBorder()),
            items: _sucursales
                .map((s) => DropdownMenuItem<int>(value: s['id_sucursal'] as int, child: Text(s['nombre'].toString())))
                .toList(),
            onChanged: _onCambioSucursal,
          ),
          if (_sucursalSeleccionada != null) ...[
            const SizedBox(height: 12),
            _seccionReservas(offline),
          ],

          const SizedBox(height: 20),
          const Divider(),
          const Text('Venta actual', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),

          if (_ventaVacia) const Text('Sin prendas agregadas.', style: TextStyle(color: AppColors.grey)),

          ..._reservasVenta.map(_tarjetaReservaVenta),

          ..._items.map((item) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Row(
                    children: [
                      Expanded(child: Text(item.nombre, style: const TextStyle(fontWeight: FontWeight.w600))),
                      IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () => _decrementar(item)),
                      Text('${item.cantidad}'),
                      IconButton(icon: const Icon(Icons.add_circle_outline), onPressed: () => _incrementar(item)),
                      Text('Bs ${(item.precio * item.cantidad).toStringAsFixed(2)}', style: const TextStyle(fontWeight: FontWeight.w700)),
                      IconButton(icon: const Icon(Icons.close, color: AppColors.danger), onPressed: () => _quitar(item)),
                    ],
                  ),
                ),
              )),

          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('Total', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
              Text('Bs ${_total.toStringAsFixed(2)}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.accent)),
            ],
          ),
          if (_reservasVenta.isNotEmpty)
            Text(
              'Incluye el saldo de ${_reservasVenta.length} reserva(s): Bs ${_totalSaldos.toStringAsFixed(2)}.',
              style: const TextStyle(fontSize: 12, color: AppColors.grey),
            ),
          const SizedBox(height: 16),

          // NUEVO (CU08): cliente opcional.
          TextField(
            controller: _correoController,
            keyboardType: TextInputType.emailAddress,
            decoration: const InputDecoration(
              labelText: 'Correo del cliente (opcional)',
              hintText: 'cliente@correo.com',
              border: OutlineInputBorder(),
            ),
          ),
          if (!offline.enLinea)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                'Sin conexión se valida al sincronizar; si no existe, la venta queda sin cliente.',
                style: TextStyle(fontSize: 12, color: AppColors.grey),
              ),
            ),
          const SizedBox(height: 12),

          DropdownButtonFormField<String>(
            value: _metodoPago,
            decoration: const InputDecoration(labelText: 'Método de pago', border: OutlineInputBorder()),
            items: [
              const DropdownMenuItem(value: 'EFECTIVO', child: Text('Efectivo')),
              DropdownMenuItem(
                value: 'TARJETA',
                enabled: offline.enLinea,
                child: Text(
                  'Tarjeta (datáfono físico)',
                  style: TextStyle(color: offline.enLinea ? null : AppColors.grey),
                ),
              ),
              DropdownMenuItem(
                value: 'QR',
                enabled: offline.enLinea,
                child: Text('QR', style: TextStyle(color: offline.enLinea ? null : AppColors.grey)),
              ),
            ],
            onChanged: (value) => setState(() => _metodoPago = value ?? 'EFECTIVO'),
          ),
          if (!offline.enLinea)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                'Sin conexión solo se aceptan pagos en efectivo.',
                style: TextStyle(fontSize: 12, color: _naranja),
              ),
            ),
          if (!offline.enLinea && _reservasVenta.isNotEmpty)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                _errorReservasOffline,
                style: TextStyle(fontSize: 12, color: AppColors.danger),
              ),
            ),

          if (_metodoPago == 'QR' && !_ventaVacia) ...[
            const SizedBox(height: 16),
            const Text(
              'Mostrale este código al cliente para que pague desde su app bancaria.',
              style: TextStyle(fontSize: 12, color: AppColors.grey),
            ),
            const SizedBox(height: 8),
            Center(
              child: QrImageView(
                data: _qrData,
                size: 180,
              ),
            ),
          ],

          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: const TextStyle(color: AppColors.danger)),
          ],

          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: (_registrando || (!offline.enLinea && _reservasVenta.isNotEmpty)) ? null : _registrarVenta,
            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
            child: Text(_registrando
                ? 'Registrando...'
                : (offline.enLinea ? 'Registrar Venta' : 'Guardar venta sin conexión')),
          ),

          if (offline.ventas.isNotEmpty || offline.resultado != null) ...[
            const SizedBox(height: 24),
            _seccionCola(offline),
          ],
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  /// NUEVO (Fase 2): reservas pagadas de la sucursal, listas para retirar.
  Widget _seccionReservas(PosOfflineService offline) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text('Reservas por retirar',
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
                ),
                if (offline.enLinea)
                  IconButton(
                    icon: const Icon(Icons.refresh),
                    onPressed: _cargandoReservas ? null : _cargarReservas,
                  ),
              ],
            ),
            if (!offline.enLinea)
              const Text(
                'Sin conexión no se pueden cobrar reservas.',
                style: TextStyle(fontSize: 13, color: _naranja),
              )
            else if (_cargandoReservas)
              const Padding(
                padding: EdgeInsets.all(8),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_reservasDisponibles.isEmpty)
              const Text(
                'No hay reservas pagadas por retirar en esta sucursal.',
                style: TextStyle(fontSize: 13, color: AppColors.grey),
              )
            else
              for (final r in _reservasDisponibles)
                Container(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  decoration: const BoxDecoration(
                    border: Border(top: BorderSide(color: Color(0xFFF0F0F0))),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Reserva #${r.idReserva} · ${r.cliente}',
                                style: const TextStyle(fontWeight: FontWeight.w600)),
                            Text(r.prendas.map((p) => '${p['variante']}').join(', '),
                                style: const TextStyle(fontSize: 12, color: Color(0xFF555555))),
                            Text(
                              'Pagado Bs ${r.pagado.toStringAsFixed(2)} · Saldo Bs ${r.saldo.toStringAsFixed(2)}',
                              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      _reservaAgregada(r)
                          ? const Text('Agregada', style: TextStyle(color: AppColors.success))
                          : ElevatedButton(
                              onPressed: () => _agregarReserva(r),
                              child: const Text('Agregar'),
                            ),
                    ],
                  ),
                ),
          ],
        ),
      ),
    );
  }

  Widget _tarjetaReservaVenta(ReservaVenta r) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      color: const Color(0xFFF5F5FA),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Reserva #${r.idReserva} · ${r.cliente}',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  ...r.prendas.map((p) => Text('• ${p['variante']}', style: const TextStyle(fontSize: 13))),
                  Text(
                    'Total Bs ${r.total.toStringAsFixed(2)} · Pagado al reservar Bs ${r.pagado.toStringAsFixed(2)}',
                    style: const TextStyle(fontSize: 12, color: AppColors.grey),
                  ),
                  const Text('Se retira completa.', style: TextStyle(fontSize: 12, color: AppColors.grey)),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                const Text('Saldo', style: TextStyle(fontSize: 12, color: AppColors.grey)),
                Text('Bs ${r.saldo.toStringAsFixed(2)}', style: const TextStyle(fontWeight: FontWeight.w700)),
              ],
            ),
            IconButton(
              icon: const Icon(Icons.close, color: AppColors.danger),
              onPressed: () => _quitarReserva(r),
            ),
          ],
        ),
      ),
    );
  }

  Widget _bannerConexion(PosOfflineService offline) {
    final enLinea = offline.enLinea;
    final fecha = offline.fechaCatalogo;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: enLinea ? const Color(0xFFE8F5E9) : _fondoNaranja,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Icon(Icons.circle, size: 10, color: enLinea ? const Color(0xFF2E7D32) : _naranja),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  enLinea ? 'En línea' : 'Sin conexión',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: enLinea ? const Color(0xFF1B5E20) : const Color(0xFF8A4B00),
                  ),
                ),
                if (!enLinea)
                  const Text(
                    'Las ventas en efectivo se guardan en este dispositivo y se envían al recuperar internet.',
                    style: TextStyle(fontSize: 12, color: Color(0xFF8A4B00)),
                  ),
                if (fecha != null)
                  Text(
                    'Catálogo guardado: ${offline.totalCatalogo} prendas, el ${_fmt.format(fecha.toLocal())}.'
                    '${enLinea ? '' : ' Los precios y el stock pueden estar desactualizados.'}',
                    style: const TextStyle(fontSize: 12),
                  ),
                if (fecha == null && !enLinea)
                  const Text(
                    'No hay catálogo guardado en este dispositivo: conéctate una vez para descargarlo.',
                    style: TextStyle(fontSize: 12),
                  ),
              ],
            ),
          ),
          if (enLinea)
            TextButton(
              onPressed: offline.actualizandoCatalogo ? null : offline.actualizarCatalogo,
              child: Text(offline.actualizandoCatalogo ? 'Actualizando...' : 'Actualizar catálogo'),
            ),
        ],
      ),
    );
  }

  Widget _seccionCola(PosOfflineService offline) {
    final r = offline.resultado;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Ventas sin conexión',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                if (offline.registradasEnServidor > 0)
                  OutlinedButton(
                    onPressed: offline.limpiarConfirmadas,
                    child: const Text('Quitar registradas'),
                  ),
                OutlinedButton(
                  onPressed: (!offline.enLinea || offline.sincronizando || offline.pendientes == 0)
                      ? null
                      : offline.sincronizar,
                  child: Text(offline.sincronizando ? 'Sincronizando...' : 'Sincronizar ahora'),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '${offline.pendientes} por enviar · ${offline.confirmadas} confirmada(s)'
              '${offline.enConflicto > 0 ? ' · ${offline.enConflicto} en conflicto' : ''}'
              '${offline.rechazadas > 0 ? ' · ${offline.rechazadas} rechazada(s)' : ''}',
              style: const TextStyle(fontSize: 13, color: AppColors.grey),
            ),
            if (r != null) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: r.error != null ? const Color(0xFFFDECEA) : const Color(0xFFE8F5E9),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  r.error ??
                      'Última sincronización (${DateFormat('dd/MM HH:mm').format(r.fecha.toLocal())}): '
                          '${r.sincronizadas} registrada(s), ${r.enConflicto} en conflicto, '
                          '${r.duplicadas} ya registrada(s) antes, ${r.rechazadas} rechazada(s).',
                  style: TextStyle(
                    fontSize: 13,
                    color: r.error != null ? const Color(0xFF8E2A20) : const Color(0xFF1B5E20),
                  ),
                ),
              ),
            ],
            for (final v in offline.ventas) _filaVenta(v),
          ],
        ),
      ),
    );
  }

  Widget _filaVenta(VentaLocal v) {
    final (fondo, texto) = _coloresEstado(v.estado);
    final enConflicto = v.estado == EstadoVentaLocal.enConflicto;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: Color(0xFFF0F0F0))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(v.sucursal.isNotEmpty ? v.sucursal : 'Sucursal',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                child: Text(
                  _textoEstado(v),
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: texto),
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            '${_fmt.format(v.fechaOperacion.toLocal())} · ${v.prendas} prenda(s) · Bs ${v.total.toStringAsFixed(2)}',
            style: const TextStyle(fontSize: 13, color: Color(0xFF555555)),
          ),
          if (v.correoCliente != null)
            Text('Cliente: ${v.correoCliente}', style: const TextStyle(fontSize: 13, color: Color(0xFF555555))),
          Text('Código: ${v.uuid}',
              style: const TextStyle(fontSize: 11, fontFamily: 'monospace', color: Color(0xFF999999))),
          if (v.estado == EstadoVentaLocal.confirmada && v.fechaConfirmacion != null)
            Text(
              'Confirmada el ${_fmt.format(v.fechaConfirmacion!.toLocal())}'
              '${v.mensaje != null ? ' · ${v.mensaje}' : ''}',
              style: const TextStyle(fontSize: 13, color: Color(0xFF1B5E20)),
            ),
          if (v.estado == EstadoVentaLocal.rechazada)
            Text('Motivo: ${v.mensaje ?? ''}',
                style: const TextStyle(fontSize: 13, color: Color(0xFFC0392B))),
          // NUEVO (CU08): detalle del conflicto.
          if (enConflicto) ...[
            if (v.mensaje != null)
              Text(v.mensaje!, style: const TextStyle(fontSize: 13, color: Color(0xFF8A6D00))),
            for (final c in v.conflictos)
              Text(
                c['tipo'] == 'PRECIO'
                    ? '${c['prenda']}: cobrado Bs ${c['precio_offline']}, precio actual Bs ${c['precio_servidor']} '
                        '(diferencia Bs ${c['diferencia']})'
                    : '${c['prenda']}: se vendieron ${c['cantidad']}, en el servidor quedaban ${c['stock_disponible']}',
                style: const TextStyle(fontSize: 12, color: Color(0xFF8A6D00)),
              ),
            const Text('Lo revisa el encargado o el administrador.',
                style: TextStyle(fontSize: 12, color: AppColors.grey, fontStyle: FontStyle.italic)),
          ],
          if (v.estado == EstadoVentaLocal.rechazada)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => _descartar(v),
                child: const Text('Descartar', style: TextStyle(color: AppColors.danger)),
              ),
            ),
        ],
      ),
    );
  }

  Widget _comprobanteEnLinea() {
    final venta = _ventaConfirmada!;
    final items = (venta['items'] ?? []) as List<dynamic>;
    final pagadoReservas = double.tryParse('${venta['pagado_reservas'] ?? ''}') ?? 0;
    final cliente = venta['cliente'] as Map?;
    return Scaffold(
      appBar: AppBar(title: const Text('Punto de Venta')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Icon(Icons.check_circle, color: Colors.green, size: 56),
          const SizedBox(height: 12),
          Text('Venta #${venta['id_venta']} - ${venta['sucursal']}', style: const TextStyle(fontWeight: FontWeight.w600)),
          Text('Cajero: ${venta['usuario']}'),
          if (cliente != null) Text('Cliente: ${cliente['nombre']} (${cliente['correo']})'),
          Text('Método de pago: ${venta['metodo_pago']}'),
          const SizedBox(height: 12),
          ...items.map((item) => ListTile(
                title: Text(item['variante'].toString()),
                subtitle: Text(
                  'x${item['cantidad']} - Bs ${item['precio_unitario']}'
                  '${item['reservado'] == true ? ' · reserva' : ''}',
                ),
                trailing: Text('Bs ${item['subtotal']}', style: const TextStyle(fontWeight: FontWeight.w600)),
              )),
          const Divider(),
          if (pagadoReservas > 0)
            Text('Pagado al reservar: - Bs ${pagadoReservas.toStringAsFixed(2)}',
                style: const TextStyle(color: AppColors.success)),
          Text(
            '${pagadoReservas > 0 ? 'Total cobrado' : 'Total'}: Bs ${venta['total']}',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 20),
          ElevatedButton(
            onPressed: _nuevaVenta,
            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
            child: const Text('Nueva venta'),
          ),
        ],
      ),
    );
  }

  Widget _comprobanteOffline(VentaLocal venta) {
    return Scaffold(
      appBar: AppBar(title: const Text('Punto de Venta')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              border: Border.all(color: _naranja, width: 2),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Venta guardada sin conexión',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                  decoration: BoxDecoration(color: _fondoNaranja, borderRadius: BorderRadius.circular(999)),
                  child: const Text(
                    'Registrada localmente · pendiente de enviar',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: _naranja),
                  ),
                ),
                const SizedBox(height: 8),
                Text('${venta.sucursal} - ${_fmt.format(venta.fechaOperacion.toLocal())}'),
                Text('Método de pago: ${venta.metodoPago}'),
                if (venta.correoCliente != null) Text('Cliente: ${venta.correoCliente}'),
                Text('Código: ${venta.uuid}',
                    style: const TextStyle(fontSize: 11, fontFamily: 'monospace', color: Color(0xFF777777))),
                const SizedBox(height: 8),
                ...venta.items.map((i) => ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(i.nombre),
                      subtitle: Text('x${i.cantidad} - Bs ${i.precio.toStringAsFixed(2)}'),
                      trailing: Text('Bs ${(i.precio * i.cantidad).toStringAsFixed(2)}',
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                    )),
                const Divider(),
                Text('Total: Bs ${venta.total.toStringAsFixed(2)}',
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                const Text(
                  'La venta queda confirmada cuando el servidor la registre al volver la conexión.',
                  style: TextStyle(fontSize: 13, color: Color(0xFF666666)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          ElevatedButton(
            onPressed: _nuevaVenta,
            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
            child: const Text('Nueva venta'),
          ),
        ],
      ),
    );
  }
}