// mobile/lib/features/cambios/data/cambios_service.dart
//
// NUEVO (Fase 2 - CU05 / CU06, igual que web/src/app/core/services/cambios.service.ts):
// cambio de prenda por talla o color. Lo usan el cliente (Mis pedidos), el
// personal (Cambios de prenda) y el repartidor (Entregas > Cambios).

import '../../../core/network/api_client.dart';

class CambiosService {
  final ApiClient apiClient;

  CambiosService({required this.apiClient});

  List<Map<String, dynamic>> _lista(dynamic data) {
    final lista = (data is Map ? (data['results'] ?? []) : data) as List<dynamic>;
    return lista.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  /// Cambios visibles para el usuario (filtros: estado, modalidad, motivo, sucursal, mes, pendientes).
  Future<List<Map<String, dynamic>>> listar(Map<String, dynamic> filtros) async {
    final params = <String, dynamic>{};
    filtros.forEach((k, v) {
      if (v != null && '$v'.isNotEmpty) params[k] = v;
    });
    final response = await apiClient.dio.get('/sales/cambios/', queryParameters: params);
    return _lista(response.data);
  }

  /// CU06: totales de los cambios del mes (AAAA-MM).
  Future<Map<String, dynamic>> resumenMes(String mes) async {
    final response = await apiClient.dio.get('/sales/cambios/resumen-mes/', queryParameters: {'mes': mes});
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Prendas de una venta POS o de un pedido de la empresa (personal).
  Future<Map<String, dynamic>> buscarCompra(String tipo, int numero) async {
    final response = await apiClient.dio.get(
      '/sales/cambios/buscar-compra/',
      queryParameters: {'tipo': tipo, 'numero': numero},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Tallas/colores disponibles para cambiar una prenda y si se puede cambiar.
  Future<Map<String, dynamic>> opciones({int? idVentaItem, int? idOrdenItem}) async {
    final response = await apiClient.dio.get(
      '/sales/cambios/opciones/',
      queryParameters: {
        if (idVentaItem != null) 'id_venta_item': idVentaItem,
        if (idOrdenItem != null) 'id_orden_item': idOrdenItem,
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// El cliente solicita el cambio de una prenda de su pedido con delivery.
  Future<Map<String, dynamic>> solicitar({
    required int idOrdenItem,
    required String motivo,
    required int idVariante,
    required int cantidad,
    String? observacion,
  }) async {
    final response = await apiClient.dio.post(
      '/sales/cambios/solicitar/',
      data: {
        'id_orden_item': idOrdenItem,
        'motivo': motivo,
        'id_variante': idVariante,
        'cantidad': cantidad,
        if (observacion != null && observacion.isNotEmpty) 'observacion': observacion,
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// El personal registra y completa un cambio en la tienda.
  Future<Map<String, dynamic>> registrarTienda({
    int? idVentaItem,
    int? idOrdenItem,
    required String motivo,
    required int idVariante,
    required int cantidad,
    String? observacion,
  }) async {
    final response = await apiClient.dio.post(
      '/sales/cambios/registrar-tienda/',
      data: {
        'id_venta_item': idVentaItem,
        'id_orden_item': idOrdenItem,
        'motivo': motivo,
        'id_variante': idVariante,
        'cantidad': cantidad,
        'condiciones_ok': true,
        if (observacion != null && observacion.isNotEmpty) 'observacion': observacion,
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> aprobar(int idCambio, int idRepartidor, DateTime fechaProgramada) async {
    final response = await apiClient.dio.post(
      '/sales/cambios/$idCambio/aprobar/',
      data: {
        'id_repartidor': idRepartidor,
        'fecha_programada': fechaProgramada.toUtc().toIso8601String(),
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> rechazar(int idCambio, String motivo) async {
    final response = await apiClient.dio.post('/sales/cambios/$idCambio/rechazar/', data: {'motivo': motivo});
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> enCamino(int idCambio) async {
    final response = await apiClient.dio.post('/sales/cambios/$idCambio/en-camino/');
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> completar(int idCambio, bool condicionesOk) async {
    final response = await apiClient.dio.post(
      '/sales/cambios/$idCambio/completar/',
      data: {'condiciones_ok': condicionesOk},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Repartidores activos de la empresa (para asignar la visita).
  Future<List<Map<String, dynamic>>> repartidores() async {
    final response = await apiClient.dio.get('/sales/entregas/repartidores/');
    return _lista(response.data);
  }

  /// Texto del error que manda el backend.
  static String textoError(Object e, String fallback) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map && data['error'] != null) return data['error'].toString();
      if (data is Map && data['detail'] != null) return data['detail'].toString();
    } catch (_) {}
    return fallback;
  }
}