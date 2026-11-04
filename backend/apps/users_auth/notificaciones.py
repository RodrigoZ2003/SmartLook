# backend/apps/users_auth/notificaciones.py
"""Centro de notificaciones (Fase 2 - CU16).

Los avisos se crean solos cuando cambia el estado de una reserva, un pedido,
un delivery, una devolución, un cambio de prenda o una venta sin conexión
(señales de Django conectadas en UsersAuthConfig.ready()). No hay push ni
correo: el usuario los ve en la campana de la web o del móvil.

Destinatarios:
- Cliente: reserva confirmada (pago recibido), recordatorio un día antes de
  que venza, reserva vencida o cancelada (con lo devuelto), reserva sin
  conexión registrada, pedido pagado, estados del delivery, devoluciones y
  cambios.
- Personal: solo SUPER_ADMIN (todas las empresas) y ADMIN_EMPRESA (la suya):
  nueva reserva pagada, venta sin conexión en conflicto, devolución
  solicitada y cambio solicitado. El cajero y el encargado no reciben avisos.

Cada aviso lleva una "clave" (ej. "reserva-12-CONFIRMADA") para no repetirse.
Un error al notificar nunca interrumpe la operación que lo originó.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save, pre_save
from django.utils import timezone

from .models import Notificacion, Usuario

logger = logging.getLogger(__name__)

# Rutas de la web a las que lleva cada aviso.
ENLACE_RESERVAS = "/reservations"
ENLACE_PEDIDOS = "/orders"
ENLACE_ENTREGAS = "/deliveries"
ENLACE_CONFLICTOS = "/pos/operaciones"
HORAS_RECORDATORIO = 24


# ---------------------------------------------------------------- envío
def notificar(usuarios, tipo, titulo, mensaje, enlace=None, empresa_id=None, clave=None):
    """Crea el aviso para cada usuario (una sola vez por clave). Nunca lanza errores."""
    creadas = 0
    for usuario in {u.pk: u for u in usuarios if u is not None}.values():
        try:
            with transaction.atomic():
                if clave and Notificacion.objects.filter(id_usuario=usuario, clave=clave).exists():
                    continue
                Notificacion.objects.create(
                    id_usuario=usuario,
                    id_empresa_id=empresa_id,
                    tipo=tipo,
                    titulo=titulo[:150],
                    mensaje=mensaje[:500],
                    enlace=enlace,
                    clave=clave,
                )
                creadas += 1
        except Exception:
            logger.exception("No se pudo crear la notificación '%s'.", titulo)
    return creadas


def administradores(empresa_id):
    """SUPER_ADMIN activos y ADMIN_EMPRESA activos de la empresa."""
    return list(
        Usuario.objects.filter(estado="ACTIVO")
        .filter(Q(roles__nombre="SUPER_ADMIN") | Q(roles__nombre="ADMIN_EMPRESA", id_empresa_id=empresa_id))
        .distinct()
    )


def usuario_de(cliente):
    """Usuario del cliente (o None)."""
    return cliente.id_usuario if cliente is not None else None


def _bs(valor):
    """Monto en Bs con 2 decimales."""
    return f"Bs {float(valor or 0):.2f}"


def _fecha(valor):
    """Fecha y hora local dd/mm/aaaa HH:MM."""
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else ""


def _nombre(usuario):
    """Nombre completo de un usuario."""
    return f"{usuario.nombres} {usuario.apellidos}" if usuario else "El cliente"


# ---------------------------------------------------------------- recordatorios
def generar_recordatorios(usuario):
    """Recordatorio un día antes de que venza cada reserva pagada del cliente.

    No hay tareas programadas: se revisa cuando el cliente abre la campana.
    """
    from apps.reservations.models import FittingReservation

    ahora = timezone.now()
    reservas = FittingReservation.objects.filter(
        id_cliente__id_usuario=usuario,
        estado="CONFIRMADA",
        fecha_vencimiento__gt=ahora,
        fecha_vencimiento__lte=ahora + timedelta(hours=HORAS_RECORDATORIO),
    ).select_related("id_sucursal")
    for reserva in reservas:
        saldo = reserva.saldo
        texto_saldo = f" Saldo a pagar al retirar: {_bs(saldo)}." if saldo else ""
        notificar(
            [usuario],
            "RESERVA",
            f"Tu Reserva #{reserva.id_reserva} vence mañana",
            f"Retírala en {reserva.id_sucursal.nombre} antes del {_fecha(reserva.fecha_vencimiento)}."
            f"{texto_saldo} Si vence, se devuelve lo pagado menos el 10% del total.",
            ENLACE_RESERVAS,
            reserva.id_empresa_id,
            clave=f"reserva-{reserva.id_reserva}-recordatorio",
        )


# ---------------------------------------------------------------- señales
def _guardar_estado_anterior(sender, instance, **kwargs):
    """Antes de guardar, recuerda el estado que tenía el registro."""
    instance._estado_anterior = None
    if instance.pk:
        instance._estado_anterior = (
            sender.objects.filter(pk=instance.pk).values_list("estado", flat=True).first()
        )


def _estado_nuevo(instance, created):
    """Estado al que pasó el registro, o None si no cambió."""
    anterior = None if created else getattr(instance, "_estado_anterior", None)
    return instance.estado if instance.estado != anterior else None


def _reserva(sender, instance, created, **kwargs):
    """Reserva confirmada (pago), cancelada o vencida."""
    estado = _estado_nuevo(instance, created)
    if estado not in ("CONFIRMADA", "CANCELADA", "VENCIDA"):
        return
    reserva = instance
    cliente = usuario_de(reserva.id_cliente)
    numero = f"Reserva #{reserva.id_reserva}"
    clave = f"reserva-{reserva.id_reserva}-{estado}"
    if estado == "CONFIRMADA":
        if reserva.monto_pagado:
            tipo_pago = reserva.get_tipo_pago_display().lower() if reserva.tipo_pago else "pago"
            saldo = reserva.saldo
            texto_saldo = f" Saldo a pagar al retirar: {_bs(saldo)}." if saldo else " No tienes saldo pendiente."
            notificar(
                [cliente], "RESERVA", f"Pago recibido: {numero} confirmada",
                f"Pagaste {_bs(reserva.monto_pagado)} ({tipo_pago}) y tus prendas quedaron apartadas en "
                f"{reserva.id_sucursal.nombre}.{texto_saldo} Retírala hasta el {_fecha(reserva.fecha_vencimiento)}.",
                ENLACE_RESERVAS, reserva.id_empresa_id, clave,
            )
            notificar(
                administradores(reserva.id_empresa_id), "RESERVA", f"Nueva {numero}",
                f"{_nombre(cliente)} reservó {reserva.items.count()} prenda(s) en {reserva.id_sucursal.nombre} "
                f"y pagó {_bs(reserva.monto_pagado)} ({tipo_pago}).",
                ENLACE_RESERVAS, reserva.id_empresa_id, clave,
            )
        else:
            notificar(
                [cliente], "RESERVA", f"{numero} confirmada",
                f"Tus prendas te esperan en {reserva.id_sucursal.nombre}.",
                ENLACE_RESERVAS, reserva.id_empresa_id, clave,
            )
        return
    accion = "cancelada" if estado == "CANCELADA" else "vencida"
    if reserva.monto_devuelto is not None:
        detalle = (
            f"Nota {reserva.numero_nota}: pagaste {_bs(reserva.monto_pagado)}, se retuvo "
            f"{_bs(reserva.monto_retenido)} y se te devuelve {_bs(reserva.monto_devuelto)} a tu tarjeta."
        )
    else:
        detalle = reserva.motivo_cierre or "No tenía pagos registrados."
    notificar(
        [cliente], "RESERVA", f"{numero} {accion}", detalle,
        ENLACE_RESERVAS, reserva.id_empresa_id, clave,
    )


def _pedido(sender, instance, created, **kwargs):
    """Pedido pagado."""
    if _estado_nuevo(instance, created) != "PAGADA":
        return
    pedido = instance
    if pedido.tipo_entrega == "DELIVERY":
        siguiente = "Te avisaremos cuando salga a delivery."
    else:
        sucursal = pedido.id_sucursal.nombre if pedido.id_sucursal_id else "la sucursal"
        siguiente = f"Retíralo en {sucursal}."
    notificar(
        [usuario_de(pedido.id_cliente)], "PEDIDO", f"Pedido #{pedido.id_orden} pagado",
        f"Recibimos tu pago de {_bs(pedido.total)}. {siguiente}",
        ENLACE_PEDIDOS, pedido.id_empresa_id, f"pedido-{pedido.id_orden}-PAGADA",
    )


TEXTOS_DELIVERY = {
    "EN_PREPARACION": ("se está preparando", "La tienda está preparando tu pedido."),
    "EN_CAMINO": ("está en camino", None),
    "ENTREGADO": ("fue entregado", "¡Gracias por tu compra!"),
}


def _delivery(sender, instance, created, **kwargs):
    """Estados del delivery del pedido."""
    estado = _estado_nuevo(instance, created)
    if estado not in TEXTOS_DELIVERY:
        return
    pedido = instance.id_orden
    accion, texto = TEXTOS_DELIVERY[estado]
    if estado == "EN_CAMINO":
        texto = f"{_nombre(instance.id_repartidor)} lleva tu pedido a {instance.direccion}."
    notificar(
        [usuario_de(pedido.id_cliente)], "DELIVERY", f"Tu Pedido #{pedido.id_orden} {accion}", texto,
        ENLACE_PEDIDOS, pedido.id_empresa_id, f"delivery-{instance.pk}-{estado}",
    )


def _devolucion(sender, instance, created, **kwargs):
    """Devolución solicitada (al personal) y sus estados (al cliente)."""
    from apps.sales.serializers import mensaje_devolucion_cliente

    estado = _estado_nuevo(instance, created)
    if estado is None:
        return
    devolucion = instance
    clave = f"devolucion-{devolucion.pk}-{estado}"
    if estado == "SOLICITADA":
        if devolucion.modalidad == "DELIVERY":
            origen = f"Pedido #{devolucion.id_orden_id}" if devolucion.id_orden_id else "una compra"
            notificar(
                administradores(devolucion.id_empresa_id), "DEVOLUCION",
                f"Devolución solicitada {devolucion.numero_nota}",
                f"{_nombre(usuario_de(devolucion.id_cliente))} pidió devolver prendas del {origen} "
                f"(reembolso {_bs(devolucion.monto_reembolso)}). Asigna repartidor y fecha de recojo.",
                ENLACE_ENTREGAS, devolucion.id_empresa_id, clave,
            )
        return
    if devolucion.id_cliente_id:
        notificar(
            [usuario_de(devolucion.id_cliente)], "DEVOLUCION",
            f"Devolución {devolucion.numero_nota}: {devolucion.get_estado_display().lower()}",
            mensaje_devolucion_cliente(devolucion),
            ENLACE_PEDIDOS, devolucion.id_empresa_id, clave,
        )


def _cambio(sender, instance, created, **kwargs):
    """Cambio solicitado (al personal) y sus estados (al cliente)."""
    from apps.sales.serializers import mensaje_para_cliente

    estado = _estado_nuevo(instance, created)
    if estado is None:
        return
    cambio = instance
    clave = f"cambio-{cambio.pk}-{estado}"
    if estado == "SOLICITADO":
        if cambio.modalidad == "DELIVERY":
            notificar(
                administradores(cambio.id_empresa_id), "CAMBIO", f"Cambio de prenda solicitado {cambio.numero_nota}",
                f"{_nombre(usuario_de(cambio.id_cliente))} pidió cambiar {cambio.id_variante_devuelta} por "
                f"{cambio.id_variante_entregada}. Asigna repartidor y fecha.",
                ENLACE_ENTREGAS, cambio.id_empresa_id, clave,
            )
        return
    if cambio.id_cliente_id:
        notificar(
            [usuario_de(cambio.id_cliente)], "CAMBIO",
            f"Cambio de prenda {cambio.numero_nota}: {cambio.get_estado_display().lower()}",
            mensaje_para_cliente(cambio),
            ENLACE_PEDIDOS, cambio.id_empresa_id, clave,
        )


def _operacion_sync(sender, instance, created, **kwargs):
    """Venta sin conexión en conflicto (al personal) y reserva sin conexión registrada (al cliente)."""
    estado = _estado_nuevo(instance, created)
    operacion = instance
    clave = f"sync-{operacion.pk}-{estado}"
    if estado == "EN_CONFLICTO" and operacion.tipo == "VENTA_POS":
        venta = f"Venta #{operacion.id_venta_id}" if operacion.id_venta_id else "Una venta"
        notificar(
            administradores(operacion.id_empresa_id), "CONFLICTO", "Venta sin conexión en conflicto",
            f"{venta} de {_nombre(operacion.id_usuario)}: {operacion.mensaje or 'revisa el detalle'}.",
            ENLACE_CONFLICTOS, operacion.id_empresa_id, clave,
        )
    elif estado == "SINCRONIZADA" and operacion.tipo == "RESERVA" and operacion.id_reserva_id:
        reserva = operacion.id_reserva
        limite = f" antes del {_fecha(reserva.fecha_limite_pago)}" if reserva.fecha_limite_pago else ""
        notificar(
            [usuario_de(reserva.id_cliente)], "RESERVA", f"Reserva #{reserva.id_reserva} registrada",
            f"Tu reserva hecha sin conexión llegó a {reserva.id_sucursal.nombre}. Págala{limite}; "
            f"si no, vencerá y las prendas no quedarán apartadas.",
            ENLACE_RESERVAS, reserva.id_empresa_id, clave,
        )


def conectar_senales():
    """Conecta las señales (se llama una vez desde UsersAuthConfig.ready())."""
    from apps.reservations.models import FittingReservation
    from apps.sales.models import CambioPrenda, Delivery, Devolucion, Order, SyncOperacion

    receptores = [
        (FittingReservation, _reserva),
        (Order, _pedido),
        (Delivery, _delivery),
        (Devolucion, _devolucion),
        (CambioPrenda, _cambio),
        (SyncOperacion, _operacion_sync),
    ]
    for modelo, receptor in receptores:
        etiqueta = modelo.__name__
        pre_save.connect(_guardar_estado_anterior, sender=modelo, dispatch_uid=f"notif-pre-{etiqueta}")
        post_save.connect(receptor, sender=modelo, dispatch_uid=f"notif-post-{etiqueta}")