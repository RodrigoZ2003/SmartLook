# backend/apps/analytics/apps.py
# NUEVO (Fase 3 - CU09): analítica con Machine Learning.

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    """Configuración de la app de analítica con Machine Learning."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
    verbose_name = "Analítica (Machine Learning)"