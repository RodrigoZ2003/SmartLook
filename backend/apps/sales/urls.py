# backend/apps/sales/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CambioPrendaViewSet,
    CartViewSet,
    CartItemViewSet,
    OrderViewSet,
    PosSaleViewSet,
    DeliveryViewSet,
    DevolucionViewSet,
    SyncOperacionViewSet,
)

router = DefaultRouter()
router.register("carritos", CartViewSet, basename="carritos")
router.register("carrito-items", CartItemViewSet, basename="carrito-items")
router.register("ordenes", OrderViewSet, basename="ordenes")
router.register("ventas-pos", PosSaleViewSet, basename="ventas-pos")
router.register("entregas", DeliveryViewSet, basename="entregas")
router.register("devoluciones", DevolucionViewSet, basename="devoluciones")
# NUEVO (SaaS - paso 6): sincronización de operaciones sin conexión.
router.register("sync", SyncOperacionViewSet, basename="sync")
# NUEVO (Fase 2 - CU05 / CU06): cambio de prenda por talla o color.
router.register("cambios", CambioPrendaViewSet, basename="cambios")

urlpatterns = [
    path("", include(router.urls)),
]