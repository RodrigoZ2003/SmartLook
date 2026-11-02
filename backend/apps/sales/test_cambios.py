"""Pruebas del cambio de prenda por talla o color (Fase 2 - CU05) y de la
consulta de cambios del mes (CU06).

- En tienda (NO_LE_QUEDA): se completa en el momento; sale la prenda nueva
  y entra la devuelta.
- Con delivery (ERROR_TIENDA): el cliente lo solicita, el encargado lo aprueba
  con repartidor y fecha (máximo 48 h), el repartidor lo completa. Sale la
  prenda enviada por error al aprobar y vuelve al completar; la comprada no
  se toca.
- Reglas: plazo de 7 días, un cambio por prenda, mismo precio, condiciones de
  la prenda, rechazo que revierte el stock, roles y aislamiento por empresa.

Ejecutar: python manage.py test apps.sales.test_cambios
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import ProductoVariante, Talla
from apps.inventory.models import StockItem
from apps.sales.models import CambioPrenda, Delivery, Order, OrderItem
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

URL = "/api/sales/cambios/"


class CambioPrendaTests(TestCase):
    """Flujo completo del cambio de prenda y sus reglas."""

    @classmethod
    def setUpTestData(cls):
        """Polera M (comprada), L (mismo precio) y XL (otro precio), con su personal."""
        plan = crear_plan("PRUEBA_CAMBIOS", 10)
        cls.empresa = crear_empresa("Empresa Cambios", "empresa-cambios", plan)
        cls.sucursal = crear_sucursal(cls.empresa, "Sucursal Cambios", crear_ciudad())
        cls.m = crear_prenda(cls.empresa, cls.sucursal, "CAMBIO-M", 10)
        cls.l = cls._otra_talla("L", "CAMBIO-L", Decimal("100.00"), 5)
        cls.xl = cls._otra_talla("XL", "CAMBIO-XL", Decimal("120.00"), 5)
        crear_usuario("cajero@cambios.test", "CAJERO", cls.empresa, cls.sucursal)
        crear_usuario("admin@cambios.test", "ADMIN_EMPRESA", cls.empresa)
        cls.repartidor = crear_usuario("repartidor@cambios.test", "REPARTIDOR", cls.empresa)
        usuario_cliente = crear_usuario("cliente@cambios.test", "CLIENTE")
        cls.cliente = Cliente.objects.get(id_usuario=usuario_cliente)
        otra = crear_empresa("Otra Cambios", "otra-cambios", plan)
        crear_usuario("admin@otra-cambios.test", "ADMIN_EMPRESA", otra)

    @classmethod
    def _otra_talla(cls, talla, codigo, precio, stock):
        """Otra variante de la misma polera con su stock en la sucursal."""
        variante = ProductoVariante.objects.create(
            id_producto=cls.m.id_producto,
            id_talla=Talla.objects.get_or_create(nombre=talla)[0],
            id_color=cls.m.id_color,
            codigo_producto=codigo,
            precio=precio,
            cantidad=stock,
        )
        StockItem.objects.create(
            id_sucursal=cls.sucursal, id_variante=variante, cantidad=stock, id_empresa=cls.empresa
        )
        return variante

    def setUp(self):
        """Sesiones de cada rol."""
        self.cajero = cliente_api("cajero@cambios.test")
        self.admin = cliente_api("admin@cambios.test")
        self.rep = cliente_api("repartidor@cambios.test")
        self.cli = cliente_api("cliente@cambios.test")

    # ---------------------------------------------------------------- utilidades
    def stock(self, variante):
        """Unidades de la variante en la sucursal."""
        return StockItem.objects.get(id_sucursal=self.sucursal, id_variante=variante).cantidad

    def venta_pos(self):
        """Venta POS de 1 polera M; devuelve el id de su línea."""
        respuesta = self.cajero.post(
            "/api/sales/ventas-pos/registrar/",
            {"id_sucursal": self.sucursal.id_sucursal, "metodo_pago": "EFECTIVO",
             "items": [{"id_variante": self.m.id_variante, "cantidad": 1}]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return respuesta.data["items"][0]["id_item"]

    def pedido_entregado(self, dias_desde_entrega=0):
        """Pedido con delivery de 1 polera M entregado hace N días; devuelve su línea."""
        orden = Order.objects.create(
            id_cliente=self.cliente, id_sucursal=self.sucursal, total=Decimal("100.00"),
            estado="ENTREGADA", tipo_entrega="DELIVERY",
        )
        item = OrderItem.objects.create(
            id_orden=orden, id_variante=self.m, cantidad=1,
            precio_unitario=Decimal("100.00"), subtotal=Decimal("100.00"),
        )
        Delivery.objects.create(
            id_orden=orden, direccion="Calle Prueba 1", latitud=0, longitud=0, distancia_km=1,
            costo_envio=0, estado="ENTREGADO",
            fecha_entrega=timezone.now() - timedelta(days=dias_desde_entrega),
        )
        return item.id_item

    def solicitar(self, id_orden_item, motivo="ERROR_TIENDA", variante=None):
        """El cliente solicita el cambio."""
        return self.cli.post(
            f"{URL}solicitar/",
            {"id_orden_item": id_orden_item, "motivo": motivo,
             "id_variante": (variante or self.l).id_variante},
            format="json",
        )

    def aprobar(self, id_cambio, horas=24):
        """El administrador aprueba con el repartidor y una visita en N horas."""
        return self.admin.post(
            f"{URL}{id_cambio}/aprobar/",
            {"id_repartidor": self.repartidor.id_usuario,
             "fecha_programada": (timezone.now() + timedelta(hours=horas)).isoformat()},
            format="json",
        )

    # ---------------------------------------------------------------- en tienda
    def test_cambio_en_tienda_mueve_el_stock(self):
        """NO_LE_QUEDA en tienda: COMPLETADO, entra la M devuelta y sale la L."""
        id_item = self.venta_pos()
        m, l = self.stock(self.m), self.stock(self.l)
        respuesta = self.cajero.post(
            f"{URL}registrar-tienda/",
            {"id_venta_item": id_item, "motivo": "NO_LE_QUEDA", "id_variante": self.l.id_variante,
             "condiciones_ok": True},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data["estado"], "COMPLETADO")
        self.assertTrue(respuesta.data["numero_nota"].startswith("NC-"))
        self.assertEqual(self.stock(self.m), m + 1)
        self.assertEqual(self.stock(self.l), l - 1)

    def test_un_solo_cambio_por_prenda(self):
        """La misma prenda no se puede cambiar dos veces."""
        id_item = self.venta_pos()
        datos = {"id_venta_item": id_item, "motivo": "NO_LE_QUEDA",
                 "id_variante": self.l.id_variante, "condiciones_ok": True}
        self.assertEqual(self.cajero.post(f"{URL}registrar-tienda/", datos, format="json").status_code, 201)
        segunda = self.cajero.post(f"{URL}registrar-tienda/", datos, format="json")
        self.assertEqual(segunda.status_code, 400)
        self.assertIn("ya tiene un cambio", segunda.data["error"])

    def test_tienda_exige_verificar_condiciones(self):
        """Sin confirmar que la prenda está sin uso y con etiqueta, no se registra."""
        respuesta = self.cajero.post(
            f"{URL}registrar-tienda/",
            {"id_venta_item": self.venta_pos(), "motivo": "NO_LE_QUEDA",
             "id_variante": self.l.id_variante, "condiciones_ok": False},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400)

    def test_no_le_queda_solo_al_mismo_precio(self):
        """No se puede cambiar a una talla con otro precio."""
        respuesta = self.solicitar(self.pedido_entregado(), "NO_LE_QUEDA", self.xl)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("mismo precio", respuesta.data["error"])

    # ---------------------------------------------------------------- con delivery
    def test_flujo_delivery_por_error_de_la_tienda(self):
        """Solicitado -> Programado -> En camino -> Completado, con el stock correcto."""
        respuesta = self.solicitar(self.pedido_entregado())
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        id_cambio = respuesta.data["id_cambio"]
        self.assertEqual(respuesta.data["estado"], "SOLICITADO")
        m, l = self.stock(self.m), self.stock(self.l)
        aprobado = self.aprobar(id_cambio)
        self.assertEqual(aprobado.status_code, 200, aprobado.data)
        self.assertEqual(aprobado.data["estado"], "PROGRAMADO")
        self.assertEqual(self.stock(self.l), l - 1)
        self.assertEqual(self.stock(self.m), m)
        vista_cliente = self.cli.get(f"{URL}{id_cambio}/")
        self.assertIn("pasará el", vista_cliente.data["mensaje_cliente"])
        self.assertEqual(self.rep.post(f"{URL}{id_cambio}/en-camino/").status_code, 200)
        completado = self.rep.post(f"{URL}{id_cambio}/completar/", {"condiciones_ok": True}, format="json")
        self.assertEqual(completado.status_code, 200, completado.data)
        self.assertEqual(completado.data["estado"], "COMPLETADO")
        self.assertEqual(self.stock(self.l), l)
        self.assertEqual(self.stock(self.m), m)

    def test_visita_fuera_de_las_48_horas(self):
        """La fecha de la visita debe estar dentro de las 48 horas."""
        id_cambio = self.solicitar(self.pedido_entregado()).data["id_cambio"]
        self.assertEqual(self.aprobar(id_cambio, horas=72).status_code, 400)

    def test_plazo_de_7_dias_vencido(self):
        """Un pedido entregado hace 8 días ya no admite cambio."""
        respuesta = self.solicitar(self.pedido_entregado(dias_desde_entrega=8))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("Venció el plazo", respuesta.data["error"])

    def test_rechazar_un_cambio_aprobado_revierte_el_stock(self):
        """Si se rechaza después de aprobar, la prenda descontada vuelve al stock."""
        id_cambio = self.solicitar(self.pedido_entregado()).data["id_cambio"]
        l = self.stock(self.l)
        self.aprobar(id_cambio)
        rechazo = self.admin.post(f"{URL}{id_cambio}/rechazar/", {"motivo": "Prenda usada"}, format="json")
        self.assertEqual(rechazo.status_code, 200, rechazo.data)
        self.assertEqual(rechazo.data["estado"], "RECHAZADO")
        self.assertEqual(self.stock(self.l), l)

    # ---------------------------------------------------------------- roles y empresas
    def test_el_cliente_no_aprueba(self):
        """Aprobar es del encargado o el administrador (el cliente recibe 403)."""
        id_cambio = self.solicitar(self.pedido_entregado()).data["id_cambio"]
        respuesta = self.cli.post(f"{URL}{id_cambio}/aprobar/", {}, format="json")
        self.assertEqual(respuesta.status_code, 403)

    def test_otra_empresa_no_ve_el_cambio(self):
        """El administrador de otra empresa no ve ni aprueba el cambio."""
        id_cambio = self.solicitar(self.pedido_entregado()).data["id_cambio"]
        ajeno = cliente_api("admin@otra-cambios.test")
        self.assertEqual(ajeno.get(f"{URL}{id_cambio}/").status_code, 404)
        self.assertEqual(ajeno.post(f"{URL}{id_cambio}/aprobar/", {}, format="json").status_code, 404)

    # ---------------------------------------------------------------- CU06
    def test_resumen_del_mes(self):
        """La consulta del mes cuenta los cambios por estado y motivo."""
        self.cajero.post(
            f"{URL}registrar-tienda/",
            {"id_venta_item": self.venta_pos(), "motivo": "NO_LE_QUEDA",
             "id_variante": self.l.id_variante, "condiciones_ok": True},
            format="json",
        )
        self.solicitar(self.pedido_entregado())
        resumen = self.admin.get(f"{URL}resumen-mes/").data
        self.assertEqual(resumen["total"], 2)
        self.assertEqual(resumen["completados"], 1)
        self.assertEqual(resumen["en_proceso"], 1)
        self.assertEqual(resumen["por_motivo"], {"NO_LE_QUEDA": 1, "ERROR_TIENDA": 1})
        self.assertEqual(CambioPrenda.objects.count(), 2)