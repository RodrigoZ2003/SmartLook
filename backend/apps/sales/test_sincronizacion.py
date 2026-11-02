"""Pruebas de la sincronización sin conexión (5.4, RNF05 idempotencia, RNF06)
y de los conflictos de las ventas POS (Fase 2 - CU08).

- Una venta POS hecha sin conexión se registra una sola vez aunque el
  dispositivo la reenvíe (mismo UUID = DUPLICADA, sin descontar stock dos veces).
- Si el precio cobrado sin conexión no es el del servidor, la venta se
  registra con el precio cobrado y queda EN_CONFLICTO.
- Si no hay stock al sincronizar, la venta se registra EN_CONFLICTO sin
  descontar stock; reenviarla no la duplica.
- Los conflictos los resuelve el encargado o el administrador de la propia
  empresa: confirmar (ajusta el stock) o devolver el efectivo (anula la
  venta, repone el stock y genera la nota de devolución).
- Lo mismo (idempotencia y rechazos) para las reservas hechas sin conexión.
  MODIFICADO (Fase 2 - reservas con anticipo): la reserva sincronizada queda
  "Pendiente de pago" (3 horas) y no aparta stock hasta que se paga.

Ejecutar: python manage.py test apps.sales.test_sincronizacion
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.inventory.models import StockItem
from apps.reservations.models import FittingReservation
from apps.sales.models import NotaDevolucionPos, PosSale, SyncOperacion
from common.pruebas import (
    cliente_api,
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)

URL_VENTAS = "/api/sales/sync/ventas-pos/"
URL_RESERVAS = "/api/reservations/reservas/sync/"


class SincronizacionTests(TestCase):
    """Idempotencia, conflictos y rechazos de las operaciones sin conexión."""

    @classmethod
    def setUpTestData(cls):
        """Empresa con una sucursal, una prenda (Bs 100) con 5 unidades y su personal."""
        plan = crear_plan("PRUEBA_SYNC", 10)
        cls.empresa = crear_empresa("Empresa Sync Prueba", "empresa-sync-prueba", plan)
        cls.sucursal = crear_sucursal(cls.empresa, "Sucursal Sync", crear_ciudad())
        cls.variante = crear_prenda(cls.empresa, cls.sucursal, "PRUEBA-SYNC-1", 5)
        crear_usuario("cajero@sync-prueba.test", "CAJERO", cls.empresa, cls.sucursal)
        crear_usuario("admin@sync-prueba.test", "ADMIN_EMPRESA", cls.empresa)
        crear_usuario("cliente@sync-prueba.test", "CLIENTE")
        otra = crear_empresa("Otra Empresa Sync", "otra-empresa-sync", plan)
        crear_usuario("admin@otra-sync.test", "ADMIN_EMPRESA", otra)

    def setUp(self):
        """Sesiones del cajero, del administrador y del cliente."""
        self.cajero = cliente_api("cajero@sync-prueba.test")
        self.admin = cliente_api("admin@sync-prueba.test")
        self.cliente = cliente_api("cliente@sync-prueba.test")

    # ---------------------------------------------------------------- utilidades
    def venta(self, cantidad=1, id_uuid=None, precio=None, correo_cliente=None, id_variante=None):
        """Operación de venta POS como la arma la web o el móvil."""
        item = {"id_variante": id_variante or self.variante.id_variante, "cantidad": cantidad}
        if precio is not None:
            item["precio_unitario"] = precio
        operacion = {
            "uuid": id_uuid or str(uuid.uuid4()),
            "fecha_operacion": timezone.now().isoformat(),
            "id_sucursal": self.sucursal.id_sucursal,
            "metodo_pago": "EFECTIVO",
            "items": [item],
        }
        if correo_cliente:
            operacion["correo_cliente"] = correo_cliente
        return operacion

    def reserva(self, id_uuid=None):
        """Operación de reserva como la arma la web o el móvil."""
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        return {
            "uuid": id_uuid or str(uuid.uuid4()),
            "fecha_operacion": timezone.now().isoformat(),
            "id_sucursal": self.sucursal.id_sucursal,
            "fecha_reserva": manana,
            "hora_reserva": "16:00",
            "items": [{"id_variante": self.variante.id_variante}],
        }

    def enviar(self, api, url, operaciones):
        """Envía un lote y devuelve los resultados."""
        respuesta = api.post(url, {"operaciones": operaciones}, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data["resultados"]

    def stock(self):
        """Unidades de la prenda en la sucursal."""
        return StockItem.objects.get(id_sucursal=self.sucursal, id_variante=self.variante).cantidad

    def resolver(self, api, operacion_uuid, accion, nota=None):
        """Resuelve el conflicto de la operación indicada y devuelve la respuesta."""
        operacion = SyncOperacion.objects.get(uuid=operacion_uuid)
        return api.post(
            f"/api/sales/sync/{operacion.id_operacion}/resolver/",
            {"accion": accion, "nota": nota},
            format="json",
        )

    # ---------------------------------------------------------------- ventas POS
    def test_venta_se_registra_y_descuenta_stock(self):
        """La primera vez la venta queda SINCRONIZADA y descuenta el stock."""
        resultado = self.enviar(self.cajero, URL_VENTAS, [self.venta(cantidad=2)])[0]
        self.assertEqual(resultado["estado"], "SINCRONIZADA")
        self.assertIsNotNone(resultado["id_venta"])
        self.assertEqual(self.stock(), 3)

    def test_reenviar_la_misma_venta_no_la_duplica(self):
        """El mismo UUID enviado otra vez responde DUPLICADA con la venta original."""
        operacion = self.venta()
        primera = self.enviar(self.cajero, URL_VENTAS, [operacion])[0]
        segunda = self.enviar(self.cajero, URL_VENTAS, [operacion])[0]
        self.assertEqual(segunda["estado"], "DUPLICADA")
        self.assertEqual(segunda["id_venta"], primera["id_venta"])
        self.assertEqual(PosSale.objects.filter(id_sucursal=self.sucursal).count(), 1)
        self.assertEqual(self.stock(), 4)
        self.assertEqual(SyncOperacion.objects.get(uuid=operacion["uuid"]).reintentos, 1)

    def test_mismo_uuid_dos_veces_en_un_lote(self):
        """Si el mismo UUID viene dos veces en un envío, solo se registra una venta."""
        operacion = self.venta()
        resultados = self.enviar(self.cajero, URL_VENTAS, [operacion, operacion])
        self.assertEqual([r["estado"] for r in resultados], ["SINCRONIZADA", "DUPLICADA"])
        self.assertEqual(PosSale.objects.filter(id_sucursal=self.sucursal).count(), 1)

    def test_uuid_invalido_se_rechaza(self):
        """Una operación sin UUID válido se rechaza sin registrar nada."""
        resultado = self.enviar(self.cajero, URL_VENTAS, [self.venta(id_uuid="no-es-un-uuid")])[0]
        self.assertEqual(resultado["estado"], "RECHAZADA")
        self.assertFalse(PosSale.objects.filter(id_sucursal=self.sucursal).exists())

    def test_prenda_inexistente_se_rechaza(self):
        """Datos inválidos (prenda que no existe) se rechazan, no quedan en conflicto."""
        resultado = self.enviar(self.cajero, URL_VENTAS, [self.venta(id_variante=999999)])[0]
        self.assertEqual(resultado["estado"], "RECHAZADA")
        self.assertFalse(PosSale.objects.filter(id_sucursal=self.sucursal).exists())

    # ---------------------------------------------------------------- conflictos (CU08)
    def test_precio_igual_al_del_servidor_se_sincroniza(self):
        """Si el precio cobrado coincide con el del servidor no hay conflicto."""
        resultado = self.enviar(self.cajero, URL_VENTAS, [self.venta(precio="100.00")])[0]
        self.assertEqual(resultado["estado"], "SINCRONIZADA")
        self.assertEqual(PosSale.objects.get(pk=resultado["id_venta"]).estado, "REGISTRADA")

    def test_precio_distinto_queda_en_conflicto(self):
        """Se registra con el precio cobrado sin conexión y queda EN_CONFLICTO con la diferencia."""
        resultado = self.enviar(self.cajero, URL_VENTAS, [self.venta(cantidad=2, precio="80.00")])[0]
        self.assertEqual(resultado["estado"], "EN_CONFLICTO")
        self.assertEqual(resultado["tipo_conflicto"], "PRECIO")
        self.assertEqual(resultado["conflictos"][0]["diferencia"], "-40.00")
        venta = PosSale.objects.get(pk=resultado["id_venta"])
        self.assertEqual(venta.estado, "EN_CONFLICTO")
        self.assertEqual(venta.total, Decimal("160.00"))
        self.assertEqual(self.stock(), 3)

    def test_venta_sin_stock_queda_en_conflicto_sin_descontar(self):
        """Sin stock: la venta se registra EN_CONFLICTO, no toca el stock y no se duplica."""
        operacion = self.venta(cantidad=50)
        resultado = self.enviar(self.cajero, URL_VENTAS, [operacion])[0]
        self.assertEqual(resultado["estado"], "EN_CONFLICTO")
        self.assertEqual(resultado["tipo_conflicto"], "STOCK")
        self.assertIn("sin stock suficiente", resultado["mensaje"])
        self.assertEqual(self.stock(), 5)
        self.assertTrue(PosSale.objects.get(pk=resultado["id_venta"]).items.get().sin_stock)
        reenvio = self.enviar(self.cajero, URL_VENTAS, [operacion])[0]
        self.assertEqual(reenvio["estado"], "EN_CONFLICTO")
        self.assertEqual(PosSale.objects.filter(id_sucursal=self.sucursal).count(), 1)
        self.assertEqual(self.stock(), 5)

    def test_confirmar_conflicto_de_stock_ajusta_el_inventario(self):
        """Confirmar deja la venta REGISTRADA y el stock en max(0, actual - vendido)."""
        operacion = self.venta(cantidad=7)
        self.enviar(self.cajero, URL_VENTAS, [operacion])
        respuesta = self.resolver(self.admin, operacion["uuid"], "CONFIRMAR", "Estaba en tienda")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["resolucion"], "CONFIRMADA")
        self.assertFalse(respuesta.data["puede_resolver"])
        self.assertEqual(respuesta.data["venta"]["estado"], "REGISTRADA")
        self.assertEqual(self.stock(), 0)

    def test_devolver_efectivo_anula_repone_y_genera_nota(self):
        """Devolver anula la venta, repone lo descontado y genera la nota por el total."""
        operacion = self.venta(cantidad=2, precio="80.00")
        self.enviar(self.cajero, URL_VENTAS, [operacion])
        self.assertEqual(self.stock(), 3)
        respuesta = self.resolver(self.admin, operacion["uuid"], "DEVOLVER", "Cliente devolvió")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["resolucion"], "DEVUELTA")
        self.assertEqual(respuesta.data["venta"]["estado"], "ANULADA")
        self.assertEqual(respuesta.data["nota_devolucion"]["monto_devuelto"], "160.00")
        self.assertEqual(self.stock(), 5)
        self.assertEqual(NotaDevolucionPos.objects.count(), 1)

    def test_no_se_resuelve_dos_veces(self):
        """Una operación ya resuelta no se puede volver a resolver."""
        operacion = self.venta(precio="90.00")
        self.enviar(self.cajero, URL_VENTAS, [operacion])
        self.assertEqual(self.resolver(self.admin, operacion["uuid"], "CONFIRMAR").status_code, 200)
        segunda = self.resolver(self.admin, operacion["uuid"], "DEVOLVER")
        self.assertEqual(segunda.status_code, 400)
        self.assertEqual(self.stock(), 4)

    def test_cajero_no_puede_resolver_conflictos(self):
        """Solo encargado o administrador resuelven: el cajero recibe 403."""
        operacion = self.venta(precio="90.00")
        self.enviar(self.cajero, URL_VENTAS, [operacion])
        self.assertEqual(self.resolver(self.cajero, operacion["uuid"], "CONFIRMAR").status_code, 403)

    def test_otra_empresa_no_ve_ni_resuelve_el_conflicto(self):
        """El administrador de otra empresa no ve la operación (404 al resolver)."""
        operacion = self.venta(precio="90.00")
        self.enviar(self.cajero, URL_VENTAS, [operacion])
        ajeno = cliente_api("admin@otra-sync.test")
        self.assertEqual(self.resolver(ajeno, operacion["uuid"], "DEVOLVER").status_code, 404)
        historial = ajeno.get("/api/sales/sync/")
        self.assertEqual(historial.data["count"], 0)

    def test_historial_filtra_conflictos_pendientes(self):
        """?pendientes=1 trae solo los conflictos sin resolver."""
        self.enviar(self.cajero, URL_VENTAS, [self.venta(), self.venta(precio="90.00")])
        respuesta = self.admin.get("/api/sales/sync/?pendientes=1")
        self.assertEqual(respuesta.data["count"], 1)
        self.assertTrue(respuesta.data["results"][0]["puede_resolver"])
        resumen = self.admin.get("/api/sales/sync/resumen/").data
        self.assertEqual(resumen["SINCRONIZADA"], 1)
        self.assertEqual(resumen["pendientes"], 1)

    def test_cliente_opcional_por_correo(self):
        """Con correo de un cliente existente la venta queda a su nombre; si no existe, sin cliente."""
        con_cliente = self.enviar(
            self.cajero, URL_VENTAS, [self.venta(correo_cliente="cliente@sync-prueba.test")]
        )[0]
        self.assertIsNotNone(PosSale.objects.get(pk=con_cliente["id_venta"]).id_cliente_id)
        sin_cliente = self.enviar(
            self.cajero, URL_VENTAS, [self.venta(correo_cliente="nadie@sync-prueba.test")]
        )[0]
        self.assertEqual(sin_cliente["estado"], "SINCRONIZADA")
        self.assertIn("no encontrado", sin_cliente["mensaje"])
        self.assertIsNone(PosSale.objects.get(pk=sin_cliente["id_venta"]).id_cliente_id)

    # ---------------------------------------------------------------- reservas
    def test_reenviar_la_misma_reserva_no_la_duplica(self):
        """La reserva se crea una vez (pendiente de pago, sin apartar stock); el reenvío es DUPLICADA."""
        operacion = self.reserva()
        primera = self.enviar(self.cliente, URL_RESERVAS, [operacion])[0]
        segunda = self.enviar(self.cliente, URL_RESERVAS, [operacion])[0]
        self.assertEqual(primera["estado"], "SINCRONIZADA")
        self.assertEqual(segunda["estado"], "DUPLICADA")
        self.assertEqual(segunda["id_reserva"], primera["id_reserva"])
        reservas = FittingReservation.objects.filter(id_sucursal=self.sucursal)
        self.assertEqual(reservas.count(), 1)
        self.assertEqual(reservas.first().estado, "PENDIENTE_PAGO")
        self.assertIsNotNone(reservas.first().fecha_limite_pago)
        self.assertEqual(self.stock(), 5)

    def test_reserva_sin_stock_se_rechaza(self):
        """Sin stock en la sucursal, la reserva se rechaza y no queda creada."""
        StockItem.objects.filter(id_sucursal=self.sucursal).update(cantidad=0)
        resultado = self.enviar(self.cliente, URL_RESERVAS, [self.reserva()])[0]
        self.assertEqual(resultado["estado"], "RECHAZADA")
        self.assertFalse(FittingReservation.objects.filter(id_sucursal=self.sucursal).exists())

    def test_solo_el_cliente_sincroniza_reservas(self):
        """El personal no puede usar el endpoint de reservas del cliente (403)."""
        respuesta = self.cajero.post(URL_RESERVAS, {"operaciones": [self.reserva()]}, format="json")
        self.assertEqual(respuesta.status_code, 403)