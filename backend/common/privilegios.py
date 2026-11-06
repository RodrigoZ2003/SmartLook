"""Permisos por rol (arreglo RF02 - usuarios, roles y permisos).

Los permisos son las filas de la tabla "permisos" y se asignan a cada rol en
la tabla "rol_permiso" desde la pantalla "Permisos por rol" (solo el
SUPER_ADMIN guarda). Se reutilizan los 11 que ya existían y se agregaron los
que faltaban para las pantallas nuevas.

Cada pantalla tiene hasta dos niveles:
    VER_...        ver la opción del menú y entrar a la pantalla (consultar).
    GESTIONAR_...  botones y formularios de crear, editar y eliminar.
GESTIONAR incluye VER.

- SUPER_ADMIN y ADMIN_EMPRESA hacen todo (no dependen de rol_permiso).
- ENCARGADO_SUCURSAL, CAJERO y REPARTIDOR: lo marcado en rol_permiso.
  Por defecto tienen lo de la tabla acordada (POR_DEFECTO). Si se desmarca un
  permiso que el rol trae por defecto, se le quita; si se marca uno extra,
  se le agrega.

Cómo se aplica en el backend: las clases de common/permissions.py revisan la
pantalla de la ruta pedida (RUTAS): GET necesita VER o GESTIONAR; crear,
editar o eliminar necesita GESTIONAR.
"""
from rest_framework.permissions import SAFE_METHODS

# Roles fijos del sistema (tabla "roles").
ROLES_SISTEMA = (
    "SUPER_ADMIN",
    "ADMIN_EMPRESA",
    "ENCARGADO_SUCURSAL",
    "CAJERO",
    "CLIENTE",
    "REPARTIDOR",
)

# Pantallas con permisos, en el orden del menú.
# (código del módulo, nombre visible, privilegio para ver, privilegio para gestionar)
# None = esa pantalla no tiene ese nivel.
MODULOS = (
    ("dashboard", "Dashboard", "VER_DASHBOARD", None),
    ("catalogo", "Catálogo", "CONSULTAR_CATALOGO", None),
    ("reservas", "Reservas", "VER_RESERVAS", "GESTIONAR_RESERVAS"),
    ("pos", "Punto de venta", None, "REGISTRAR_VENTAS"),
    ("cambios", "Cambios de prenda", None, "GESTIONAR_CAMBIOS"),
    ("devoluciones", "Devoluciones", "VER_DEVOLUCIONES", "GESTIONAR_DEVOLUCIONES"),
    ("entregas", "Entregas", "VER_ENTREGAS", "GESTIONAR_ENTREGAS"),
    ("reportes", "Reportes", "VER_REPORTES", None),
    ("asistente", "Asistente", None, "USAR_ASISTENTE"),
    ("analitica", "Analítica", "VER_ANALITICA", None),
    ("inventario", "Inventario", "VER_INVENTARIO", "GESTIONAR_INVENTARIO"),
    ("traspasos", "Traspasos", "VER_TRASPASOS", "GESTIONAR_TRASPASOS"),
    ("sucursales", "Sucursales", "VER_SUCURSALES", "GESTIONAR_SUCURSALES"),
    ("proveedores", "Proveedores", "VER_PROVEEDORES", "GESTIONAR_PROVEEDORES"),
    ("productos", "Productos", "VER_PRODUCTOS", "GESTIONAR_PRODUCTOS"),
    ("atributos", "Atributos de producto", "VER_ATRIBUTOS", "GESTIONAR_ATRIBUTOS"),
    ("usuarios", "Usuarios y roles", "VER_USUARIOS", "GESTIONAR_USUARIOS"),
    ("permisos", "Permisos por rol", None, "GESTIONAR_ROLES"),
    ("clientes", "Clientes", "VER_CLIENTES", None),
    ("fidelidad", "Fidelidad", "VER_FIDELIDAD", None),
    ("bitacora", "Bitácora", "VER_BITACORA", None),
)

# Ruta de la API -> pantalla (módulo) a la que pertenece. Se revisan en
# orden y gana el primer prefijo que coincida. Las rutas que no están aquí
# (empresas, planes, suscripciones...) solo se deciden por el rol.
RUTAS = (
    ("/api/bi/", "dashboard"),
    ("/api/catalog/sucursales/", "sucursales"),
    ("/api/catalog/productos/", "productos"),
    ("/api/catalog/variantes/", "productos"),
    ("/api/catalog/proveedores/", "proveedores"),
    ("/api/catalog/categorias/", "atributos"),
    ("/api/catalog/marcas/", "atributos"),
    ("/api/catalog/temporadas/", "atributos"),
    ("/api/catalog/colecciones/", "atributos"),
    ("/api/catalog/tallas/", "atributos"),
    ("/api/catalog/colores/", "atributos"),
    ("/api/inventory/traspasos/", "traspasos"),
    ("/api/inventory/", "inventario"),
    ("/api/reservations/reservas/", "reservas"),
    ("/api/sales/ventas-pos/", "pos"),
    ("/api/sales/sync/", "pos"),
    ("/api/fidelidad/pos/", "pos"),
    ("/api/sales/entregas/", "entregas"),
    ("/api/sales/devoluciones/", "devoluciones"),
    ("/api/sales/cambios/", "cambios"),
    ("/api/innovation/reportes/", "reportes"),
    ("/api/innovation/asistente/", "asistente"),
    ("/api/analytics/clientes/", "clientes"),
    ("/api/analytics/", "analitica"),
    ("/api/fidelidad/regla/", "fidelidad"),
    ("/api/fidelidad/monitoreo/", "fidelidad"),
    ("/api/auth/usuarios/", "usuarios"),
    ("/api/auth/permisos/", "permisos"),
    ("/api/auth/bitacora/", "bitacora"),
)

# Permisos que se marcan en la pantalla (los del cliente no:
# REALIZAR_RESERVAS y REALIZAR_COMPRAS son de la cuenta del cliente).
ASIGNABLES = frozenset(
    privilegio
    for _codigo, _nombre, ver, gestionar in MODULOS
    for privilegio in (ver, gestionar)
    if privilegio
)

# Roles cuyos permisos se configuran en la pantalla.
ROLES_CONFIGURABLES = ("ENCARGADO_SUCURSAL", "CAJERO", "REPARTIDOR")
# Estos hacen todo y no dependen de rol_permiso.
ROLES_TODO = ("SUPER_ADMIN", "ADMIN_EMPRESA")

# Permisos por defecto de cada rol (tabla acordada). La migración 0015 los
# carga en rol_permiso; después se cambian desde la pantalla.
POR_DEFECTO = {
    "ENCARGADO_SUCURSAL": (
        "VER_DASHBOARD", "CONSULTAR_CATALOGO", "VER_RESERVAS", "GESTIONAR_RESERVAS",
        "REGISTRAR_VENTAS", "GESTIONAR_CAMBIOS", "VER_DEVOLUCIONES", "GESTIONAR_DEVOLUCIONES",
        "VER_ENTREGAS", "GESTIONAR_ENTREGAS", "VER_REPORTES", "USAR_ASISTENTE",
        "VER_INVENTARIO", "GESTIONAR_INVENTARIO", "VER_TRASPASOS", "GESTIONAR_TRASPASOS",
        "VER_SUCURSALES", "VER_PRODUCTOS",
    ),
    "CAJERO": (
        "VER_DASHBOARD", "CONSULTAR_CATALOGO", "VER_RESERVAS", "REGISTRAR_VENTAS",
        "GESTIONAR_CAMBIOS", "VER_DEVOLUCIONES", "GESTIONAR_DEVOLUCIONES",
    ),
    "REPARTIDOR": ("VER_ENTREGAS", "GESTIONAR_ENTREGAS"),
}

# Privilegios de cada módulo: {codigo: (ver, gestionar)}.
_POR_MODULO = {codigo: (ver, gestionar) for codigo, _nombre, ver, gestionar in MODULOS}

# GESTIONAR_X incluye VER_X.
_VER_INCLUIDO = {
    gestionar: ver
    for _codigo, _nombre, ver, gestionar in MODULOS
    if ver and gestionar
}


def expandir(privilegios):
    """Agrega los VER_... que vienen incluidos en cada GESTIONAR_..."""
    resultado = set(privilegios)
    for privilegio in privilegios:
        incluido = _VER_INCLUIDO.get(privilegio)
        if incluido:
            resultado.add(incluido)
    return resultado


def _roles_de(usuario):
    """Nombres de los roles del usuario (se guardan en el objeto)."""
    roles = getattr(usuario, "_roles_permiso", None)
    if roles is None:
        roles = set(usuario.roles.values_list("nombre", flat=True))
        try:
            usuario._roles_permiso = roles
        except AttributeError:
            pass
    return roles


def es_configurable(usuario):
    """True si sus accesos dependen de rol_permiso (no es SUPER_ADMIN, ADMIN_EMPRESA ni cliente)."""
    if not getattr(usuario, "is_authenticated", False) or not usuario.id_empresa_id:
        return False
    roles = _roles_de(usuario)
    return not roles & set(ROLES_TODO) and bool(roles & set(ROLES_CONFIGURABLES))


def privilegios_de(usuario):
    """Permisos que los roles del usuario tienen marcados en rol_permiso.

    Vacío para SUPER_ADMIN y ADMIN_EMPRESA (hacen todo por su rol) y para
    clientes.
    """
    from apps.users_auth.models import Permiso

    if not es_configurable(usuario):
        return set()
    roles = _roles_de(usuario) & set(ROLES_CONFIGURABLES)
    nombres = Permiso.objects.filter(
        estado=True,
        nombre__in=ASIGNABLES,
        rolpermiso__id_rol__nombre__in=roles,
    ).values_list("nombre", flat=True)
    return expandir(nombres)


def _por_defecto_de(usuario):
    """Permisos que sus roles traen por defecto (tabla acordada)."""
    resultado = set()
    for rol in _roles_de(usuario):
        resultado.update(POR_DEFECTO.get(rol, ()))
    return expandir(resultado)


def _privilegios_guardados(usuario):
    """privilegios_de(usuario) guardado en el objeto para no repetir la consulta."""
    privilegios = getattr(usuario, "_privilegios_rol", None)
    if privilegios is None:
        privilegios = privilegios_de(usuario)
        try:
            usuario._privilegios_rol = privilegios
        except AttributeError:
            pass
    return privilegios


def privilegios_de_request(request):
    """Permisos del usuario de la petición (calculados una sola vez)."""
    return _privilegios_guardados(request.user)


def tiene_privilegio(usuario, nombre):
    """True si el permiso le fue AGREGADO a su rol (marcado y no viene por defecto).

    Lo usan las vistas que deciden por rol: lo que el rol ya hacía por
    defecto sigue funcionando igual; esto solo cubre lo que se le agregó.
    """
    return nombre in _privilegios_guardados(usuario) and nombre not in _por_defecto_de(usuario)


def tiene_alguno(usuario, *nombres):
    """True si alguno de esos permisos le fue agregado a su rol."""
    return any(tiene_privilegio(usuario, nombre) for nombre in nombres)


def modulo_de_request(request):
    """Módulo (pantalla) al que pertenece la ruta pedida, o None.

    Caso especial: la lista de clientes usa /api/auth/usuarios/?rol=CLIENTE,
    que pertenece a la pantalla Clientes y no a Usuarios.
    """
    ruta = request.path
    if ruta.startswith("/api/auth/usuarios/"):
        params = getattr(request, "query_params", request.GET)
        if request.method in SAFE_METHODS and params.get("rol") == "CLIENTE":
            return "clientes"
    for prefijo, modulo in RUTAS:
        if ruta.startswith(prefijo):
            return modulo
    return None


def privilegio_requerido(modulo, metodo):
    """Privilegio que hace falta para usar el módulo con ese método HTTP.

    Consultar (GET) pide VER; crear, editar o eliminar pide GESTIONAR. Si el
    módulo tiene un solo nivel, ese nivel sirve para todo.
    """
    ver, gestionar = _POR_MODULO.get(modulo, (None, None))
    if metodo in SAFE_METHODS:
        return ver or gestionar
    return gestionar or ver


def _requerido(request):
    """Permiso que pide la ruta y el método (o None si la ruta no se controla)."""
    modulo = modulo_de_request(request)
    if modulo is None:
        return None
    return privilegio_requerido(modulo, request.method)


def permite_por_privilegio(request):
    """True si el rol del usuario tiene marcado el permiso de la ruta pedida."""
    if not es_configurable(request.user):
        return False
    requerido = _requerido(request)
    return bool(requerido) and requerido in privilegios_de_request(request)


def quitado_al_rol(request):
    """True si el permiso de la ruta venía por defecto en su rol y se le desmarcó."""
    if not es_configurable(request.user):
        return False
    requerido = _requerido(request)
    if not requerido:
        return False
    return (
        requerido in _por_defecto_de(request.user)
        and requerido not in privilegios_de_request(request)
    )