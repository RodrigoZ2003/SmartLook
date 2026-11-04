// mobile/lib/core/notificaciones/notificaciones_service.dart
//
// NUEVO (Fase 2 - CU16, igual que web/src/app/core/services/notificaciones.service.ts):
// centro de notificaciones. Sin push ni Firebase: mientras la pantalla que lo
// crea está abierta, consulta el contador cada minuto si el teléfono tiene red.
// Lo usan el cliente (pestaña "Avisos") y SUPER_ADMIN / ADMIN_EMPRESA (campana
// del panel). Cajero, encargado y repartidor no lo usan.

import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';

import '../network/api_client.dart';
import '../offline/conexion.dart';

class NotificacionesService extends ChangeNotifier {
  static const Duration _intervalo = Duration(minutes: 1);

  final ApiClient apiClient;
  Timer? _timer;
  int _noLeidas = 0;

  NotificacionesService({required this.apiClient});

  /// Cantidad de avisos sin leer (lo que muestra la campana).
  int get noLeidas => _noLeidas;

  /// Empieza a consultar el contador (al abrir la pantalla) y cada minuto.
  void iniciar() {
    actualizarContador();
    _timer?.cancel();
    _timer = Timer.periodic(_intervalo, (_) => actualizarContador());
  }

  /// Consulta el contador solo si hay red; un fallo no se muestra al usuario.
  /// El backend también genera aquí los recordatorios de reservas por vencer.
  Future<void> actualizarContador() async {
    try {
      final estado = await Connectivity().checkConnectivity();
      if (!tieneRed(estado)) return;
      final response = await apiClient.dio.get('/auth/notificaciones/contador/');
      final valor = (response.data as Map)['no_leidas'];
      final n = valor is int ? valor : int.tryParse('$valor') ?? 0;
      if (n != _noLeidas) {
        _noLeidas = n;
        notifyListeners();
      }
    } catch (_) {}
  }

  /// Últimos avisos del usuario, del más reciente al más antiguo.
  Future<List<Map<String, dynamic>>> listar() async {
    final response = await apiClient.dio.get(
      '/auth/notificaciones/',
      queryParameters: {'page_size': 20},
    );
    final data = response.data;
    final lista = (data is Map ? (data['results'] ?? []) : data) as List<dynamic>;
    return lista.map((n) => Map<String, dynamic>.from(n as Map)).toList();
  }

  /// Marca un aviso como leído.
  Future<void> leer(int id) async {
    await apiClient.dio.post('/auth/notificaciones/$id/leer/');
    if (_noLeidas > 0) {
      _noLeidas--;
      notifyListeners();
    }
    actualizarContador();
  }

  /// Marca todos los avisos como leídos.
  Future<void> leerTodas() async {
    await apiClient.dio.post('/auth/notificaciones/leer-todas/');
    _noLeidas = 0;
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}