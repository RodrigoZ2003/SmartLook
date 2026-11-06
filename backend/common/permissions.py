# backend/common/permissions.py
# MODIFICADO (arreglo RF02 - usuarios, roles y permisos): las clases del
# personal aplican los permisos marcados para cada rol en "Permisos por rol"
# (tabla rol_permiso, ver common/privilegios.py):
# - Si el rol entra por su nombre (como antes), se le niega solo si se le
#   desmarcó el permiso de esa pantalla.
# - Si no entra por su nombre, se le permite si se le marcó ese permiso.
# SUPER_ADMIN y ADMIN_EMPRESA hacen todo. IsSuperAdmin, IsCliente e
# IsClienteOrReadOnly no cambian.
from rest_framework.permissions import SAFE_METHODS, BasePermission

from common.privilegios import permite_por_privilegio, quitado_al_rol


def _tiene_rol(request, roles):
    """True si el usuario autenticado tiene alguno de los roles indicados."""
    return request.user.is_authenticated and request.user.roles.filter(
        nombre__in=roles
    ).exists()


def _rol_o_privilegio(request, roles):
    """Rol permitido (salvo permiso desmarcado) o permiso marcado para su rol."""
    if _tiene_rol(request, roles):
        return not quitado_al_rol(request)
    return permite_por_privilegio(request)


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        """Solo SUPER_ADMIN."""
        return _tiene_rol(request, ["SUPER_ADMIN"])


class IsAdminEmpresa(BasePermission):
    def has_permission(self, request, view):
        """SUPER_ADMIN o ADMIN_EMPRESA (o su rol tiene el permiso de la pantalla)."""
        return _rol_o_privilegio(request, ["SUPER_ADMIN", "ADMIN_EMPRESA"])


class IsEncargadoSucursal(BasePermission):
    def has_permission(self, request, view):
        """SUPER_ADMIN, ADMIN_EMPRESA o ENCARGADO_SUCURSAL (o permiso de su rol)."""
        return _rol_o_privilegio(
            request, ["SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL"]
        )


class IsCajero(BasePermission):
    def has_permission(self, request, view):
        """Personal con acceso a caja (incluye roles superiores o permiso de su rol)."""
        return _rol_o_privilegio(
            request, ["SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL", "CAJERO"]
        )


class IsCliente(BasePermission):
    def has_permission(self, request, view):
        """Solo CLIENTE."""
        return _tiene_rol(request, ["CLIENTE"])


class IsClienteOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        """Lectura libre; escritura solo para CLIENTE."""
        if request.method in SAFE_METHODS:
            return True
        return _tiene_rol(request, ["CLIENTE"])


class IsAdminEmpresaOrReadOnly(BasePermission):
    """
    Lectura libre para cualquiera (incluye visitantes sin login, porque
    el catálogo web es público) - escritura (crear/editar/eliminar)
    solo para SUPER_ADMIN/ADMIN_EMPRESA o un rol con GESTIONAR de esa pantalla.
    """
    def has_permission(self, request, view):
        """Lectura libre; escritura para SUPER_ADMIN/ADMIN_EMPRESA o permiso de su rol."""
        if request.method in SAFE_METHODS:
            return True
        return _rol_o_privilegio(request, ["SUPER_ADMIN", "ADMIN_EMPRESA"])


class IsGlobalEditableSoloSuperAdmin(BasePermission):
    """
    NUEVO (SaaS): para catálogos GLOBALES compartidos por todas las
    empresas (País, Ciudad, Talla, Color). Lectura libre; crear un valor
    nuevo lo puede hacer SUPER_ADMIN o ADMIN_EMPRESA (o un rol con
    GESTIONAR_ATRIBUTOS); editar o eliminar solo SUPER_ADMIN, porque el
    cambio afectaría a todas las empresas.
    """
    def has_permission(self, request, view):
        """Aplica las reglas de lectura, creación y edición descritas arriba."""
        if request.method in SAFE_METHODS:
            return True
        if not request.user.is_authenticated:
            return False
        if request.method == "POST":
            return _rol_o_privilegio(request, ["SUPER_ADMIN", "ADMIN_EMPRESA"])
        return _tiene_rol(request, ["SUPER_ADMIN"])


class IsRepartidor(BasePermission):
    def has_permission(self, request, view):
        """Personal con acceso a entregas (incluye roles superiores o permiso de su rol)."""
        return _rol_o_privilegio(
            request, ["SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL", "REPARTIDOR"]
        )