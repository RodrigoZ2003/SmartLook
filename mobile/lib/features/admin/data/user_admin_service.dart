// mobile/lib/features/admin/data/user_admin_service.dart
//
// Gestión de usuarios, roles, permisos, bitácora y clientes.
// MODIFICADO: getUsuarios() y getClientes() traen TODAS las páginas del
// backend (antes solo la primera, de 20: los usuarios nuevos no aparecían).

import '../../../core/network/api_client.dart';

class UserAdminService {
  static const int _tamanoPagina = 100;

  final ApiClient apiClient;

  UserAdminService({required this.apiClient});

  /// Pide la página 1 y sigue con la 2, 3... mientras el backend indique que hay más.
  Future<List<dynamic>> _todasLasPaginas(String ruta, {Map<String, dynamic>? params}) async {
    final todos = <dynamic>[];
    var pagina = 1;
    while (true) {
      final response = await apiClient.dio.get(
        ruta,
        queryParameters: {...?params, 'page_size': _tamanoPagina, 'page': pagina},
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

  Future<List<dynamic>> getUsuarios() async {
    return _todasLasPaginas('/auth/usuarios/');
  }

  Future<List<dynamic>> getRoles() async {
    final response = await apiClient.dio.get('/auth/roles/');
    final data = response.data;
    return (data['results'] ?? data) as List<dynamic>;
  }

  Future<void> crearUsuario(Map<String, dynamic> datos) async {
    await apiClient.dio.post('/auth/usuarios/', data: datos);
  }

  Future<void> actualizarUsuario(int id, Map<String, dynamic> datos) async {
    await apiClient.dio.patch('/auth/usuarios/$id/', data: datos);
  }

  Future<void> eliminarUsuario(int id) async {
    await apiClient.dio.delete('/auth/usuarios/$id/');
  }

  Future<List<dynamic>> getPermisos() async {
    final response = await apiClient.dio.get('/auth/permisos/');
    final data = response.data;
    return (data['results'] ?? data) as List<dynamic>;
  }

  Future<List<int>> getRolPermisos(int idRol) async {
    final response = await apiClient.dio.get('/auth/roles/$idRol/permisos/');
    return List<int>.from(response.data['permisos'] ?? []);
  }

  Future<void> actualizarRolPermisos(int idRol, List<int> permisos) async {
    await apiClient.dio.put(
      '/auth/roles/$idRol/permisos/',
      data: {'permisos': permisos},
    );
  }

  Future<List<dynamic>> getBitacora() async {
    final response = await apiClient.dio.get('/auth/bitacora/');
    final data = response.data;
    return (data['results'] ?? data) as List<dynamic>;
  }

  Future<List<dynamic>> getClientes() async {
    return _todasLasPaginas('/auth/usuarios/', params: {'rol': 'CLIENTE'});
  }
}