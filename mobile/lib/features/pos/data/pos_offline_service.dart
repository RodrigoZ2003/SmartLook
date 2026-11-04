// mobile/lib/features/pos/data/pos_offline_service.dart
//
// NUEVO (SaaS - 6.2/6.4): POS sin conexión en el móvil (SQLite).
// - Cola local de ventas hechas sin internet, cada una con UUID propio,
//   empresa, sucursal, usuario y la hora en que se hizo.
// - Estados de cada venta local (igual que la web):
//     REGISTRADA    guardada en el teléfono, aún no enviada.
//     ENVIADA       enviada al servidor, esperando respuesta.
//     CONFIRMADA    el servidor la registró (queda con su número de venta).
//     EN_CONFLICTO  el servidor la registró, pero con precio distinto o sin
//                   stock: la revisa el encargado o el administrador (CU08).
//     RECHAZADA     el servidor no la aceptó (queda con el motivo).
//   Una venta nunca se borra por haberse intentado enviar: si el envío
//   falla vuelve a REGISTRADA (el UUID evita duplicados al reenviarla).
// - Copia local del catálogo y de las sucursales con la fecha de descarga.
// - Stock local: al guardar una venta se resta; al descartar una rechazada
//   se devuelve; al volver a descargar se restan las ventas sin enviar.
// - Se sincroniza al recuperar la red, al abrir el POS y con "Sincronizar
//   ahora"; si hay red pero el servidor no responde, reintenta cada 20 s.
// MODIFICADO (Fase 2 - CU08, igual que la web): cada venta envía el precio
// cobrado sin conexión y el correo del cliente (opcional). En SQLite la venta
// en conflicto se guarda CONFIRMADA (el servidor la registró) con
// en_conflicto = 1, y se muestra como EN_CONFLICTO.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../../../core/offline/offline_db.dart';
import '../../../core/services/auth_service.dart';

class EstadoVentaLocal {
  static const String registrada = 'REGISTRADA';
  static const String enviada = 'ENVIADA';
  static const String confirmada = 'CONFIRMADA';
  static const String enConflicto = 'EN_CONFLICTO';
  static const String rechazada = 'RECHAZADA';
}

class ItemVentaLocal {
  final int idVariante;
  final String nombre;
  final double precio;
  final int cantidad;

  const ItemVentaLocal({
    required this.idVariante,
    required this.nombre,
    required this.precio,
    required this.cantidad,
  });

  factory ItemVentaLocal.fromFila(Map<String, Object?> fila) {
    return ItemVentaLocal(
      idVariante: fila['id_variante'] as int,
      nombre: fila['nombre'] as String,
      precio: (fila['precio'] as num).toDouble(),
      cantidad: fila['cantidad'] as int,
    );
  }
}

class VentaLocal {
  final String uuid;
  final int idSucursal;
  final String sucursal;
  final String metodoPago;
  final String? correoCliente;
  final double total;
  final DateTime fechaOperacion;
  final String estado;
  final String? mensaje;
  final int intentos;
  final int? idVenta;
  final DateTime? fechaConfirmacion;
  final String? tipoConflicto;
  final List<Map<String, dynamic>> conflictos;
  final List<ItemVentaLocal> items;

  const VentaLocal({
    required this.uuid,
    required this.idSucursal,
    required this.sucursal,
    required this.metodoPago,
    required this.correoCliente,
    required this.total,
    required this.fechaOperacion,
    required this.estado,
    required this.mensaje,
    required this.intentos,
    required this.idVenta,
    required this.fechaConfirmacion,
    required this.tipoConflicto,
    required this.conflictos,
    required this.items,
  });

  factory VentaLocal.fromFila(Map<String, Object?> fila, List<ItemVentaLocal> items) {
    final enConflicto = ((fila['en_conflicto'] as int?) ?? 0) == 1;
    List<Map<String, dynamic>> conflictos = const [];
    final texto = fila['conflictos'] as String?;
    if (texto != null && texto.isNotEmpty) {
      try {
        conflictos = (jsonDecode(texto) as List)
            .map((c) => Map<String, dynamic>.from(c as Map))
            .toList();
      } catch (_) {}
    }
    final confirmacion = fila['fecha_confirmacion'] as String?;
    return VentaLocal(
      uuid: fila['uuid'] as String,
      idSucursal: fila['id_sucursal'] as int,
      sucursal: (fila['sucursal'] as String?) ?? '',
      metodoPago: fila['metodo_pago'] as String,
      correoCliente: fila['correo_cliente'] as String?,
      total: (fila['total'] as num).toDouble(),
      fechaOperacion: DateTime.parse(fila['fecha_operacion'] as String),
      estado: enConflicto ? EstadoVentaLocal.enConflicto : fila['estado'] as String,
      mensaje: fila['mensaje'] as String?,
      intentos: (fila['intentos'] as int?) ?? 0,
      idVenta: fila['id_venta'] as int?,
      fechaConfirmacion: confirmacion != null ? DateTime.tryParse(confirmacion) : null,
      tipoConflicto: fila['tipo_conflicto'] as String?,
      conflictos: conflictos,
      items: items,
    );
  }

  bool get porEnviar =>
      estado == EstadoVentaLocal.registrada || estado == EstadoVentaLocal.enviada;

  int get prendas => items.fold<int>(0, (suma, i) => suma + i.cantidad);
}

class ResultadoSync {
  int sincronizadas = 0;
  int duplicadas = 0;
  int enConflicto = 0;
  int rechazadas = 0;
  String? error;
  final DateTime fecha;

  ResultadoSync(this.fecha);
}

class PosOfflineService extends ChangeNotifier {
  static const String _tipoSync = 'VENTA_POS';
  static const String _recursoCatalogo = 'catalogo_pos';
  static const String _recursoSucursales = 'sucursales_pos';
  static const int _maxPorLote = 100;
  static const int _paginaCatalogo = 100;
  static const int _maxPaginasCatalogo = 50;
  static const Duration _intervaloReintento = Duration(seconds: 20);
  static const Duration vigenciaCatalogo = Duration(minutes: 30);

  final ApiClient _api;
  final AuthService _auth;
  final OfflineDb _db = OfflineDb.instancia;
  final Uuid _uuid = const Uuid();

  bool _enLinea = true;
  bool _hayRed = true;
  bool _sincronizando = false;
  bool _actualizandoCatalogo = false;
  bool _comprobando = false;
  List<VentaLocal> _ventas = [];
  ResultadoSync? _resultado;
  DateTime? _fechaCatalogo;
  int _totalCatalogo = 0;
  int? _usuarioCargado;
  StreamSubscription<List<ConnectivityResult>>? _subConectividad;
  Timer? _timer;

  PosOfflineService({required ApiClient api, required AuthService auth})
      : _api = api,
        _auth = auth {
    _auth.addListener(_alCambiarSesion);
    _iniciar();
  }

  // ---------------------------------------------------------------- estado
  bool get enLinea => _enLinea;
  bool get sincronizando => _sincronizando;
  bool get actualizandoCatalogo => _actualizandoCatalogo;
  List<VentaLocal> get ventas => List.unmodifiable(_ventas);
  ResultadoSync? get resultado => _resultado;
  DateTime? get fechaCatalogo => _fechaCatalogo;
  int get totalCatalogo => _totalCatalogo;
  int get pendientes => _ventas.where((v) => v.porEnviar).length;
  int get confirmadas =>
      _ventas.where((v) => v.estado == EstadoVentaLocal.confirmada).length;
  int get enConflicto =>
      _ventas.where((v) => v.estado == EstadoVentaLocal.enConflicto).length;
  int get rechazadas =>
      _ventas.where((v) => v.estado == EstadoVentaLocal.rechazada).length;

  /// Ventas que el servidor ya registró (confirmadas y en conflicto).
  int get registradasEnServidor => confirmadas + enConflicto;

  int? get _idUsuario => _auth.currentUser?.idUsuario;

  // ---------------------------------------------------------------- conexión
  Future<void> _iniciar() async {
    try {
      _hayRed = _tieneRed(await Connectivity().checkConnectivity());
      _enLinea = _hayRed;
    } catch (_) {
      // Si no se puede consultar, se asume en línea y lo corrige el primer error de red.
    }
    _subConectividad = Connectivity().onConnectivityChanged.listen((estado) {
      _hayRed = _tieneRed(estado);
      if (_hayRed) {
        _comprobarServidor();
      } else {
        _cambiarEnLinea(false);
      }
    });
    _timer = Timer.periodic(_intervaloReintento, (_) => _comprobarServidor());
    await recargar();
    sincronizar();
  }

  bool _tieneRed(List<ConnectivityResult> estado) =>
      estado.any((r) => r != ConnectivityResult.none);

  void _cambiarEnLinea(bool valor) {
    if (_enLinea == valor) return;
    _enLinea = valor;
    notifyListeners();
  }

  /// Una petición falló por red: se trata como sin conexión.
  void marcarSinConexion() => _cambiarEnLinea(false);

  /// true si el error es de red (sin respuesta del servidor).
  bool esErrorDeRed(Object error) {
    if (error is! DioException) return false;
    switch (error.type) {
      case DioExceptionType.connectionError:
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return true;
      case DioExceptionType.unknown:
        return error.error is SocketException || error.response == null;
      default:
        return false;
    }
  }

  /// Hay red pero el POS está "Sin conexión" porque el servidor no
  /// respondía: si ahora responde (con cualquier código), vuelve a "En línea".
  Future<void> _comprobarServidor() async {
    if (_enLinea || !_hayRed || _comprobando || _idUsuario == null) return;
    _comprobando = true;
    try {
      await _api.dio.get(
        '/catalog/sucursales/',
        queryParameters: {'page_size': 1},
        options: Options(receiveTimeout: const Duration(seconds: 15)),
      );
      _volverEnLinea();
    } catch (e) {
      if (!esErrorDeRed(e)) _volverEnLinea();
    } finally {
      _comprobando = false;
    }
  }

  void _volverEnLinea() {
    _cambiarEnLinea(true);
    sincronizar();
  }

  void _alCambiarSesion() {
    if (_usuarioCargado == _idUsuario) return;
    _resultado = null;
    recargar().then((_) => sincronizar());
  }

  // ---------------------------------------------------------------- lectura local
  /// Carga las ventas locales del usuario de la sesión (las más recientes
  /// primero), la fecha del catálogo y la última sincronización.
  Future<void> recargar() async {
    final id = _idUsuario;
    _usuarioCargado = id;
    if (id == null) {
      _ventas = [];
      _fechaCatalogo = null;
      _totalCatalogo = 0;
      notifyListeners();
      return;
    }
    try {
      final db = await _db.db;
      final filas = await db.query(
        'ventas_local',
        where: 'id_usuario = ?',
        whereArgs: [id],
        orderBy: 'fecha_operacion DESC',
      );
      final filasItems = await db.rawQuery(
        'SELECT i.* FROM venta_items_local i '
        'JOIN ventas_local v ON v.uuid = i.uuid_venta '
        'WHERE v.id_usuario = ? ORDER BY i.id_item',
        [id],
      );
      final itemsPorVenta = <String, List<ItemVentaLocal>>{};
      for (final fila in filasItems) {
        itemsPorVenta
            .putIfAbsent(fila['uuid_venta'] as String, () => [])
            .add(ItemVentaLocal.fromFila(fila));
      }
      _ventas = filas
          .map((f) => VentaLocal.fromFila(f, itemsPorVenta[f['uuid']] ?? const []))
          .toList();

      final meta = await db.query(
        'descargas_local',
        where: 'id_usuario = ? AND recurso = ?',
        whereArgs: [id, _recursoCatalogo],
      );
      if (meta.isNotEmpty) {
        _fechaCatalogo = DateTime.parse(meta.first['fecha'] as String);
        _totalCatalogo = meta.first['total'] as int;
      } else {
        _fechaCatalogo = null;
        _totalCatalogo = 0;
      }

      final ultimo = await db.query(
        'sync_resultados',
        where: 'id_usuario = ? AND tipo = ?',
        whereArgs: [id, _tipoSync],
        orderBy: 'fecha DESC',
        limit: 1,
      );
      if (ultimo.isNotEmpty) {
        final f = ultimo.first;
        _resultado = ResultadoSync(DateTime.parse(f['fecha'] as String))
          ..sincronizadas = f['sincronizadas'] as int
          ..duplicadas = f['duplicadas'] as int
          ..enConflicto = (f['en_conflicto'] as int?) ?? 0
          ..rechazadas = f['rechazadas'] as int
          ..error = f['error'] as String?;
      }
    } catch (_) {
      _ventas = [];
    }
    notifyListeners();
  }

  // ---------------------------------------------------------------- catálogo local
  /// Descarga el catálogo si no hay copia o tiene más de 30 minutos.
  Future<void> prepararCatalogo() async {
    final fecha = _fechaCatalogo;
    final antiguo = fecha == null || DateTime.now().difference(fecha) > vigenciaCatalogo;
    if (_enLinea && antiguo) await actualizarCatalogo();
  }

  Future<void> actualizarCatalogo() async {
    final id = _idUsuario;
    if (id == null || !_enLinea || _actualizandoCatalogo) return;
    _actualizandoCatalogo = true;
    notifyListeners();
    try {
      final variantes = <Map<String, Object?>>[];
      for (var pagina = 1; pagina <= _maxPaginasCatalogo; pagina++) {
        final response = await _api.dio.get(
          '/catalog/variantes/',
          queryParameters: {'page_size': _paginaCatalogo, 'page': pagina},
        );
        final data = response.data;
        final filas = (data is Map ? (data['results'] ?? []) : data) as List;
        for (final v in filas) {
          variantes.add({
            'id_usuario': id,
            'id_variante': v['id_variante'] as int,
            'id_producto': v['id_producto'] is int ? v['id_producto'] as int : null,
            'nombre_completo': '${v['nombre_completo'] ?? ''}',
            'codigo_producto': v['codigo_producto']?.toString(),
            'precio': double.tryParse('${v['precio']}') ?? 0,
            'cantidad': int.tryParse('${v['cantidad']}') ?? 0,
          });
        }
        if (data is! Map || data['next'] == null) break;
      }
      // Las ventas que aún no llegan al servidor todavía no bajaron su stock allá.
      final sinEnviar = _cantidadesPorVariante(
        _ventas.where((v) => v.porEnviar).expand((v) => v.items),
      );
      final ahora = DateTime.now().toUtc().toIso8601String();
      final db = await _db.db;
      await db.transaction((txn) async {
        await txn.delete('variantes_local', where: 'id_usuario = ?', whereArgs: [id]);
        final batch = txn.batch();
        for (final v in variantes) {
          final restar = sinEnviar[v['id_variante']] ?? 0;
          final cantidad = (v['cantidad'] as int) - restar;
          batch.insert(
            'variantes_local',
            {...v, 'cantidad': cantidad < 0 ? 0 : cantidad},
            conflictAlgorithm: ConflictAlgorithm.replace,
          );
        }
        batch.insert(
          'descargas_local',
          {
            'id_usuario': id,
            'recurso': _recursoCatalogo,
            'fecha': ahora,
            'total': variantes.length,
          },
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
        await batch.commit(noResult: true);
      });
      _fechaCatalogo = DateTime.parse(ahora);
      _totalCatalogo = variantes.length;
    } catch (e) {
      if (esErrorDeRed(e)) marcarSinConexion();
    } finally {
      _actualizandoCatalogo = false;
      notifyListeners();
    }
  }

  /// Busca en la copia local por nombre o código (sin importar tildes).
  /// Devuelve mapas con las mismas claves que /catalog/variantes/.
  Future<List<Map<String, dynamic>>> buscarLocal(String termino) async {
    final id = _idUsuario;
    final buscado = _normalizar(termino.trim());
    if (id == null || buscado.isEmpty) return [];
    final db = await _db.db;
    final filas = await db.query(
      'variantes_local',
      where: 'id_usuario = ?',
      whereArgs: [id],
      orderBy: 'nombre_completo',
    );
    return filas
        .where((f) =>
            _normalizar('${f['nombre_completo']}').contains(buscado) ||
            _normalizar('${f['codigo_producto'] ?? ''}').contains(buscado))
        .take(50)
        .map((f) => {
              'id_variante': f['id_variante'],
              'nombre_completo': f['nombre_completo'],
              'codigo_producto': f['codigo_producto'],
              'precio': f['precio'],
              'cantidad': f['cantidad'],
            })
        .toList();
  }

  /// Revisa la venta contra el stock local conocido. Devuelve el motivo si
  /// alguna prenda no alcanza, o null si se puede vender.
  Future<String?> validarStockLocal(List<ItemVentaLocal> items) async {
    final id = _idUsuario;
    if (id == null || _fechaCatalogo == null) return null;
    final db = await _db.db;
    final pedidas = _cantidadesPorVariante(items);
    for (final entrada in pedidas.entries) {
      final filas = await db.query(
        'variantes_local',
        where: 'id_usuario = ? AND id_variante = ?',
        whereArgs: [id, entrada.key],
      );
      if (filas.isEmpty) continue;
      final disponible = filas.first['cantidad'] as int;
      if (entrada.value > disponible) {
        return 'Stock local insuficiente para ${filas.first['nombre_completo']}: quedan $disponible.';
      }
    }
    return null;
  }

  // ---------------------------------------------------------------- sucursales locales
  Future<void> guardarSucursales(List<dynamic> sucursales) async {
    final id = _idUsuario;
    if (id == null) return;
    try {
      final db = await _db.db;
      await db.transaction((txn) async {
        await txn.delete('sucursales_local', where: 'id_usuario = ?', whereArgs: [id]);
        final batch = txn.batch();
        for (final s in sucursales) {
          batch.insert(
            'sucursales_local',
            {
              'id_usuario': id,
              'id_sucursal': s['id_sucursal'] as int,
              'id_empresa': s['id_empresa'] is int ? s['id_empresa'] as int : null,
              'nombre': '${s['nombre'] ?? ''}',
            },
            conflictAlgorithm: ConflictAlgorithm.replace,
          );
        }
        batch.insert(
          'descargas_local',
          {
            'id_usuario': id,
            'recurso': _recursoSucursales,
            'fecha': DateTime.now().toUtc().toIso8601String(),
            'total': sucursales.length,
          },
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
        await batch.commit(noResult: true);
      });
    } catch (_) {
      // Si no se pudo guardar, sin conexión se usará la copia anterior.
    }
  }

  Future<List<Map<String, dynamic>>> sucursalesLocales() async {
    final id = _idUsuario;
    if (id == null) return [];
    final db = await _db.db;
    final filas = await db.query(
      'sucursales_local',
      where: 'id_usuario = ?',
      whereArgs: [id],
      orderBy: 'nombre',
    );
    return filas
        .map((f) => {'id_sucursal': f['id_sucursal'], 'nombre': f['nombre']})
        .toList();
  }

  // ---------------------------------------------------------------- cola de ventas
  /// Guarda la venta sin conexión y resta su stock local (una transacción).
  Future<VentaLocal> guardarVenta({
    required int idSucursal,
    required String sucursal,
    required String metodoPago,
    required List<ItemVentaLocal> items,
    String? correoCliente,
  }) async {
    final usuario = _auth.currentUser;
    if (usuario == null) {
      throw StateError('No hay una sesión iniciada.');
    }
    final uuid = _uuid.v4();
    final ahora = DateTime.now().toUtc();
    final total = items.fold<double>(0, (s, i) => s + i.precio * i.cantidad);
    final correo = (correoCliente ?? '').trim().isEmpty ? null : correoCliente!.trim();
    final db = await _db.db;
    await db.transaction((txn) async {
      await txn.insert('ventas_local', {
        'uuid': uuid,
        'id_usuario': usuario.idUsuario,
        'id_empresa': usuario.idEmpresa,
        'id_sucursal': idSucursal,
        'sucursal': sucursal,
        'metodo_pago': metodoPago,
        'correo_cliente': correo,
        'total': total,
        'fecha_operacion': ahora.toIso8601String(),
        'estado': EstadoVentaLocal.registrada,
        'intentos': 0,
      });
      for (final item in items) {
        await txn.insert('venta_items_local', {
          'uuid_venta': uuid,
          'id_variante': item.idVariante,
          'nombre': item.nombre,
          'precio': item.precio,
          'cantidad': item.cantidad,
        });
      }
      await _ajustarStock(txn, usuario.idUsuario, items, -1);
    });
    await recargar();
    return VentaLocal(
      uuid: uuid,
      idSucursal: idSucursal,
      sucursal: sucursal,
      metodoPago: metodoPago,
      correoCliente: correo,
      total: total,
      fechaOperacion: ahora,
      estado: EstadoVentaLocal.registrada,
      mensaje: null,
      intentos: 0,
      idVenta: null,
      fechaConfirmacion: null,
      tipoConflicto: null,
      conflictos: const [],
      items: items,
    );
  }

  /// Solo se descartan las rechazadas, después de que el cajero leyó el
  /// motivo. Como el servidor no la registró, sus prendas vuelven al stock local.
  Future<void> descartar(VentaLocal venta) async {
    final id = _idUsuario;
    if (id == null || venta.estado != EstadoVentaLocal.rechazada) return;
    final db = await _db.db;
    await db.transaction((txn) async {
      await txn.delete('ventas_local',
          where: 'uuid = ? AND id_usuario = ?', whereArgs: [venta.uuid, id]);
      await _ajustarStock(txn, id, venta.items, 1);
    });
    await recargar();
  }

  /// Quita del teléfono el historial de ventas ya registradas por el servidor
  /// (confirmadas y en conflicto: el conflicto se resuelve en el servidor).
  Future<void> limpiarConfirmadas() async {
    final id = _idUsuario;
    if (id == null) return;
    final db = await _db.db;
    await db.delete('ventas_local',
        where: 'id_usuario = ? AND estado = ?',
        whereArgs: [id, EstadoVentaLocal.confirmada]);
    await recargar();
  }

  // signo -1 resta (venta guardada), +1 devuelve (venta descartada).
  Future<void> _ajustarStock(
    Transaction txn,
    int idUsuario,
    List<ItemVentaLocal> items,
    int signo,
  ) async {
    for (final entrada in _cantidadesPorVariante(items).entries) {
      await txn.rawUpdate(
        'UPDATE variantes_local SET cantidad = MAX(0, cantidad + ?) '
        'WHERE id_usuario = ? AND id_variante = ?',
        [signo * entrada.value, idUsuario, entrada.key],
      );
    }
  }

  // ---------------------------------------------------------------- sincronización
  Future<ResultadoSync?> sincronizar() async {
    final id = _idUsuario;
    if (_sincronizando || id == null || !_hayRed) return null;
    if (await _api.getToken() == null) return null;
    await recargar();
    final pendientes = _ventas.where((v) => v.porEnviar).toList()
      ..sort((a, b) => a.fechaOperacion.compareTo(b.fechaOperacion));
    if (pendientes.isEmpty) return null;

    _sincronizando = true;
    notifyListeners();
    final resultado = ResultadoSync(DateTime.now().toUtc());
    try {
      for (var i = 0; i < pendientes.length; i += _maxPorLote) {
        final fin = (i + _maxPorLote < pendientes.length) ? i + _maxPorLote : pendientes.length;
        await _enviarLote(id, pendientes.sublist(i, fin), resultado);
      }
    } catch (e) {
      resultado.error = _textoErrorSync(e);
      if (esErrorDeRed(e)) marcarSinConexion();
    } finally {
      _sincronizando = false;
      _resultado = resultado;
      await _guardarResultado(id, resultado);
      await recargar();
    }
    return resultado;
  }

  Future<void> _enviarLote(int idUsuario, List<VentaLocal> lote, ResultadoSync resultado) async {
    final db = await _db.db;
    final ahora = DateTime.now().toUtc().toIso8601String();
    final uuids = lote.map((v) => v.uuid).toList();
    final marcas = List.filled(uuids.length, '?').join(',');
    await db.rawUpdate(
      'UPDATE ventas_local SET estado = ?, intentos = intentos + 1, fecha_ultimo_intento = ? '
      'WHERE uuid IN ($marcas)',
      [EstadoVentaLocal.enviada, ahora, ...uuids],
    );
    await recargar();

    Response response;
    try {
      response = await _api.dio.post(
        '/sales/sync/ventas-pos/',
        data: {
          'operaciones': lote
              .map((v) => {
                    'uuid': v.uuid,
                    'fecha_operacion': v.fechaOperacion.toUtc().toIso8601String(),
                    'id_sucursal': v.idSucursal,
                    'metodo_pago': v.metodoPago,
                    if (v.correoCliente != null) 'correo_cliente': v.correoCliente,
                    // CU08: el precio que se cobró sin conexión (el servidor lo compara).
                    'items': v.items
                        .map((i) => {
                              'id_variante': i.idVariante,
                              'cantidad': i.cantidad,
                              'precio_unitario': i.precio.toStringAsFixed(2),
                            })
                        .toList(),
                  })
              .toList(),
        },
      );
    } catch (e) {
      // No llegó respuesta válida: todo el lote vuelve a REGISTRADA para reintentar.
      await db.rawUpdate(
        'UPDATE ventas_local SET estado = ? WHERE uuid IN ($marcas)',
        [EstadoVentaLocal.registrada, ...uuids],
      );
      rethrow;
    }

    // El servidor respondió: hay conexión.
    _cambiarEnLinea(true);
    final sinRespuesta = uuids.toSet();
    final resultados = (response.data is Map ? response.data['resultados'] : null) as List? ?? [];
    await db.transaction((txn) async {
      for (final r in resultados) {
        final uuid = r['uuid']?.toString();
        if (uuid == null || !sinRespuesta.remove(uuid)) continue;
        final estado = r['estado']?.toString();
        final ahoraConfirmacion = DateTime.now().toUtc().toIso8601String();
        if (estado == 'SINCRONIZADA' || estado == 'DUPLICADA') {
          String? mensaje = estado == 'DUPLICADA' ? 'Ya estaba registrada en el servidor.' : null;
          final texto = r['mensaje']?.toString();
          if (estado == 'SINCRONIZADA' && texto != null && texto != 'Venta registrada.') {
            mensaje = texto;
          }
          await txn.update(
            'ventas_local',
            {
              'estado': EstadoVentaLocal.confirmada,
              'en_conflicto': 0,
              'id_venta': r['id_venta'] is int ? r['id_venta'] as int : null,
              'fecha_confirmacion': ahoraConfirmacion,
              'mensaje': mensaje,
            },
            where: 'uuid = ?',
            whereArgs: [uuid],
          );
          if (estado == 'SINCRONIZADA') {
            resultado.sincronizadas += 1;
          } else {
            resultado.duplicadas += 1;
          }
        } else if (estado == 'EN_CONFLICTO') {
          // CU08: el servidor registró la venta, pero queda para revisión.
          await txn.update(
            'ventas_local',
            {
              'estado': EstadoVentaLocal.confirmada,
              'en_conflicto': 1,
              'id_venta': r['id_venta'] is int ? r['id_venta'] as int : null,
              'fecha_confirmacion': ahoraConfirmacion,
              'mensaje': r['mensaje']?.toString() ?? 'Venta registrada en conflicto.',
              'tipo_conflicto': r['tipo_conflicto']?.toString(),
              'conflictos': jsonEncode(r['conflictos'] ?? []),
            },
            where: 'uuid = ?',
            whereArgs: [uuid],
          );
          resultado.enConflicto += 1;
        } else {
          await txn.update(
            'ventas_local',
            {
              'estado': EstadoVentaLocal.rechazada,
              'mensaje': r['mensaje']?.toString() ?? 'El servidor rechazó la venta.',
            },
            where: 'uuid = ?',
            whereArgs: [uuid],
          );
          resultado.rechazadas += 1;
        }
      }
      // Las que no vinieron en la respuesta se reintentan después.
      for (final uuid in sinRespuesta) {
        await txn.update(
          'ventas_local',
          {'estado': EstadoVentaLocal.registrada},
          where: 'uuid = ?',
          whereArgs: [uuid],
        );
      }
    });
  }

  Future<void> _guardarResultado(int idUsuario, ResultadoSync r) async {
    try {
      final db = await _db.db;
      await db.insert('sync_resultados', {
        'id_usuario': idUsuario,
        'tipo': _tipoSync,
        'fecha': r.fecha.toIso8601String(),
        'sincronizadas': r.sincronizadas,
        'duplicadas': r.duplicadas,
        'en_conflicto': r.enConflicto,
        'rechazadas': r.rechazadas,
        'error': r.error,
      });
    } catch (_) {
      // El resultado igual se muestra en pantalla.
    }
  }

  String _textoErrorSync(Object error) {
    if (esErrorDeRed(error)) {
      return 'Sin conexión con el servidor. Las ventas siguen guardadas y se enviarán después.';
    }
    if (error is DioException) {
      if (error.response?.statusCode == 401) {
        return 'Tu sesión expiró. Inicia sesión de nuevo para enviar las ventas pendientes.';
      }
      final data = error.response?.data;
      if (data is Map) {
        if (data['detail'] != null) return data['detail'].toString();
        if (data['error'] != null) return data['error'].toString();
      }
    }
    return 'No se pudieron enviar las ventas pendientes.';
  }

  // ---------------------------------------------------------------- utilidades
  Map<int, int> _cantidadesPorVariante(Iterable<ItemVentaLocal> items) {
    final cantidades = <int, int>{};
    for (final item in items) {
      cantidades[item.idVariante] = (cantidades[item.idVariante] ?? 0) + item.cantidad;
    }
    return cantidades;
  }

  /// Quita tildes y pasa a minúsculas para buscar sin importar cómo se escribió.
  String _normalizar(String texto) {
    const conTilde = 'áàäâéèëêíìïîóòöôúùüûñ';
    const sinTilde = 'aaaaeeeeiiiioooouuuun';
    final minus = texto.toLowerCase();
    final buffer = StringBuffer();
    for (final rune in minus.runes) {
      final c = String.fromCharCode(rune);
      final i = conTilde.indexOf(c);
      buffer.write(i >= 0 ? sinTilde[i] : c);
    }
    return buffer.toString();
  }

  @override
  void dispose() {
    _auth.removeListener(_alCambiarSesion);
    _subConectividad?.cancel();
    _timer?.cancel();
    super.dispose();
  }
}