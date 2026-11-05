# backend/apps/inventory/urls.py
#
# MODIFICADO (Fase 3 - CU07): rutas de traspasos entre sucursales.
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StockItemViewSet, InventoryMovementViewSet, MovementCreateView
from .views_traspasos import (
    OpcionesTraspasoView,
    StockTraspasoView,
    SugerenciasTraspasoView,
    TraspasoAccionView,
    TraspasoDetalleView,
    TraspasosView,
)

router = DefaultRouter()
router.register("stock", StockItemViewSet, basename="stock")
router.register("movimientos", InventoryMovementViewSet, basename="movimientos")

urlpatterns = [
    path("movimientos/registrar/", MovementCreateView.as_view(), name="registrar-movimiento"),
    # NUEVO (Fase 3 - CU07): traspasos entre sucursales.
    path("traspasos/", TraspasosView.as_view(), name="traspasos"),
    path("traspasos/opciones/", OpcionesTraspasoView.as_view(), name="traspasos-opciones"),
    path("traspasos/stock/", StockTraspasoView.as_view(), name="traspasos-stock"),
    path("traspasos/sugerencias/", SugerenciasTraspasoView.as_view(), name="traspasos-sugerencias"),
    path("traspasos/<int:id_traspaso>/", TraspasoDetalleView.as_view(), name="traspaso-detalle"),
    path("traspasos/<int:id_traspaso>/aprobar/", TraspasoAccionView.as_view(accion="aprobar"), name="traspaso-aprobar"),
    path("traspasos/<int:id_traspaso>/rechazar/", TraspasoAccionView.as_view(accion="rechazar"), name="traspaso-rechazar"),
    path("traspasos/<int:id_traspaso>/recibir/", TraspasoAccionView.as_view(accion="recibir"), name="traspaso-recibir"),
    path("traspasos/<int:id_traspaso>/cancelar/", TraspasoAccionView.as_view(accion="cancelar"), name="traspaso-cancelar"),
    path("", include(router.urls)),
]