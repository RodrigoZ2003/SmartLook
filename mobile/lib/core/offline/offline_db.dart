// mobile/lib/core/offline/offline_db.dart
//
// Base de datos local SQLite del móvil (SaaS - 6.3).
// Guarda lo necesario para operar sin conexión y la cola de operaciones
// pendientes de sincronizar.
//
// Versión 1 (POS sin conexión, personal):
//   sucursales_local          sucursales autorizadas del usuario
//   variantes_local           prendas con precio y stock conocido (POS)
//   descargas_local           fecha y tamaño de cada descarga
//   ventas_local              ventas hechas sin conexión
//   venta_items_local         detalle de cada venta (FK CASCADE)
//   sync_resultados           resultado de cada sincronización (ventas y reservas)
// Versión 2 (reservas sin conexión, cliente):
//   productos_local           subconjunto del catálogo para el cliente
//   variantes_producto_local  tallas/colores con precio y existencias (FK CASCADE)
//   reservas_local            reservas hechas sin conexión
//   reserva_items_local       prendas de cada reserva (FK CASCADE)
//   cache_json                copias de listas del servidor (ej. mis reservas)
// Versión 3 (Fase 2 - CU08, igual que la web):
//   ventas_local + correo_cliente  cliente opcional de la venta
//                + en_conflicto    1 si el servidor la registró en conflicto
//                + tipo_conflicto  PRECIO / STOCK / PRECIO_Y_STOCK
//                + conflictos      detalle por prenda (JSON)
//   sync_resultados + en_conflicto  cantidad en conflicto por sincronización
//   Solo se agregan columnas (sin recrear tablas): no se pierde nada.
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

class OfflineDb {
  OfflineDb._();

  static final OfflineDb instancia = OfflineDb._();

  static const String _nombre = 'smartlook_offline.db';
  static const int _version = 3;

  Future<Database>? _apertura;

  /// Base abierta una sola vez para toda la app.
  Future<Database> get db => _apertura ??= _abrir();

  Future<Database> _abrir() async {
    final ruta = p.join(await getDatabasesPath(), _nombre);
    return openDatabase(
      ruta,
      version: _version,
      onConfigure: (db) async {
        // Integridad referencial (detalles -> cabeceras).
        await db.execute('PRAGMA foreign_keys = ON');
      },
      onCreate: (db, version) async {
        await _crearVersion1(db);
        await _crearVersion2(db);
        await _crearVersion3(db);
      },
      onUpgrade: (db, anterior, nueva) async {
        // Migración sin perder datos: solo se agregan tablas y columnas nuevas.
        if (anterior < 2) await _crearVersion2(db);
        if (anterior < 3) await _crearVersion3(db);
      },
    );
  }

  Future<void> _crearVersion1(Database db) async {
    final batch = db.batch();
    batch.execute('''
      CREATE TABLE sucursales_local (
        id_usuario INTEGER NOT NULL,
        id_sucursal INTEGER NOT NULL,
        id_empresa INTEGER,
        nombre TEXT NOT NULL,
        PRIMARY KEY (id_usuario, id_sucursal)
      )
    ''');
    batch.execute('''
      CREATE TABLE variantes_local (
        id_usuario INTEGER NOT NULL,
        id_variante INTEGER NOT NULL,
        id_producto INTEGER,
        nombre_completo TEXT NOT NULL,
        codigo_producto TEXT,
        precio REAL NOT NULL,
        cantidad INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (id_usuario, id_variante)
      )
    ''');
    batch.execute('''
      CREATE TABLE descargas_local (
        id_usuario INTEGER NOT NULL,
        recurso TEXT NOT NULL,
        fecha TEXT NOT NULL,
        total INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (id_usuario, recurso)
      )
    ''');
    batch.execute('''
      CREATE TABLE ventas_local (
        uuid TEXT PRIMARY KEY,
        id_usuario INTEGER NOT NULL,
        id_empresa INTEGER,
        id_sucursal INTEGER NOT NULL,
        sucursal TEXT,
        metodo_pago TEXT NOT NULL,
        total REAL NOT NULL,
        fecha_operacion TEXT NOT NULL,
        estado TEXT NOT NULL
          CHECK (estado IN ('REGISTRADA', 'ENVIADA', 'CONFIRMADA', 'RECHAZADA')),
        mensaje TEXT,
        intentos INTEGER NOT NULL DEFAULT 0,
        fecha_ultimo_intento TEXT,
        id_venta INTEGER,
        fecha_confirmacion TEXT
      )
    ''');
    batch.execute('''
      CREATE TABLE venta_items_local (
        id_item INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid_venta TEXT NOT NULL
          REFERENCES ventas_local (uuid) ON DELETE CASCADE,
        id_variante INTEGER NOT NULL,
        nombre TEXT NOT NULL,
        precio REAL NOT NULL,
        cantidad INTEGER NOT NULL CHECK (cantidad > 0)
      )
    ''');
    batch.execute('''
      CREATE TABLE sync_resultados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_usuario INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        fecha TEXT NOT NULL,
        sincronizadas INTEGER NOT NULL DEFAULT 0,
        duplicadas INTEGER NOT NULL DEFAULT 0,
        rechazadas INTEGER NOT NULL DEFAULT 0,
        error TEXT
      )
    ''');
    batch.execute('CREATE INDEX idx_ventas_usuario_estado ON ventas_local (id_usuario, estado)');
    batch.execute('CREATE INDEX idx_items_venta ON venta_items_local (uuid_venta)');
    batch.execute('CREATE INDEX idx_sync_usuario_tipo ON sync_resultados (id_usuario, tipo, fecha)');
    await batch.commit(noResult: true);
  }

  Future<void> _crearVersion2(Database db) async {
    final batch = db.batch();
    batch.execute('''
      CREATE TABLE productos_local (
        id_producto INTEGER PRIMARY KEY,
        id_empresa INTEGER,
        empresa_nombre TEXT,
        nombre TEXT NOT NULL,
        descripcion TEXT,
        genero TEXT,
        tipo_prenda TEXT,
        categoria TEXT,
        marca TEXT,
        imagen_producto TEXT,
        fecha_descarga TEXT NOT NULL
      )
    ''');
    batch.execute('''
      CREATE TABLE variantes_producto_local (
        id_variante INTEGER PRIMARY KEY,
        id_producto INTEGER NOT NULL
          REFERENCES productos_local (id_producto) ON DELETE CASCADE,
        talla TEXT,
        color TEXT,
        codigo_hex TEXT,
        codigo_producto TEXT,
        precio REAL NOT NULL,
        cantidad INTEGER NOT NULL DEFAULT 0,
        imagen_variante TEXT,
        estado TEXT
      )
    ''');
    batch.execute('''
      CREATE TABLE reservas_local (
        uuid TEXT PRIMARY KEY,
        id_usuario INTEGER NOT NULL,
        id_empresa INTEGER,
        empresa_nombre TEXT,
        id_sucursal INTEGER NOT NULL,
        sucursal TEXT,
        fecha_reserva TEXT NOT NULL,
        hora_reserva TEXT NOT NULL,
        fecha_operacion TEXT NOT NULL,
        estado TEXT NOT NULL
          CHECK (estado IN ('REGISTRADA', 'ENVIADA', 'CONFIRMADA', 'RECHAZADA')),
        mensaje TEXT,
        intentos INTEGER NOT NULL DEFAULT 0,
        fecha_ultimo_intento TEXT,
        id_reserva INTEGER,
        fecha_confirmacion TEXT
      )
    ''');
    batch.execute('''
      CREATE TABLE reserva_items_local (
        id_item INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid_reserva TEXT NOT NULL
          REFERENCES reservas_local (uuid) ON DELETE CASCADE,
        id_variante INTEGER NOT NULL,
        label TEXT NOT NULL
      )
    ''');
    batch.execute('''
      CREATE TABLE cache_json (
        id_usuario INTEGER NOT NULL,
        clave TEXT NOT NULL,
        fecha TEXT NOT NULL,
        datos TEXT NOT NULL,
        PRIMARY KEY (id_usuario, clave)
      )
    ''');
    batch.execute('CREATE INDEX idx_variantes_producto ON variantes_producto_local (id_producto)');
    batch.execute('CREATE INDEX idx_reservas_usuario_estado ON reservas_local (id_usuario, estado)');
    batch.execute('CREATE INDEX idx_items_reserva ON reserva_items_local (uuid_reserva)');
    await batch.commit(noResult: true);
  }

  /// Fase 2 - CU08: cliente opcional y conflictos de las ventas sin conexión.
  Future<void> _crearVersion3(Database db) async {
    final batch = db.batch();
    batch.execute('ALTER TABLE ventas_local ADD COLUMN correo_cliente TEXT');
    batch.execute('ALTER TABLE ventas_local ADD COLUMN en_conflicto INTEGER NOT NULL DEFAULT 0');
    batch.execute('ALTER TABLE ventas_local ADD COLUMN tipo_conflicto TEXT');
    batch.execute('ALTER TABLE ventas_local ADD COLUMN conflictos TEXT');
    batch.execute('ALTER TABLE sync_resultados ADD COLUMN en_conflicto INTEGER NOT NULL DEFAULT 0');
    await batch.commit(noResult: true);
  }
}