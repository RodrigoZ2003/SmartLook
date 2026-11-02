"""Reservas con anticipo, vencimiento y cancelación con reembolso (Fase 2).

Reglas:
- Al reservar, el cliente paga por Stripe (solo tarjeta) el anticipo
  (porcentaje de la empresa, 50% por defecto) o el 100%, a su elección.
  La reserva queda CONFIRMADA y la prenda apartada (SALIDA de stock)
  recién cuando se verifica el pago.
- Una reserva sin pagar (creada en línea o sincronizada sin conexión) tiene
  3 horas para pagarse; si no, vence y no se mueve stock ni dinero.
- El saldo (precio total menos lo pagado) se cobra al retirar en tienda o en
  el checkout del delivery (ver apps/sales/services.py). El retiro es de la
  reserva completa.
- Vencimiento: 1 semana después de la fecha y hora reservadas. Si no se
  retiró, la reserva vence, las prendas vuelven al stock y se devuelve por
  Stripe lo pagado MENOS el 10% del precio total.
- CU17 - Cancelación por el cliente antes de vencer: misma regla (nunca se
  devuelve el pago completo).
- Reservas anteriores a esta fase (sin pago): vencen a la semana y solo se
  liberan las prendas.
- Cada devolución queda como nota (NR-000001): pagado, retenido, devuelto.
- Si al pagar ya no queda stock, la reserva se cancela y se devuelve el 100%
  (no es culpa del cliente).
- El vencimiento se procesa al usar el sistema (lista de reservas, login,
  POS) y con el comando "python manage.py vencer_reservas".
"""
import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.inventory.models import StockItem
from apps.sales.integrations.stripe_payment import (
    PagoRechazadoError, crear_intento_pago, reembolsar_pago, verificar_pago,
)
from common.utils import log_audit

from .models import HORAS_PAGO_OFFLINE, PORCENTAJE_RETENCION, FittingReservation
from .services import ReservationStockError, ReservationStockService

logger = logging.getLogger(__name__)

CENTAVO = Decimal("0.01")
TIPOS_PAGO = ("ANTICIPO", "TOTAL")
# Estados en los que la reserva todavía puede vencer o cancelarse.
ESTADOS_ABIERTOS = ("PENDIENTE", "PENDIENTE_PAGO", "CONFIRMADA")


def _redondear(valor):
    """Redondea a centavos."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _auditar(usuario, accion, reserva, texto):
    """Registra el evento de la reserva en la bitácora de su empresa."""
    if usuario is None:
        usuario = reserva.id_cliente.id_usuario
    log_audit(
        usuario=usuario,
        accion=accion,
        tabla_afectada="fitting_reservation",
        registro_id=reserva.id_reserva,
        descripcion=f"{texto} - Reserva #{reserva.id_reserva} ({reserva.id_sucursal.nombre})",
        empresa=reserva.id_empresa_id,
    )


def _sin_pago(reserva):
    """True si la reserva no tiene nada pagado (anterior a esta fase o sin pagar)."""
    return not reserva.monto_pagado


def verificar_disponibilidad(reserva):
    """Revisa (sin descontar) que haya stock de cada prenda en la sucursal."""
    pedidas = reserva.items.values("id_variante").annotate(n=Count("id_item"))
    for fila in pedidas:
        stock = StockItem.objects.filter(
            id_sucursal=reserva.id_sucursal, id_variante_id=fila["id_variante"]
        ).values_list("cantidad", flat=True).first() or 0
        if stock < fila["n"]:
            variante = reserva.items.filter(id_variante_id=fila["id_variante"]).first().id_variante
            raise ValueError(f"'{variante}' ya no tiene stock disponible en {reserva.id_sucursal.nombre}.")


def preparar_montos(reserva, limite_pago=None):
    """Congela los precios de las prendas y el total; deja la reserva esperando pago."""
    total = Decimal("0")
    for item in reserva.items.select_related("id_variante"):
        item.precio_unitario = item.id_variante.precio
        item.save(update_fields=["precio_unitario"])
        total += item.precio_unitario
    reserva.monto_total = _redondear(total)
    reserva.monto_pagado = Decimal("0")
    reserva.estado = "PENDIENTE_PAGO"
    reserva.fecha_limite_pago = limite_pago or (timezone.now() + timedelta(hours=HORAS_PAGO_OFFLINE))
    reserva.fecha_vencimiento = reserva.calcular_vencimiento()
    reserva.save()


def _bloquear(id_reserva):
    """Reserva bloqueada para modificarla (dentro de una transacción)."""
    try:
        return FittingReservation.objects.select_for_update(of=("self",)).select_related(
            "id_sucursal", "id_empresa", "id_cliente__id_usuario"
        ).get(pk=id_reserva)
    except FittingReservation.DoesNotExist:
        raise ValueError("Reserva no encontrada.")


def _reembolsar(reserva, retener):
    """Devuelve lo pagado (menos la retención) por Stripe y deja los montos de la nota.

    retener=True aplica el 10% del precio total (vence o la cancela el
    cliente); retener=False devuelve todo (no hubo stock al pagar).
    """
    pagado = reserva.monto_pagado or Decimal("0")
    retenido = Decimal("0")
    if retener and pagado > 0:
        retenido = min(_redondear((reserva.monto_total or 0) * PORCENTAJE_RETENCION / 100), pagado)
    devuelto = pagado - retenido
    if devuelto > 0 and reserva.referencia_pago:
        try:
            reserva.referencia_reembolso = reembolsar_pago(reserva.referencia_pago, devuelto)
        except PagoRechazadoError as e:
            raise ValueError(f"Stripe no aceptó el reembolso: {e}")
    reserva.monto_retenido = retenido
    reserva.monto_devuelto = devuelto


def _liberar_prendas(reserva, usuario, motivo):
    """Repone el stock de las prendas apartadas y las quita del carrito."""
    from apps.sales.models import CartItem

    if reserva.estado == "PENDIENTE_PAGO":
        # Sin pago no se apartó stock: solo se cierran las prendas.
        reserva.items.filter(estado="PENDIENTE").update(estado="DEVUELTO")
        CartItem.objects.filter(id_reserva_item__id_reserva=reserva).delete()
        return
    for item in list(reserva.items.filter(estado="PENDIENTE")):
        ReservationStockService.liberar_item(item, usuario=usuario, motivo=motivo)


class ReservaPagoService:
    """Pago, vencimiento y cancelación de las reservas con anticipo."""

    @staticmethod
    @transaction.atomic
    def iniciar_pago(id_reserva, cliente, tipo_pago):
        """Crea el cobro en Stripe por el anticipo o el total. Devuelve (reserva, client_secret)."""
        reserva = _bloquear(id_reserva)
        if reserva.id_cliente_id != cliente.pk:
            raise ValueError("Reserva no encontrada.")
        if reserva.estado != "PENDIENTE_PAGO":
            raise ValueError("Esta reserva no está pendiente de pago.")
        if reserva.fecha_limite_pago and timezone.now() > reserva.fecha_limite_pago:
            raise ValueError("Venció el plazo para pagar esta reserva.")
        tipo_pago = (tipo_pago or "").upper()
        if tipo_pago not in TIPOS_PAGO:
            raise ValueError("Elige pagar el anticipo o el total.")
        verificar_disponibilidad(reserva)
        porcentaje = reserva.id_empresa.porcentaje_anticipo if tipo_pago == "ANTICIPO" else Decimal("100")
        monto = _redondear(reserva.monto_total * porcentaje / 100)
        try:
            referencia, client_secret = crear_intento_pago(monto)
        except PagoRechazadoError as e:
            raise ValueError(f"No se pudo iniciar el pago: {e}")
        reserva.tipo_pago = tipo_pago
        reserva.porcentaje_anticipo = porcentaje
        reserva.monto_a_pagar = monto
        reserva.referencia_pago = referencia
        reserva.save(update_fields=["tipo_pago", "porcentaje_anticipo", "monto_a_pagar", "referencia_pago"])
        return reserva, client_secret

    @staticmethod
    @transaction.atomic
    def confirmar_pago(id_reserva, cliente, referencia_pago):
        """Verifica el pago en Stripe, aparta las prendas y confirma la reserva."""
        reserva = _bloquear(id_reserva)
        if reserva.id_cliente_id != cliente.pk:
            raise ValueError("Reserva no encontrada.")
        if reserva.estado != "PENDIENTE_PAGO":
            raise ValueError("Esta reserva no está pendiente de pago.")
        if not reserva.referencia_pago or reserva.referencia_pago != referencia_pago:
            raise ValueError("La referencia de pago no corresponde a esta reserva.")
        try:
            verificar_pago(referencia_pago)
        except PagoRechazadoError as e:
            raise ValueError(f"Pago rechazado: {e}")
        ahora = timezone.now()
        reserva.monto_pagado = reserva.monto_a_pagar
        reserva.fecha_pago = ahora
        try:
            with transaction.atomic():
                ReservationStockService.reservar_items(reserva)
        except ReservationStockError as e:
            # Se cobró pero ya no hay stock: se devuelve todo y se cancela.
            _reembolsar(reserva, retener=False)
            reserva.estado = "CANCELADA"
            reserva.motivo_cierre = f"Sin stock al confirmar el pago: {e}"[:255]
            reserva.fecha_cierre = ahora
            reserva.items.filter(estado="PENDIENTE").update(estado="DEVUELTO")
            reserva.save()
            _auditar(None, "RESERVA_SIN_STOCK", reserva, f"Pago devuelto por falta de stock (Bs {reserva.monto_devuelto})")
            return reserva
        reserva.estado = "CONFIRMADA"
        reserva.fecha_limite_pago = None
        reserva.save()
        ReservationStockService.confirmar_reserva(reserva)
        _auditar(
            None, "RESERVA_PAGADA", reserva,
            f"{reserva.id_cliente.id_usuario} pagó Bs {reserva.monto_pagado} "
            f"({reserva.get_tipo_pago_display().lower()}); saldo Bs {reserva.saldo}",
        )
        return reserva

    @staticmethod
    @transaction.atomic
    def cancelar(id_reserva, usuario, motivo=None):
        """CU17 - El cliente cancela: se libera la prenda y se devuelve lo pagado menos el 10%."""
        reserva = _bloquear(id_reserva)
        if reserva.estado not in ESTADOS_ABIERTOS:
            raise ValueError("Esta reserva ya no se puede cancelar.")
        ahora = timezone.now()
        vence = reserva.fecha_vencimiento or reserva.calcular_vencimiento()
        if reserva.estado == "CONFIRMADA" and ahora > vence:
            raise ValueError("La reserva ya venció.")
        texto = (motivo or "").strip()[:200]
        _liberar_prendas(reserva, usuario, f"Cancelación Reserva #{reserva.id_reserva} (cliente)")
        if not _sin_pago(reserva):
            _reembolsar(reserva, retener=True)
        reserva.estado = "CANCELADA"
        reserva.motivo_cierre = f"Cancelada por el cliente{': ' + texto if texto else ''}"[:255]
        reserva.fecha_cierre = ahora
        reserva.save()
        detalle = "Cancelada (sin pago)" if reserva.monto_devuelto is None else (
            f"Cancelada: pagado Bs {reserva.monto_pagado}, retenido Bs {reserva.monto_retenido}, "
            f"devuelto Bs {reserva.monto_devuelto}"
        )
        _auditar(usuario, "RESERVA_CANCELADA", reserva, detalle)
        return reserva

    @staticmethod
    @transaction.atomic
    def vencer(id_reserva):
        """Vence una reserva (sin pago a tiempo o sin retirar a la semana)."""
        reserva = _bloquear(id_reserva)
        ahora = timezone.now()
        if reserva.estado == "PENDIENTE_PAGO":
            if not reserva.fecha_limite_pago or ahora <= reserva.fecha_limite_pago:
                return None
            motivo = f"Venció el plazo de {HORAS_PAGO_OFFLINE} horas para pagar"
        elif reserva.estado in ("PENDIENTE", "CONFIRMADA"):
            vence = reserva.fecha_vencimiento or reserva.calcular_vencimiento()
            if ahora <= vence:
                return None
            motivo = "No se retiró dentro de la semana"
        else:
            return None
        usuario = reserva.id_cliente.id_usuario
        _liberar_prendas(reserva, usuario, f"Reserva #{reserva.id_reserva} vencida")
        if not _sin_pago(reserva):
            _reembolsar(reserva, retener=True)
        reserva.estado = "VENCIDA"
        reserva.motivo_cierre = motivo
        reserva.fecha_cierre = ahora
        reserva.save()
        detalle = (
            f"Vencida ({motivo.lower()})" if reserva.monto_devuelto is None else
            f"Vencida: pagado Bs {reserva.monto_pagado}, retenido Bs {reserva.monto_retenido}, "
            f"devuelto Bs {reserva.monto_devuelto}"
        )
        _auditar(usuario, "RESERVA_VENCIDA", reserva, detalle)
        return reserva

    @staticmethod
    def procesar_vencimientos(empresa_id=None, cliente=None):
        """Vence todas las reservas cuyo plazo pasó. Devuelve cuántas vencieron.

        Cada reserva se procesa en su propia transacción: si Stripe falla con
        una, queda abierta para el próximo intento y se siguen las demás.
        """
        ahora = timezone.now()
        pendientes = FittingReservation.objects.filter(
            Q(estado="PENDIENTE_PAGO", fecha_limite_pago__lt=ahora)
            | Q(estado__in=("PENDIENTE", "CONFIRMADA"), fecha_vencimiento__lt=ahora)
            | Q(estado__in=("PENDIENTE", "CONFIRMADA"), fecha_vencimiento__isnull=True)
        )
        if empresa_id is not None:
            pendientes = pendientes.filter(id_empresa_id=empresa_id)
        if cliente is not None:
            pendientes = pendientes.filter(id_cliente=cliente)
        vencidas = 0
        for id_reserva in list(pendientes.values_list("id_reserva", flat=True)):
            try:
                if ReservaPagoService.vencer(id_reserva) is not None:
                    vencidas += 1
            except ValueError as e:
                logger.warning("No se pudo vencer la reserva %s: %s", id_reserva, e)
        return vencidas