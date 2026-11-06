# backend/apps/fidelidad/servicio.py
#
# NUEVO (Fase 3 - CU18): reglas del descuento por fidelidad.
#
# Compra que cuenta (por cliente, empresa y mes calendario en hora de Bolivia):
#   - pedido web pagado (PAGADA, ENVIADA o ENTREGADA), por su fecha de creación;
#   - venta POS REGISTRADA con el correo del cliente, por su fecha de venta (la
#     venta sin conexión conserva la hora en que se hizo).
#   El retiro de una reserva genera un pedido o una venta, así que cuenta ahí.
#   No cuentan: pendientes, canceladas, ventas anuladas o en conflicto y las
#   compras devueltas por completo (devolución completada de todas sus prendas).
#
# Beneficio: al llegar a las compras requeridas, la siguiente compra sin
# reservas en esa empresa tiene el porcentaje de descuento en las prendas (el
# envío se cobra completo). Una vez por mes y se reinicia el día 1.
import calendar
import logging
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import BeneficioFidelidad, ReglaFidelidad

logger = logging.getLogger(__name__)

ESTADOS_PEDIDO_PAGADO = ("PAGADA", "ENVIADA", "ENTREGADA")
ENLACE_CLIENTE = "/cart"
CENTAVO = Decimal("0.01")


# --------------------------------------------------------------- fechas

def periodo_de(fecha=None):
    """Día 1 del mes (hora de Bolivia) de una fecha/hora; por defecto, ahora."""
    local = timezone.localtime(fecha) if fecha else timezone.localtime()
    return local.date().replace(day=1)


def ultimo_dia(periodo):
    """Último día del mes del periodo."""
    return periodo.replace(day=calendar.monthrange(periodo.year, periodo.month)[1])


def rango_mes(periodo):
    """(inicio, fin) del mes como fechas/horas con zona: [inicio, fin)."""
    zona = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(periodo, time.min), zona)
    siguiente = ultimo_dia(periodo) + timedelta(days=1)
    return inicio, timezone.make_aware(datetime.combine(siguiente, time.min), zona)


def _redondear(valor):
    """Monto con 2 decimales."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------- conteo

def _devuelta_completa(lineas, filtro):
    """True si todas las unidades de las líneas tienen una devolución completada."""
    from apps.sales.models import DevolucionItem

    total = sum(linea.cantidad for linea in lineas)
    if total == 0:
        return False
    devuelto = DevolucionItem.objects.filter(
        id_devolucion__estado="COMPLETADA", **{f"{filtro}__in": lineas}
    ).aggregate(total=Sum("cantidad"))["total"] or 0
    return devuelto >= total


def compras_del_mes(id_cliente, id_empresa, periodo=None):
    """Compras que cuentan del cliente en la empresa durante el mes."""
    from apps.sales.models import Order, OrderItem, PosSale

    periodo = periodo or periodo_de()
    inicio, fin = rango_mes(periodo)
    compras = 0
    pedidos = Order.objects.filter(
        id_cliente_id=id_cliente, id_empresa_id=id_empresa,
        estado__in=ESTADOS_PEDIDO_PAGADO, fecha_creacion__gte=inicio, fecha_creacion__lt=fin,
    )
    for pedido in pedidos:
        lineas = list(OrderItem.objects.filter(id_orden=pedido))
        if not _devuelta_completa(lineas, "id_orden_item"):
            compras += 1
    ventas = PosSale.objects.filter(
        id_cliente_id=id_cliente, id_empresa_id=id_empresa,
        estado="REGISTRADA", fecha_venta__gte=inicio, fecha_venta__lt=fin,
    ).prefetch_related("items")
    for venta in ventas:
        if not _devuelta_completa(list(venta.items.all()), "id_venta_item"):
            compras += 1
    return compras


# --------------------------------------------------------------- estado

def estado(cliente, empresa, periodo=None):
    """Progreso del cliente en la empresa durante el mes y si tiene el descuento."""
    regla = ReglaFidelidad.vigente()
    periodo = periodo or periodo_de()
    compras = compras_del_mes(cliente.pk, empresa.pk, periodo)
    beneficio = BeneficioFidelidad.objects.filter(
        id_cliente=cliente, id_empresa=empresa, periodo=periodo
    ).first()
    usado = bool(beneficio and beneficio.usado)
    requeridas = regla.compras_requeridas
    return {
        "id_empresa": empresa.pk,
        "empresa": empresa.nombre,
        "activa": regla.activa,
        "compras": compras,
        "requeridas": requeridas,
        "faltan": max(requeridas - compras, 0),
        "porcentaje": float(regla.porcentaje),
        "disponible": regla.activa and not usado and compras >= requeridas,
        "usado": usado,
        "fecha_uso": beneficio.fecha_uso if usado else None,
        "monto_descuento": float(beneficio.monto_descuento or 0) if usado else 0.0,
        "vence": ultimo_dia(periodo),
    }


def calcular_descuento(cliente, empresa, subtotal_prendas, tiene_reservas=False):
    """Descuento de una compra: (monto, porcentaje, aviso).

    monto es 0 si el cliente no tiene el beneficio o si la compra lleva prendas
    reservadas (en ese caso el aviso explica que se usará en la próxima compra).
    """
    if cliente is None or empresa is None:
        return Decimal("0"), Decimal("0"), None
    datos = estado(cliente, empresa)
    if not datos["disponible"]:
        return Decimal("0"), Decimal("0"), None
    porcentaje = Decimal(str(datos["porcentaje"]))
    if tiene_reservas:
        return Decimal("0"), porcentaje, (
            "Tu compra tiene prendas reservadas: el descuento por fidelidad se "
            "aplicará en tu próxima compra sin reservas de este mes."
        )
    return _redondear(Decimal(subtotal_prendas) * porcentaje / 100), porcentaje, None


def _beneficio_del_mes(cliente_id, empresa_id, periodo, bloquear=False):
    """Beneficio del cliente en la empresa durante el mes (se crea si no existe)."""
    try:
        with transaction.atomic():
            beneficio, _ = BeneficioFidelidad.objects.get_or_create(
                id_cliente_id=cliente_id, id_empresa_id=empresa_id, periodo=periodo
            )
    except IntegrityError:
        beneficio = BeneficioFidelidad.objects.get(
            id_cliente_id=cliente_id, id_empresa_id=empresa_id, periodo=periodo
        )
    if bloquear:
        beneficio = BeneficioFidelidad.objects.select_for_update().get(pk=beneficio.pk)
    return beneficio


def apartar_para_pedido(orden, porcentaje, monto):
    """Vincula el descuento a un pedido web pendiente de pago (todavía no es uso)."""
    beneficio = _beneficio_del_mes(orden.id_cliente_id, orden.id_empresa_id, periodo_de(), bloquear=True)
    if beneficio.usado:
        raise ValueError("Ya usaste tu descuento por fidelidad de este mes.")
    beneficio.id_orden = orden
    beneficio.porcentaje = porcentaje
    beneficio.monto_descuento = monto
    beneficio.save(update_fields=["id_orden", "porcentaje", "monto_descuento"])
    return beneficio


def confirmar_uso_pedido(orden):
    """Marca como usado el descuento del pedido pagado (si lo tenía)."""
    beneficio = BeneficioFidelidad.objects.select_for_update().filter(id_orden=orden).first()
    if beneficio is None or beneficio.usado:
        return beneficio
    beneficio.fecha_uso = timezone.now()
    beneficio.save(update_fields=["fecha_uso"])
    return beneficio


def registrar_uso_venta(venta, porcentaje, monto):
    """Marca como usado el descuento en una venta POS."""
    beneficio = _beneficio_del_mes(venta.id_cliente_id, venta.id_empresa_id, periodo_de(), bloquear=True)
    if beneficio.usado:
        raise ValueError("El cliente ya usó su descuento por fidelidad de este mes.")
    beneficio.id_orden = None
    beneficio.id_venta = venta
    beneficio.porcentaje = porcentaje
    beneficio.monto_descuento = monto
    beneficio.fecha_uso = timezone.now()
    beneficio.save(update_fields=["id_orden", "id_venta", "porcentaje", "monto_descuento", "fecha_uso"])
    return beneficio


def descuento_de(orden=None, venta=None):
    """Monto del descuento por fidelidad usado en un pedido o una venta (0 si no tuvo)."""
    filtro = {"id_orden": orden} if orden is not None else {"id_venta": venta}
    beneficio = BeneficioFidelidad.objects.filter(fecha_uso__isnull=False, **filtro).first()
    return beneficio.monto_descuento if beneficio else Decimal("0")


def compra_con_descuento(orden=None, venta=None):
    """True si el pedido o la venta usó el descuento (no admite devolución ni cambio)."""
    return descuento_de(orden=orden, venta=venta) > 0


# --------------------------------------------------------------- aviso

def verificar_meta(cliente, empresa, periodo=None):
    """Si el cliente llegó a las compras requeridas este mes, lo registra y le avisa una vez."""
    from apps.users_auth.notificaciones import notificar

    regla = ReglaFidelidad.vigente()
    periodo = periodo or periodo_de()
    if not regla.activa or periodo != periodo_de():
        return False
    if compras_del_mes(cliente.pk, empresa.pk, periodo) < regla.compras_requeridas:
        return False
    beneficio = _beneficio_del_mes(cliente.pk, empresa.pk, periodo)
    if beneficio.usado or beneficio.fecha_alcanzado is not None:
        return False
    beneficio.fecha_alcanzado = timezone.now()
    beneficio.save(update_fields=["fecha_alcanzado"])
    porcentaje = f"{regla.porcentaje.normalize():f}"
    notificar(
        [cliente.id_usuario],
        "FIDELIDAD",
        f"¡Tu próxima compra en {empresa.nombre} tiene {porcentaje}% de descuento!",
        (
            f"Llegaste a {regla.compras_requeridas} compras este mes. Válido hasta el "
            f"{ultimo_dia(periodo):%d/%m} en prendas, sin reservas."
        ),
        ENLACE_CLIENTE,
        empresa.pk,
        f"fidelidad-{cliente.pk}-{empresa.pk}-{periodo:%Y%m}",
    )
    return True


def verificar_mes_actual():
    """Revisa a todos los clientes con compras este mes (al cambiar la regla). Devuelve cuántos ganaron."""
    from apps.sales.models import Order, PosSale
    from apps.users_auth.models import Cliente, Empresa

    inicio, fin = rango_mes(periodo_de())
    pares = set(Order.objects.filter(
        estado__in=ESTADOS_PEDIDO_PAGADO, fecha_creacion__gte=inicio, fecha_creacion__lt=fin,
        id_empresa__isnull=False,
    ).values_list("id_cliente_id", "id_empresa_id"))
    pares |= set(PosSale.objects.filter(
        estado="REGISTRADA", fecha_venta__gte=inicio, fecha_venta__lt=fin,
        id_cliente__isnull=False, id_empresa__isnull=False,
    ).values_list("id_cliente_id", "id_empresa_id"))
    clientes = Cliente.objects.select_related("id_usuario").in_bulk({c for c, _ in pares})
    empresas = Empresa.objects.in_bulk({e for _, e in pares})
    return sum(1 for c, e in pares if verificar_meta(clientes[c], empresas[e]))


def _al_guardar_compra(sender, instance, **kwargs):
    """Señal: tras guardar un pedido o una venta POS, revisa si el cliente llegó a la meta."""
    if instance.id_cliente_id is None or instance.id_empresa_id is None:
        return
    try:
        # Punto de guardado propio: un error aquí nunca anula la compra.
        with transaction.atomic():
            fecha = getattr(instance, "fecha_venta", None) or getattr(instance, "fecha_creacion", None)
            verificar_meta(instance.id_cliente, instance.id_empresa, periodo_de(fecha))
    except Exception:
        logger.exception("No se pudo revisar el descuento por fidelidad.")


def conectar_senales():
    """Conecta las señales (se llama una vez desde FidelidadConfig.ready())."""
    from django.db.models.signals import post_save

    from apps.sales.models import Order, PosSale

    post_save.connect(_al_guardar_compra, sender=Order, dispatch_uid="fidelidad-pedido")
    post_save.connect(_al_guardar_compra, sender=PosSale, dispatch_uid="fidelidad-venta")