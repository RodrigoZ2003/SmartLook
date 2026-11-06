"""Datos del inicio de sesión con los permisos del rol (arreglo RF02).

El login y /api/auth/mis-privilegios/ devuelven los permisos que el rol del
usuario tiene marcados en "Permisos por rol" (tabla rol_permiso). La web y el
móvil los usan para mostrar solo las pantallas permitidas; el backend vuelve
a validarlos en cada petición.
"""
from common.privilegios import privilegios_de

from .serializers import UsuarioSerializer


def datos_sesion(usuario):
    """Datos del usuario para el inicio de sesión: los de siempre + sus permisos."""
    datos = UsuarioSerializer(usuario).data
    datos["privilegios"] = sorted(privilegios_de(usuario))
    return datos