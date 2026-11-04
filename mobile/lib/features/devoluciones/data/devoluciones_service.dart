// mobile/lib/features/devoluciones/data/devoluciones_service.dart
//
// NUEVO (Fase 2 - CU12, igual que web/src/app/core/services/devoluciones.service.ts):
// devolución de prendas con reembolso y nota de devolución. Lo usan el
// personal (Devoluciones) y el repartidor (Entregas > Devoluciones).

import '../../../core/network/api_client.dart';

/// Motivos de devolución (los mismos textos del backend y la web).
const List<Map<String, String>> motivosDevolucionTienda = [
  {'valor': 'PRODUCTO_DANADO', 'texto': 'Llegó dañada o con defecto'},
  {'valor': 'ERROR_TIENDA', 'texto': 'Le llegó otra prenda'},
  {'valor': 'NO_LA_QUIERO', 'texto': 'Ya no la quiere / no le gustó'},
];

class DevolucionesService {
  final ApiClient apiClient;

  DevolucionesService({required this.apiClient});

  List<Map<String, dynamic>> _lista(dynamic data) {
    final lista = (data is Map ? (data['results'] ?? []) : data) as List<dynamic>;
    return lista.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  /// Devoluciones visibles para el usuario (filtros: estado, modalidad, sucursal, mes, pendientes).
  Future<List<Map<String, dynamic>>> listar(Map<String, dynamic> filtros) async {
    final params = <String, dynamic>{};
    filtros.forEach((k, v) {
      if (v != null && '$v'.isNotEmpty) params[k] = v;
    });
    final response = await apiClient.dio.get('/sales/devoluciones/', queryParameters: params);
    return _lista(response.data);
  }

  /// Prendas de una venta POS o de un pedido con lo que se puede devolver de cada una.
  Future<Map<String, dynamic>> buscarCompra(String tipo, int numero) async {
    final response = await apiClient.dio.get(
      '/sales/devoluciones/buscar-compra/',
      queryParameters: {'tipo': tipo, 'numero': numero},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Montos de la devolución sin guardarla.
  Future<Map<String, dynamic>> calcular(String tipo, int numero, List<Map<String, dynamic>> items) async {
    final response = await apiClient.dio.post(
      '/sales/devoluciones/calcular/',
      data: {'tipo': tipo, 'numero': numero, 'items': items},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// El personal registra y completa la devolución en la tienda.
  Future<Map<String, dynamic>> registrarTienda({
    required String tipo,
    required int numero,
    required List<Map<String, dynamic>> items,
    String? observacion,
  }) async {
    final response = await apiClient.dio.post(
      '/sales/devoluciones/registrar-tienda/',
      data: {
        'tipo': tipo,
        'numero': numero,
        'items': items,
        'condiciones_ok': true,
        if (observacion != null && observacion.isNotEmpty) 'observacion': observacion,
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> aprobar(int id, int idRepartidor, DateTime fechaProgramada) async {
    final response = await apiClient.dio.post(
      '/sales/devoluciones/$id/aprobar/',
      data: {
        'id_repartidor': idRepartidor,
        'fecha_programada': fechaProgramada.toUtc().toIso8601String(),
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> rechazar(int id, String motivo) async {
    final response = await apiClient.dio.post('/sales/devoluciones/$id/rechazar/', data: {'motivo': motivo});
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> enCamino(int id) async {
    final response = await apiClient.dio.post('/sales/devoluciones/$id/en-camino/');
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> completar(int id, bool condicionesOk) async {
    final response = await apiClient.dio.post(
      '/sales/devoluciones/$id/completar/',
      data: {'condiciones_ok': condicionesOk},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Repartidores activos de la empresa (para asignar el recojo).
  Future<List<Map<String, dynamic>>> repartidores() async {
    final response = await apiClient.dio.get('/sales/entregas/repartidores/');
    return _lista(response.data);
  }

  static String textoError(Object e, String fallback) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map && data['error'] != null) return data['error'].toString();
      if (data is Map && data['detail'] != null) return data['detail'].toString();
    } catch (_) {}
    return fallback;
  }
}