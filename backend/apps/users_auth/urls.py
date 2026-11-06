# backend/apps/users_auth/urls.py
# MODIFICADO (Fase 2 - CU16): rutas del centro de notificaciones.
# MODIFICADO (arreglo RF02): permisos del usuario que inició sesión.
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegistroClienteView,
    LoginView,
    UsuarioViewSet,
    RolViewSet,
    PermisoViewSet,
    BitacoraViewSet,
)
from .views_suscripcion import PlanSuscripcionViewSet, SuscripcionViewSet
from .views_empresa import EmpresaViewSet, PerfilView
from .views_notificaciones import NotificacionViewSet
from .views_grupos import MisPrivilegiosView

router = DefaultRouter()
router.register("usuarios", UsuarioViewSet, basename="usuarios")
router.register("roles", RolViewSet, basename="roles")
router.register("permisos", PermisoViewSet, basename="permisos")
router.register("bitacora", BitacoraViewSet, basename="bitacora")
# NUEVO (SaaS - paso 5): planes y suscripciones.
router.register("planes", PlanSuscripcionViewSet, basename="planes")
router.register("suscripciones", SuscripcionViewSet, basename="suscripciones")
# NUEVO (SaaS): empresas (tenants) con su logo, administrador y suscripción.
router.register("empresas", EmpresaViewSet, basename="empresas")
# NUEVO (Fase 2 - CU16): centro de notificaciones.
router.register("notificaciones", NotificacionViewSet, basename="notificaciones")

urlpatterns = [
    path("registro/", RegistroClienteView.as_view(), name="registro"),
    path("login/", LoginView.as_view(), name="login"),
    # NUEVO: perfil del usuario autenticado (consulta y edición).
    path("perfil/", PerfilView.as_view(), name="perfil"),
    # NUEVO (arreglo RF02): permisos actuales del rol del usuario.
    path("mis-privilegios/", MisPrivilegiosView.as_view(), name="mis-privilegios"),
    path("", include(router.urls)),
]