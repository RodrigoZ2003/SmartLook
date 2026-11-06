"""Pruebas de la API del descuento por fidelidad (CU18).

- Solo el SUPER_ADMIN cambia la regla; el ADMIN_EMPRESA la ve.
- Monitoreo: el ADMIN_EMPRESA ve solo a los clientes de su empresa; el
  SUPER_ADMIN, a todos.
- El cliente ve su progreso del mes por empresa.
- El POS web consulta si el cliente (por su correo) tiene el descuento.

Ejecutar:
    python manage.py test apps.fidelidad.test_api --settings=config.settings.test
"""
from decimal import Decimal

from django.test import TestCase

from apps.fidelidad.models import ReglaFidelidad
from apps.sales.models import Order, OrderItem
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

URL = "/api/fidelidad/"


class FidelidadApiTests(TestCase):
    """Cliente con 5 compras en A y 1 en B."""

    @classmethod
    def setUpTestData(cls):
        """Dos empresas con su administrador, un cajero en A y un cliente."""
        plan = crear_plan("PRUEBA_FIDELIDAD_API", 10)
        ciudad = crear_ciudad()
        cls.empresa_a = crear_empresa("Empresa Fidelidad D", "empresa-fidelidad-d", plan)
        cls.empresa_b = crear_empresa("Empresa Fidelidad E", "empresa-fidelidad-e", plan)
        cls.sucursal_a = crear_sucursal(cls.empresa_a, "Sucursal FD1", ciudad)
        cls.sucursal_b = crear_sucursal(cls.empresa_b, "Sucursal FE1", ciudad)
        variante_a = crear_prenda(cls.empresa_a, cls.sucursal_a, "FID-D-1", 20)
        variante_b = crear_prenda(cls.empresa_b, cls.sucursal_b, "FID-E-1", 20)
        crear_usuario("super@fidelidad-api.test", "SUPER_ADMIN")
        crear_usuario("admin@fidelidad-d.test", "ADMIN_EMPRESA", cls.empresa_a)
        crear_usuario("admin@fidelidad-e.test", "ADMIN_EMPRESA", cls.empresa_b)
        crear_usuario("cajero@fidelidad-d.test", "CAJERO", cls.empresa_a, cls.sucursal_a)
        cls.cliente = Cliente.objects.get(id_usuario=crear_usuario("cliente@fidelidad-api.test", "CLIENTE"))
        compras = [(cls.empresa_a, cls.sucursal_a, variante_a)] * 5 + [(cls.empresa_b, cls.sucursal_b, variante_b)]
        for empresa, sucursal, variante in compras:
            orden = Order.objects.create(
                id_cliente=cls.cliente, id_sucursal=sucursal, id_empresa=empresa,
                total=Decimal("100.00"), estado="PAGADA",
            )
            OrderItem.objects.create(
                id_orden=orden, id_variante=variante, cantidad=1,
                precio_unitario=Decimal("100.00"), subtotal=Decimal("100.00"),
            )

    def test_solo_el_super_admin_cambia_la_regla(self):
        """El ADMIN_EMPRESA ve la regla pero no la cambia; el SUPER_ADMIN sí."""
        datos = {"compras_requeridas": 1, "porcentaje": 30, "activa": True}
        admin = cliente_api("admin@fidelidad-d.test")
        self.assertEqual(admin.get(f"{URL}regla/").data["compras_requeridas"], 5)
        self.assertEqual(admin.put(f"{URL}regla/", datos, format="json").status_code, 403)
        respuesta = cliente_api("super@fidelidad-api.test").put(f"{URL}regla/", datos, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["porcentaje"], 30.0)
        self.assertEqual(respuesta.data["ganaron_ahora"], 1)
        self.assertEqual(ReglaFidelidad.vigente().compras_requeridas, 1)

    def test_regla_invalida(self):
        """Porcentaje fuera de 1-100 o compras fuera de 1-50 se rechazan."""
        api = cliente_api("super@fidelidad-api.test")
        malos = [
            {"compras_requeridas": 5, "porcentaje": 120, "activa": True},
            {"compras_requeridas": 0, "porcentaje": 50, "activa": True},
            {"compras_requeridas": 5, "porcentaje": 50},
        ]
        for datos in malos:
            self.assertEqual(api.put(f"{URL}regla/", datos, format="json").status_code, 400)

    def test_monitoreo_aislado_por_empresa(self):
        """El administrador de A solo ve la fila de A; el SUPER_ADMIN ve A y B."""
        datos = cliente_api("admin@fidelidad-d.test").get(f"{URL}monitoreo/").data
        self.assertEqual([f["empresa"] for f in datos["clientes"]], ["Empresa Fidelidad D"])
        self.assertEqual(datos["clientes"][0]["estado"], "DISPONIBLE")
        self.assertEqual(datos["resumen"]["por_usar"], 1)
        todos = cliente_api("super@fidelidad-api.test").get(f"{URL}monitoreo/").data
        self.assertEqual(len(todos["clientes"]), 2)
        self.assertEqual(cliente_api("cajero@fidelidad-d.test").get(f"{URL}monitoreo/").status_code, 403)

    def test_progreso_del_cliente(self):
        """El cliente ve A con el descuento disponible y B con 1 de 5."""
        datos = cliente_api("cliente@fidelidad-api.test").get(f"{URL}mi-progreso/").data
        por_empresa = {f["empresa"]: f for f in datos["empresas"]}
        self.assertTrue(por_empresa["Empresa Fidelidad D"]["disponible"])
        self.assertEqual(por_empresa["Empresa Fidelidad E"]["faltan"], 4)

    def test_consulta_del_pos(self):
        """El cajero de A ve que el cliente tiene el descuento; no puede consultar con una sucursal de B."""
        api = cliente_api("cajero@fidelidad-d.test")
        respuesta = api.get(
            f"{URL}pos/", {"correo": "cliente@fidelidad-api.test", "id_sucursal": self.sucursal_a.pk}
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertTrue(respuesta.data["disponible"])
        self.assertEqual(respuesta.data["porcentaje"], 50.0)
        otra = api.get(f"{URL}pos/", {"correo": "cliente@fidelidad-api.test", "id_sucursal": self.sucursal_b.pk})
        self.assertEqual(otra.status_code, 404)