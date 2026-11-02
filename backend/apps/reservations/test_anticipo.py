"""Pruebas de las reservas con anticipo, vencimiento y cancelación (Fase 2 - CU17).

- La reserva queda pendiente de pago y aparta la prenda recién al pagar por
  Stripe el anticipo (50%) o el total.
- En el POS y en el checkout se cobra solo el saldo y la reserva se retira
  completa.
- Cancelar (CU17) o vencer devuelve lo pagado menos el 10% del precio total,
  con nota de devolución; sin pago vence a las 3 horas sin mover stock.
- Una reserva pagada no se puede quitar del carrito ni completar con saldo.
Stripe se simula con mock (crear, verificar y reembolsar).

Ejecutar: python manage.py test apps.reservations.test_anticipo
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import ProductoVariante, Talla
from apps.inventory.models import StockItem
from apps.reservations.models import FittingReservation
from apps.sales.models import CartItem
from common.pruebas import (
    cliente_api,
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)

URL = "/api/reservations/reservas/"
CREAR_PAGO = "apps.reservations.pagos.crear_intento_pago"
VERIFICAR_PAGO = "apps.reservations.pagos.verificar_pago"
REEMBOLSO = "apps.reservations.pagos.reembolsar_pago"


class ReservaAnticipoTests(TestCase):
    """Pago, saldo, retiro completo, cancelación y vencimiento de las reservas."""

    @classmethod
    def setUpTestData(cls):
        """Polera M (Bs 100) y L (Bs 50) con 5 unidades, personal y un cliente."""
        plan = crear_plan("PRUEBA_RESERVAS", 10)
        cls.empresa = crear_empresa("Empresa Reservas", "empresa-reservas", plan)
        cls.sucursal = crear_sucursal(cls.empresa, "Sucursal Reservas", crear_ciudad())
        cls.m = crear_prenda(cls.empresa, cls.sucursal, "RESERVA-M", 5)
        cls.l = ProductoVariante.objects.create(
            id_producto=cls.m.id_producto,
            id_talla=Talla.objects.get_or_create(nombre="L")[0],
            id_color=cls.m.id_color,
            codigo_producto="RESERVA-L",
            precio=Decimal("50.00"),
            cantidad=5,
        )
        StockItem.objects.create(
            id_sucursal=cls.sucursal, id_variante=cls.l, cantidad=5, id_empresa=cls.empresa
        )
        crear_usuario("cajero@reservas.test", "CAJERO", cls.empresa, cls.sucursal)
        crear_usuario("admin@reservas.test", "ADMIN_EMPRESA", cls.empresa)
        crear_usuario("cliente@reservas.test", "CLIENTE")

    def setUp(self):
        """Sesiones de cada rol."""
        self.cajero = cliente_api("cajero@reservas.test")
        self.admin = cliente_api("admin@reservas.test")
        self.cli = cliente_api("cliente@reservas.test")

    # ---------------------------------------------------------------- utilidades
    def stock(self, variante):
        """Unidades de la variante en la sucursal."""
        return StockItem.objects.get(id_sucursal=self.sucursal, id_variante=variante).cantidad

    def crear(self, tipo_pago="ANTICIPO", variantes=None):
        """El cliente crea la reserva (para mañana a las 16:00) y se inicia el cobro."""
        datos = {
            "id_sucursal": self.sucursal.id_sucursal,
            "fecha_reserva": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "hora_reserva": "16:00",
            "items": [{"id_variante": v.id_variante} for v in (variantes or [self.m])],
        }
        if tipo_pago:
            datos["tipo_pago"] = tipo_pago
        with mock.patch(CREAR_PAGO, return_value=("pi_reserva", "secreto")):
            respuesta = self.cli.post(URL, datos, format="json")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return respuesta.data

    def pagar(self, id_reserva):
        """El cliente confirma el pago hecho en Stripe."""
        with mock.patch(VERIFICAR_PAGO, return_value="pi_reserva"):
            respuesta = self.cli.post(
                f"{URL}{id_reserva}/pagar/", {"referencia_pago": "pi_reserva"}, format="json"
            )
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data

    # ---------------------------------------------------------------- pago
    def test_anticipo_del_50_aparta_la_prenda_al_pagar(self):
        """Crear no toca el stock; pagar el 50% confirma y aparta la prenda."""
        creada = self.crear()
        self.assertEqual(creada["estado"], "PENDIENTE_PAGO")
        self.assertEqual(Decimal(creada["monto_total"]), Decimal("100.00"))
        self.assertEqual(Decimal(creada["monto_a_pagar"]), Decimal("50.00"))
        self.assertEqual(creada["pago"]["client_secret"], "secreto")
        self.assertEqual(self.stock(self.m), 5)
        pagada = self.pagar(creada["id_reserva"])
        self.assertEqual(pagada["estado"], "CONFIRMADA")
        self.assertEqual(Decimal(pagada["monto_pagado"]), Decimal("50.00"))
        self.assertEqual(Decimal(pagada["saldo"]), Decimal("50.00"))
        self.assertEqual(self.stock(self.m), 4)

    def test_pago_total_no_deja_saldo(self):
        """Pagando el 100% el saldo queda en cero."""
        pagada = self.pagar(self.crear("TOTAL")["id_reserva"])
        self.assertEqual(Decimal(pagada["monto_pagado"]), Decimal("100.00"))
        self.assertEqual(Decimal(pagada["saldo"]), Decimal("0.00"))

    # ---------------------------------------------------------------- retiro
    def test_pos_cobra_solo_el_saldo(self):
        """En caja se cobra el saldo de la reserva completa y queda COMPLETADA."""
        reserva = self.pagar(self.crear(variantes=[self.m, self.l])["id_reserva"])
        self.assertEqual(Decimal(reserva["saldo"]), Decimal("75.00"))
        items = [{"id_reserva_item": i["id_item"], "cantidad": 1} for i in reserva["items"]]
        respuesta = self.cajero.post(
            "/api/sales/ventas-pos/registrar/",
            {"id_sucursal": self.sucursal.id_sucursal, "metodo_pago": "EFECTIVO", "items": items},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(Decimal(respuesta.data["total"]), Decimal("75.00"))
        self.assertEqual(FittingReservation.objects.get(pk=reserva["id_reserva"]).estado, "COMPLETADA")
        self.assertEqual(self.stock(self.m), 4)
        self.assertEqual(self.stock(self.l), 4)

    def test_la_reserva_se_retira_completa(self):
        """No se puede cobrar solo una de las prendas de la reserva."""
        reserva = self.pagar(self.crear(variantes=[self.m, self.l])["id_reserva"])
        respuesta = self.cajero.post(
            "/api/sales/ventas-pos/registrar/",
            {"id_sucursal": self.sucursal.id_sucursal, "metodo_pago": "EFECTIVO",
             "items": [{"id_reserva_item": reserva["items"][0]["id_item"], "cantidad": 1}]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("se retira completa", respuesta.data["error"])

    def test_checkout_cobra_solo_el_saldo(self):
        """En el checkout en línea la reserva pagada cobra solo lo que falta."""
        reserva = self.pagar(self.crear()["id_reserva"])
        with mock.patch("apps.sales.services.crear_intento_pago", return_value=("pi_orden", "s")) as cobro:
            respuesta = self.cli.post(
                "/api/sales/carritos/checkout/",
                {"id_sucursal": self.sucursal.id_sucursal, "tipo_entrega": "RETIRO"},
                format="json",
            )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        cobro.assert_called_once_with(Decimal("50.00"))
        self.assertEqual(Decimal(reserva["saldo"]), Decimal("50.00"))

    def test_no_se_quita_del_carrito_una_reserva_pagada(self):
        """La prenda de una reserva pagada no se puede sacar del carrito."""
        reserva = self.pagar(self.crear()["id_reserva"])
        item = CartItem.objects.get(id_reserva_item__id_reserva_id=reserva["id_reserva"])
        respuesta = self.cli.delete(f"/api/sales/carrito-items/{item.id_item}/")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self.stock(self.m), 4)

    def test_no_se_completa_a_mano_con_saldo(self):
        """El personal no puede completar una reserva que todavía debe saldo."""
        reserva = self.pagar(self.crear()["id_reserva"])
        respuesta = self.admin.post(f"{URL}{reserva['id_reserva']}/completar/")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("saldo", respuesta.data["error"])

    # ---------------------------------------------------------------- CU17 y vencimiento
    def test_cancelar_devuelve_lo_pagado_menos_el_10(self):
        """CU17: del anticipo de Bs 50 se retienen Bs 10 (10% del total) y se devuelven Bs 40."""
        reserva = self.pagar(self.crear()["id_reserva"])
        with mock.patch(REEMBOLSO, return_value="re_reserva") as reembolso:
            respuesta = self.cli.post(f"{URL}{reserva['id_reserva']}/cancelar/", {}, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        reembolso.assert_called_once_with("pi_reserva", Decimal("40.00"))
        self.assertEqual(respuesta.data["estado"], "CANCELADA")
        self.assertTrue(respuesta.data["numero_nota"].startswith("NR-"))
        self.assertEqual(Decimal(respuesta.data["monto_retenido"]), Decimal("10.00"))
        self.assertEqual(Decimal(respuesta.data["monto_devuelto"]), Decimal("40.00"))
        self.assertEqual(self.stock(self.m), 5)

    def test_el_personal_no_cancela_una_reserva_pagada(self):
        """La cancelación con reembolso es del cliente."""
        reserva = self.pagar(self.crear()["id_reserva"])
        respuesta = self.admin.post(f"{URL}{reserva['id_reserva']}/cancelar/", {}, format="json")
        self.assertEqual(respuesta.status_code, 400)

    def test_vence_a_la_semana_con_reembolso(self):
        """Pagada al 100% y sin retirar: el comando la vence y devuelve Bs 90."""
        reserva = self.pagar(self.crear("TOTAL")["id_reserva"])
        FittingReservation.objects.filter(pk=reserva["id_reserva"]).update(
            fecha_vencimiento=timezone.now() - timedelta(minutes=1)
        )
        with mock.patch(REEMBOLSO, return_value="re_reserva"):
            call_command("vencer_reservas", stdout=StringIO())
        vencida = FittingReservation.objects.get(pk=reserva["id_reserva"])
        self.assertEqual(vencida.estado, "VENCIDA")
        self.assertEqual(vencida.monto_retenido, Decimal("10.00"))
        self.assertEqual(vencida.monto_devuelto, Decimal("90.00"))
        self.assertEqual(self.stock(self.m), 5)

    def test_sin_pagar_vence_a_las_3_horas_al_listar(self):
        """Sin pago, al pasar las 3 horas vence al listar las reservas, sin nota ni stock."""
        creada = self.crear(tipo_pago=None)
        FittingReservation.objects.filter(pk=creada["id_reserva"]).update(
            fecha_limite_pago=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(self.cli.get(URL).status_code, 200)
        vencida = FittingReservation.objects.get(pk=creada["id_reserva"])
        self.assertEqual(vencida.estado, "VENCIDA")
        self.assertIsNone(vencida.numero_nota)
        self.assertEqual(self.stock(self.m), 5)