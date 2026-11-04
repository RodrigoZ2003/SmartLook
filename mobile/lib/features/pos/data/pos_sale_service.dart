// mobile/lib/features/pos/data/pos_sale_service.dart
//
// MODIFICADO (Fase 2 - CU08, igual que web pos-sale.service.ts): cliente
// opcional en la venta en línea e historial / resolución de las operaciones
// hechas sin conexión.
// MODIFICADO (Fase 2 - reservas con anticipo): las prendas de una reserva
// confirmada se cobran con "id_reserva_item" (solo el saldo) y se listan las
// reservas confirmadas de la sucursal para retirarlas en caja.

import '../../../core/network/api_client.dart';

class PosSaleService {
  final ApiClient apiClient;

  PosSaleService({required this.apiClient});

  /// Cada ítem lleva {id_variante, cantidad} o {id_reserva_item, cantidad: 1}.
  Future<Map<String, dynamic>> registrarVenta({
    required int idSucursal,
    required String metodoPago,
    required List<Map<String, dynamic>> items,
    String? correoCliente,
  }) async {
    final response = await apiClient.dio.post(
      '/sales/ventas-pos/registrar/',
      data: {
        'id_sucursal': idSucursal,
        'metodo_pago': metodoPago,
        'items': items,
        if (correoCliente != null && correoCliente.isNotEmpty) 'correo_cliente': correoCliente,
      },
    );
    return response.data as Map<String, dynamic>;
  }

  /// NUEVO (Fase 2): reservas pagadas (confirmadas) de la sucursal, listas para retirar.
  /// Al listar, el backend también vence las reservas cuyo plazo pasó.
  Future<List<dynamic>> reservasPorRetirar(int idSucursal) async {
    final response = await apiClient.dio.get(
      '/reservations/reservas/',
      queryParameters: {'estado': 'CONFIRMADA', 'sucursal': idSucursal, 'page_size': 100},
    );
    final data = response.data;
    return (data is Map ? (data['results'] ?? []) : data) as List<dynamic>;
  }

  /// CU08: historial de operaciones sin conexión (paginado, con filtros).
  Future<Map<String, dynamic>> listarOperaciones(Map<String, dynamic> filtros) async {
    final params = <String, dynamic>{};
    filtros.forEach((clave, valor) {
      if (valor != null && '$valor'.isNotEmpty) params[clave] = valor;
    });
    final response = await apiClient.dio.get('/sales/sync/', queryParameters: params);
    final data = response.data;
    if (data is Map) return Map<String, dynamic>.from(data);
    return {'results': data, 'count': (data as List).length};
  }

  /// CU08: cantidades por estado y conflictos pendientes de resolver.
  Future<Map<String, dynamic>> resumenOperaciones({String? empresa}) async {
    final response = await apiClient.dio.get(
      '/sales/sync/resumen/',
      queryParameters: {if (empresa != null && empresa.isNotEmpty) 'empresa': empresa},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// CU08: confirma la venta en conflicto (CONFIRMAR) o devuelve el efectivo (DEVOLVER).
  Future<Map<String, dynamic>> resolverOperacion(int idOperacion, String accion, String? nota) async {
    final response = await apiClient.dio.post(
      '/sales/sync/$idOperacion/resolver/',
      data: {'accion': accion, 'nota': nota},
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Empresas (solo SUPER_ADMIN las necesita para filtrar).
  Future<List<dynamic>> listarEmpresas() async {
    final response = await apiClient.dio.get('/auth/empresas/', queryParameters: {'page_size': 100});
    final data = response.data;
    return (data is Map ? (data['results'] ?? []) : data) as List<dynamic>;
  }

  /// Sucursales visibles para el usuario (el SUPER_ADMIN puede filtrar por empresa).
  Future<List<dynamic>> listarSucursales({String? empresa}) async {
    final response = await apiClient.dio.get(
      '/catalog/sucursales/',
      queryParameters: {'page_size': 100, if (empresa != null && empresa.isNotEmpty) 'empresa': empresa},
    );
    final data = response.data;
    return (data is Map ? (data['results'] ?? []) : data) as List<dynamic>;
  }
}