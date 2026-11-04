// mobile/lib/features/reservations/presentation/reservation_status_screen.dart
//
// Lista las reservas del cliente (el backend filtra por el usuario).
// MODIFICADO (SaaS - 6.2): el cliente ve también sus reservas hechas sin
// conexión con su estado (Registrada localmente, Enviada, Recibida,
// Rechazada), puede sincronizarlas, descartar las rechazadas y quitar las
// recibidas. Sin conexión, la lista del servidor sale de la copia guardada.
// MODIFICADO (Fase 2 - reservas con anticipo y CU17, igual que la web): cada
// reserva muestra lo pagado, el saldo y sus plazos. El cliente paga las
// pendientes de pago (PagoReservaWidget) y al cancelar ve cuánto se le
// devuelve (lo pagado menos el 10% del total); las canceladas o vencidas
// muestran su nota NR.
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/reservation_service.dart';
import '../data/reserva_offline_service.dart';
import 'pago_reserva_widget.dart';
import 'reservation_form_screen.dart';

class ReservationStatusScreen extends StatefulWidget {
  const ReservationStatusScreen({super.key});

  @override
  State<ReservationStatusScreen> createState() => _ReservationStatusScreenState();
}

class _ReservationStatusScreenState extends State<ReservationStatusScreen> {
  static const Color _naranja = Color(0xFFE65100);
  static const Color _textoNaranja = Color(0xFF8A4B00);
  static const Color _fondoNaranja = Color(0xFFFFF3E0);

  late final ReservationService _reservationService;
  late final ReservaOfflineService _offline;
  final DateFormat _fmt = DateFormat('dd/MM/yyyy HH:mm');

  List<dynamic> _reservas = [];
  bool _loading = true;
  bool _sinDatosGuardados = false;
  DateTime? _fechaCopia;
  ResultadoSyncReservas? _ultimoResultado;

  // NUEVO (Fase 2): reserva que se está pagando y la que se está cancelando.
  int? _idPagando;
  int? _idCancelando;
  String _mensaje = '';
  String _errorAccion = '';

  @override
  void initState() {
    super.initState();
    _reservationService = ReservationService(apiClient: context.read<ApiClient>());
    _offline = context.read<ReservaOfflineService>();
    _ultimoResultado = _offline.resultado;
    _offline.addListener(_alCambiarOffline);
    _offline.recargar();
    _offline.sincronizar();
    _cargar();
  }

  @override
  void dispose() {
    _offline.removeListener(_alCambiarOffline);
    super.dispose();
  }

  // Las reservas recibidas en una sincronización ya aparecen en la lista del servidor.
  void _alCambiarOffline() {
    final r = _offline.resultado;
    if (r != null && r != _ultimoResultado && r.sincronizadas + r.duplicadas > 0) {
      _ultimoResultado = r;
      _cargar();
    } else {
      _ultimoResultado = r;
    }
  }

  Future<void> _cargar() async {
    setState(() {
      _loading = true;
      _sinDatosGuardados = false;
    });
    try {
      final reservas = await _reservationService.getReservas();
      _offline.guardarMisReservas(reservas);
      if (!mounted) return;
      setState(() {
        _reservas = reservas;
        _fechaCopia = null;
        _loading = false;
      });
    } catch (e) {
      if (_offline.esErrorDeRedApi(e)) {
        _offline.marcarSinConexion();
        final copia = await _offline.misReservasLocales();
        if (!mounted) return;
        setState(() {
          _loading = false;
          if (copia != null) {
            _reservas = copia.$1;
            _fechaCopia = copia.$2;
          } else {
            _sinDatosGuardados = true;
          }
        });
        return;
      }
      if (mounted) setState(() => _loading = false);
    }
  }

  bool _tieneSaldo(Map reserva) => montoReserva(reserva['saldo']) > 0;

  bool _tienePago(Map reserva) => montoReserva(reserva['monto_pagado']) > 0;

  String _textoFecha(dynamic valor) {
    final f = fechaReservaLocal(valor);
    return f == null ? '' : _fmt.format(f);
  }

  // CU17: avisa cuánto se devuelve antes de cancelar.
  String _textoConfirmarCancelacion(Map reserva) {
    final c = reserva['cancelacion'];
    if (c is! Map || montoReserva(c['pagado']) <= 0) {
      return '¿Cancelar la Reserva #${reserva['id_reserva']}? Las prendas dejarán de estar reservadas.';
    }
    return '¿Cancelar la Reserva #${reserva['id_reserva']}?\n\n'
        'Pagaste: Bs ${bsReserva(c['pagado'])}\n'
        'Se retiene el ${reserva['porcentaje_retencion']}% del total: Bs ${bsReserva(c['retenido'])}\n'
        'Se te devuelve a la tarjeta: Bs ${bsReserva(c['devuelto'])}';
  }

  Future<void> _cancelar(Map reserva) async {
    setState(() {
      _mensaje = '';
      _errorAccion = '';
    });
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        content: Text(_textoConfirmarCancelacion(reserva)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Volver')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Cancelar reserva', style: TextStyle(color: AppColors.danger)),
          ),
        ],
      ),
    );
    if (confirmar != true) return;
    final id = reserva['id_reserva'] as int;
    setState(() => _idCancelando = id);
    try {
      final cancelada = await _reservationService.cancelarReserva(id);
      if (!mounted) return;
      final nota = cancelada['numero_nota'];
      setState(() {
        _idCancelando = null;
        _mensaje = (nota != null && '$nota'.isNotEmpty)
            ? 'Reserva #${cancelada['id_reserva']} cancelada. Nota $nota: se devuelven '
                'Bs ${bsReserva(cancelada['monto_devuelto'])} a tu tarjeta.'
            : 'Reserva #$id cancelada.';
      });
      _cargar();
    } catch (e) {
      if (!mounted) return;
      String mensaje = 'No se pudo cancelar la reserva.';
      if (_offline.esErrorDeRedApi(e)) {
        mensaje = 'Sin conexión: la reserva no se puede cancelar ahora. Inténtalo al recuperar internet.';
      } else {
        try {
          final data = (e as dynamic).response?.data;
          if (data is Map && data['error'] != null) mensaje = data['error'].toString();
        } catch (_) {}
      }
      setState(() {
        _idCancelando = null;
        _errorAccion = mensaje;
      });
    }
  }

  // ---------------------------------------------------------------- pago (Fase 2)
  void _abrirPago(Map reserva) {
    setState(() {
      _mensaje = '';
      _errorAccion = '';
      _idPagando = reserva['id_reserva'] as int;
    });
  }

  void _cerrarPago() {
    setState(() => _idPagando = null);
  }

  void _onPagada(Map<String, dynamic> reserva) {
    setState(() {
      _idPagando = null;
      _mensaje = 'Reserva #${reserva['id_reserva']} confirmada: pagaste Bs ${bsReserva(reserva['monto_pagado'])}'
          '${_tieneSaldo(reserva) ? ' y pagarás Bs ${bsReserva(reserva['saldo'])} al retirar.' : '.'}';
    });
    _cargar();
  }

  // ---------------------------------------------------------------- reservas sin conexión
  Future<void> _descartar(ReservaLocal reserva) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        content: const Text('¿Descartar esta reserva rechazada? Se borrará de este dispositivo.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Descartar', style: TextStyle(color: AppColors.danger)),
          ),
        ],
      ),
    );
    if (confirmar == true) await _offline.descartar(reserva);
  }

  Color _colorEstado(String estado) {
    switch (estado) {
      case 'PENDIENTE':
        return Colors.orange;
      case 'PENDIENTE_PAGO':
        return _naranja;
      case 'CONFIRMADA':
        return Colors.blue;
      case 'COMPLETADA':
        return AppColors.success;
      case 'CANCELADA':
        return AppColors.danger;
      default:
        return AppColors.grey;
    }
  }

  String _textoEstadoLocal(ReservaLocal r) {
    switch (r.estado) {
      case EstadoReservaLocal.confirmada:
        // Fase 2: el servidor la recibió "Pendiente de pago" (3 horas para pagarla).
        return r.idReserva != null ? 'Recibida · Reserva #${r.idReserva}' : 'Recibida';
      case EstadoReservaLocal.rechazada:
        return 'Rechazada';
      case EstadoReservaLocal.enviada:
        return 'Enviada';
      default:
        return 'Registrada localmente';
    }
  }

  (Color, Color) _coloresLocal(String estado) {
    switch (estado) {
      case EstadoReservaLocal.enviada:
        return (const Color(0xFFE3F2FD), const Color(0xFF0D47A1));
      case EstadoReservaLocal.confirmada:
        return (const Color(0xFFE8F5E9), const Color(0xFF1B5E20));
      case EstadoReservaLocal.rechazada:
        return (const Color(0xFFFDECEA), const Color(0xFFC0392B));
      default:
        return (_fondoNaranja, _naranja);
    }
  }

  @override
  Widget build(BuildContext context) {
    final offline = context.watch<ReservaOfflineService>();
    final mostrarCola = offline.reservas.isNotEmpty || offline.resultado != null;
    return Scaffold(
      appBar: AppBar(title: const Text('Mis Reservas')),
      body: RefreshIndicator(
        onRefresh: () async {
          await offline.sincronizar();
          await _cargar();
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
          children: [
            if (_errorAccion.isNotEmpty)
              _caja(_errorAccion, const Color(0xFFFDECEA), const Color(0xFFC0392B)),
            if (_mensaje.isNotEmpty)
              _caja(_mensaje, const Color(0xFFE8F5E9), const Color(0xFF1B5E20)),
            if (mostrarCola) ...[
              _seccionCola(offline),
              const SizedBox(height: 16),
            ],
            if (_fechaCopia != null)
              _caja(
                'Sin conexión: lista guardada el ${_fmt.format(_fechaCopia!.toLocal())}. Puede estar desactualizada.',
                _fondoNaranja,
                _textoNaranja,
              ),
            if (_loading)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_sinDatosGuardados)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Sin conexión y sin reservas guardadas en este dispositivo. Se mostrarán al recuperar internet.',
                  textAlign: TextAlign.center,
                ),
              )
            else if (_reservas.isEmpty)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: Text('Todavía no tienes reservas.')),
              )
            else
              ..._reservas.map((r) => _tarjetaServidor(Map<String, dynamic>.from(r as Map))),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          await Navigator.push(
            context,
            MaterialPageRoute(builder: (context) => const ReservationFormScreen()),
          );
          _offline.recargar();
          _cargar();
        },
        icon: const Icon(Icons.add),
        label: const Text('Nueva Reserva'),
      ),
    );
  }

  Widget _caja(String texto, Color fondo, Color color) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(6)),
      child: Text(texto, style: TextStyle(fontSize: 13, color: color)),
    );
  }

  Widget _filaMonto(String etiqueta, String valor, {bool resaltar = false, Color? color}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Expanded(child: Text(etiqueta, style: TextStyle(fontSize: 13, color: color ?? AppColors.grey))),
          Text(
            valor,
            style: TextStyle(
              fontSize: 13,
              color: color,
              fontWeight: resaltar ? FontWeight.bold : FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  Widget _tarjetaServidor(Map<String, dynamic> reserva) {
    final items = (reserva['items'] ?? []) as List<dynamic>;
    final estado = '${reserva['estado']}';
    final id = reserva['id_reserva'] as int;
    final enLinea = _fechaCopia == null;
    final empresa = reserva['empresa_nombre'];
    final nota = reserva['numero_nota'];
    final tieneNota = nota != null && '$nota'.isNotEmpty;
    final puedeCancelar = reserva['puede_cancelar'] == true && enLinea;
    final puedePagar = reserva['puede_pagar'] == true && enLinea;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Reserva #$id', style: const TextStyle(fontSize: 12, color: AppColors.grey)),
                      Text(
                        '${empresa != null ? '$empresa · ' : ''}${reserva['sucursal'] ?? ''}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _colorEstado(estado).withOpacity(0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    '${reserva['estado_display'] ?? estado}',
                    style: TextStyle(
                      color: _colorEstado(estado),
                      fontWeight: FontWeight.w600,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text('Fecha: ${fechaCortaReserva(reserva['fecha_reserva'])}   '
                'Hora: ${horaCortaReserva(reserva['hora_reserva'])}'),
            const SizedBox(height: 6),
            const Text('Prendas:', style: TextStyle(fontWeight: FontWeight.w600)),
            ...items.map((item) => Text(
                  '• ${item['variante']}'
                  '${item['precio_unitario'] != null ? ' · Bs ${bsReserva(item['precio_unitario'])}' : ''}',
                )),
            // NUEVO (Fase 2): pago, saldo y plazos.
            if (reserva['monto_total'] != null) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: AppColors.light, borderRadius: BorderRadius.circular(6)),
                child: Column(
                  children: [
                    _filaMonto('Total', 'Bs ${bsReserva(reserva['monto_total'])}'),
                    if (_tienePago(reserva))
                      _filaMonto(
                        'Pagado (${'${reserva['tipo_pago_display'] ?? ''}'.toLowerCase()})',
                        'Bs ${bsReserva(reserva['monto_pagado'])}',
                      ),
                    if (estado == 'CONFIRMADA')
                      _filaMonto('Saldo al retirar', 'Bs ${bsReserva(reserva['saldo'])}', resaltar: true),
                  ],
                ),
              ),
            ],
            if (estado == 'PENDIENTE_PAGO' && reserva['fecha_limite_pago'] != null) ...[
              const SizedBox(height: 8),
              Text(
                'Págala antes del ${_textoFecha(reserva['fecha_limite_pago'])}; si no, vence y las prendas no quedan apartadas.',
                style: const TextStyle(fontSize: 13, color: _textoNaranja),
              ),
            ],
            if ((estado == 'CONFIRMADA' || estado == 'PENDIENTE') && reserva['fecha_vencimiento'] != null) ...[
              const SizedBox(height: 8),
              Text(
                'Retírala hasta el ${_textoFecha(reserva['fecha_vencimiento'])}'
                '${_tienePago(reserva) ? '; después vence y se devuelve lo pagado menos el ${reserva['porcentaje_retencion']}% del total' : ''}.',
                style: const TextStyle(fontSize: 13, color: AppColors.grey),
              ),
            ],
            // NUEVO (Fase 2 - CU17): nota de devolución al cancelar o vencer.
            if (tieneNota) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.greyLight),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Nota de devolución $nota', style: const TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 4),
                    _filaMonto('Pagado', 'Bs ${bsReserva(reserva['monto_pagado'])}'),
                    _filaMonto(
                      'Retenido (${reserva['porcentaje_retencion']}% del total)',
                      'Bs ${bsReserva(reserva['monto_retenido'])}',
                    ),
                    _filaMonto(
                      'Devuelto a la tarjeta',
                      'Bs ${bsReserva(reserva['monto_devuelto'])}',
                      resaltar: true,
                      color: AppColors.success,
                    ),
                    if (reserva['fecha_cierre'] != null)
                      Text(_textoFecha(reserva['fecha_cierre']),
                          style: const TextStyle(fontSize: 11, color: AppColors.grey)),
                  ],
                ),
              ),
            ],
            if (reserva['motivo_cierre'] != null &&
                '${reserva['motivo_cierre']}'.isNotEmpty &&
                (estado == 'CANCELADA' || estado == 'VENCIDA')) ...[
              const SizedBox(height: 6),
              Text('${reserva['motivo_cierre']}',
                  style: const TextStyle(fontSize: 13, color: AppColors.grey, fontStyle: FontStyle.italic)),
            ],
            if (_idPagando == id) ...[
              const SizedBox(height: 10),
              PagoReservaWidget(
                reserva: reserva,
                onPagada: _onPagada,
                onPagarDespues: _cerrarPago,
              ),
            ] else if (puedeCancelar || puedePagar) ...[
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  if (puedeCancelar)
                    TextButton(
                      onPressed: _idCancelando == id ? null : () => _cancelar(reserva),
                      child: Text(
                        _idCancelando == id ? 'Cancelando...' : 'Cancelar reserva',
                        style: const TextStyle(color: AppColors.danger),
                      ),
                    ),
                  if (puedePagar) ...[
                    const SizedBox(width: 8),
                    ElevatedButton(
                      onPressed: () => _abrirPago(reserva),
                      child: const Text('Pagar ahora'),
                    ),
                  ],
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _seccionCola(ReservaOfflineService offline) {
    final r = offline.resultado;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Reservas sin conexión',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                if (offline.confirmadas > 0)
                  OutlinedButton(
                    onPressed: offline.limpiarConfirmadas,
                    child: const Text('Quitar recibidas'),
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
              '${offline.pendientes} por enviar · ${offline.confirmadas} recibida(s)'
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
                          '${r.sincronizadas} registrada(s), ${r.duplicadas} ya registrada(s) antes, '
                          '${r.rechazadas} rechazada(s).',
                  style: TextStyle(
                    fontSize: 13,
                    color: r.error != null ? const Color(0xFF8E2A20) : const Color(0xFF1B5E20),
                  ),
                ),
              ),
            ],
            for (final reserva in offline.reservas) _filaLocal(reserva),
          ],
        ),
      ),
    );
  }

  Widget _filaLocal(ReservaLocal r) {
    final (fondo, texto) = _coloresLocal(r.estado);
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
                child: Text(r.sucursal.isNotEmpty ? r.sucursal : 'Sucursal',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                child: Text(
                  _textoEstadoLocal(r),
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: texto),
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text('Para el ${r.fechaReserva} a las ${r.horaReserva} · ${r.items.length} prenda(s)',
              style: const TextStyle(fontSize: 13, color: Color(0xFF555555))),
          Text(r.items.map((i) => i.label).join(', '),
              style: const TextStyle(fontSize: 13, color: Color(0xFF555555))),
          Text('Registrada el ${_fmt.format(r.fechaOperacion.toLocal())}',
              style: const TextStyle(fontSize: 13, color: Color(0xFF555555))),
          Text('Código: ${r.uuid}',
              style: const TextStyle(fontSize: 11, fontFamily: 'monospace', color: Color(0xFF999999))),
          if (r.estado == EstadoReservaLocal.confirmada && r.fechaConfirmacion != null)
            Text(
              'Confirmada el ${_fmt.format(r.fechaConfirmacion!.toLocal())}'
              '${r.mensaje != null ? ' · ${r.mensaje}' : ''}',
              style: const TextStyle(fontSize: 13, color: Color(0xFF1B5E20)),
            ),
          if (r.estado == EstadoReservaLocal.rechazada) ...[
            Text('Motivo: ${r.mensaje ?? ''}',
                style: const TextStyle(fontSize: 13, color: Color(0xFFC0392B))),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => _descartar(r),
                child: const Text('Descartar', style: TextStyle(color: AppColors.danger)),
              ),
            ),
          ],
        ],
      ),
    );
  }
}