"""Pruebas del centro de notificaciones (Fase 2 - CU16).

- Al pagar una reserva se avisa al cliente (pago recibido) y al personal que
  recibe avisos: SUPER_ADMIN y ADMIN_EMPRESA de esa empresa; nunca al cajero
  ni al administrador de otra empresa.
- Al cancelar, el aviso indica lo pagado, lo retenido y lo devuelto.
- Contador de no leídas, marcar una y marcar todas; nadie lee avisos ajenos.
- Recordatorio un día antes de que venza la reserva, una sola vez.
- Venta sin conexión en conflicto: aviso solo a SUPER_ADMIN y ADMIN_EMPRESA.
- Pedido pagado: aviso al cliente.
Stripe se simula con mock.

Ejecutar: python manage.py test apps.users_auth.test_notificaciones
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.reservations.models import FittingReservation
from apps.sales.models import Order
from apps.users_auth.models import Cliente, Notificacion, Usuario
from common.pruebas import (
    cliente_api,
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)

URL = "/api/auth/notificaciones/"
URL_RESERVAS = "/api/reservations/reservas/"
CREAR_PAGO = "apps.reservations.pagos.crear_intento_pago"
VERIFICAR_PAGO = "apps.reservations.pagos.verificar_pago"
REEMBOLSO = "apps.reservations.pagos.reembolsar_pago"


class NotificacionesTests(TestCase):
    """Quién recibe cada aviso y cómo se marcan como leídos."""

    @classmethod
    def setUpTestData(cls):
        """Dos empresas, su personal, un SUPER_ADMIN y un cliente."""
        plan = crear_plan("PRUEBA_NOTIF", 10)
        cls.empresa = crear_empresa("Empresa Avisos", "empresa-avisos", plan)
        cls.sucursal = crear_sucursal(cls.empresa, "Sucursal Avisos", crear_ciudad())
        cls.variante = crear_prenda(cls.empresa, cls.sucursal, "AVISO-1", 5)
        otra = crear_empresa("Otra Empresa Avisos", "otra-empresa-avisos", plan)
        crear_usuario("super@avisos.test", "SUPER_ADMIN")
        crear_usuario("admin@avisos.test", "ADMIN_EMPRESA", cls.empresa)
        crear_usuario("cajero@avisos.test", "CAJERO", cls.empresa, cls.sucursal)
        crear_usuario("admin@otra-avisos.test", "ADMIN_EMPRESA", otra)
        crear_usuario("cliente@avisos.test", "CLIENTE")

    def setUp(self):
        """Sesión del cliente."""
        self.cli = cliente_api("cliente@avisos.test")

    # ---------------------------------------------------------------- utilidades
    def avisos(self, correo, tipo=None):
        """Notificaciones de un usuario (opcionalmente de un tipo)."""
        queryset = Notificacion.objects.filter(id_usuario__correo=correo)
        if tipo:
            queryset = queryset.filter(tipo=tipo)
        return queryset

    def reserva_pagada(self):
        """El cliente reserva la prenda (Bs 100) y paga el anticipo (Bs 50)."""
        datos = {
            "id_sucursal": self.sucursal.id_sucursal,
            "fecha_reserva": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "hora_reserva": "16:00",
            "items": [{"id_variante": self.variante.id_variante}],
            "tipo_pago": "ANTICIPO",
        }
        with mock.patch(CREAR_PAGO, return_value=("pi_aviso", "secreto")):
            creada = self.cli.post(URL_RESERVAS, datos, format="json")
        self.assertEqual(creada.status_code, 201, creada.data)
        with mock.patch(VERIFICAR_PAGO, return_value="pi_aviso"):
            pagada = self.cli.post(
                f"{URL_RESERVAS}{creada.data['id_reserva']}/pagar/",
                {"referencia_pago": "pi_aviso"}, format="json",
            )
        self.assertEqual(pagada.status_code, 200, pagada.data)
        return pagada.data

    # ---------------------------------------------------------------- reservas
    def test_pago_de_reserva_avisa_al_cliente_y_a_los_administradores(self):
        """Cliente, SUPER_ADMIN y ADMIN_EMPRESA reciben aviso; cajero y otra empresa no."""
        reserva = self.reserva_pagada()
        aviso = self.avisos("cliente@avisos.test", "RESERVA").get()
        self.assertIn("Pago recibido", aviso.titulo)
        self.assertIn("Bs 50.00", aviso.mensaje)
        for correo in ("super@avisos.test", "admin@avisos.test"):
            self.assertEqual(
                self.avisos(correo, "RESERVA").get().titulo, f"Nueva Reserva #{reserva['id_reserva']}"
            )
        self.assertFalse(self.avisos("cajero@avisos.test").exists())
        self.assertFalse(self.avisos("admin@otra-avisos.test").exists())

    def test_cancelar_avisa_lo_devuelto(self):
        """El aviso de cancelación indica pagado, retenido y devuelto."""
        reserva = self.reserva_pagada()
        with mock.patch(REEMBOLSO, return_value="re_aviso"):
            respuesta = self.cli.post(f"{URL_RESERVAS}{reserva['id_reserva']}/cancelar/", {}, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        aviso = self.avisos("cliente@avisos.test").get(titulo__endswith="cancelada")
        self.assertIn("Bs 50.00", aviso.mensaje)
        self.assertIn("Bs 10.00", aviso.mensaje)
        self.assertIn("Bs 40.00", aviso.mensaje)

    def test_recordatorio_un_dia_antes_una_sola_vez(self):
        """Si la reserva vence en menos de un día, se avisa una sola vez."""
        reserva = self.reserva_pagada()
        FittingReservation.objects.filter(pk=reserva["id_reserva"]).update(
            fecha_vencimiento=timezone.now() + timedelta(hours=2)
        )
        self.cli.get(f"{URL}contador/")
        self.cli.get(URL)
        recordatorios = self.avisos("cliente@avisos.test").filter(titulo__endswith="vence mañana")
        self.assertEqual(recordatorios.count(), 1)

    # ---------------------------------------------------------------- campana
    def test_contador_y_marcar_como_leidas(self):
        """Contador de no leídas, leer una, leer todas; un aviso ajeno da 404."""
        self.reserva_pagada()
        aviso = self.avisos("cliente@avisos.test").first()
        self.assertEqual(self.cli.get(f"{URL}contador/").data["no_leidas"], 1)
        ajeno = cliente_api("admin@avisos.test")
        self.assertEqual(ajeno.post(f"{URL}{aviso.id_notificacion}/leer/").status_code, 404)
        leida = self.cli.post(f"{URL}{aviso.id_notificacion}/leer/")
        self.assertTrue(leida.data["leida"])
        self.assertEqual(self.cli.get(f"{URL}contador/").data["no_leidas"], 0)
        self.assertEqual(ajeno.get(f"{URL}contador/").data["no_leidas"], 1)
        ajeno.post(f"{URL}leer-todas/")
        self.assertEqual(ajeno.get(f"{URL}contador/").data["no_leidas"], 0)
        lista = self.cli.get(URL)
        self.assertEqual(lista.status_code, 200)

    # ---------------------------------------------------------------- otros eventos
    def test_venta_en_conflicto_avisa_solo_a_los_administradores(self):
        """Una venta sin conexión con otro precio avisa a SUPER_ADMIN y ADMIN_EMPRESA."""
        cajero = cliente_api("cajero@avisos.test")
        operacion = {
            "uuid": str(uuid.uuid4()),
            "fecha_operacion": timezone.now().isoformat(),
            "id_sucursal": self.sucursal.id_sucursal,
            "metodo_pago": "EFECTIVO",
            "items": [{"id_variante": self.variante.id_variante, "cantidad": 1, "precio_unitario": "80.00"}],
        }
        respuesta = cajero.post("/api/sales/sync/ventas-pos/", {"operaciones": [operacion]}, format="json")
        self.assertEqual(respuesta.data["resultados"][0]["estado"], "EN_CONFLICTO")
        self.assertTrue(self.avisos("super@avisos.test", "CONFLICTO").exists())
        self.assertTrue(self.avisos("admin@avisos.test", "CONFLICTO").exists())
        self.assertFalse(self.avisos("cajero@avisos.test").exists())
        self.assertFalse(self.avisos("admin@otra-avisos.test").exists())

    def test_pedido_pagado_avisa_al_cliente(self):
        """Cuando el pedido pasa a PAGADA, el cliente recibe el aviso."""
        cliente = Cliente.objects.get(id_usuario__correo="cliente@avisos.test")
        pedido = Order.objects.create(
            id_cliente=cliente,
            id_sucursal=self.sucursal,
            id_empresa=self.empresa,
            total=Decimal("100.00"),
            estado="PENDIENTE",
            metodo_pago="TARJETA",
            referencia_pago="pi_pedido_aviso",
            tipo_entrega="RETIRO",
            costo_envio=Decimal("0.00"),
        )
        self.assertFalse(self.avisos("cliente@avisos.test", "PEDIDO").exists())
        pedido.estado = "PAGADA"
        pedido.save()
        aviso = self.avisos("cliente@avisos.test", "PEDIDO").get()
        self.assertEqual(aviso.titulo, f"Pedido #{pedido.id_orden} pagado")
        self.assertEqual(Usuario.objects.get(correo="cliente@avisos.test").notificaciones.count(), 1)