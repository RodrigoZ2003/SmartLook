// mobile/lib/features/reservations/presentation/reservation_form_screen.dart
//
// Formulario para que el cliente agregue varias prendas, elija sucursal,
// fecha y hora y confirme la reserva.
// MODIFICADO (SaaS - 6.2): reserva sin conexión (igual que la web).
// - Sin internet (o si se corta al enviar), la reserva se guarda en SQLite
//   como "Registrada localmente" y se envía sola al volver la conexión.
// - Los productos y sucursales salen de la copia guardada sin conexión.
// - Una reserva solo puede tener prendas de una misma tienda, y solo se
//   ofrecen las sucursales activas de esa tienda.
// MODIFICADO (Fase 2 - reservas con anticipo, igual que la web): la reserva
// se crea "Pendiente de pago" y a continuación se paga con Stripe (anticipo
// o total, ver PagoReservaWidget). Si el cliente paga después, tiene 3
// horas para hacerlo desde "Mis reservas".
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/reservation_service.dart';
import '../data/reserva_offline_service.dart';
import 'pago_reserva_widget.dart';

class ReservationFormScreen extends StatefulWidget {
  const ReservationFormScreen({super.key});

  @override
  State<ReservationFormScreen> createState() => _ReservationFormScreenState();
}

class _ReservationFormScreenState extends State<ReservationFormScreen> {
  static const Color _textoNaranja = Color(0xFF8A4B00);
  static const Color _fondoNaranja = Color(0xFFFFF3E0);

  late final ReservationService _reservationService;
  late final ReservaOfflineService _offline;

  List<Map<String, dynamic>> _productos = [];
  List<dynamic> _sucursales = [];

  int? _productoSeleccionado;
  int? _varianteSeleccionada;
  int? _sucursalSeleccionada;
  DateTime? _fecha;
  TimeOfDay? _hora;

  final List<Map<String, dynamic>> _items = [];

  bool _loading = true;
  bool _enviando = false;
  bool _guardadaSinConexion = false;
  String _error = '';
  String _exito = '';

  // NUEVO (Fase 2): reserva recién creada que espera el pago.
  Map<String, dynamic>? _reservaPorPagar;
  Map<String, dynamic>? _reservaPagada;
  bool _avisoPendientePago = false;

  @override
  void initState() {
    super.initState();
    final apiClient = context.read<ApiClient>();
    _reservationService = ReservationService(apiClient: apiClient);
    _offline = context.read<ReservaOfflineService>();
    _cargarDatos();
  }

  Future<void> _cargarDatos() async {
    await Future.wait([_cargarProductos(), _cargarSucursales()]);
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _cargarProductos() async {
    if (_offline.enLinea) {
      try {
        final productos = await _offline.descargarProductos();
        if (mounted) setState(() => _productos = productos);
        return;
      } catch (e) {
        if (_offline.esErrorDeRedApi(e)) _offline.marcarSinConexion();
      }
    }
    final locales = await _offline.productosLocales();
    if (mounted) setState(() => _productos = locales);
  }

  Future<void> _cargarSucursales() async {
    if (_offline.enLinea) {
      try {
        final response = await context.read<ApiClient>().dio.get('/catalog/sucursales/');
        final lista = (response.data['results'] ?? response.data) as List<dynamic>;
        if (mounted) setState(() => _sucursales = lista);
        _offline.guardarSucursales(lista);
        return;
      } catch (e) {
        if (_offline.esErrorDeRedApi(e)) _offline.marcarSinConexion();
      }
    }
    final locales = await _offline.sucursalesLocales();
    if (mounted) setState(() => _sucursales = locales);
  }

  Map<String, dynamic>? get _productoActual {
    if (_productoSeleccionado == null) return null;
    for (final p in _productos) {
      if (p['id_producto'] == _productoSeleccionado) return p;
    }
    return null;
  }

  /// Tienda de las prendas ya agregadas (todas deben ser de la misma).
  Map<String, dynamic>? get _empresaReserva {
    if (_items.isEmpty) return null;
    return {'id': _items.first['id_empresa'], 'nombre': _items.first['empresa_nombre']};
  }

  /// Solo sucursales activas de la tienda de las prendas agregadas.
  List<dynamic> get _sucursalesDisponibles {
    final empresa = _empresaReserva;
    return _sucursales
        .where((s) =>
            (s['estado'] == null || s['estado'] == 'ACTIVA') &&
            (empresa == null || empresa['id'] == null || s['id_empresa'] == empresa['id']))
        .toList();
  }

  void _agregarItem() {
    setState(() => _error = '');
    final producto = _productoActual;
    if (producto == null || _varianteSeleccionada == null) {
      setState(() => _error = 'Selecciona un producto y una variante antes de agregar.');
      return;
    }
    final variantes = (producto['variantes'] ?? []) as List<dynamic>;
    Map? variante;
    for (final v in variantes) {
      if (v['id_variante'] == _varianteSeleccionada) variante = v as Map;
    }
    if (variante == null) return;
    if (_items.any((i) => i['id_variante'] == variante!['id_variante'])) {
      setState(() => _error = 'Esa prenda ya está en la reserva.');
      return;
    }
    final empresa = _empresaReserva;
    final idEmpresa = producto['id_empresa'];
    if (empresa != null && empresa['id'] != null && idEmpresa != null && empresa['id'] != idEmpresa) {
      setState(() => _error =
          'Una reserva solo puede tener prendas de una misma tienda (${empresa['nombre']}).');
      return;
    }
    setState(() {
      _items.add({
        'id_variante': variante!['id_variante'],
        'label': '${producto['nombre']} - ${variante['talla']?['nombre'] ?? ''} - '
            '${variante['color']?['nombre'] ?? ''}',
        'id_empresa': idEmpresa,
        'empresa_nombre': producto['empresa_nombre'],
      });
      _varianteSeleccionada = null;
      if (!_sucursalesDisponibles.any((s) => s['id_sucursal'] == _sucursalSeleccionada)) {
        _sucursalSeleccionada = null;
      }
    });
  }

  void _quitarItem(int index) {
    setState(() => _items.removeAt(index));
  }

  Future<void> _elegirFecha() async {
    final hoy = DateTime.now();
    final seleccionada = await showDatePicker(
      context: context,
      initialDate: hoy,
      firstDate: DateTime(hoy.year, hoy.month, hoy.day),
      lastDate: hoy.add(const Duration(days: 90)),
    );
    if (seleccionada != null) setState(() => _fecha = seleccionada);
  }

  Future<void> _elegirHora() async {
    final seleccionada = await showTimePicker(context: context, initialTime: TimeOfDay.now());
    if (seleccionada != null) setState(() => _hora = seleccionada);
  }

  String get _fechaStr => DateFormat('yyyy-MM-dd').format(_fecha!);

  String get _horaStr =>
      '${_hora!.hour.toString().padLeft(2, '0')}:${_hora!.minute.toString().padLeft(2, '0')}';

  Future<void> _enviar() async {
    setState(() {
      _error = '';
      _exito = '';
      _guardadaSinConexion = false;
      _reservaPagada = null;
      _avisoPendientePago = false;
    });
    if (_sucursalSeleccionada == null) {
      setState(() => _error = 'Selecciona una sucursal.');
      return;
    }
    if (_fecha == null || _hora == null) {
      setState(() => _error = 'Selecciona fecha y hora.');
      return;
    }
    final ahora = DateTime.now();
    if (_fecha!.isBefore(DateTime(ahora.year, ahora.month, ahora.day))) {
      setState(() => _error = 'La fecha de la reserva no puede ser anterior a hoy.');
      return;
    }
    if (_items.isEmpty) {
      setState(() => _error = 'Agrega al menos una prenda a la reserva.');
      return;
    }
    if (!_offline.enLinea) {
      await _guardarSinConexion();
      return;
    }

    setState(() => _enviando = true);
    try {
      final reserva = await _reservationService.crearReserva(
        idSucursal: _sucursalSeleccionada!,
        fechaReserva: _fechaStr,
        horaReserva: _horaStr,
        variantesIds: _items.map((i) => i['id_variante'] as int).toList(),
      );
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _reservaPorPagar = reserva;
        _limpiarFormulario();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _enviando = false);
      // Se cortó la conexión al enviar: la reserva se guarda en el teléfono.
      if (_offline.esErrorDeRedApi(e)) {
        _offline.marcarSinConexion();
        await _guardarSinConexion();
        return;
      }
      String mensaje = 'No se pudo crear la reserva. Intenta nuevamente.';
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
    String sucursal = '';
    for (final s in _sucursales) {
      if (s['id_sucursal'] == _sucursalSeleccionada) sucursal = '${s['nombre']}';
    }
    final empresa = _empresaReserva;
    setState(() => _enviando = true);
    try {
      await _offline.guardar(
        idSucursal: _sucursalSeleccionada!,
        sucursal: sucursal,
        idEmpresa: empresa?['id'] as int?,
        empresaNombre: empresa?['nombre'] as String?,
        fechaReserva: _fechaStr,
        horaReserva: _horaStr,
        items: _items
            .map((i) => ItemReservaLocal(
                  idVariante: i['id_variante'] as int,
                  label: i['label'] as String,
                ))
            .toList(),
      );
      if (!mounted) return;
      setState(() {
        _guardadaSinConexion = true;
        _exito = 'Sin conexión: la reserva quedó guardada en este dispositivo como '
            '"Registrada localmente" y se enviará sola al recuperar internet. Desde ese momento '
            'tendrás 3 horas para pagarla en "Mis reservas".';
        _limpiarFormulario();
      });
    } catch (_) {
      if (mounted) setState(() => _error = 'No se pudo guardar la reserva en este dispositivo.');
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  // NUEVO (Fase 2): el pago se confirmó; la prenda quedó apartada.
  void _onPagada(Map<String, dynamic> reserva) {
    setState(() {
      _reservaPorPagar = null;
      _reservaPagada = reserva;
    });
  }

  // NUEVO (Fase 2): el cliente decidió pagar después (tiene 3 horas).
  void _onPagarDespues() {
    final reserva = _reservaPorPagar;
    final limite = fechaReservaLocal(reserva?['fecha_limite_pago']);
    final hora = limite != null ? ' hasta las ${DateFormat('HH:mm').format(limite)}' : '';
    setState(() {
      _reservaPorPagar = null;
      _exito = 'La Reserva #${reserva?['id_reserva']} quedó pendiente de pago$hora. '
          'Págala desde "Mis reservas"; si no, vencerá y las prendas no quedarán apartadas.';
      _avisoPendientePago = true;
    });
  }

  void _limpiarFormulario() {
    _items.clear();
    _sucursalSeleccionada = null;
    _fecha = null;
    _hora = null;
  }

  void _verMisReservas() {
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final offline = context.watch<ReservaOfflineService>();
    return Scaffold(
      appBar: AppBar(title: const Text('Reservar Prendas')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (!offline.enLinea)
                    _aviso(
                      'Sin conexión: la reserva se guardará en este dispositivo y se enviará al recuperar internet. '
                      'Las prendas y sucursales son las que se consultaron antes y pueden estar desactualizadas.',
                    ),
                  if (!offline.enLinea && _productos.isEmpty)
                    _aviso(
                      'No hay productos guardados en este dispositivo: abre el catálogo con conexión una vez para poder reservar sin internet.',
                    ),
                  if (_reservaPorPagar != null)
                    PagoReservaWidget(
                      reserva: _reservaPorPagar!,
                      onPagada: _onPagada,
                      onPagarDespues: _onPagarDespues,
                    )
                  else ...[
                    if (_reservaPagada != null) _resumenPagada(_reservaPagada!),
                    _formulario(offline),
                  ],
                ],
              ),
            ),
    );
  }

  Widget _formulario(ReservaOfflineService offline) {
    final empresa = _empresaReserva;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Agregar Prenda', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        DropdownButtonFormField<int>(
          value: _productoSeleccionado,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Producto', border: OutlineInputBorder()),
          items: _productos
              .map<DropdownMenuItem<int>>((p) => DropdownMenuItem(
                    value: p['id_producto'] as int,
                    child: Text(
                      p['empresa_nombre'] != null
                          ? '${p['nombre']} (${p['empresa_nombre']})'
                          : p['nombre'].toString(),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ))
              .toList(),
          onChanged: (value) => setState(() {
            _productoSeleccionado = value;
            _varianteSeleccionada = null;
          }),
        ),
        if (_productoActual != null) ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            value: _varianteSeleccionada,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Talla / Color', border: OutlineInputBorder()),
            items: ((_productoActual!['variantes'] ?? []) as List<dynamic>)
                .map<DropdownMenuItem<int>>((v) => DropdownMenuItem(
                      value: v['id_variante'] as int,
                      child: Text('${v['talla']?['nombre']} - ${v['color']?['nombre']} (Bs ${v['precio']})'),
                    ))
                .toList(),
            onChanged: (value) => setState(() => _varianteSeleccionada = value),
          ),
        ],
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            onPressed: _agregarItem,
            child: const Text('+ Agregar a la reserva'),
          ),
        ),
        if (_items.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(
            empresa?['nombre'] != null
                ? 'Prendas en esta reserva · ${empresa!['nombre']}'
                : 'Prendas en esta reserva',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          ..._items.asMap().entries.map(
                (entry) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(entry.value['label']),
                  trailing: IconButton(
                    icon: const Icon(Icons.close, color: AppColors.danger),
                    onPressed: () => _quitarItem(entry.key),
                  ),
                ),
              ),
        ],
        const Divider(height: 32),
        const Text('Datos de la Reserva', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        DropdownButtonFormField<int>(
          key: ValueKey('sucursales-${empresa?['id']}'),
          value: _sucursalesDisponibles.any((s) => s['id_sucursal'] == _sucursalSeleccionada)
              ? _sucursalSeleccionada
              : null,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Sucursal', border: OutlineInputBorder()),
          items: _sucursalesDisponibles
              .map<DropdownMenuItem<int>>((s) => DropdownMenuItem(
                    value: s['id_sucursal'] as int,
                    child: Text(s['nombre'].toString()),
                  ))
              .toList(),
          onChanged: (value) => setState(() => _sucursalSeleccionada = value),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: _elegirFecha,
                child: Text(_fecha == null ? 'Elegir fecha' : DateFormat('dd/MM/yyyy').format(_fecha!)),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: OutlinedButton(
                onPressed: _elegirHora,
                child: Text(_hora == null ? 'Elegir hora' : _hora!.format(context)),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (_error.isNotEmpty) Text(_error, style: const TextStyle(color: AppColors.danger)),
        if (_exito.isNotEmpty)
          (_guardadaSinConexion || _avisoPendientePago)
              ? _aviso(_exito, conEnlace: true)
              : Text(_exito, style: const TextStyle(color: AppColors.success)),
        const SizedBox(height: 16),
        ElevatedButton(
          onPressed: _enviando ? null : _enviar,
          style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
          child: Text(_enviando
              ? 'Enviando...'
              : (offline.enLinea ? 'Reservar y pagar' : 'Guardar reserva sin conexión')),
        ),
      ],
    );
  }

  Widget _resumenPagada(Map<String, dynamic> r) {
    const verde = Color(0xFF1B5E20);
    final vence = fechaReservaLocal(r['fecha_vencimiento']);
    final tieneSaldo = montoReserva(r['saldo']) > 0;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: const Color(0xFFE8F5E9), borderRadius: BorderRadius.circular(8)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '¡Reserva #${r['id_reserva']} confirmada!',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: verde),
          ),
          const SizedBox(height: 6),
          Text(
            'Pagaste Bs ${bsReserva(r['monto_pagado'])} '
            '(${'${r['tipo_pago_display'] ?? ''}'.toLowerCase()}) y tus prendas quedaron apartadas en ${r['sucursal']}.',
            style: const TextStyle(color: verde),
          ),
          if (tieneSaldo) ...[
            const SizedBox(height: 4),
            Text.rich(
              TextSpan(
                text: 'Saldo a pagar al retirar: ',
                children: [
                  TextSpan(
                    text: 'Bs ${bsReserva(r['saldo'])}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const TextSpan(text: '.'),
                ],
              ),
              style: const TextStyle(color: verde),
            ),
          ],
          const SizedBox(height: 4),
          Text(
            'Te esperamos el ${fechaCortaReserva(r['fecha_reserva'])} a las ${horaCortaReserva(r['hora_reserva'])}.'
            '${vence != null ? ' Puedes retirarla hasta el ${DateFormat('dd/MM/yyyy HH:mm').format(vence)}; después vence y se devuelve lo pagado menos el ${r['porcentaje_retencion']}% del total.' : ''}',
            style: const TextStyle(color: verde),
          ),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: _verMisReservas, child: const Text('Ver mis reservas')),
        ],
      ),
    );
  }

  Widget _aviso(String texto, {bool conEnlace = false}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: _fondoNaranja, borderRadius: BorderRadius.circular(6)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(texto, style: const TextStyle(fontSize: 13, color: _textoNaranja)),
          if (conEnlace)
            TextButton(
              onPressed: _verMisReservas,
              style: TextButton.styleFrom(padding: EdgeInsets.zero, foregroundColor: _textoNaranja),
              child: const Text('Ver mis reservas', style: TextStyle(fontWeight: FontWeight.w600)),
            ),
        ],
      ),
    );
  }
}