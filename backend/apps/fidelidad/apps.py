# backend/apps/fidelidad/apps.py
# NUEVO (Fase 3 - CU18): descuento por fidelidad. Al iniciar conecta las
# señales que revisan si el cliente llegó a la meta del mes (ver servicio.py).

from django.apps import AppConfig


class FidelidadConfig(AppConfig):
    """Configuración de la app de descuento por fidelidad."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fidelidad"
    verbose_name = "Descuento por fidelidad"

    def ready(self):
        """Conecta las señales de pedidos y ventas POS."""
        from .servicio import conectar_senales

        conectar_senales()