# backend/apps/users_auth/apps.py
# MODIFICADO (Fase 2 - CU16): al iniciar, conecta las señales del centro de
# notificaciones (ver apps/users_auth/notificaciones.py).
from django.apps import AppConfig


class UsersAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users_auth"
    verbose_name = "Usuarios y Autenticación"

    def ready(self):
        """Conecta las señales que crean las notificaciones."""
        from .notificaciones import conectar_senales

        conectar_senales()