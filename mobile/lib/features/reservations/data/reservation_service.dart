// mobile/lib/features/reservations/data/reservation_service.dart
//
// Consume /api/reservations/reservas/ (CU11 crear, CU12/CU13 listar,
// cancelar, confirmar y completar).
// MODIFICADO (Fase 2 - reservas con anticipo, igual que la web): la reserva
// se crea "Pendiente de pago" (3 horas para pagarla), se paga con Stripe
// (anticipo o total) y al cancelarla se devuelve lo pagado menos el 10%
// del total (CU17).

import '../../../core/network/api_client.dart';

class ReservationService {
  final ApiClient apiClient;

  ReservationService({required this.apiClient});

  /// Crea la reserva "Pendiente de pago" (3 horas para pagarla).
  Future<Map<String, dynamic>> crearReserva({
    required int idSucursal,
    required String fechaReserva,
    required String horaReserva,
    required List<int> variantesIds,
  }) async {
    final response = await apiClient.dio.post(
      '/reservations/reservas/',
      data: {
        'id_sucursal': idSucursal,
        'fecha_reserva': fechaReserva,
        'hora_reserva': horaReserva,
        'items': variantesIds.map((id) => {'id_variante': id}).toList(),
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// El backend vence antes de listar las reservas cuyo plazo pasó.
  Future<List<dynamic>> getReservas({String? estado, int? idSucursal}) async {
    final params = <String, dynamic>{};
    if (estado != null) params['estado'] = estado;
    if (idSucursal != null) params['sucursal'] = idSucursal;
    final response = await apiClient.dio.get(
      '/reservations/reservas/',
      queryParameters: params.isEmpty ? null : params,
    );
    final data = response.data;
    return (data is Map ? (data['results'] ?? []) : data) as List<dynamic>;
  }

  /// Crea el cobro en Stripe por el anticipo o el total.
  /// Devuelve {reserva, pago: {client_secret, referencia_pago, monto}}.
  Future<Map<String, dynamic>> iniciarPago(int id, String tipoPago) async {
    final response = await apiClient.dio.post(
      '/reservations/reservas/$id/iniciar-pago/',
      data: {'tipo_pago': tipoPago},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Confirma el pago hecho en Stripe: la reserva queda CONFIRMADA y la prenda apartada.
  Future<Map<String, dynamic>> pagar(int id, String referenciaPago) async {
    final response = await apiClient.dio.post(
      '/reservations/reservas/$id/pagar/',
      data: {'referencia_pago': referenciaPago},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// CU17: si está pagada, se devuelve lo pagado menos el 10% del total.
  Future<Map<String, dynamic>> cancelarReserva(int id, {String motivo = ''}) async {
    final response = await apiClient.dio.post(
      '/reservations/reservas/$id/cancelar/',
      data: {'motivo': motivo},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> confirmarReserva(int id) async {
    final response = await apiClient.dio.post('/reservations/reservas/$id/confirmar/');
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> completarReserva(int id) async {
    final response = await apiClient.dio.post('/reservations/reservas/$id/completar/');
    return Map<String, dynamic>.from(response.data as Map);
  }
}