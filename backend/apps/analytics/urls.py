# backend/apps/analytics/urls.py
#
# NUEVO (Fase 3 - CU09): rutas de Analítica con Machine Learning.
# Incluido en config/urls.py bajo "api/analytics/".

from django.urls import path

from .views import DashboardAnaliticaView, ExportarAnaliticaView, ReentrenarView

urlpatterns = [
    path("dashboard/", DashboardAnaliticaView.as_view(), name="analitica-dashboard"),
    path("reentrenar/", ReentrenarView.as_view(), name="analitica-reentrenar"),
    path("exportar/", ExportarAnaliticaView.as_view(), name="analitica-exportar"),
]