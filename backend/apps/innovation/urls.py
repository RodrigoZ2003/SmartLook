# backend/apps/innovation/urls.py
#
# Incluido en config/urls.py bajo "api/innovation/".

from django.urls import path, include

from rest_framework.routers import DefaultRouter

from .views import ARTryOnSessionViewSet
from .views_chatbot import ChatbotHistorialView, ChatbotView
from .views_gestion import (
    AsistenteGestionView,
    ReporteDetalleView,
    ReporteExportarView,
    ReportesGestionView,
)
from .views_reportes import GenerarReporteView, OpcionesReporteView

router = DefaultRouter()

router.register("ar-sessions", ARTryOnSessionViewSet, basename="ar-sessions")

urlpatterns = [
    # CU18/CU19: asistente virtual para el cliente.
    path("chatbot/", ChatbotView.as_view(), name="chatbot"),
    path("chatbot/historial/", ChatbotHistorialView.as_view(), name="chatbot-historial"),
    # NUEVO (CU20): asistente de gestión para el personal.
    path("asistente/", AsistenteGestionView.as_view(), name="asistente-gestion"),
    path("asistente/reportes/", ReportesGestionView.as_view(), name="asistente-reportes"),
    path(
        "asistente/reportes/<int:id_reporte>/",
        ReporteDetalleView.as_view(),
        name="asistente-reporte",
    ),
    path(
        "asistente/reportes/<int:id_reporte>/exportar/",
        ReporteExportarView.as_view(),
        name="asistente-reporte-exportar",
    ),
    # NUEVO (Fase 3 - CU13): reportes convencionales sin IA (los tres planes).
    path("reportes/opciones/", OpcionesReporteView.as_view(), name="reportes-opciones"),
    path("reportes/generar/", GenerarReporteView.as_view(), name="reportes-generar"),
    path("", include(router.urls)),
]