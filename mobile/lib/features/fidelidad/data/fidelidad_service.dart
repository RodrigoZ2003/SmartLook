// mobile/lib/features/fidelidad/data/fidelidad_service.dart
//
// NUEVO (Fase 3 - CU18, igual que web/src/app/core/services/fidelidad.service.ts):
// descuento por fidelidad, solo lado cliente.
//   GET /fidelidad/mi-progreso/[?id_empresa=]  progreso del mes por tienda
// Lo usan el carrito (tienda elegida) y Mis pedidos (todas las tiendas).
// El checkout no cambia: el backend vuelve a calcular el descuento al cobrar.

import 'package:intl/intl.dart';

import '../../../core/network/api_client.dart';

class FidelidadService {
  final ApiClient apiClient;

  FidelidadService({required this.apiClient});

  /// Progreso del mes: {mes, vence, regla{compras_requeridas, porcentaje, activa},
  /// empresas[{id_empresa, empresa, compras, requeridas, faltan, estado,
  /// estado_display, disponible, porcentaje, uso, monto_descuento, fecha_uso}]}.
  /// Con [idEmpresa] devuelve solo esa tienda (para el carrito).
  Future<Map<String, dynamic>> miProgreso({int? idEmpresa}) async {
    final response = await apiClient.dio.get(
      '/fidelidad/mi-progreso/',
      queryParameters: idEmpresa != null ? {'id_empresa': idEmpresa} : null,
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  /// Fila de una tienda dentro de la respuesta de [miProgreso] (o null).
  static Map<String, dynamic>? filaDeEmpresa(Map<String, dynamic> datos, int idEmpresa) {
    final empresas = (datos['empresas'] ?? []) as List<dynamic>;
    for (final e in empresas) {
      final fila = Map<String, dynamic>.from(e as Map);
      if (fila['id_empresa'] == idEmpresa) return fila;
    }
    return null;
  }

  /// Lista de tiendas de la respuesta de [miProgreso].
  static List<Map<String, dynamic>> empresas(Map<String, dynamic> datos) {
    final lista = (datos['empresas'] ?? []) as List<dynamic>;
    return lista.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  /// Número del JSON como double (acepta int, double o texto).
  static double numero(dynamic valor) => double.tryParse('${valor ?? ''}') ?? 0;

  /// Porcentaje como en la web: 50.0 -> "50", 12.5 -> "12.5".
  static String porcentajeTexto(dynamic valor) {
    final p = numero(valor);
    return p == p.roundToDouble() ? p.toStringAsFixed(0) : '$p';
  }

  /// Mismo cálculo que la web: round(prendas x porcentaje) / 100.
  /// El envío no se descuenta.
  static double descuentoSobre(double prendas, dynamic porcentaje) {
    return (prendas * numero(porcentaje)).round() / 100;
  }

  /// Avance de la barra entre 0 y 1 (compras / requeridas, máximo 1).
  static double avance(dynamic compras, dynamic requeridas) {
    final req = numero(requeridas);
    final valor = numero(compras) / (req < 1 ? 1 : req);
    return valor > 1 ? 1 : valor;
  }

  /// "AAAA-MM-DD" (fecha sin hora, ya en hora de Bolivia) -> "dd/MM/yyyy".
  static String fecha(dynamic valor) {
    final dt = DateTime.tryParse('${valor ?? ''}');
    return dt == null ? '' : DateFormat('dd/MM/yyyy').format(dt);
  }
}