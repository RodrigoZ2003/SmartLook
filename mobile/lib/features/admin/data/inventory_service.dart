// mobile/lib/features/admin/data/inventory_service.dart
//
// Consume /api/inventory/stock/, /api/inventory/movimientos/ y
// /api/inventory/movimientos/registrar/, además de /api/catalog/sucursales/
// y /api/catalog/variantes/ para selectores.
// NUEVO (CU16): getVariantes() acepta un parámetro opcional de búsqueda
// (código o nombre) para el mostrador de caja.
// MODIFICADO (corrección listas incompletas): la API devuelve las listas por
// páginas (20 por defecto) y antes solo se leía la primera, así que las
// prendas nuevas no aparecían en los selectores. Ahora se leen todas las
// páginas.

import '../../../core/network/api_client.dart';

class InventoryService {
  final ApiClient apiClient;

  InventoryService({required this.apiClient});

  /// NUEVO: pide todas las páginas de una lista y las devuelve juntas. Si la
  /// respuesta no viene paginada, la devuelve tal cual.
  Future<List<dynamic>> _todasLasPaginas(String ruta, [Map<String, dynamic>? filtros]) async {
    final todas = <dynamic>[];
    var pagina = 1;
    while (true) {
      final response = await apiClient.dio.get(
        ruta,
        queryParameters: {...?filtros, 'page_size': 100, 'page': pagina},
      );
      final data = response.data;
      if (data is List) {
        todas.addAll(data);
        break;
      }
      todas.addAll((data['results'] ?? []) as List<dynamic>);
      if (data['next'] == null) break;
      pagina++;
    }
    return todas;
  }

  Future<List<dynamic>> getStock() => _todasLasPaginas('/inventory/stock/');

  Future<List<dynamic>> getMovimientos() => _todasLasPaginas('/inventory/movimientos/');

  Future<List<dynamic>> getSucursales() => _todasLasPaginas('/catalog/sucursales/');

  Future<List<dynamic>> getVariantes({String? busqueda}) => _todasLasPaginas(
        '/catalog/variantes/',
        busqueda != null && busqueda.isNotEmpty ? {'busqueda': busqueda} : null,
      );

  Future<void> registrarMovimiento({
    required int idSucursal,
    required int idVariante,
    required String tipoMovimiento,
    required int cantidad,
    String? motivo,
  }) async {
    await apiClient.dio.post(
      '/inventory/movimientos/registrar/',
      data: {
        'id_sucursal': idSucursal,
        'id_variante': idVariante,
        'tipo_movimiento': tipoMovimiento,
        'cantidad': cantidad,
        'motivo': motivo,
      },
    );
  }
}