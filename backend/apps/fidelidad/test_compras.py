"""Pruebas del descuento por fidelidad en el checkout y en el POS (CU18).

- Checkout web: con el beneficio, Stripe cobra las prendas con el descuento
  y, al confirmarse el pago, el beneficio queda usado.
- POS web (aplicar_fidelidad=true y correo del cliente): la venta sale con el
  descuento una sola vez por mes.
- POS del celular (sin aplicar_fidelidad): no hay descuento, pero la venta cuenta.
- La compra con descuento no admite devolución ni cambio; la compra normal sí.
Stripe se simula con mock.

Ejecutar:
    python manage.py test apps.fidelidad.test_compras --settings=config.settings.test
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from apps.fidelidad import servicio
from apps.sales.cambios import OrigenCambio, motivo_no_elegible
from apps.sales.devoluciones import cargar_compra
from apps.sales.models import Cart, CartItem, Order, OrderItem, PosSaleItem
from apps.users_auth.models import Cliente
from common.pruebas import (
    cliente_api,
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)

URL_POS = "/api/sales/ventas-pos/registrar/"
CREAR_PAGO = "apps.sales.services.crear_intento_pago"
VERIFICAR_PAGO = "apps.sales.services.verificar_pago"


class FidelidadComprasTests(TestCase):
    """Cliente con 5 compras pagadas este mes en la empresa (ya tiene el beneficio)."""

    @classmethod
    def setUpTestData(cls):
        """Empresa con una prenda de Bs 100, cajero y cliente con 5 pedidos pagados."""
        plan = crear_plan("PRUEBA_FIDELIDAD_COMPRAS", 10)
        cls.empresa = crear_empresa("Empresa Fidelidad C", "empresa-fidelidad-c", plan)
        cls.sucursal = crear_sucursal(cls.empresa, "Sucursal FC1", crear_ciudad())
        cls.variante = crear_prenda(cls.empresa, cls.sucursal, "FID-C-1", 50)
        crear_usuario("cajero@fidelidad-c.test", "CAJERO", cls.empresa, cls.sucursal)
        cls.cliente = Cliente.objects.get(id_usuario=crear_usuario("cliente@fidelidad-c.test", "CLIENTE"))
        for _ in range(5):
            orden = Order.objects.create(
                id_cliente=cls.cliente, id_sucursal=cls.sucursal, id_empresa=cls.empresa,
                total=Decimal("100.00"), estado="PAGADA",
            )
            OrderItem.objects.create(
                id_orden=orden, id_variante=cls.variante, cantidad=1,
                precio_unitario=Decimal("100.00"), subtotal=Decimal("100.00"),
            )

    def vender(self, aplicar=True, cantidad=2):
        """Venta POS con el correo del cliente."""
        datos = {
            "id_sucursal": self.sucursal.id_sucursal,
            "metodo_pago": "EFECTIVO",
            "correo_cliente": "cliente@fidelidad-c.test",
            "items": [{"id_variante": self.variante.id_variante, "cantidad": cantidad}],
        }
        if aplicar:
            datos["aplicar_fidelidad"] = True
        respuesta = cliente_api("cajero@fidelidad-c.test").post(URL_POS, datos, format="json")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return respuesta.data

    def test_pos_web_aplica_el_descuento_una_vez(self):
        """2 prendas (Bs 200) con 50% = Bs 100; la siguiente venta del mes ya no tiene descuento."""
        self.assertEqual(Decimal(self.vender()["total"]), Decimal("100.00"))
        self.assertTrue(servicio.estado(self.cliente, self.empresa)["usado"])
        self.assertEqual(Decimal(self.vender()["total"]), Decimal("200.00"))

    def test_pos_del_celular_no_descuenta_pero_cuenta(self):
        """Sin aplicar_fidelidad la venta se cobra completa y suma una compra más."""
        self.assertEqual(Decimal(self.vender(aplicar=False)["total"]), Decimal("200.00"))
        datos = servicio.estado(self.cliente, self.empresa)
        self.assertEqual(datos["compras"], 6)
        self.assertTrue(datos["disponible"])

    def test_checkout_web_cobra_con_descuento_y_lo_usa_al_pagar(self):
        """Stripe cobra Bs 50 por una prenda de Bs 100 y al pagar el beneficio queda usado."""
        carrito = Cart.objects.create(id_cliente=self.cliente, estado="ACTIVO", id_empresa=self.empresa)
        CartItem.objects.create(id_carrito=carrito, id_variante=self.variante, cantidad=1)
        api = cliente_api("cliente@fidelidad-c.test")
        with mock.patch(CREAR_PAGO, return_value=("pi_fidelidad", "secreto")) as cobro:
            respuesta = api.post(
                "/api/sales/carritos/checkout/",
                {"id_sucursal": self.sucursal.id_sucursal, "tipo_entrega": "RETIRO"},
                format="json",
            )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        cobro.assert_called_once_with(Decimal("50.00"))
        self.assertTrue(servicio.estado(self.cliente, self.empresa)["disponible"])
        with mock.patch(VERIFICAR_PAGO, return_value="pi_fidelidad"):
            pagado = api.post(
                "/api/sales/carritos/confirmar_pago/", {"referencia_pago": "pi_fidelidad"}, format="json"
            )
        self.assertEqual(pagado.status_code, 200, pagado.data)
        orden = Order.objects.get(referencia_pago="pi_fidelidad")
        self.assertEqual(orden.total, Decimal("50.00"))
        self.assertTrue(servicio.compra_con_descuento(orden=orden))
        self.assertTrue(servicio.estado(self.cliente, self.empresa)["usado"])

    def test_compra_con_descuento_no_admite_devolucion_ni_cambio(self):
        """La venta con descuento queda bloqueada; la venta normal sí se puede devolver y cambiar."""
        con_descuento = self.vender()["id_venta"]
        normal = self.vender()["id_venta"]
        compra = cargar_compra("VENTA", con_descuento)
        self.assertIn("descuento por fidelidad", compra.problema_compra("TIENDA"))
        linea = PosSaleItem.objects.get(id_venta_id=con_descuento)
        self.assertIn("descuento por fidelidad", motivo_no_elegible(OrigenCambio(venta_item=linea), "TIENDA"))
        self.assertIsNone(cargar_compra("VENTA", normal).problema_compra("TIENDA"))
        linea_normal = PosSaleItem.objects.get(id_venta_id=normal)
        self.assertIsNone(motivo_no_elegible(OrigenCambio(venta_item=linea_normal), "TIENDA"))