// mobile/lib/core/models/user_model.dart
//
// MODIFICADO (SaaS - A.2): el usuario trae su empresa y su sucursal
// (vacías para SUPER_ADMIN y clientes). Se agregan la pantalla de inicio
// según el rol (misma regla que la web) y copyWith().
// MODIFICADO (arreglo RF02): el usuario trae los permisos de su rol
// ("privilegios", vienen en el login y en /auth/mis-privilegios/) y
// puedeVer() decide qué tarjetas del panel se muestran (misma regla que la
// web: SUPER_ADMIN y ADMIN_EMPRESA todo; el resto según sus permisos).
// puedeGestionar() decide si se muestran los botones de crear, editar y
// eliminar dentro de cada pantalla.

// NUEVO (arreglo RF02): pantalla del panel -> permisos que la muestran
// (VER_x o GESTIONAR_x), igual que REGLAS de acceso.service.ts en la web.
const Map<String, List<String>> _permisosPorPantalla = {
  'dashboard': ['VER_DASHBOARD'],
  'catalogo': ['CONSULTAR_CATALOGO'],
  'reservas': ['VER_RESERVAS', 'GESTIONAR_RESERVAS'],
  'pos': ['REGISTRAR_VENTAS'],
  'cambios': ['GESTIONAR_CAMBIOS'],
  'devoluciones': ['VER_DEVOLUCIONES', 'GESTIONAR_DEVOLUCIONES'],
  'entregas': ['VER_ENTREGAS', 'GESTIONAR_ENTREGAS'],
  'inventario': ['VER_INVENTARIO', 'GESTIONAR_INVENTARIO'],
  'sucursales': ['VER_SUCURSALES', 'GESTIONAR_SUCURSALES'],
  'productos': ['VER_PRODUCTOS', 'GESTIONAR_PRODUCTOS'],
  'proveedores': ['VER_PROVEEDORES', 'GESTIONAR_PROVEEDORES'],
  'atributos': ['VER_ATRIBUTOS', 'GESTIONAR_ATRIBUTOS'],
  'usuarios': ['VER_USUARIOS', 'GESTIONAR_USUARIOS'],
  'clientes': ['VER_CLIENTES'],
  'bitacora': ['VER_BITACORA'],
};

// NUEVO (arreglo RF02): pantalla -> permiso GESTIONAR que muestra los botones
// de crear, editar y eliminar.
const Map<String, String> _gestionarPorPantalla = {
  'inventario': 'GESTIONAR_INVENTARIO',
  'sucursales': 'GESTIONAR_SUCURSALES',
  'productos': 'GESTIONAR_PRODUCTOS',
  'proveedores': 'GESTIONAR_PROVEEDORES',
  'atributos': 'GESTIONAR_ATRIBUTOS',
  'usuarios': 'GESTIONAR_USUARIOS',
};

class User {
  /// Roles que entran al panel (igual que ROLES_PERSONAL de la web).
  static const List<String> rolesPersonal = [
    'SUPER_ADMIN',
    'ADMIN_EMPRESA',
    'ENCARGADO_SUCURSAL',
    'CAJERO',
  ];

  final int idUsuario;
  final String nombres;
  final String apellidos;
  final String correo;
  final String? telefono;
  final String estado;
  final String? ultimoAcceso;
  final List<Role> roles;
  // NUEVO (SaaS): empresa (tenant) y sucursal del usuario.
  final int? idEmpresa;
  final String? empresaNombre;
  final int? idSucursal;
  final String? sucursalNombre;
  // NUEVO (arreglo RF02): permisos del rol del usuario.
  final List<String> privilegios;

  User({
    required this.idUsuario,
    required this.nombres,
    required this.apellidos,
    required this.correo,
    this.telefono,
    required this.estado,
    this.ultimoAcceso,
    required this.roles,
    this.idEmpresa,
    this.empresaNombre,
    this.idSucursal,
    this.sucursalNombre,
    this.privilegios = const [],
  });

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      idUsuario: json['id_usuario'] ?? 0,
      nombres: json['nombres'] ?? '',
      apellidos: json['apellidos'] ?? '',
      correo: json['correo'] ?? '',
      telefono: json['telefono'],
      estado: json['estado'] ?? 'ACTIVO',
      ultimoAcceso: json['ultimo_acceso'],
      roles: (json['roles'] as List<dynamic>? ?? [])
          .map((role) => Role.fromJson(role))
          .toList(),
      idEmpresa: json['id_empresa'] as int?,
      empresaNombre: json['empresa_nombre'] as String?,
      idSucursal: json['id_sucursal'] as int?,
      sucursalNombre: json['sucursal_nombre'] as String?,
      privilegios: (json['privilegios'] as List<dynamic>? ?? [])
          .map((p) => p.toString())
          .toList(),
    );
  }

  /// Copia con los datos personales cambiados (lo demás se conserva).
  User copyWith({
    String? nombres,
    String? apellidos,
    String? telefono,
    List<String>? privilegios,
  }) {
    return User(
      idUsuario: idUsuario,
      nombres: nombres ?? this.nombres,
      apellidos: apellidos ?? this.apellidos,
      correo: correo,
      telefono: telefono ?? this.telefono,
      estado: estado,
      ultimoAcceso: ultimoAcceso,
      roles: roles,
      idEmpresa: idEmpresa,
      empresaNombre: empresaNombre,
      idSucursal: idSucursal,
      sucursalNombre: sucursalNombre,
      privilegios: privilegios ?? this.privilegios,
    );
  }

  String get nombreCompleto => '$nombres $apellidos';

  bool hasRole(String roleName) {
    return roles.any((role) => role.nombre == roleName);
  }

  /// NUEVO (arreglo RF02): SUPER_ADMIN y ADMIN_EMPRESA hacen todo.
  bool get esAdministrador => hasRole('SUPER_ADMIN') || hasRole('ADMIN_EMPRESA');

  /// NUEVO (arreglo RF02): true si el usuario puede ver esa pantalla del
  /// panel. El backend vuelve a validar todo; aquí solo se decide qué se muestra.
  bool puedeVer(String pantalla) {
    if (esAdministrador) return true;
    final permisos = _permisosPorPantalla[pantalla] ?? const <String>[];
    return permisos.any(privilegios.contains);
  }

  /// NUEVO (arreglo RF02): true si además puede crear, editar y eliminar en
  /// esa pantalla.
  bool puedeGestionar(String pantalla) {
    if (esAdministrador) return true;
    final permiso = _gestionarPorPantalla[pantalla];
    return permiso != null && privilegios.contains(permiso);
  }

  bool get esPersonal => roles.any((r) => rolesPersonal.contains(r.nombre));

  bool get esSoloRepartidor => hasRole('REPARTIDOR') && !esPersonal;

  /// Pantalla inicial según el rol.
  String get rutaInicio {
    if (esPersonal) return '/admin';
    if (esSoloRepartidor) return '/entregas';
    return '/catalog';
  }

  /// Nombre de la sucursal sin el nombre de la empresa delante
  /// ("FASHIONSTORE Ventura" -> "Ventura"), igual que en la web.
  String? get sucursalCorta {
    final nombre = sucursalNombre;
    if (nombre == null || nombre.isEmpty) return null;
    final empresa = empresaNombre ?? '';
    if (empresa.isNotEmpty && nombre.toUpperCase().startsWith('${empresa.toUpperCase()} ')) {
      final resto = nombre.substring(empresa.length + 1).trim();
      return resto.isEmpty ? nombre : resto;
    }
    return nombre;
  }
}

class Role {
  final int idRol;
  final String nombre;
  final String? descripcion;
  final bool estado;

  Role({
    required this.idRol,
    required this.nombre,
    this.descripcion,
    required this.estado,
  });

  factory Role.fromJson(Map<String, dynamic> json) {
    return Role(
      idRol: json['id_rol'] ?? 0,
      nombre: json['nombre'] ?? '',
      descripcion: json['descripcion'],
      estado: json['estado'] ?? true,
    );
  }
}