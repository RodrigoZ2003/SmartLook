// mobile/lib/features/cart_checkout/presentation/cart_screen.dart
//
// MODIFICADO (SaaS - A.1): un carrito por tienda. Arriba, chips con cada
// tienda y su cantidad de prendas; se paga un carrito a la vez y solo se
// ofrecen las sucursales de la tienda elegida.
// MODIFICADO (Fase 2 - reservas con anticipo, igual que la web): las prendas
// de una reserva muestran su precio reservado, no cambian de cantidad ni se
// quitan si la reserva está pagada (se cancela desde "Mis reservas"), y el
// total ya viene con lo pagado al reservar descontado (se cobra solo el saldo).
// MODIFICADO (Fase 3 - CU18, igual que la web): descuento por fidelidad. Si el
// cliente ganó el descuento del mes en la tienda elegida y el carrito no tiene
// reservas, se muestra la línea "Descuento por fidelidad" y el total ya
// descontado (el envío se cobra completo). El backend vuelve a calcularlo al
// cobrar. Debajo del resumen, un aviso con el progreso del mes en esa tienda.

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart'
    show
        FlutterMap,
        MapController,
        MapOptions,
        Marker,
        MarkerLayer,
        RichAttributionWidget,
        TextSourceAttribution,
        TileLayer;
import 'package:flutter_stripe/flutter_stripe.dart' hide Card;
import 'package:geolocator/geolocator.dart'
    show Geolocator, LocationAccuracy, LocationPermission, LocationSettings;
import 'package:latlong2/latlong.dart' show LatLng;
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';
import '../../fidelidad/data/fidelidad_service.dart';
import '../data/cart_service.dart';

class _MensajeError implements Exception {
  final String texto;
  const _MensajeError(this.texto);
}

class CartScreen extends StatefulWidget {
  const CartScreen({super.key});

  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  late final CartService _cartService;
  late final FidelidadService _fidelidadService;
  final MapController _mapController = MapController();
  final TextEditingController _direccionCtrl = TextEditingController();
  final TextEditingController _referenciaCtrl = TextEditingController();

  // Santa Cruz de la Sierra: centro del mapa cuando aún no hay sucursal ni punto.
  static const LatLng _centroDefecto = LatLng(-17.7834, -63.1821);

  // SaaS: carritos activos (uno por tienda) y la tienda elegida.
  List<Map<String, dynamic>> _carritos = [];
  int? _empresaSeleccionada;
  Map<String, dynamic>? _carrito;
  bool _loading = true;

  List<dynamic> _sucursales = [];
  int? _sucursalSeleccionada;
  String? _errorPago;
  Map<String, dynamic>? _ordenConfirmada;

  // CU21: entrega
  String _tipoEntrega = 'RETIRO'; // RETIRO | DELIVERY
  double? _lat;
  double? _lng;
  bool _ubicando = false;
  bool _cotizando = false;
  Map<String, dynamic>? _cotizacion;
  int _geocodificacionId = 0;
  int _cotizacionId = 0;

  // Flujo de pago con Stripe
  bool _mostrarFormularioPago = false;
  bool _iniciandoPago = false;
  bool _confirmandoPago = false;
  String? _clientSecret;
  bool _tarjetaCompleta = false;

  // CU18: progreso del descuento por fidelidad en la tienda elegida.
  Map<String, dynamic>? _fidelidad;
  bool _reglaFidelidadActiva = false;
  int _fidelidadId = 0;

  @override
  void initState() {
    super.initState();
    final apiClient = context.read<ApiClient>();
    _cartService = CartService(apiClient: apiClient);
    _fidelidadService = FidelidadService(apiClient: apiClient);
    _cargar();
    _cargarSucursales();
  }

  @override
  void dispose() {
    _direccionCtrl.dispose();
    _referenciaCtrl.dispose();
    _mapController.dispose();
    super.dispose();
  }

  // ---- Datos derivados ----

  /// Sucursales de la tienda del carrito elegido.
  List<dynamic> get _sucursalesTienda => _sucursales
      .where((s) => s['id_empresa'] == _empresaSeleccionada)
      .toList();

  LatLng? get _puntoCliente =>
      (_lat != null && _lng != null) ? LatLng(_lat!, _lng!) : null;

  LatLng? get _puntoSucursal {
    for (final s in _sucursalesTienda) {
      if (s['id_sucursal'] == _sucursalSeleccionada) {
        final lat = double.tryParse('${s['latitud']}');
        final lng = double.tryParse('${s['longitud']}');
        if (lat != null && lng != null) return LatLng(lat, lng);
      }
    }
    return null;
  }

  /// Fase 2: el total del carrito ya es el saldo (precio de las prendas menos lo pagado al reservar).
  double get _totalProductos => double.tryParse('${_carrito?['total']}') ?? 0;

  double get _subtotalPrendas => double.tryParse('${_carrito?['subtotal_prendas']}') ?? 0;

  double get _pagadoReservas => double.tryParse('${_carrito?['pagado_reservas']}') ?? 0;

  /// NUEVO (Fase 2): el carrito tiene prendas de reservas ya pagadas (anticipo o total).
  bool get _tienePagoReservas => _pagadoReservas > 0;

  /// NUEVO (Fase 2): todo está pagado y se retira en tienda (no hay nada que cobrar).
  bool get _sinSaldoParaRetiro =>
      _tipoEntrega == 'RETIRO' && _tienePagoReservas && !(_totalProductos > 0);

  /// NUEVO (CU18): el carrito tiene prendas de alguna reserva.
  bool get _tieneReservas {
    final items = (_carrito?['items'] ?? []) as List<dynamic>;
    return items.any((i) => i['reservado'] == true);
  }

  /// NUEVO (CU18): descuento por fidelidad sobre las prendas (0 si no aplica).
  double get _descuentoFidelidad {
    if (_fidelidad?['disponible'] != true || _tieneReservas) return 0;
    return FidelidadService.descuentoSobre(_totalProductos, _fidelidad!['porcentaje']);
  }

  /// NUEVO (CU18): prendas a cobrar (con el descuento por fidelidad, si tiene).
  double get _totalPrendas => _totalProductos - _descuentoFidelidad;

  double get _costoEnvio => (_tipoEntrega == 'DELIVERY' && _cotizacion != null)
      ? (double.tryParse('${_cotizacion!['costo_envio']}') ?? 0)
      : 0;

  // Total a cobrar: prendas (con descuento) + envío (solo si es delivery y ya hay cotización).
  double get _totalAPagar => _totalPrendas + _costoEnvio;

  bool get _pagoEnCurso => _mostrarFormularioPago || _iniciandoPago || _confirmandoPago;

  int _prendasDe(Map<String, dynamic> carrito) {
    final items = (carrito['items'] ?? []) as List<dynamic>;
    return items.fold<int>(0, (suma, i) => suma + ((i['cantidad'] ?? 0) as int));
  }

  String _bs(dynamic valor) => (double.tryParse('${valor ?? ''}') ?? 0).toStringAsFixed(2);

  // ---- Carga ----

  Future<void> _cargar() async {
    // El spinner solo aparece la primera vez, para no destruir el mapa al cambiar cantidades.
    setState(() => _loading = _carrito == null && _carritos.isEmpty);
    try {
      final carritos = await _cartService.getCarritosActivos();
      if (!mounted) return;
      Map<String, dynamic>? elegido;
      for (final c in carritos) {
        if (c['id_empresa'] == _empresaSeleccionada) elegido = c;
      }
      final cambioTienda = elegido == null;
      elegido ??= carritos.isNotEmpty ? carritos.first : null;
      setState(() {
        _carritos = carritos;
        _carrito = elegido;
        _empresaSeleccionada = elegido?['id_empresa'] as int?;
        _loading = false;
        if (cambioTienda) _limpiarCheckout();
      });
      _cargarFidelidad();
      final items = (elegido?['items'] ?? []) as List<dynamic>;
      // Si cambió la cantidad de prendas, el costo de envío también puede cambiar.
      if (!cambioTienda &&
          _tipoEntrega == 'DELIVERY' &&
          _lat != null &&
          _ordenConfirmada == null &&
          items.isNotEmpty) {
        _cotizar();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
    }
  }

  /// NUEVO (CU18): progreso del descuento por fidelidad en la tienda elegida.
  /// Un fallo no se muestra: el carrito sigue sin la línea de descuento.
  Future<void> _cargarFidelidad() async {
    final idEmpresa = _empresaSeleccionada;
    final id = ++_fidelidadId;
    if (idEmpresa == null) {
      setState(() => _fidelidad = null);
      return;
    }
    try {
      final datos = await _fidelidadService.miProgreso(idEmpresa: idEmpresa);
      // Si cambió de tienda mientras esperaba, se descarta esta respuesta.
      if (!mounted || id != _fidelidadId) return;
      final regla = (datos['regla'] ?? {}) as Map;
      setState(() {
        _reglaFidelidadActiva = regla['activa'] == true;
        _fidelidad = FidelidadService.filaDeEmpresa(datos, idEmpresa);
      });
    } catch (_) {
      if (!mounted || id != _fidelidadId) return;
      setState(() => _fidelidad = null);
    }
  }

  Future<void> _cargarSucursales() async {
    try {
      final sucursales = await _cartService.getSucursales();
      if (!mounted) return;
      setState(() => _sucursales = sucursales);
    } catch (_) {
      if (!mounted) return;
      setState(() => _sucursales = []);
    }
  }

  /// Cambia de tienda: cada carrito tiene su propia sucursal y entrega.
  void _onCambioTienda(int idEmpresa) {
    if (idEmpresa == _empresaSeleccionada || _pagoEnCurso) return;
    Map<String, dynamic>? elegido;
    for (final c in _carritos) {
      if (c['id_empresa'] == idEmpresa) elegido = c;
    }
    setState(() {
      _empresaSeleccionada = idEmpresa;
      _carrito = elegido;
      _fidelidad = null;
      _limpiarCheckout();
    });
    _cargarFidelidad();
  }

  /// Deja sin sucursal, entrega ni cotización (al cambiar de tienda).
  void _limpiarCheckout() {
    _sucursalSeleccionada = null;
    _errorPago = null;
    _reiniciarEntrega();
  }

  Future<void> _incrementar(Map<String, dynamic> item) async {
    await _cartService.actualizarCantidad(item['id_item'] as int, (item['cantidad'] as int) + 1);
    _cargar();
  }

  Future<void> _decrementar(Map<String, dynamic> item) async {
    final cantidad = item['cantidad'] as int;
    if (cantidad <= 1) {
      await _quitar(item);
      return;
    }
    await _cartService.actualizarCantidad(item['id_item'] as int, cantidad - 1);
    _cargar();
  }

  Future<void> _quitar(Map<String, dynamic> item) async {
    try {
      await _cartService.quitarItem(item['id_item'] as int);
    } catch (e) {
      if (mounted) setState(() => _errorPago = _extraerError(e, 'No se pudo quitar la prenda.'));
    }
    _cargar();
  }

  String _extraerError(Object e, String fallback) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map && data['error'] != null) return data['error'].toString();
      if (data is Map && data['detail'] != null) return data['detail'].toString();
    } catch (_) {}
    return fallback;
  }

  // ---- CU21: entrega ----

  void _onCambioTipo(String tipo) {
    setState(() {
      _tipoEntrega = tipo;
      _cotizacion = null;
      _errorPago = null;
    });
    // Al volver a Delivery con una ubicación ya elegida, se recotiza sola.
    if (tipo == 'DELIVERY' && _lat != null && _sucursalSeleccionada != null) {
      _cotizar();
    }
  }

  void _onCambioSucursal(int? value) {
    setState(() {
      _sucursalSeleccionada = value;
      _cotizacion = null;
      _errorPago = null;
    });
    if (_tipoEntrega == 'DELIVERY') {
      if (_lat != null) {
        _cotizar();
      } else {
        final p = _puntoSucursal;
        if (p != null) _moverMapa(p, 14);
      }
    }
  }

  void _moverMapa(LatLng punto, double zoom) {
    try {
      _mapController.move(punto, zoom);
    } catch (_) {
      // El mapa todavía no está dibujado: se centrará solo al construirse.
    }
  }

  // El cliente marcó un punto (GPS o toque en el mapa): se guarda, se completa
  // la dirección y se cotiza el envío.
  void _marcarPunto(LatLng p, {bool moverMapa = false}) {
    setState(() {
      _lat = p.latitude;
      _lng = p.longitude;
    });
    if (moverMapa) _moverMapa(p, 16);
    _completarDireccion(p);
    _cotizar();
  }

  Future<void> _usarMiUbicacion() async {
    setState(() {
      _ubicando = true;
      _errorPago = null;
    });
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        throw const _MensajeError('Activa la ubicación (GPS) de tu teléfono e intenta de nuevo.');
      }
      var permiso = await Geolocator.checkPermission();
      if (permiso == LocationPermission.denied) {
        permiso = await Geolocator.requestPermission();
      }
      if (permiso == LocationPermission.denied ||
          permiso == LocationPermission.deniedForever) {
        throw const _MensajeError(
          'Permite el acceso a la ubicación para calcular tu envío. También puedes marcar el punto tocando el mapa.',
        );
      }
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15),
        ),
      );
      if (!mounted) return;
      setState(() => _ubicando = false);
      _marcarPunto(LatLng(pos.latitude, pos.longitude), moverMapa: true);
    } on _MensajeError catch (e) {
      if (!mounted) return;
      setState(() {
        _ubicando = false;
        _errorPago = e.texto;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _ubicando = false;
        _errorPago = 'No se pudo obtener tu ubicación. Marca el punto tocando el mapa.';
      });
    }
  }

  // Rellena "Dirección de entrega" con la dirección del punto (OpenStreetMap).
  Future<void> _completarDireccion(LatLng p) async {
    final id = ++_geocodificacionId;
    final direccion = await _cartService.direccionDesdeCoordenadas(p.latitude, p.longitude);
    // Si el cliente movió el punto otra vez mientras esperaba, se descarta esta respuesta.
    if (!mounted || id != _geocodificacionId || direccion == null) return;
    setState(() => _direccionCtrl.text = direccion);
  }

  Future<void> _cotizar() async {
    if (_sucursalSeleccionada == null) {
      setState(() => _errorPago = 'Selecciona primero la sucursal que despacha tu pedido.');
      return;
    }
    if (_lat == null || _lng == null) return;
    final id = ++_cotizacionId;
    setState(() {
      _cotizando = true;
      _errorPago = null;
    });
    try {
      final data = await _cartService.cotizarEnvio(
        idSucursal: _sucursalSeleccionada!,
        latitud: _lat!,
        longitud: _lng!,
      );
      if (!mounted || id != _cotizacionId) return;
      setState(() {
        _cotizacion = data;
        _cotizando = false;
      });
    } catch (e) {
      if (!mounted || id != _cotizacionId) return;
      setState(() {
        _cotizacion = null;
        _cotizando = false;
        _errorPago = _extraerError(e, 'No se pudo cotizar el envío.');
      });
    }
  }

  void _reiniciarEntrega() {
    _tipoEntrega = 'RETIRO';
    _lat = null;
    _lng = null;
    _cotizacion = null;
    _cotizacionId++;
    _geocodificacionId++;
    _cotizando = false;
    _direccionCtrl.clear();
    _referenciaCtrl.clear();
  }

  // ---- Pago ----

  // Paso 1: crea el intento de pago y muestra el formulario de tarjeta.
  Future<void> _iniciarPago() async {
    if (_sucursalSeleccionada == null) {
      setState(() => _errorPago = _tipoEntrega == 'DELIVERY'
          ? 'Selecciona la sucursal que despacha tu pedido.'
          : 'Selecciona una sucursal de entrega/retiro.');
      return;
    }

    Map<String, dynamic>? entrega;
    if (_tipoEntrega == 'DELIVERY') {
      final direccion = _direccionCtrl.text.trim();
      if (direccion.isEmpty) {
        setState(() => _errorPago = 'Ingresa tu dirección de entrega.');
        return;
      }
      if (_lat == null || _lng == null) {
        setState(() => _errorPago =
            'Marca tu ubicación en el mapa o toca "Usar mi ubicación" para calcular el envío.');
        return;
      }
      if (_cotizacion == null) {
        setState(() => _errorPago = 'Espera a que se calcule el costo de envío.');
        return;
      }
      entrega = {
        'direccion': direccion,
        'referencia': _referenciaCtrl.text.trim(),
        'latitud': _lat,
        'longitud': _lng,
      };
    }

    setState(() {
      _iniciandoPago = true;
      _errorPago = null;
    });
    try {
      final data = await _cartService.checkout(_sucursalSeleccionada!, entrega: entrega);
      if (!mounted) return;
      setState(() {
        _clientSecret = data['client_secret'] as String;
        _mostrarFormularioPago = true;
        _iniciandoPago = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorPago = _extraerError(e, 'No se pudo iniciar el pago. Intenta nuevamente.');
        _iniciandoPago = false;
      });
    }
  }

  // Paso 2: confirma la tarjeta con Stripe y cierra la orden en el backend.
  Future<void> _confirmarPago() async {
    if (_clientSecret == null || !_tarjetaCompleta) return;
    setState(() {
      _confirmandoPago = true;
      _errorPago = null;
    });
    try {
      final paymentIntent = await Stripe.instance.confirmPayment(
        paymentIntentClientSecret: _clientSecret!,
        data: const PaymentMethodParams.card(
          paymentMethodData: PaymentMethodData(),
        ),
      );

      final orden = await _cartService.confirmarPago(paymentIntent.id);
      if (!mounted) return;
      setState(() {
        _ordenConfirmada = orden;
        _mostrarFormularioPago = false;
        _confirmandoPago = false;
        _clientSecret = null;
        _tarjetaCompleta = false;
      });
      _cargar();
    } on StripeException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorPago = e.error.localizedMessage ?? 'La tarjeta fue rechazada.';
        _confirmandoPago = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorPago = _extraerError(e, 'No se pudo cerrar la orden.');
        _confirmandoPago = false;
      });
    }
  }

  void _cancelarPago() {
    setState(() {
      _mostrarFormularioPago = false;
      _clientSecret = null;
      _errorPago = null;
      _tarjetaCompleta = false;
    });
  }

  // ---- Interfaz ----

  @override
  Widget build(BuildContext context) {
    if (_ordenConfirmada != null) {
      return _pantallaConfirmacion();
    }

    final items = (_carrito?['items'] ?? []) as List<dynamic>;
    return Scaffold(
      appBar: AppBar(title: const Text('Mi Carrito')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : items.isEmpty
              ? RefreshIndicator(
                  onRefresh: _cargar,
                  child: ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: const [
                      SizedBox(height: 200),
                      Center(child: Text('Tu carrito está vacío.')),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _cargar,
                  child: SingleChildScrollView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _chipsTiendas(),
                        const SizedBox(height: 12),
                        for (final item in items) _tarjetaItem(item as Map<String, dynamic>),
                        const SizedBox(height: 8),
                        _resumen(),
                        if (_fidelidad != null && _reglaFidelidadActiva) _avisoFidelidad(),
                        const SizedBox(height: 16),
                        if (!_mostrarFormularioPago) _seccionEntrega(),
                        if (_errorPago != null) ...[
                          const SizedBox(height: 8),
                          Text(_errorPago!, style: const TextStyle(color: AppColors.danger)),
                        ],
                        if (_sinSaldoParaRetiro) ...[
                          const SizedBox(height: 12),
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: const Color(0xFFE8F5E9),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: const Text(
                              'Ya pagaste todo al reservar: retira tus prendas en la sucursal, no hace falta pagar aquí.',
                              style: TextStyle(color: Color(0xFF1B5E20)),
                            ),
                          ),
                        ],
                        const SizedBox(height: 12),
                        if (!_mostrarFormularioPago && !_sinSaldoParaRetiro)
                          ElevatedButton(
                            onPressed: _iniciandoPago ? null : _iniciarPago,
                            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
                            child: Text(_iniciandoPago ? 'Preparando pago...' : 'Continuar al pago'),
                          ),
                        if (_mostrarFormularioPago) _seccionPago(),
                        const SizedBox(height: 24),
                      ],
                    ),
                  ),
                ),
    );
  }

  /// NUEVO (SaaS - A.1): una chip por tienda con su cantidad de prendas.
  Widget _chipsTiendas() {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: _carritos.map((c) {
        final idEmpresa = c['id_empresa'] as int?;
        final seleccionada = idEmpresa == _empresaSeleccionada;
        return ChoiceChip(
          avatar: Icon(
            Icons.storefront,
            size: 18,
            color: seleccionada ? AppColors.white : AppColors.dark,
          ),
          label: Text('${c['empresa_nombre'] ?? ''} (${_prendasDe(c)})'),
          selected: seleccionada,
          selectedColor: AppColors.accent,
          showCheckmark: false,
          labelStyle: TextStyle(
            color: seleccionada ? AppColors.white : AppColors.dark,
            fontWeight: FontWeight.w600,
          ),
          onSelected: (idEmpresa == null || _pagoEnCurso)
              ? null
              : (_) => _onCambioTienda(idEmpresa),
        );
      }).toList(),
    );
  }

  Widget _pantallaConfirmacion() {
    final orden = _ordenConfirmada!;
    final esDelivery = orden['tipo_entrega'] == 'DELIVERY';
    final delivery = orden['delivery'] as Map?;
    final empresa = orden['empresa_nombre']?.toString() ?? '';
    final quedan = _carritos.isNotEmpty;
    return Scaffold(
      appBar: AppBar(title: const Text('Mi Carrito')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.check_circle, color: Colors.green, size: 64),
            const SizedBox(height: 16),
            const Text('¡Compra realizada con éxito!',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            if (empresa.isNotEmpty) ...[
              Text('Tienda: $empresa', textAlign: TextAlign.center),
              const SizedBox(height: 4),
            ],
            Text('Orden #${orden['id_orden']} - Total Bs ${orden['total']}'),
            const SizedBox(height: 4),
            if (esDelivery)
              Text(
                'Envío a domicilio (Bs ${orden['costo_envio']}): ${delivery?['direccion'] ?? ''}',
                textAlign: TextAlign.center,
              )
            else
              Text('Retiro en sucursal: ${orden['sucursal']}', textAlign: TextAlign.center),
            const SizedBox(height: 4),
            Text('Referencia de pago (Stripe): ${orden['referencia_pago']}',
                textAlign: TextAlign.center),
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: () => setState(() {
                _ordenConfirmada = null;
                _limpiarCheckout();
              }),
              child: Text(quedan ? 'Ver mis otros carritos' : 'Seguir comprando'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _tarjetaItem(Map<String, dynamic> item) {
    // Fase 2: prenda de una reserva (precio congelado, se retira completa).
    final reservado = item['reservado'] == true;
    final puedeQuitar = item['puede_quitar'] != false;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item['variante'].toString(),
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  Text(
                    'Bs ${item['precio_unitario']} c/u',
                    style: const TextStyle(color: AppColors.grey, fontSize: 12),
                  ),
                  if (reservado)
                    Text(
                      'Reserva #${item['id_reserva']}${!puedeQuitar ? ' · pagada al reservar' : ''}',
                      style: const TextStyle(
                        color: AppColors.accent,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                ],
              ),
            ),
            if (!reservado)
              IconButton(
                icon: const Icon(Icons.remove_circle_outline),
                onPressed: _pagoEnCurso ? null : () => _decrementar(item),
              ),
            Padding(
              padding: EdgeInsets.symmetric(horizontal: reservado ? 8 : 0),
              child: Text('${item['cantidad']}'),
            ),
            if (!reservado)
              IconButton(
                icon: const Icon(Icons.add_circle_outline),
                onPressed: _pagoEnCurso ? null : () => _incrementar(item),
              ),
            const SizedBox(width: 8),
            Text(
              'Bs ${item['subtotal']}',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            if (puedeQuitar)
              IconButton(
                icon: const Icon(Icons.close, color: AppColors.danger),
                onPressed: _pagoEnCurso ? null : () => _quitar(item),
              )
            else
              const Tooltip(
                message: 'Para no llevarla, cancela la reserva desde Mis reservas',
                child: Padding(
                  padding: EdgeInsets.only(left: 8),
                  child: Text(
                    'Se retira\ncompleta',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 11, color: AppColors.grey),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _filaResumen(String etiqueta, String valor, {bool grande = false, Color? color}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(etiqueta,
              style: TextStyle(fontSize: grande ? 18 : 15, fontWeight: FontWeight.w600, color: color)),
          Text(
            valor,
            style: TextStyle(
              fontSize: grande ? 20 : 15,
              fontWeight: FontWeight.bold,
              color: grande ? AppColors.accent : color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _resumen() {
    final esDelivery = _tipoEntrega == 'DELIVERY';
    return Column(
      children: [
        const Divider(),
        // NUEVO (Fase 2): lo pagado al reservar se descuenta del total.
        if (_tienePagoReservas) ...[
          _filaResumen('Precio de las prendas', 'Bs ${_bs(_subtotalPrendas)}'),
          _filaResumen('Pagado al reservar', '- Bs ${_bs(_pagadoReservas)}', color: AppColors.success),
        ],
        // NUEVO (CU18): descuento por fidelidad sobre las prendas.
        if (_descuentoFidelidad > 0) ...[
          _filaResumen('Precio de las prendas', 'Bs ${_totalProductos.toStringAsFixed(2)}'),
          _filaResumen(
            'Descuento por fidelidad (${FidelidadService.porcentajeTexto(_fidelidad!['porcentaje'])}%)',
            '- Bs ${_descuentoFidelidad.toStringAsFixed(2)}',
            color: const Color(0xFF1E6B3A),
          ),
        ],
        _filaResumen(
          esDelivery ? 'Subtotal' : (_tienePagoReservas ? 'Saldo a pagar' : 'Total'),
          'Bs ${_totalPrendas.toStringAsFixed(2)}',
          grande: !esDelivery,
        ),
        if (esDelivery && _cotizacion != null) ...[
          _filaResumen(
            'Envío (${_cotizacion!['distancia_km']} km)',
            'Bs ${_costoEnvio.toStringAsFixed(2)}',
          ),
          _filaResumen('Total a pagar', 'Bs ${_totalAPagar.toStringAsFixed(2)}', grande: true),
        ],
      ],
    );
  }

  /// NUEVO (CU18): aviso del descuento por fidelidad en esta tienda (textos de la web).
  Widget _avisoFidelidad() {
    final f = _fidelidad!;
    final porcentaje = FidelidadService.porcentajeTexto(f['porcentaje']);
    final tienda = '${_carrito?['empresa_nombre'] ?? ''}';
    final lista = _descuentoFidelidad > 0;
    String texto;
    switch (f['estado']) {
      case 'DISPONIBLE':
        texto = _tieneReservas
            ? 'Tienes $porcentaje% de descuento por fidelidad, pero tu carrito tiene prendas '
                'reservadas: se aplicará en tu próxima compra sin reservas de este mes.'
            : '¡Tienes $porcentaje% de descuento por fidelidad en esta compra! El envío se cobra '
                'completo. Esta compra no admite devolución ni cambio.';
        break;
      case 'USADO':
        texto = 'Ya usaste tu descuento por fidelidad de este mes en $tienda (${f['uso'] ?? ''}).';
        break;
      default:
        texto = 'Llevas ${f['compras']} de ${f['requeridas']} compras este mes en $tienda. '
            'Al llegar a ${f['requeridas']}, tu siguiente compra tendrá $porcentaje% de descuento.';
    }
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: lista ? const Color(0xFFE8F5E9) : const Color(0xFFEEF3FB),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        texto,
        style: TextStyle(
          color: lista ? const Color(0xFF1B5E20) : const Color(0xFF0F3460),
          fontWeight: lista ? FontWeight.w600 : FontWeight.w400,
        ),
      ),
    );
  }

  Widget _seccionEntrega() {
    final esDelivery = _tipoEntrega == 'DELIVERY';
    final sucursales = _sucursalesTienda;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment<String>(
              value: 'RETIRO',
              label: Text('Retiro'),
              icon: Icon(Icons.store_outlined),
            ),
            ButtonSegment<String>(
              value: 'DELIVERY',
              label: Text('Delivery'),
              icon: Icon(Icons.delivery_dining),
            ),
          ],
          selected: {_tipoEntrega},
          onSelectionChanged: (seleccion) => _onCambioTipo(seleccion.first),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<int>(
          // La key fuerza a reconstruir el campo al cambiar de tienda.
          key: ValueKey('sucursal-$_empresaSeleccionada'),
          value: sucursales.any((s) => s['id_sucursal'] == _sucursalSeleccionada)
              ? _sucursalSeleccionada
              : null,
          decoration: InputDecoration(
            labelText: esDelivery ? 'Sucursal que despacha tu pedido' : 'Sucursal de retiro',
            border: const OutlineInputBorder(),
          ),
          items: sucursales
              .map((s) => DropdownMenuItem<int>(
                    value: s['id_sucursal'] as int,
                    child: Text(s['nombre'].toString()),
                  ))
              .toList(),
          onChanged: _onCambioSucursal,
        ),
        if (esDelivery) ...[
          const SizedBox(height: 12),
          TextField(
            controller: _direccionCtrl,
            maxLength: 250,
            maxLines: 2,
            minLines: 1,
            decoration: const InputDecoration(
              labelText: 'Dirección de entrega',
              border: OutlineInputBorder(),
              counterText: '',
            ),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _referenciaCtrl,
            maxLength: 250,
            decoration: const InputDecoration(
              labelText: 'Referencia (opcional)',
              border: OutlineInputBorder(),
              counterText: '',
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: (_ubicando || _cotizando) ? null : _usarMiUbicacion,
            icon: const Icon(Icons.my_location),
            label: Text(_ubicando
                ? 'Obteniendo ubicación...'
                : (_lat != null ? 'Actualizar mi ubicación' : 'Usar mi ubicación')),
          ),
          const SizedBox(height: 12),
          _mapa(),
          const SizedBox(height: 4),
          const Text(
            'Toca el mapa para indicar dónde entregamos tu pedido.',
            style: TextStyle(fontSize: 12, color: AppColors.grey),
          ),
          if (_cotizando) ...[
            const SizedBox(height: 8),
            const Text('Calculando el costo de envío...', style: TextStyle(fontSize: 13)),
          ],
          if (_cotizacion != null && !_cotizando) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFEEF3FB),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Distancia: ${_cotizacion!['distancia_km']} km '
                    '(${_cotizacion!['fuente_distancia'] == 'openrouteservice' ? 'ruta real por calles' : 'distancia aproximada'})',
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'Costo de envío: Bs ${_costoEnvio.toStringAsFixed(2)}',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ],
              ),
            ),
          ],
        ],
      ],
    );
  }

  Widget _mapa() {
    final cliente = _puntoCliente;
    final sucursal = _puntoSucursal;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        height: 280,
        child: FlutterMap(
          mapController: _mapController,
          options: MapOptions(
            initialCenter: cliente ?? sucursal ?? _centroDefecto,
            initialZoom: cliente != null ? 16 : 14,
            onTap: (tapPosition, punto) => _marcarPunto(punto),
          ),
          children: [
            TileLayer(
              urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'com.example.smartlook_mobile',
            ),
            MarkerLayer(
              markers: [
                if (sucursal != null)
                  Marker(
                    point: sucursal,
                    width: 36,
                    height: 36,
                    child: const Icon(Icons.store, color: Color(0xFFE94560), size: 32),
                  ),
                if (cliente != null)
                  Marker(
                    point: cliente,
                    width: 40,
                    height: 40,
                    alignment: Alignment.topCenter,
                    child: const Icon(Icons.location_on, color: Color(0xFF0F3460), size: 40),
                  ),
              ],
            ),
            RichAttributionWidget(
              attributions: [
                TextSourceAttribution('© OpenStreetMap contributors'),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // Paso 2: campo de tarjeta real (SDK de Stripe)
  Widget _seccionPago() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('Datos de la tarjeta', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        CardField(
          enablePostalCode: false,
          numberHintText: '4242 4242 4242 4242',
          onCardChanged: (details) {
            setState(() => _tarjetaCompleta = details?.complete ?? false);
          },
        ),
        const SizedBox(height: 4),
        const Text(
          'Tarjeta de prueba: 4242 4242 4242 4242, fecha futura y CVC.',
          style: TextStyle(fontSize: 12, color: AppColors.grey),
        ),
        const SizedBox(height: 12),
        ElevatedButton(
          onPressed: (_confirmandoPago || !_tarjetaCompleta) ? null : _confirmarPago,
          style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
          child: Text(_confirmandoPago
              ? 'Procesando pago...'
              : 'Pagar Bs ${_totalAPagar.toStringAsFixed(2)}'),
        ),
        TextButton(
          onPressed: _confirmandoPago ? null : _cancelarPago,
          child: const Text('Cancelar'),
        ),
      ],
    );
  }
}