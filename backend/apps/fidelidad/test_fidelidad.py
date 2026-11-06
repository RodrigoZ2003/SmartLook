"""Pruebas del descuento por fidelidad (CU18): conteo y beneficio.

- Cuentan los pedidos web pagados y las ventas POS registradas con el correo
  del cliente, por empresa y por mes calendario (hora de Bolivia).
- No cuentan: pedidos pendientes o cancelados, ventas anuladas, compras de
  otro mes ni compras devueltas por completo (la devolución parcial sí cuenta).
- Al llegar a la meta se avisa al cliente una sola vez; el descuento se usa
  una vez por mes y no se aplica si la compra lleva prendas reservadas.
- La regla (compras y porcentaje) la elige el SUPER_ADMIN y aplica de inmediato.

Ejecutar:
    python manage.py test apps.fidelidad.test_fidelidad --settings=config.settings.test
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.fidelidad import servicio
from apps.fidelidad.models import BeneficioFidelidad, ReglaFidelidad
from apps.sales.models import Devolucion, DevolucionItem, Order, OrderItem, PosSale
from apps.users_auth.models import Cliente, Notificacion
from common.pruebas import (
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)


class FidelidadTests(TestCase):
    """Empresas A y B, un cliente y un cajero en A."""

    @classmethod
    def setUpTestData(cls):
        """Datos comunes: dos empresas con una prenda cada una."""
        plan = crear_plan("PRUEBA_FIDELIDAD", 10)
        ciudad = crear_ciudad()
        cls.empresa_a = crear_empresa("Empresa Fidelidad A", "empresa-fidelidad-a", plan)
        cls.empresa_b = crear_empresa("Empresa Fidelidad B", "empresa-fidelidad-b", plan)
        cls.sucursal_a = crear_sucursal(cls.empresa_a, "Sucursal FA1", ciudad)
        cls.sucursal_b = crear_sucursal(cls.empresa_b, "Sucursal FB1", ciudad)
        cls.variante_a = crear_prenda(cls.empresa_a, cls.sucursal_a, "FID-A-1", 50)
        cls.cajero = crear_usuario("cajero@fidelidad-a.test", "CAJERO", cls.empresa_a, cls.sucursal_a)
        cls.cliente = Cliente.objects.get(id_usuario=crear_usuario("cliente@fidelidad.test", "CLIENTE"))

    def pedido(self, estado="PAGADA", empresa=None, sucursal=None):
        """Pedido web de una prenda (Bs 100)."""
        orden = Order.objects.create(
            id_cliente=self.cliente, id_sucursal=sucursal or self.sucursal_a,
            id_empresa=empresa or self.empresa_a, total=Decimal("100.00"), estado=estado,
        )
        OrderItem.objects.create(
            id_orden=orden, id_variante=self.variante_a, cantidad=1,
            precio_unitario=Decimal("100.00"), subtotal=Decimal("100.00"),
        )
        return orden

    def venta(self, estado="REGISTRADA"):
        """Venta POS con el correo del cliente."""
        return PosSale.objects.create(
            id_sucursal=self.sucursal_a, id_usuario=self.cajero, id_empresa=self.empresa_a,
            id_cliente=self.cliente, total=Decimal("100.00"), metodo_pago="EFECTIVO", estado=estado,
        )

    def compras(self, empresa=None):
        """Compras que cuentan este mes."""
        return servicio.compras_del_mes(self.cliente.pk, (empresa or self.empresa_a).pk)

    def avisos(self):
        """Notificaciones de fidelidad del cliente."""
        return Notificacion.objects.filter(id_usuario=self.cliente.id_usuario, tipo="FIDELIDAD")

    def test_cuentan_pedidos_y_ventas_en_tienda(self):
        """3 pedidos pagados + 2 ventas POS = 5 compras."""
        for _ in range(3):
            self.pedido()
        for _ in range(2):
            self.venta()
        self.assertEqual(self.compras(), 5)

    def test_no_cuentan_pendientes_canceladas_ni_anuladas(self):
        """Pedido pendiente o cancelado y venta anulada o en conflicto no cuentan."""
        self.pedido("PENDIENTE")
        self.pedido("CANCELADA")
        self.venta("ANULADA")
        self.venta("EN_CONFLICTO")
        self.assertEqual(self.compras(), 0)

    def test_cada_empresa_cuenta_aparte(self):
        """Las compras en B no suman en A."""
        self.pedido()
        self.pedido(empresa=self.empresa_b, sucursal=self.sucursal_b)
        self.assertEqual(self.compras(), 1)
        self.assertEqual(self.compras(self.empresa_b), 1)

    def test_compras_del_mes_anterior_no_cuentan(self):
        """El conteo se reinicia el día 1."""
        orden = self.pedido()
        inicio, _ = servicio.rango_mes(servicio.periodo_de())
        Order.objects.filter(pk=orden.pk).update(fecha_creacion=inicio - timedelta(minutes=1))
        self.assertEqual(self.compras(), 0)

    def test_devolucion_completa_descuenta_y_parcial_no(self):
        """Una compra devuelta por completo deja de contar; una parcial sigue contando."""
        orden = self.pedido()
        linea = OrderItem.objects.get(id_orden=orden)
        Order.objects.filter(pk=orden.pk).update(estado="ENTREGADA")
        devolucion = Devolucion.objects.create(
            id_orden=orden, id_cliente=self.cliente, id_empresa=self.empresa_a,
            id_sucursal=self.sucursal_a, estado="SOLICITADA",
        )
        DevolucionItem.objects.create(
            id_devolucion=devolucion, id_orden_item=linea, cantidad=1, motivo="NO_LA_QUIERO",
        )
        self.assertEqual(self.compras(), 1)
        Devolucion.objects.filter(pk=devolucion.pk).update(estado="COMPLETADA", fecha_completado=timezone.now())
        self.assertEqual(self.compras(), 0)

    def test_meta_avisa_una_sola_vez(self):
        """Al llegar a 5 compras el cliente recibe un solo aviso y tiene el descuento."""
        for _ in range(4):
            self.pedido()
        self.assertEqual(self.avisos().count(), 0)
        self.venta()
        self.pedido()
        self.assertEqual(self.avisos().count(), 1)
        datos = servicio.estado(self.cliente, self.empresa_a)
        self.assertTrue(datos["disponible"])
        self.assertEqual(datos["faltan"], 0)
        self.assertIsNotNone(BeneficioFidelidad.objects.get(id_cliente=self.cliente).fecha_alcanzado)

    def test_regla_elegida_por_el_super_admin_aplica_de_inmediato(self):
        """Con 3 compras y 30% el cliente con 3 compras ya tiene el descuento."""
        for _ in range(3):
            self.pedido()
        self.assertFalse(servicio.estado(self.cliente, self.empresa_a)["disponible"])
        ReglaFidelidad.objects.filter(pk=ReglaFidelidad.vigente().pk).update(
            compras_requeridas=3, porcentaje=Decimal("30.00")
        )
        self.assertEqual(servicio.verificar_mes_actual(), 1)
        monto, porcentaje, aviso = servicio.calcular_descuento(self.cliente, self.empresa_a, Decimal("200.00"))
        self.assertEqual((monto, porcentaje, aviso), (Decimal("60.00"), Decimal("30.00"), None))

    def test_regla_inactiva_no_da_descuento(self):
        """Si el SUPER_ADMIN desactiva la regla, nadie tiene descuento."""
        for _ in range(5):
            self.pedido()
        ReglaFidelidad.objects.filter(pk=ReglaFidelidad.vigente().pk).update(activa=False)
        monto, _, _ = servicio.calcular_descuento(self.cliente, self.empresa_a, Decimal("100.00"))
        self.assertEqual(monto, Decimal("0"))

    def test_descuento_no_aplica_con_prendas_reservadas(self):
        """Con reservas el monto es 0 y el aviso explica que pasa a la próxima compra."""
        for _ in range(5):
            self.pedido()
        monto, porcentaje, aviso = servicio.calcular_descuento(
            self.cliente, self.empresa_a, Decimal("100.00"), tiene_reservas=True
        )
        self.assertEqual((monto, porcentaje), (Decimal("0"), Decimal("50.00")))
        self.assertIn("próxima compra sin reservas", aviso)
        self.assertTrue(servicio.estado(self.cliente, self.empresa_a)["disponible"])

    def test_uso_en_tienda_una_vez_por_mes(self):
        """Tras usarlo en una venta POS ya no está disponible y no se puede usar de nuevo."""
        for _ in range(5):
            self.pedido()
        venta = self.venta()
        servicio.registrar_uso_venta(venta, Decimal("50.00"), Decimal("50.00"))
        datos = servicio.estado(self.cliente, self.empresa_a)
        self.assertFalse(datos["disponible"])
        self.assertTrue(datos["usado"])
        self.assertTrue(servicio.compra_con_descuento(venta=venta))
        with self.assertRaises(ValueError):
            servicio.registrar_uso_venta(self.venta(), Decimal("50.00"), Decimal("50.00"))

    def test_pedido_web_aparta_y_confirma_el_uso(self):
        """El pedido pendiente aparta el descuento; recién al pagarse queda usado."""
        for _ in range(5):
            self.pedido()
        orden = self.pedido("PENDIENTE")
        servicio.apartar_para_pedido(orden, Decimal("50.00"), Decimal("50.00"))
        self.assertTrue(servicio.estado(self.cliente, self.empresa_a)["disponible"])
        self.assertFalse(servicio.compra_con_descuento(orden=orden))
        servicio.confirmar_uso_pedido(orden)
        self.assertTrue(servicio.compra_con_descuento(orden=orden))
        self.assertFalse(servicio.estado(self.cliente, self.empresa_a)["disponible"])