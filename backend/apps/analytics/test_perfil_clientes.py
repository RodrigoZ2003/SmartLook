"""Pruebas del perfil de clientes por empresa (CU04).

- El ADMIN_EMPRESA solo ve a los clientes con actividad en su empresa: pedido
  web (no pendiente), compra en tienda con su correo o reserva pagada.
- El SUPER_ADMIN ve a todos, con sus empresas y el detalle por empresa.
- Total gastado = compras pagadas - reembolsos de devoluciones completadas.
- El perfil de un cliente ajeno responde 404; encargado y cliente reciben 403.
- El segmento de ML solo se muestra en las empresas donde el cliente compró.

Ejecutar:
    python manage.py test apps.analytics.test_perfil_clientes --settings=config.settings.test
"""
from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import EntrenamientoModelo, SegmentoCliente
from apps.reservations.models import FittingReservation
from apps.sales.models import Devolucion, Order, OrderItem, PosSale
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

URL = "/api/analytics/clientes/"


class PerfilClientesTests(TestCase):
    """Empresa A con pedidos y una reserva; empresa B con una compra en tienda."""

    @classmethod
    def setUpTestData(cls):
        """Clientes con actividad en A, en B, solo pendiente en A y sin actividad."""
        plan = crear_plan("PRUEBA_PERFIL", 10)
        ciudad = crear_ciudad()
        cls.empresa_a = crear_empresa("Empresa Perfil A", "empresa-perfil-a", plan)
        cls.empresa_b = crear_empresa("Empresa Perfil B", "empresa-perfil-b", plan)
        cls.sucursal_a = crear_sucursal(cls.empresa_a, "Sucursal PA1", ciudad)
        cls.sucursal_b = crear_sucursal(cls.empresa_b, "Sucursal PB1", ciudad)
        variante_a = crear_prenda(cls.empresa_a, cls.sucursal_a, "PERFIL-A-1", 20)
        crear_prenda(cls.empresa_b, cls.sucursal_b, "PERFIL-B-1", 20)

        crear_usuario("admin@perfil-a.test", "ADMIN_EMPRESA", cls.empresa_a)
        crear_usuario("admin@perfil-b.test", "ADMIN_EMPRESA", cls.empresa_b)
        crear_usuario("encargado@perfil-a.test", "ENCARGADO_SUCURSAL", cls.empresa_a, cls.sucursal_a)
        cajero_b = crear_usuario("cajero@perfil-b.test", "CAJERO", cls.empresa_b, cls.sucursal_b)
        crear_usuario("super@perfil.test", "SUPER_ADMIN")
        cls.c1 = Cliente.objects.get(id_usuario=crear_usuario("c1@perfil.test", "CLIENTE"))
        cls.c2 = Cliente.objects.get(id_usuario=crear_usuario("c2@perfil.test", "CLIENTE"))
        cls.c3 = Cliente.objects.get(id_usuario=crear_usuario("c3@perfil.test", "CLIENTE"))
        cls.c4 = Cliente.objects.get(id_usuario=crear_usuario("c4@perfil.test", "CLIENTE"))

        # c1: dos pedidos pagados en A (100 y 200) y una devolución completada de 50.
        pedido = None
        for total in ("100.00", "200.00"):
            pedido = Order.objects.create(
                id_cliente=cls.c1, id_sucursal=cls.sucursal_a, id_empresa=cls.empresa_a,
                total=Decimal(total), estado="PAGADA",
            )
            OrderItem.objects.create(
                id_orden=pedido, id_variante=variante_a, cantidad=1,
                precio_unitario=Decimal(total), subtotal=Decimal(total),
            )
        Devolucion.objects.create(
            id_orden=pedido, id_cliente=cls.c1, id_empresa=cls.empresa_a, id_sucursal=cls.sucursal_a,
            estado="COMPLETADA", monto_reembolso=Decimal("50.00"), fecha_completado=timezone.now(),
        )
        # c2: compra en tienda (POS con su correo) solo en B.
        PosSale.objects.create(
            id_sucursal=cls.sucursal_b, id_usuario=cajero_b, id_empresa=cls.empresa_b,
            id_cliente=cls.c2, total=Decimal("80.00"), metodo_pago="EFECTIVO",
        )
        # c3: solo una reserva pagada en A.
        FittingReservation.objects.create(
            id_cliente=cls.c3, id_sucursal=cls.sucursal_a, id_empresa=cls.empresa_a,
            fecha_reserva=timezone.localdate() + timedelta(days=2), hora_reserva=time(10, 0),
            estado="CONFIRMADA",
        )
        # c4: solo un pedido pendiente de pago en A (no es cliente de A).
        Order.objects.create(
            id_cliente=cls.c4, id_sucursal=cls.sucursal_a, id_empresa=cls.empresa_a,
            total=Decimal("90.00"), estado="PENDIENTE",
        )
        # Segmentación vigente en B que incluye a c1 (que nunca compró en B).
        entrenamiento = EntrenamientoModelo.objects.create(
            id_empresa=cls.empresa_b, tipo="SEGMENTACION", ventana_meses=12, algoritmo="KMeans", vigente=True,
        )
        SegmentoCliente.objects.create(
            id_entrenamiento=entrenamiento, id_empresa=cls.empresa_b, id_cliente=cls.c1, segmento="VIP",
            recencia_dias=3, frecuencia=10, monto=Decimal("900.00"),
        )

    def correos(self, correo_admin):
        """Correos de los clientes que ve un administrador."""
        datos = cliente_api(correo_admin).get(URL).data["clientes"]
        return {c["correo"] for c in datos}

    def test_admin_empresa_solo_ve_sus_clientes(self):
        """A ve a c1 (pedidos) y c3 (reserva); no a c2 (otra empresa) ni a c4 (pendiente)."""
        self.assertEqual(self.correos("admin@perfil-a.test"), {"c1@perfil.test", "c3@perfil.test"})

    def test_compra_en_tienda_cuenta_como_cliente(self):
        """B ve a c2, que solo compró en tienda con su correo."""
        self.assertEqual(self.correos("admin@perfil-b.test"), {"c2@perfil.test"})

    def test_super_admin_ve_a_todos(self):
        """El SUPER_ADMIN ve a c1, c2 y c3 con sus empresas."""
        datos = cliente_api("super@perfil.test").get(URL).data
        self.assertTrue(datos["super_admin"])
        por_correo = {c["correo"]: c for c in datos["clientes"]}
        self.assertEqual(set(por_correo), {"c1@perfil.test", "c2@perfil.test", "c3@perfil.test"})
        self.assertEqual(por_correo["c2@perfil.test"]["empresas"], ["Empresa Perfil B"])

    def test_total_gastado_resta_reembolsos(self):
        """c1: 100 + 200 - 50 de reembolso = 250 en 2 compras."""
        datos = cliente_api("admin@perfil-a.test").get(URL).data["clientes"]
        c1 = next(c for c in datos if c["correo"] == "c1@perfil.test")
        self.assertEqual(c1["compras"], 2)
        self.assertEqual(c1["total_gastado"], 250.0)

    def test_perfil_de_cliente_propio_y_ajeno(self):
        """A abre el perfil de c1; el de c2 (cliente de B) responde 404."""
        api = cliente_api("admin@perfil-a.test")
        self.assertEqual(api.get(f"{URL}{self.c2.id_cliente}/").status_code, 404)
        r = api.get(f"{URL}{self.c1.id_cliente}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["resumen"]["compras"], 2)
        self.assertEqual(r.data["resumen"]["ticket_promedio"], 150.0)
        self.assertEqual(r.data["resumen"]["devoluciones"], 1)
        self.assertEqual(r.data["preferencias"]["prendas"][0]["nombre"], "Polera PERFIL-A-1")
        self.assertEqual(r.data["preferencias"]["tallas"][0]["nombre"], "M")
        tipos = {h["tipo"] for h in r.data["historial"]}
        self.assertEqual(tipos, {"PEDIDO", "DEVOLUCION"})
        self.assertEqual(r.data["por_empresa"], [])

    def test_super_admin_ve_el_detalle_por_empresa(self):
        """El perfil del SUPER_ADMIN trae las compras por empresa."""
        r = cliente_api("super@perfil.test").get(f"{URL}{self.c1.id_cliente}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["por_empresa"], [{"empresa": "Empresa Perfil A", "compras": 2, "total": 300.0}])

    def test_segmento_solo_en_empresas_donde_compro(self):
        """El segmento VIP de c1 en B no se muestra: c1 nunca compró en B."""
        datos = cliente_api("super@perfil.test").get(URL).data["clientes"]
        c1 = next(c for c in datos if c["correo"] == "c1@perfil.test")
        self.assertEqual(c1["segmentos"], [])
        r = cliente_api("super@perfil.test").get(f"{URL}{self.c1.id_cliente}/")
        self.assertEqual(r.data["segmentos"], [])

    def test_encargado_y_cliente_no_acceden(self):
        """Solo SUPER_ADMIN y ADMIN_EMPRESA."""
        self.assertEqual(cliente_api("encargado@perfil-a.test").get(URL).status_code, 403)
        self.assertEqual(cliente_api("c1@perfil.test").get(URL).status_code, 403)