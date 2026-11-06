from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.users_auth.urls")),
    path("api/catalog/", include("apps.catalog.urls")),
    path("api/inventory/", include("apps.inventory.urls")),
    path("api/reservations/", include("apps.reservations.urls")),
    path("api/sales/", include("apps.sales.urls")),
    path("api/innovation/", include("apps.innovation.urls")),
    path("api/bi/", include("apps.bi_reports.urls")),
    # NUEVO (Fase 3 - CU09): analítica con Machine Learning.
    path("api/analytics/", include("apps.analytics.urls")),
    # NUEVO (Fase 3 - CU18): descuento por fidelidad.
    path("api/fidelidad/", include("apps.fidelidad.urls")),
    # Documentación
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]