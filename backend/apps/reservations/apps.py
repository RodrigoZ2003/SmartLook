"""Configuración de la app de reservas."""
from django.apps import AppConfig


class ReservationsConfig(AppConfig):
    """App de reservas de prendas (vestidor)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reservations"
    verbose_name = "Reservas"

    def ready(self):
        """Conecta las señales (quitar del carrito las reservas cerradas)."""
        from . import signals  # noqa: F401