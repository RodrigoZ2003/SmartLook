// mobile/lib/features/reservations/presentation/pago_reserva_widget.dart
//
// NUEVO (Fase 2 - reservas con anticipo): pago de una reserva con Stripe,
// igual que PagoReservaComponent de la web. El cliente elige pagar el
// anticipo o el total; se crea el cobro en el backend, se confirma la
// tarjeta con Stripe y luego se avisa al backend para que confirme la
// reserva y aparte las prendas. Se usa al crear la reserva y desde
// "Mis reservas" (reservas sin pagar).
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_stripe/flutter_stripe.dart' hide Card;
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/reservation_service.dart';

/// Monto que llega del backend (texto o número) como double.
double montoReserva(dynamic valor) => double.tryParse('${valor ?? ''}') ?? 0;

/// Monto con dos decimales (sin "Bs").
String bsReserva(dynamic valor) => montoReserva(valor).toStringAsFixed(2);

/// Fecha ISO del backend en la hora local del teléfono.
DateTime? fechaReservaLocal(dynamic valor) {
  if (valor == null) return null;
  return DateTime.tryParse('$valor')?.toLocal();
}

/// Porcentaje sin decimales cuando es entero (50.00 -> 50).
String porcentajeReserva(dynamic valor) {
  final n = montoReserva(valor);
  return n == n.roundToDouble() ? n.toStringAsFixed(0) : n.toStringAsFixed(2);
}

/// "2026-11-08" -> "08/11/2026".
String fechaCortaReserva(dynamic valor) {
  final f = DateTime.tryParse('${valor ?? ''}');
  return f == null ? '${valor ?? ''}' : DateFormat('dd/MM/yyyy').format(f);
}

/// "15:30:00" -> "15:30".
String horaCortaReserva(dynamic valor) {
  final texto = '${valor ?? ''}';
  return texto.length >= 5 ? texto.substring(0, 5) : texto;
}

class PagoReservaWidget extends StatefulWidget {
  /// Reserva "Pendiente de pago" tal como la devuelve el backend (con opciones_pago).
  final Map<String, dynamic> reserva;
  final ValueChanged<Map<String, dynamic>> onPagada;
  final VoidCallback onPagarDespues;

  const PagoReservaWidget({
    super.key,
    required this.reserva,
    required this.onPagada,
    required this.onPagarDespues,
  });

  @override
  State<PagoReservaWidget> createState() => _PagoReservaWidgetState();
}

class _PagoReservaWidgetState extends State<PagoReservaWidget> {
  static const Color _textoNaranja = Color(0xFF8A4B00);
  static const Color _fondoNaranja = Color(0xFFFFF3E0);

  late final ReservationService _service;
  String _tipoPago = 'ANTICIPO';
  bool _tarjetaCompleta = false;
  bool _pagando = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _service = ReservationService(apiClient: context.read<ApiClient>());
    final opciones = _opciones;
    if (opciones.isNotEmpty && !opciones.any((o) => o['tipo'] == 'ANTICIPO')) {
      _tipoPago = '${opciones.first['tipo']}';
    }
  }

  List<Map> get _opciones =>
      ((widget.reserva['opciones_pago'] ?? []) as List<dynamic>).whereType<Map>().toList();

  double get _montoElegido {
    for (final o in _opciones) {
      if (o['tipo'] == _tipoPago) return montoReserva(o['monto']);
    }
    return 0;
  }

  double get _saldoAlRetirar =>
      math.max(montoReserva(widget.reserva['monto_total']) - _montoElegido, 0);

  String _etiqueta(Map opcion) => opcion['tipo'] == 'TOTAL'
      ? 'Pagar el total'
      : 'Pagar el anticipo (${porcentajeReserva(opcion['porcentaje'])}%)';

  String _extraerError(Object e, String fallback) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map && data['error'] != null) return data['error'].toString();
      if (data is Map && data['detail'] != null) return data['detail'].toString();
    } catch (_) {}
    return fallback;
  }

  Future<void> _pagar() async {
    if (_pagando || !_tarjetaCompleta || _opciones.isEmpty) return;
    final id = widget.reserva['id_reserva'] as int;
    setState(() {
      _pagando = true;
      _error = null;
    });

    // 1. El backend crea el cobro en Stripe por el monto elegido.
    Map<String, dynamic> pago;
    try {
      final data = await _service.iniciarPago(id, _tipoPago);
      pago = Map<String, dynamic>.from(data['pago'] as Map);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _extraerError(e, 'No se pudo iniciar el pago. Intenta nuevamente.');
        _pagando = false;
      });
      return;
    }

    // 2. Stripe confirma la tarjeta.
    try {
      await Stripe.instance.confirmPayment(
        paymentIntentClientSecret: '${pago['client_secret']}',
        data: const PaymentMethodParams.card(
          paymentMethodData: PaymentMethodData(),
        ),
      );
    } on StripeException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.error.localizedMessage ?? 'La tarjeta fue rechazada.';
        _pagando = false;
      });
      return;
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'La tarjeta fue rechazada.';
        _pagando = false;
      });
      return;
    }

    // 3. El backend confirma la reserva y aparta las prendas.
    try {
      final reserva = await _service.pagar(id, '${pago['referencia_pago']}');
      if (!mounted) return;
      setState(() => _pagando = false);
      widget.onPagada(reserva);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _extraerError(
          e,
          'El pago se hizo, pero no se pudo confirmar la reserva. Revisa "Mis reservas".',
        );
        _pagando = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final reserva = widget.reserva;
    final limite = fechaReservaLocal(reserva['fecha_limite_pago']);
    final opciones = _opciones;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.greyLight),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Pagar la Reserva #${reserva['id_reserva']}',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          if (limite != null) ...[
            const SizedBox(height: 6),
            Align(
              alignment: Alignment.centerLeft,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                decoration: BoxDecoration(
                  color: _fondoNaranja,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  'Paga antes de las ${DateFormat('HH:mm').format(limite)} '
                  'del ${DateFormat('dd/MM/yyyy').format(limite)}',
                  style: const TextStyle(fontSize: 12, color: _textoNaranja),
                ),
              ),
            ),
          ],
          const SizedBox(height: 10),
          Text.rich(
            TextSpan(
              text: 'Total de las prendas: ',
              children: [
                TextSpan(
                  text: 'Bs ${bsReserva(reserva['monto_total'])}',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          for (final o in opciones)
            Container(
              margin: const EdgeInsets.only(bottom: 6),
              decoration: BoxDecoration(
                color: _tipoPago == o['tipo'] ? const Color(0xFFF5F5FA) : Colors.white,
                border: Border.all(
                  color: _tipoPago == o['tipo'] ? AppColors.secondary : AppColors.greyLight,
                ),
                borderRadius: BorderRadius.circular(6),
              ),
              child: ListTile(
                dense: true,
                contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                leading: Radio<String>(
                  value: '${o['tipo']}',
                  groupValue: _tipoPago,
                  onChanged: _pagando ? null : (v) => setState(() => _tipoPago = v ?? _tipoPago),
                ),
                title: Text(_etiqueta(o)),
                trailing: Text(
                  'Bs ${bsReserva(o['monto'])}',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                onTap: _pagando ? null : () => setState(() => _tipoPago = '${o['tipo']}'),
              ),
            ),
          if (_saldoAlRetirar > 0) ...[
            const SizedBox(height: 4),
            Text(
              'El saldo de Bs ${_saldoAlRetirar.toStringAsFixed(2)} se paga al retirar en la tienda '
              'o en el checkout del delivery.',
              style: const TextStyle(fontSize: 13, color: AppColors.grey),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            'La prenda se aparta recién cuando se confirma el pago. Si no la retiras dentro de la '
            'semana siguiente a la fecha reservada, o si cancelas la reserva, se te devuelve lo '
            'pagado menos el ${reserva['porcentaje_retencion']}% del total.',
            style: const TextStyle(fontSize: 13, color: AppColors.grey),
          ),
          const SizedBox(height: 14),
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
            'Tarjeta de prueba: 4242 4242 4242 4242, cualquier fecha futura y CVC.',
            style: TextStyle(fontSize: 12, color: AppColors.grey),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppColors.dangerBg,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(_error!, style: const TextStyle(fontSize: 13, color: AppColors.danger)),
            ),
          ],
          const SizedBox(height: 12),
          ElevatedButton(
            onPressed: (_pagando || opciones.isEmpty || !_tarjetaCompleta) ? null : _pagar,
            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
            child: Text(_pagando
                ? 'Procesando pago...'
                : 'Pagar Bs ${_montoElegido.toStringAsFixed(2)}'),
          ),
          TextButton(
            onPressed: _pagando ? null : widget.onPagarDespues,
            child: const Text('Pagar después'),
          ),
        ],
      ),
    );
  }
}