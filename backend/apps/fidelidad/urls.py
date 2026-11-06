# backend/apps/fidelidad/urls.py
# NUEVO (Fase 3 - CU18): rutas del descuento por fidelidad (/api/fidelidad/).

from django.urls import path

from .views import ClientePosView, MiProgresoView, MonitoreoFidelidadView, ReglaFidelidadView

urlpatterns = [
    path("regla/", ReglaFidelidadView.as_view(), name="fidelidad-regla"),
    path("monitoreo/", MonitoreoFidelidadView.as_view(), name="fidelidad-monitoreo"),
    path("mi-progreso/", MiProgresoView.as_view(), name="fidelidad-mi-progreso"),
    path("pos/", ClientePosView.as_view(), name="fidelidad-pos"),
]