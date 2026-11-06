"""CU12 - Devolución de prendas con reembolso y nota de devolución.

Reglas (Fase 2):
- Plazo: 7 días desde la compra (venta POS o pedido con retiro) o desde la
  entrega (pedido con delivery).
- Motivos y reembolso de cada prenda:
    PRODUCTO_DANADO -> llegó dañada o con defecto. 100%. No vuelve al stock.
    ERROR_TIENDA    -> le llegó otra prenda. 100%. Vuelve al stock.
    NO_LA_QUIERO    -> ya no la quiere / no le gustó. 90%: la empresa
                       retiene el 10%. Vuelve al stock.
- Envío: si el pedido fue con delivery y alguna prenda se devuelve por
  culpa de la tienda (dañada u otra prenda), se devuelve el costo de envío,
  una sola vez por pedido. Si el cliente ya no la quiere, no se devuelve.
- Modalidades:
    TIENDA   -> la registra el personal y se completa en el momento (venta
                POS, pedido con retiro o el cliente que trae un pedido).
    DELIVERY -> la solicita el cliente desde "Mis pedidos" (pedido con
                delivery entregado). El encargado la aprueba asignando
                repartidor y fecha de recojo dentro de 48 horas; el
                repartidor marca "En camino" y "Completada" al recoger y
                revisar la prenda.
- Al completar: vuelve al stock lo que corresponde y se reembolsa:
    pedido pagado con tarjeta en línea -> reembolso en Stripe;
    venta POS -> efectivo en caja;
    otro caso (pago anterior sin Stripe) -> se registra como manual.
  Stock: entra la prenda de la compra, salvo la dañada. Con ERROR_TIENDA
  también entra la comprada: nunca salió de la tienda (se descontó al
  vender) y la que se envió por error vuelve, así el inventario cuadra.
- Una prenda con un cambio de talla/color (CU05) no se puede devolver, y
  no se puede devolver más de lo comprado.
- La devolución completada es la nota de devolución (ND-000001).
- MODIFICADO (Fase 3 - CU18): una compra que usó el descuento por fidelidad
  no admite devolución.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.fidelidad import servicio as fidelidad
from apps.inventory.services import StockService
from apps.users_auth.models import Usuario
from common.utils import log_audit

from .cambios import ESTADOS_ACTIVOS as ESTADOS_CAMBIO_ACTIVOS
from .integrations.stripe_payment import PagoRechazadoError, reembolsar_pago
from .models import CambioPrenda, Devolucion, DevolucionItem, Order, OrderItem, PosSale

PLAZO_DEVOLUCION_DIAS = 7
PLAZO_RECOJO_HORAS = 48
PORCENTAJE_RETENCION = Decimal("10")
MOTIVOS_TIENDA = ("PRODUCTO_DANADO", "ERROR_TIENDA")
MOTIVOS = MOTIVOS_TIENDA + ("NO_LA_QUIERO",)
ESTADOS_ACTIVOS = ("SOLICITADA", "PROGRAMADA", "EN_CAMINO", "COMPLETADA")
CENTAVO = Decimal("0.01")


def _redondear(valor):
    """Redondea a centavos."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


class CompraDevolucion:
    """Pedido en línea o venta POS sobre el que se pide la devolución."""

    def __init__(self, orden=None, venta=None):
        """Toma los datos comunes de la compra (sucursal, cliente, fechas, líneas)."""
        self.orden = orden
        self.venta = venta
        if venta is not None:
            self.tipo = "VENTA"
            self.numero = venta.id_venta
            self.etiqueta = f"Venta #{venta.id_venta}"
            self.sucursal = venta.id_sucursal
            self.empresa_id = venta.id_empresa_id
            self.cliente = venta.id_cliente
            self.tipo_entrega = None
            self.fecha_base = venta.fecha_venta
            self.lineas = list(venta.items.select_related(
                "id_variante__id_producto", "id_variante__id_talla", "id_variante__id_color"
            ).order_by("id_item"))
        else:
            delivery = getattr(orden, "delivery", None) if orden.tipo_entrega == "DELIVERY" else None
            self.tipo = "PEDIDO"
            self.numero = orden.id_orden
            self.etiqueta = f"Pedido #{orden.id_orden}"
            self.sucursal = orden.id_sucursal
            self.empresa_id = orden.id_empresa_id
            self.cliente = orden.id_cliente
            self.tipo_entrega = orden.tipo_entrega
            self.fecha_base = (
                delivery.fecha_entrega if delivery and delivery.fecha_entrega else orden.fecha_creacion
            )
            self.lineas = list(OrderItem.objects.filter(id_orden=orden).select_related(
                "id_variante__id_producto", "id_variante__id_talla", "id_variante__id_color"
            ).order_by("id_item"))

    @property
    def vence(self):
        """Fecha y hora en que vence el plazo para devolver."""
        return self.fecha_base + timedelta(days=PLAZO_DEVOLUCION_DIAS)

    def filtro_linea(self, linea):
        """Filtro de DevolucionItem / CambioPrenda para una línea."""
        if self.tipo == "VENTA":
            return {"id_venta_item": linea}
        return {"id_orden_item": linea}

    def ya_devuelto(self, linea):
        """Unidades de la línea ya devueltas o con devolución en curso."""
        return DevolucionItem.objects.filter(
            id_devolucion__estado__in=ESTADOS_ACTIVOS, **self.filtro_linea(linea)
        ).aggregate(total=Sum("cantidad"))["total"] or 0

    def disponible(self, linea):
        """Unidades de la línea que todavía se pueden devolver."""
        return max(0, linea.cantidad - self.ya_devuelto(linea))

    def problema_compra(self, modalidad):
        """Motivo por el que la compra no se puede devolver, o None."""
        # NUEVO (CU18): la compra con descuento por fidelidad no se devuelve.
        if fidelidad.compra_con_descuento(orden=self.orden, venta=self.venta):
            return "Esta compra usó el descuento por fidelidad: no admite devolución."
        if self.tipo == "VENTA":
            if self.venta.estado != "REGISTRADA":
                return "La venta está anulada o tiene un conflicto sin resolver."
            if modalidad == "DELIVERY":
                return "Las ventas en tienda se devuelven en la tienda."
        elif self.tipo_entrega == "DELIVERY":
            if self.orden.estado != "ENTREGADA":
                return "El pedido todavía no fue entregado."
        else:
            if self.orden.estado not in ("PAGADA", "ENTREGADA"):
                return "El pedido no está pagado."
            if modalidad == "DELIVERY":
                return "Los pedidos con retiro se devuelven en la tienda."
        if timezone.now() > self.vence:
            return (
                f"Venció el plazo de {PLAZO_DEVOLUCION_DIAS} días para la devolución "
                f"({timezone.localtime(self.vence):%d/%m/%Y %H:%M})."
            )
        return None

    def problema_linea(self, linea):
        """Motivo por el que la prenda no se puede devolver, o None."""
        if CambioPrenda.objects.filter(
            estado__in=ESTADOS_CAMBIO_ACTIVOS, **self.filtro_linea(linea)
        ).exists():
            return "Esta prenda tiene un cambio de talla o color."
        if self.disponible(linea) == 0:
            return "Esta prenda ya se devolvió."
        return None

    def envio_ya_devuelto(self):
        """True si el envío del pedido ya se devolvió (o está en una devolución en curso)."""
        if self.tipo != "PEDIDO":
            return True
        return Devolucion.objects.filter(
            id_orden=self.orden, estado__in=ESTADOS_ACTIVOS, monto_envio__gt=0
        ).exists()


def cargar_compra(tipo, numero, empresa_id=None, cliente=None):
    """Busca la venta o el pedido. empresa_id/cliente limitan lo que se puede ver."""
    tipo = (tipo or "").upper()
    if tipo not in ("VENTA", "PEDIDO") or not str(numero or "").isdigit():
        raise ValueError("Indica el tipo (venta o pedido) y su número.")
    if tipo == "VENTA":
        venta = PosSale.objects.select_related(
            "id_sucursal", "id_cliente__id_usuario"
        ).filter(pk=int(numero)).first()
        if venta is None or (empresa_id is not None and venta.id_empresa_id != empresa_id) \
                or cliente is not None:
            raise ValueError(f"No existe la venta #{numero}.")
        return CompraDevolucion(venta=venta)
    orden = Order.objects.select_related(
        "id_sucursal", "id_cliente__id_usuario", "delivery"
    ).filter(pk=int(numero)).first()
    if orden is None or (empresa_id is not None and orden.id_empresa_id != empresa_id) \
            or (cliente is not None and orden.id_cliente_id != cliente.pk):
        raise ValueError(f"No existe el pedido #{numero}.")
    return CompraDevolucion(orden=orden)


def leer_items(compra, items_data):
    """Valida las prendas a devolver. Devuelve [(línea, cantidad, motivo)]."""
    if not isinstance(items_data, list) or not items_data:
        raise ValueError("Elige al menos una prenda a devolver.")
    lineas = {linea.pk: linea for linea in compra.lineas}
    pedidas = {}
    for dato in items_data:
        if not isinstance(dato, dict):
            raise ValueError("Prenda inválida.")
        try:
            id_item = int(dato.get("id_item"))
            cantidad = int(dato.get("cantidad") or 1)
        except (TypeError, ValueError):
            raise ValueError("Prenda o cantidad inválida.")
        linea = lineas.get(id_item)
        if linea is None:
            raise ValueError(f"La prenda {id_item} no es de la {compra.etiqueta.lower()}.")
        motivo = dato.get("motivo")
        if motivo not in MOTIVOS:
            raise ValueError("Elige el motivo de la devolución.")
        if id_item in pedidas:
            raise ValueError(f"La prenda {linea.id_variante} está repetida.")
        problema = compra.problema_linea(linea)
        if problema:
            raise ValueError(f"{linea.id_variante}: {problema}")
        disponible = compra.disponible(linea)
        if cantidad < 1 or cantidad > disponible:
            raise ValueError(f"{linea.id_variante}: puedes devolver entre 1 y {disponible} unidad(es).")
        pedidas[id_item] = (linea, cantidad, motivo)
    return list(pedidas.values())


def calcular(compra, items):
    """Montos de la devolución (sin guardar nada).

    items: [(línea, cantidad, motivo)]. Devuelve un dict con el detalle por
    prenda, el total de las prendas, lo retenido, el envío y el reembolso.
    """
    detalle = []
    total_prendas = total_retenido = Decimal("0")
    culpa_tienda = False
    for linea, cantidad, motivo in items:
        subtotal = _redondear(linea.precio_unitario * cantidad)
        porcentaje = PORCENTAJE_RETENCION if motivo == "NO_LA_QUIERO" else Decimal("0")
        retenido = _redondear(subtotal * porcentaje / 100)
        culpa_tienda = culpa_tienda or motivo in MOTIVOS_TIENDA
        total_prendas += subtotal
        total_retenido += retenido
        detalle.append({
            "linea": linea,
            "id_item": linea.pk,
            "prenda": str(linea.id_variante),
            "cantidad": cantidad,
            "motivo": motivo,
            "precio_unitario": linea.precio_unitario,
            "subtotal": subtotal,
            "porcentaje_retencion": porcentaje,
            "monto_retenido": retenido,
            "monto_reembolso": subtotal - retenido,
            "repone_stock": motivo != "PRODUCTO_DANADO",
        })
    envio = Decimal("0")
    if culpa_tienda and compra.tipo_entrega == "DELIVERY" and not compra.envio_ya_devuelto():
        envio = _redondear(compra.orden.costo_envio or 0)
    return {
        "items": detalle,
        "monto_prendas": total_prendas,
        "monto_retenido": total_retenido,
        "monto_envio": envio,
        "monto_reembolso": total_prendas - total_retenido + envio,
        "metodo_reembolso": metodo_de_reembolso(compra),
    }


def metodo_de_reembolso(compra):
    """STRIPE si el pedido se pagó con tarjeta en línea; EFECTIVO si es venta POS."""
    if compra.tipo == "VENTA":
        return "EFECTIVO"
    referencia = compra.orden.referencia_pago or ""
    if compra.orden.metodo_pago == "TARJETA" and referencia.startswith("pi_"):
        return "STRIPE"
    return "MANUAL"


def _crear(compra, items, modalidad, usuario, observacion):
    """Crea la devolución con sus prendas y montos (estado SOLICITADA)."""
    montos = calcular(compra, items)
    devolucion = Devolucion.objects.create(
        id_orden=compra.orden,
        id_venta=compra.venta,
        id_cliente=compra.cliente,
        id_empresa_id=compra.empresa_id,
        id_sucursal=compra.sucursal,
        modalidad=modalidad,
        estado="SOLICITADA",
        monto_prendas=montos["monto_prendas"],
        monto_retenido=montos["monto_retenido"],
        monto_envio=montos["monto_envio"],
        monto_reembolso=montos["monto_reembolso"],
        metodo_reembolso=montos["metodo_reembolso"],
        observacion=(observacion or "").strip()[:255] or None,
        solicitado_por=usuario,
    )
    for fila in montos["items"]:
        DevolucionItem.objects.create(
            id_devolucion=devolucion,
            id_orden_item=fila["linea"] if compra.tipo == "PEDIDO" else None,
            id_venta_item=fila["linea"] if compra.tipo == "VENTA" else None,
            cantidad=fila["cantidad"],
            motivo=fila["motivo"],
            precio_unitario=fila["precio_unitario"],
            porcentaje_retencion=fila["porcentaje_retencion"],
            monto_retenido=fila["monto_retenido"],
            monto_reembolso=fila["monto_reembolso"],
            repone_stock=fila["repone_stock"],
        )
    return devolucion


def _completar(devolucion, usuario):
    """Repone el stock, reembolsa y cierra la devolución (nota de devolución)."""
    items = devolucion.items.select_related("id_orden_item__id_variante", "id_venta_item__id_variante")
    for item in items:
        if not item.repone_stock:
            continue
        linea = item.id_orden_item or item.id_venta_item
        StockService.registrar_movimiento(
            sucursal=devolucion.id_sucursal,
            variante=linea.id_variante,
            usuario=usuario,
            tipo="ENTRADA",
            cantidad=item.cantidad,
            motivo=f"Prenda devuelta (devolución {devolucion.numero_nota})",
        )
    devolucion.estado = "COMPLETADA"
    devolucion.condiciones_verificadas = True
    devolucion.completado_por = usuario
    devolucion.fecha_completado = timezone.now()
    if devolucion.metodo_reembolso == "STRIPE" and devolucion.monto_reembolso > 0:
        try:
            devolucion.referencia_reembolso = reembolsar_pago(
                devolucion.id_orden.referencia_pago, devolucion.monto_reembolso
            )
        except PagoRechazadoError as e:
            raise ValueError(f"Stripe no aceptó el reembolso: {e}")
    devolucion.save()


def _auditar(usuario, accion, devolucion, texto):
    """Registra el evento de la devolución en la bitácora de su empresa."""
    if devolucion.id_orden_id:
        origen = f"Pedido #{devolucion.id_orden_id}"
    else:
        origen = f"Venta #{devolucion.id_venta_id}"
    log_audit(
        usuario=usuario,
        accion=accion,
        tabla_afectada="devolucion",
        registro_id=devolucion.id_devolucion,
        descripcion=(
            f"{usuario.nombres} {usuario.apellidos} {texto} - Devolución {devolucion.numero_nota} "
            f"del {origen}: reembolso Bs {devolucion.monto_reembolso}"
        ),
        empresa=devolucion.id_empresa_id,
    )


class DevolucionService:
    """Operaciones de la devolución con reembolso (CU12)."""

    @staticmethod
    @transaction.atomic
    def solicitar(usuario_cliente, cliente, id_orden, items_data, observacion=None):
        """El cliente pide la devolución de prendas de su pedido con delivery entregado."""
        compra = cargar_compra("PEDIDO", id_orden, cliente=cliente)
        if compra.tipo_entrega != "DELIVERY":
            raise ValueError("Los pedidos con retiro se devuelven en la tienda.")
        problema = compra.problema_compra("DELIVERY")
        if problema:
            raise ValueError(problema)
        items = leer_items(compra, items_data)
        devolucion = _crear(compra, items, "DELIVERY", usuario_cliente, observacion)
        _auditar(usuario_cliente, "DEVOLUCION_SOLICITADA", devolucion, "solicitó una devolución")
        return devolucion

    @staticmethod
    @transaction.atomic
    def registrar_en_tienda(usuario, empresa_id, tipo, numero, items_data, condiciones_ok=False,
                            observacion=None):
        """El personal registra y completa una devolución en la tienda.

        empresa_id: empresa del usuario (None para el SUPER_ADMIN).
        """
        compra = cargar_compra(tipo, numero, empresa_id=empresa_id)
        problema = compra.problema_compra("TIENDA")
        if problema:
            raise ValueError(problema)
        items = leer_items(compra, items_data)
        if not condiciones_ok:
            raise ValueError("Confirma que revisaste la prenda y cumple las condiciones del motivo.")
        devolucion = _crear(compra, items, "TIENDA", usuario, observacion)
        devolucion.aprobado_por = usuario
        devolucion.fecha_aprobacion = timezone.now()
        _completar(devolucion, usuario)
        _auditar(usuario, "DEVOLUCION_EN_TIENDA", devolucion, "registró una devolución en tienda")
        return devolucion

    @staticmethod
    def _bloquear(id_devolucion):
        """Devolución bloqueada para modificarla (dentro de una transacción)."""
        try:
            return Devolucion.objects.select_for_update(of=("self",)).select_related(
                "id_sucursal", "id_orden"
            ).get(pk=id_devolucion)
        except Devolucion.DoesNotExist:
            raise ValueError("Devolución no encontrada.")

    @staticmethod
    @transaction.atomic
    def aprobar(id_devolucion, usuario, id_repartidor, fecha_programada):
        """El encargado aprueba: asigna repartidor y fecha de recojo (máximo 48 h)."""
        devolucion = DevolucionService._bloquear(id_devolucion)
        if devolucion.estado != "SOLICITADA":
            raise ValueError("Solo se puede aprobar una devolución solicitada.")
        repartidor = Usuario.objects.filter(
            pk=id_repartidor,
            estado="ACTIVO",
            roles__nombre="REPARTIDOR",
            id_empresa_id=devolucion.id_empresa_id,
        ).first() if str(id_repartidor or "").isdigit() else None
        if repartidor is None:
            raise ValueError("Elige un repartidor activo de la empresa.")
        ahora = timezone.now()
        limite = ahora + timedelta(hours=PLAZO_RECOJO_HORAS)
        if fecha_programada is None:
            raise ValueError("Indica la fecha y hora del recojo.")
        if timezone.is_naive(fecha_programada):
            fecha_programada = timezone.make_aware(fecha_programada)
        if fecha_programada < ahora - timedelta(minutes=5) or fecha_programada > limite:
            raise ValueError(
                f"El recojo debe ser dentro de las próximas {PLAZO_RECOJO_HORAS} horas "
                f"(hasta el {timezone.localtime(limite):%d/%m/%Y %H:%M})."
            )
        devolucion.estado = "PROGRAMADA"
        devolucion.id_repartidor = repartidor
        devolucion.fecha_programada = fecha_programada
        devolucion.fecha_limite = limite
        devolucion.aprobado_por = usuario
        devolucion.fecha_aprobacion = ahora
        devolucion.save()
        _auditar(
            usuario, "DEVOLUCION_APROBADA", devolucion,
            f"aprobó la devolución y asignó a {repartidor.nombres} {repartidor.apellidos}",
        )
        return devolucion

    @staticmethod
    @transaction.atomic
    def rechazar(id_devolucion, usuario, motivo_rechazo):
        """Rechaza la devolución (todavía no movió stock ni dinero)."""
        devolucion = DevolucionService._bloquear(id_devolucion)
        if devolucion.estado not in ("SOLICITADA", "PROGRAMADA", "EN_CAMINO"):
            raise ValueError("Esta devolución ya no se puede rechazar.")
        motivo_rechazo = (motivo_rechazo or "").strip()
        if not motivo_rechazo:
            raise ValueError("Indica el motivo del rechazo.")
        devolucion.estado = "RECHAZADA"
        devolucion.motivo_rechazo = motivo_rechazo[:255]
        devolucion.save(update_fields=["estado", "motivo_rechazo"])
        _auditar(
            usuario, "DEVOLUCION_RECHAZADA", devolucion,
            f"rechazó la devolución ({devolucion.motivo_rechazo})",
        )
        return devolucion

    @staticmethod
    @transaction.atomic
    def en_camino(id_devolucion, usuario):
        """El repartidor sale a recoger la prenda."""
        devolucion = DevolucionService._bloquear(id_devolucion)
        if devolucion.estado != "PROGRAMADA":
            raise ValueError("La devolución debe estar programada.")
        devolucion.estado = "EN_CAMINO"
        devolucion.fecha_en_camino = timezone.now()
        devolucion.save(update_fields=["estado", "fecha_en_camino"])
        _auditar(usuario, "DEVOLUCION_EN_CAMINO", devolucion, "salió a recoger la devolución")
        return devolucion

    @staticmethod
    @transaction.atomic
    def completar(id_devolucion, usuario, condiciones_ok):
        """El repartidor recogió y revisó la prenda: se repone el stock y se reembolsa."""
        devolucion = DevolucionService._bloquear(id_devolucion)
        if devolucion.estado != "EN_CAMINO":
            raise ValueError("La devolución debe estar en camino.")
        if not condiciones_ok:
            raise ValueError(
                "Confirma que la prenda cumple las condiciones del motivo; si no las cumple, "
                "rechaza la devolución."
            )
        _completar(devolucion, usuario)
        _auditar(usuario, "DEVOLUCION_COMPLETADA", devolucion, "completó la devolución")
        return devolucion