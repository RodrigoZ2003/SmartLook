// mobile/lib/features/admin/data/product_admin_service.dart
//
// Archivo YA EXISTENTE. Se agrega CRUD de variantes (Paso C).
// MODIFICADO (corrección listas incompletas): getProductos() lee todas las
// páginas de la API (antes solo la primera, 20 productos).

import '../../../core/network/api_client.dart';

class ProductAdminService {
  final ApiClient apiClient;

  ProductAdminService({required this.apiClient});

  Future<List<dynamic>> getProductos() async {
    final todos = <dynamic>[];
    var pagina = 1;
    while (true) {
      final response = await apiClient.dio.get(
        '/catalog/productos/',
        queryParameters: {'page_size': 100, 'page': pagina},
      );
      final data = response.data;
      if (data is List) {
        todos.addAll(data);
        break;
      }
      todos.addAll((data['results'] ?? []) as List<dynamic>);
      if (data['next'] == null) break;
      pagina++;
    }
    return todos;
  }

  Future<void> crearProducto(Map<String, dynamic> datos) async {
    await apiClient.dio.post('/catalog/productos/', data: datos);
  }

  Future<void> actualizarProducto(int id, Map<String, dynamic> datos) async {
    await apiClient.dio.patch('/catalog/productos/$id/', data: datos);
  }

  Future<void> eliminarProducto(int id) async {
    await apiClient.dio.delete('/catalog/productos/$id/');
  }

  Future<void> crearVariante(Map<String, dynamic> datos) async {
    await apiClient.dio.post('/catalog/variantes/', data: datos);
  }

  Future<void> actualizarVariante(int id, Map<String, dynamic> datos) async {
    await apiClient.dio.patch('/catalog/variantes/$id/', data: datos);
  }

  Future<void> eliminarVariante(int id) async {
    await apiClient.dio.delete('/catalog/variantes/$id/');
  }
}