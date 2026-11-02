"""Pruebas de la devolución con reembolso y nota de devolución (Fase 2 - CU12).

- En tienda: se completa en el momento. "Ya no la quiero" devuelve el 90%
  (la empresa retiene el 10%); "dañada" devuelve el 100% y no vuelve al stock.
- Con recojo: el cliente la solicita, el encargado la aprueba con repartidor
  y fecha (máximo 48 h), el repartidor la completa y recién ahí se repone el
  stock y se reembolsa en Stripe (el reembolso real se simula con mock).
- Reglas: envío solo por culpa de la tienda y una vez por pedido, plazo de
  7 días, no más de lo comprado, prenda con cambio, rechazo, falla de Stripe,
  roles y aislamiento por empresa.

Ejecutar: python manage.py test apps.sales.test_devoluciones
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import ProductoVariante, Talla
from apps.inventory.models import StockItem
from apps.sales.integrations.stripe_payment import PagoRechazadoError
from apps.sales.models import Delivery, Devolucion, Order, OrderItem
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

URL = "/api/sales/devoluciones/"
REEMBOLSO = "apps.sales.devoluciones.reembolsar_pago"


class DevolucionTests(TestCase):
    """Flujo completo de la devolución con reembolso y sus reglas."""

    @classmethod
    def setUpTestData(cls):
        """Polera M (Bs 100) y L, con el personal de la empresa y un cliente."""
        plan = crear_plan("PRUEBA_DEVOLUCIONES", 10)
        cls.empresa = crear_empresa("Empresa Devoluciones", "empresa-devoluciones", plan)
        cls.sucursal = crear_sucursal(cls.empresa, "Sucursal Devoluciones", crear_ciudad())
        cls.m = crear_prenda(cls.empresa, cls.sucursal, "DEVOL-M", 10)
        cls.l = ProductoVariante.objects.create(
            id_producto=cls.m.id_producto,
            id_talla=Talla.objects.get_or_create(nombre="L")[0],
            id_color=cls.m.id_color,
            codigo_producto="DEVOL-L",
            precio=Decimal("100.00"),
            cantidad=5,
        )
        StockItem.objects.create(
            id_sucursal=cls.sucursal, id_variante=cls.l, cantidad=5, id_empresa=cls.empresa
        )
        crear_usuario("cajero@devol.test", "CAJERO", cls.empresa, cls.sucursal)
        crear_usuario("admin@devol.test", "ADMIN_EMPRESA", cls.empresa)
        cls.repartidor = crear_usuario("repartidor@devol.test", "REPARTIDOR", cls.empresa)
        usuario_cliente = crear_usuario("cliente@devol.test", "CLIENTE")
        cls.cliente = Cliente.objects.get(id_usuario=usuario_cliente)
        otra = crear_empresa("Otra Devoluciones", "otra-devoluciones", plan)
        crear_usuario("admin@otra-devol.test", "ADMIN_EMPRESA", otra)

    def setUp(self):
        """Sesiones de cada rol."""
        self.cajero = cliente_api("cajero@devol.test")
        self.admin = cliente_api("admin@devol.test")
        self.rep = cliente_api("repartidor@devol.test")
        self.cli = cliente_api("cliente@devol.test")

    # ---------------------------------------------------------------- utilidades
    def stock(self, variante):
        """Unidades de la variante en la sucursal."""
        return StockItem.objects.get(id_sucursal=self.sucursal, id_variante=variante).cantidad

    def venta_pos(self):
        """Venta POS en efectivo de 1 polera M; devuelve (id venta, id línea)."""
        respuesta = self.cajero.post(
            "/api/sales/ventas-pos/registrar/",
            {"id_sucursal": self.sucursal.id_sucursal, "metodo_pago": "EFECTIVO",
             "items": [{"id_variante": self.m.id_variante, "cantidad": 1}]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return respuesta.data["id_venta"], respuesta.data["items"][0]["id_item"]

    def pedido_entregado(self, dias_desde_entrega=0, lineas=1):
        """Pedido con delivery (envío Bs 20) pagado en Stripe y entregado hace N días.

        Tiene `lineas` prendas de 1 unidad (M, y L si son 2). Devuelve (orden, [ids de línea]).
        """
        variantes = [self.m, self.l][:lineas]
        orden = Order.objects.create(
            id_cliente=self.cliente, id_sucursal=self.sucursal,
            total=Decimal("100.00") * lineas + Decimal("20.00"), estado="ENTREGADA",
            tipo_entrega="DELIVERY", costo_envio=Decimal("20.00"), metodo_pago="TARJETA",
            referencia_pago="pi_prueba",
        )
        ids = [
            OrderItem.objects.create(
                id_orden=orden, id_variante=variante, cantidad=1,
                precio_unitario=Decimal("100.00"), subtotal=Decimal("100.00"),
            ).id_item
            for variante in variantes
        ]
        Delivery.objects.create(
            id_orden=orden, direccion="Calle Prueba 1", latitud=0, longitud=0, distancia_km=1,
            costo_envio=Decimal("20.00"), estado="ENTREGADO",
            fecha_entrega=timezone.now() - timedelta(days=dias_desde_entrega),
        )
        return orden, ids

    def en_tienda(self, numero, id_item, motivo, tipo="VENTA", condiciones=True):
        """El cajero registra la devolución en la tienda."""
        return self.cajero.post(
            f"{URL}registrar-tienda/",
            {"tipo": tipo, "numero": numero, "condiciones_ok": condiciones,
             "items": [{"id_item": id_item, "cantidad": 1, "motivo": motivo}]},
            format="json",
        )

    def solicitar(self, orden, id_item, motivo="ERROR_TIENDA", cantidad=1):
        """El cliente solicita la devolución con recojo."""
        return self.cli.post(
            f"{URL}solicitar/",
            {"id_orden": orden.id_orden,
             "items": [{"id_item": id_item, "cantidad": cantidad, "motivo": motivo}]},
            format="json",
        )

    def recoger(self, id_devolucion):
        """Aprobación con recojo en 24 h y repartidor en camino."""
        aprobado = self.admin.post(
            f"{URL}{id_devolucion}/aprobar/",
            {"id_repartidor": self.repartidor.id_usuario,
             "fecha_programada": (timezone.now() + timedelta(hours=24)).isoformat()},
            format="json",
        )
        self.assertEqual(aprobado.status_code, 200, aprobado.data)
        self.assertEqual(self.rep.post(f"{URL}{id_devolucion}/en-camino/").status_code, 200)

    # ---------------------------------------------------------------- en tienda
    def test_ya_no_la_quiere_devuelve_el_90_por_ciento(self):
        """NO_LA_QUIERO: retiene el 10%, efectivo en caja y la prenda vuelve al stock."""
        id_venta, id_item = self.venta_pos()
        stock = self.stock(self.m)
        respuesta = self.en_tienda(id_venta, id_item, "NO_LA_QUIERO")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        datos = respuesta.data
        self.assertEqual(datos["estado"], "COMPLETADA")
        self.assertTrue(datos["numero_nota"].startswith("ND-"))
        self.assertEqual(Decimal(datos["monto_retenido"]), Decimal("10.00"))
        self.assertEqual(Decimal(datos["monto_reembolso"]), Decimal("90.00"))
        self.assertEqual(datos["metodo_reembolso"], "EFECTIVO")
        self.assertIn("se queda con el 10%", datos["resumen_reembolso"])
        self.assertIn("Se le devuelve Bs 90.00", datos["resumen_reembolso"])
        self.assertEqual(self.stock(self.m), stock + 1)

    def test_danada_devuelve_el_100_y_no_vuelve_al_stock(self):
        """PRODUCTO_DANADO: reembolso completo y la prenda no se repone."""
        id_venta, id_item = self.venta_pos()
        stock = self.stock(self.m)
        respuesta = self.en_tienda(id_venta, id_item, "PRODUCTO_DANADO")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(Decimal(respuesta.data["monto_reembolso"]), Decimal("100.00"))
        self.assertEqual(Decimal(respuesta.data["monto_retenido"]), Decimal("0.00"))
        self.assertFalse(respuesta.data["items"][0]["repone_stock"])
        self.assertEqual(self.stock(self.m), stock)

    def test_tienda_exige_revisar_la_prenda(self):
        """Sin confirmar las condiciones de la prenda no se registra."""
        id_venta, id_item = self.venta_pos()
        respuesta = self.en_tienda(id_venta, id_item, "NO_LA_QUIERO", condiciones=False)
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(Devolucion.objects.count(), 0)

    def test_calcular_no_guarda_nada(self):
        """El cálculo previo muestra los montos sin crear la devolución."""
        id_venta, id_item = self.venta_pos()
        respuesta = self.cajero.post(
            f"{URL}calcular/",
            {"tipo": "VENTA", "numero": id_venta,
             "items": [{"id_item": id_item, "cantidad": 1, "motivo": "NO_LA_QUIERO"}]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(Decimal(respuesta.data["monto_reembolso"]), Decimal("90.00"))
        self.assertEqual(Devolucion.objects.count(), 0)

    # ---------------------------------------------------------------- con recojo
    def test_flujo_con_recojo_reembolsa_en_stripe(self):
        """Solicitada -> Programada -> En camino -> Completada; 100% + envío a la tarjeta."""
        orden, (id_item,) = self.pedido_entregado()
        respuesta = self.solicitar(orden, id_item, "ERROR_TIENDA")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        id_devolucion = respuesta.data["id_devolucion"]
        self.assertEqual(respuesta.data["estado"], "SOLICITADA")
        self.assertEqual(Decimal(respuesta.data["monto_envio"]), Decimal("20.00"))
        self.assertEqual(Decimal(respuesta.data["monto_reembolso"]), Decimal("120.00"))
        self.assertIn("te devolveremos Bs 120.00", respuesta.data["mensaje_cliente"])
        stock = self.stock(self.m)
        self.recoger(id_devolucion)
        self.assertIn("en camino", self.cli.get(f"{URL}{id_devolucion}/").data["mensaje_cliente"])
        sin_revisar = self.rep.post(f"{URL}{id_devolucion}/completar/", {"condiciones_ok": False}, format="json")
        self.assertEqual(sin_revisar.status_code, 400)
        with mock.patch(REEMBOLSO, return_value="re_prueba") as reembolso:
            completada = self.rep.post(
                f"{URL}{id_devolucion}/completar/", {"condiciones_ok": True}, format="json"
            )
        self.assertEqual(completada.status_code, 200, completada.data)
        reembolso.assert_called_once_with("pi_prueba", Decimal("120.00"))
        self.assertEqual(completada.data["estado"], "COMPLETADA")
        self.assertEqual(completada.data["metodo_reembolso"], "STRIPE")
        self.assertEqual(completada.data["referencia_reembolso"], "re_prueba")
        self.assertEqual(self.stock(self.m), stock + 1)

    def test_si_stripe_falla_no_se_completa(self):
        """Si Stripe rechaza el reembolso, la devolución sigue en camino y el stock no cambia."""
        orden, (id_item,) = self.pedido_entregado()
        id_devolucion = self.solicitar(orden, id_item).data["id_devolucion"]
        self.recoger(id_devolucion)
        stock = self.stock(self.m)
        with mock.patch(REEMBOLSO, side_effect=PagoRechazadoError("tarjeta cerrada")):
            respuesta = self.rep.post(
                f"{URL}{id_devolucion}/completar/", {"condiciones_ok": True}, format="json"
            )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("Stripe", respuesta.data["error"])
        self.assertEqual(Devolucion.objects.get(pk=id_devolucion).estado, "EN_CAMINO")
        self.assertEqual(self.stock(self.m), stock)

    def test_el_envio_se_devuelve_una_sola_vez(self):
        """La segunda devolución del mismo pedido (culpa de la tienda) ya no incluye el envío."""
        orden, (id_m, id_l) = self.pedido_entregado(lineas=2)
        primera = self.solicitar(orden, id_m, "PRODUCTO_DANADO")
        self.assertEqual(Decimal(primera.data["monto_envio"]), Decimal("20.00"))
        segunda = self.solicitar(orden, id_l, "ERROR_TIENDA")
        self.assertEqual(segunda.status_code, 201, segunda.data)
        self.assertEqual(Decimal(segunda.data["monto_envio"]), Decimal("0.00"))
        self.assertEqual(Decimal(segunda.data["monto_reembolso"]), Decimal("100.00"))

    def test_ya_no_la_quiere_no_devuelve_el_envio(self):
        """Por decisión del cliente se devuelve el 90% de la prenda y nada del envío."""
        orden, (id_item,) = self.pedido_entregado()
        respuesta = self.solicitar(orden, id_item, "NO_LA_QUIERO")
        self.assertEqual(Decimal(respuesta.data["monto_envio"]), Decimal("0.00"))
        self.assertEqual(Decimal(respuesta.data["monto_reembolso"]), Decimal("90.00"))

    def test_no_se_devuelve_mas_de_lo_comprado(self):
        """No se puede pedir más unidades de las compradas ni repetir la devolución."""
        orden, (id_item,) = self.pedido_entregado()
        self.assertEqual(self.solicitar(orden, id_item, cantidad=2).status_code, 400)
        self.assertEqual(self.solicitar(orden, id_item).status_code, 201)
        repetida = self.solicitar(orden, id_item)
        self.assertEqual(repetida.status_code, 400)
        self.assertIn("ya se devolvió", repetida.data["error"])

    def test_plazo_de_7_dias_vencido(self):
        """Un pedido entregado hace 8 días ya no admite devolución."""
        orden, (id_item,) = self.pedido_entregado(dias_desde_entrega=8)
        respuesta = self.solicitar(orden, id_item)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("Venció el plazo", respuesta.data["error"])

    def test_rechazada_permite_volver_a_solicitar(self):
        """Una devolución rechazada no cuenta: la prenda se puede volver a devolver."""
        orden, (id_item,) = self.pedido_entregado()
        id_devolucion = self.solicitar(orden, id_item).data["id_devolucion"]
        rechazo = self.admin.post(f"{URL}{id_devolucion}/rechazar/", {"motivo": "Prenda usada"}, format="json")
        self.assertEqual(rechazo.status_code, 200, rechazo.data)
        self.assertEqual(rechazo.data["estado"], "RECHAZADA")
        self.assertEqual(self.solicitar(orden, id_item).status_code, 201)

    def test_prenda_con_cambio_no_se_devuelve(self):
        """Una prenda que ya tuvo un cambio de talla o color no se puede devolver."""
        id_venta, id_item = self.venta_pos()
        cambio = self.cajero.post(
            "/api/sales/cambios/registrar-tienda/",
            {"id_venta_item": id_item, "motivo": "NO_LE_QUEDA", "id_variante": self.l.id_variante,
             "condiciones_ok": True},
            format="json",
        )
        self.assertEqual(cambio.status_code, 201, cambio.data)
        respuesta = self.en_tienda(id_venta, id_item, "NO_LA_QUIERO")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("cambio", respuesta.data["error"])

    def test_mis_pedidos_muestra_la_devolucion(self):
        """El pedido indica el plazo y el estado de su devolución."""
        orden, (id_item,) = self.pedido_entregado()
        antes = self.cli.get(f"/api/sales/ordenes/{orden.id_orden}/").data
        self.assertTrue(antes["puede_solicitar_devolucion"])
        self.solicitar(orden, id_item, "NO_LA_QUIERO")
        despues = self.cli.get(f"/api/sales/ordenes/{orden.id_orden}/").data
        self.assertFalse(despues["puede_solicitar_devolucion"])
        self.assertEqual(despues["devoluciones"][0]["estado"], "SOLICITADA")

    # ---------------------------------------------------------------- roles y empresas
    def test_el_cliente_no_aprueba(self):
        """Aprobar es del encargado o el administrador (el cliente recibe 403)."""
        orden, (id_item,) = self.pedido_entregado()
        id_devolucion = self.solicitar(orden, id_item).data["id_devolucion"]
        self.assertEqual(self.cli.post(f"{URL}{id_devolucion}/aprobar/", {}, format="json").status_code, 403)

    def test_otra_empresa_no_ve_la_compra_ni_la_devolucion(self):
        """El administrador de otra empresa no encuentra la venta ni la devolución."""
        id_venta, id_item = self.venta_pos()
        id_devolucion = self.en_tienda(id_venta, id_item, "NO_LA_QUIERO").data["id_devolucion"]
        ajeno = cliente_api("admin@otra-devol.test")
        buscar = ajeno.get(f"{URL}buscar-compra/", {"tipo": "VENTA", "numero": id_venta})
        self.assertEqual(buscar.status_code, 404)
        self.assertEqual(ajeno.get(f"{URL}{id_devolucion}/").status_code, 404)