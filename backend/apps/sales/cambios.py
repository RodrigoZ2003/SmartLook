"""CU05 - Cambio de prenda por talla o color, con plazo y nota de devolución.

Reglas (Fase 2):
- Plazo para pedir el cambio: 7 días desde la compra (venta POS o pedido
  con retiro) o desde la entrega (pedido con delivery).
- Una sola vez por prenda comprada (línea de la venta o del pedido) y solo
  a la MISMA prenda en otra talla o color.
- Motivos:
    ERROR_TIENDA -> al cliente le llegó otra talla/color de la que compró.
                    Devuelve la que le llegó y recibe la que compró.
    NO_LE_QUEDA  -> recibió lo que compró pero quiere otra talla/color, al
                    mismo precio y con stock en la sucursal.
- Modalidades:
    TIENDA   -> lo registra el personal en el momento (venta POS, pedido con
                retiro o el cliente que trae un pedido de delivery). Se
                verifica que la prenda esté sin uso y con etiqueta.
    DELIVERY -> lo solicita el cliente desde "Mis pedidos" (pedido con
                delivery entregado). El encargado lo aprueba asignando
                repartidor y fecha de visita dentro de 48 horas; el
                repartidor marca "En camino" y "Completado".
- Stock (sucursal de la venta o del pedido):
    Al aprobar (o al registrar en tienda):
      ERROR_TIENDA -> SALIDA de la prenda que se envió por error (corrige
                      el inventario: esa prenda sí salió de la tienda).
                      La prenda comprada no se toca: se descontó al
                      comprar y recién ahora sale de verdad.
      NO_LE_QUEDA  -> SALIDA de la prenda nueva (queda apartada).
    Al completar: ENTRADA de la prenda que el cliente devuelve.
    Si se rechaza un cambio ya aprobado, se revierte la SALIDA.
- El cambio completado es la nota de devolución (NC-000001).
- MODIFICADO (CU12): una prenda devuelta o con una devolución en curso no se
  puede cambiar.
- MODIFICADO (Fase 3 - CU18): una compra que usó el descuento por fidelidad no
  admite cambio.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import ProductoVariante
from apps.fidelidad import servicio as fidelidad
from apps.inventory.models import StockItem
from apps.inventory.services import StockService
from apps.users_auth.models import Usuario
from common.utils import log_audit

from .models import CambioPrenda, DevolucionItem, OrderItem, PosSaleItem

PLAZO_CAMBIO_DIAS = 7
PLAZO_ENTREGA_HORAS = 48
MOTIVOS = ("ERROR_TIENDA", "NO_LE_QUEDA")
ESTADOS_ACTIVOS = ("SOLICITADO", "PROGRAMADO", "EN_CAMINO", "COMPLETADO")
# Estados de una devolución (CU12) que bloquean el cambio de la prenda.
ESTADOS_DEVOLUCION_ACTIVOS = ("SOLICITADA", "PROGRAMADA", "EN_CAMINO", "COMPLETADA")


class OrigenCambio:
    """Línea de venta POS o de pedido sobre la que se pide el cambio."""

    def __init__(self, venta_item=None, orden_item=None):
        """Toma los datos comunes de la línea (prenda, sucursal, cliente, fechas)."""
        self.venta_item = venta_item
        self.orden_item = orden_item
        if venta_item is not None:
            venta = venta_item.id_venta
            self.tipo = "POS"
            self.etiqueta = f"Venta #{venta.id_venta}"
            self.variante = venta_item.id_variante
            self.cantidad = venta_item.cantidad
            self.sucursal = venta.id_sucursal
            self.empresa_id = venta.id_empresa_id
            self.cliente = venta.id_cliente
            self.fecha_base = venta.fecha_venta
            self.tipo_entrega = None
        else:
            orden = orden_item.id_orden
            delivery = getattr(orden, "delivery", None) if orden.tipo_entrega == "DELIVERY" else None
            self.tipo = "PEDIDO"
            self.etiqueta = f"Pedido #{orden.id_orden}"
            self.variante = orden_item.id_variante
            self.cantidad = orden_item.cantidad
            self.sucursal = orden.id_sucursal
            self.empresa_id = orden.id_empresa_id
            self.cliente = orden.id_cliente
            self.tipo_entrega = orden.tipo_entrega
            self.fecha_base = (
                delivery.fecha_entrega if delivery and delivery.fecha_entrega else orden.fecha_creacion
            )

    @property
    def vence(self):
        """Fecha y hora en que vence el plazo para pedir el cambio."""
        return self.fecha_base + timedelta(days=PLAZO_CAMBIO_DIAS)

    def filtro_item(self):
        """Filtro de CambioPrenda para esta línea."""
        if self.venta_item is not None:
            return {"id_venta_item": self.venta_item}
        return {"id_orden_item": self.orden_item}


def cargar_origen(id_venta_item=None, id_orden_item=None):
    """Busca la línea de venta o de pedido. Lanza ValueError si no existe."""
    if id_venta_item:
        try:
            item = PosSaleItem.objects.select_related(
                "id_venta__id_sucursal",
                "id_venta__id_cliente__id_usuario",
                "id_variante__id_producto",
                "id_variante__id_talla",
                "id_variante__id_color",
            ).get(pk=id_venta_item)
        except (PosSaleItem.DoesNotExist, ValueError, TypeError):
            raise ValueError("La prenda de la venta no existe.")
        return OrigenCambio(venta_item=item)
    if id_orden_item:
        try:
            item = OrderItem.objects.select_related(
                "id_orden__id_sucursal",
                "id_orden__id_cliente__id_usuario",
                "id_variante__id_producto",
                "id_variante__id_talla",
                "id_variante__id_color",
            ).get(pk=id_orden_item)
        except (OrderItem.DoesNotExist, ValueError, TypeError):
            raise ValueError("La prenda del pedido no existe.")
        return OrigenCambio(orden_item=item)
    raise ValueError("Indica la prenda de la venta o del pedido.")


def motivo_no_elegible(origen, modalidad):
    """Motivo por el que la prenda no se puede cambiar, o None si se puede."""
    # NUEVO (CU18): la compra con descuento por fidelidad no admite cambio.
    if origen.tipo == "POS":
        con_descuento = fidelidad.compra_con_descuento(venta=origen.venta_item.id_venta)
    else:
        con_descuento = fidelidad.compra_con_descuento(orden=origen.orden_item.id_orden)
    if con_descuento:
        return "Esta compra usó el descuento por fidelidad: no admite cambio."
    if origen.tipo == "POS":
        if origen.venta_item.id_venta.estado != "REGISTRADA":
            return "La venta está anulada o tiene un conflicto sin resolver."
        if modalidad == "DELIVERY":
            return "Las ventas en tienda se cambian en la tienda."
    else:
        orden = origen.orden_item.id_orden
        if origen.tipo_entrega == "DELIVERY":
            if orden.estado != "ENTREGADA":
                return "El pedido todavía no fue entregado."
        else:
            if orden.estado not in ("PAGADA", "ENTREGADA"):
                return "El pedido no está pagado."
            if modalidad == "DELIVERY":
                return "Los pedidos con retiro se cambian en la tienda."
    # MODIFICADO (CU12): no se cambia una prenda devuelta o con una devolución
    # en curso (las rechazadas no cuentan); vale para pedidos y ventas POS.
    devuelto = DevolucionItem.objects.filter(
        id_devolucion__estado__in=ESTADOS_DEVOLUCION_ACTIVOS, **origen.filtro_item()
    ).aggregate(total=Sum("cantidad"))["total"] or 0
    if devuelto:
        return "Esta prenda ya se devolvió o tiene una devolución en curso."
    if timezone.now() > origen.vence:
        return (
            f"Venció el plazo de {PLAZO_CAMBIO_DIAS} días para el cambio "
            f"({timezone.localtime(origen.vence):%d/%m/%Y %H:%M})."
        )
    if CambioPrenda.objects.filter(estado__in=ESTADOS_ACTIVOS, **origen.filtro_item()).exists():
        return "Esta prenda ya tiene un cambio (solo se permite uno por prenda)."
    return None


def stock_en(sucursal, variante):
    """Unidades de la prenda en la sucursal."""
    return StockItem.objects.filter(id_sucursal=sucursal, id_variante=variante).values_list(
        "cantidad", flat=True
    ).first() or 0


def alternativas(origen):
    """Otras tallas/colores de la misma prenda, con su precio y stock en la sucursal."""
    variantes = ProductoVariante.objects.select_related("id_talla", "id_color").filter(
        id_producto_id=origen.variante.id_producto_id
    ).exclude(pk=origen.variante.pk).exclude(estado="INACTIVO").order_by("id_talla__nombre", "id_color__nombre")
    stock = dict(
        StockItem.objects.filter(id_sucursal=origen.sucursal, id_variante__in=variantes).values_list(
            "id_variante_id", "cantidad"
        )
    )
    return [
        {
            "id_variante": v.id_variante,
            "talla": v.id_talla.nombre,
            "color": v.id_color.nombre,
            "precio": str(v.precio),
            "stock": stock.get(v.id_variante, 0),
            "mismo_precio": v.precio == origen.variante.precio,
        }
        for v in variantes
    ]


def _variantes_del_cambio(origen, motivo, id_variante, cantidad):
    """Prenda devuelta y prenda entregada según el motivo (valida las reglas)."""
    if motivo not in MOTIVOS:
        raise ValueError("Motivo de cambio inválido.")
    try:
        otra = ProductoVariante.objects.select_related("id_producto", "id_talla", "id_color").get(
            pk=id_variante, id_producto_id=origen.variante.id_producto_id
        )
    except (ProductoVariante.DoesNotExist, ValueError, TypeError):
        raise ValueError("Elige otra talla o color de la misma prenda.")
    if otra.pk == origen.variante.pk:
        raise ValueError("Elige una talla o color distinto al de la compra.")
    if motivo == "ERROR_TIENDA":
        return otra, origen.variante
    if otra.precio != origen.variante.precio:
        raise ValueError(
            f"{otra} cuesta Bs {otra.precio}; el cambio es solo al mismo precio "
            f"(Bs {origen.variante.precio})."
        )
    if stock_en(origen.sucursal, otra) < cantidad:
        raise ValueError(f"No hay stock de {otra} en {origen.sucursal.nombre}.")
    return origen.variante, otra


def _leer_cantidad(cantidad, origen):
    """Cantidad a cambiar (por defecto 1, como máximo lo comprado)."""
    try:
        cantidad = int(cantidad or 1)
    except (TypeError, ValueError):
        raise ValueError("Cantidad inválida.")
    if cantidad < 1 or cantidad > origen.cantidad:
        raise ValueError(f"La cantidad debe estar entre 1 y {origen.cantidad}.")
    return cantidad


def _salida_al_aprobar(cambio, usuario):
    """Descuenta la prenda que sale de la tienda al aprobar el cambio."""
    if cambio.motivo == "ERROR_TIENDA":
        variante = cambio.id_variante_devuelta
        motivo = f"Corrección: se envió por error en lugar de la comprada (cambio {cambio.numero_nota})"
    else:
        variante = cambio.id_variante_entregada
        motivo = f"Prenda apartada para el cambio {cambio.numero_nota}"
    try:
        StockService.registrar_movimiento(
            sucursal=cambio.id_sucursal,
            variante=variante,
            usuario=usuario,
            tipo="SALIDA",
            cantidad=cambio.cantidad,
            motivo=motivo,
        )
    except ValueError:
        if cambio.motivo == "ERROR_TIENDA":
            raise ValueError(
                f"El sistema no tiene stock de {variante} en {cambio.id_sucursal.nombre} para "
                f"corregir el envío; revisa el inventario."
            )
        raise ValueError(f"No hay stock de {variante} en {cambio.id_sucursal.nombre}.")


def _revertir_salida(cambio, usuario):
    """Devuelve al stock lo descontado al aprobar (cambio rechazado después)."""
    variante = (
        cambio.id_variante_devuelta if cambio.motivo == "ERROR_TIENDA" else cambio.id_variante_entregada
    )
    StockService.registrar_movimiento(
        sucursal=cambio.id_sucursal,
        variante=variante,
        usuario=usuario,
        tipo="ENTRADA",
        cantidad=cambio.cantidad,
        motivo=f"Cambio {cambio.numero_nota} rechazado: se revierte la salida",
    )


def _entrada_al_completar(cambio, usuario):
    """Suma al stock la prenda que el cliente devolvió."""
    StockService.registrar_movimiento(
        sucursal=cambio.id_sucursal,
        variante=cambio.id_variante_devuelta,
        usuario=usuario,
        tipo="ENTRADA",
        cantidad=cambio.cantidad,
        motivo=f"Prenda devuelta por el cambio {cambio.numero_nota}",
    )


def _auditar(usuario, accion, cambio, texto):
    """Registra el evento del cambio en la bitácora de su empresa."""
    log_audit(
        usuario=usuario,
        accion=accion,
        tabla_afectada="cambio_prenda",
        registro_id=cambio.id_cambio,
        descripcion=(
            f"{usuario.nombres} {usuario.apellidos} {texto} - Cambio {cambio.numero_nota}: "
            f"devuelve {cambio.id_variante_devuelta}, recibe {cambio.id_variante_entregada} "
            f"({cambio.id_sucursal.nombre})"
        ),
        empresa=cambio.id_empresa_id,
    )


class CambioService:
    """Operaciones del cambio de prenda (CU05)."""

    @staticmethod
    @transaction.atomic
    def solicitar(usuario_cliente, cliente, id_orden_item, motivo, id_variante, cantidad=1,
                  observacion=None):
        """El cliente pide el cambio de una prenda de su pedido con delivery entregado."""
        origen = cargar_origen(id_orden_item=id_orden_item)
        if origen.cliente is None or origen.cliente.pk != cliente.pk:
            raise ValueError("La prenda del pedido no existe.")
        if origen.tipo_entrega != "DELIVERY":
            raise ValueError("Los pedidos con retiro se cambian en la tienda.")
        problema = motivo_no_elegible(origen, "DELIVERY")
        if problema:
            raise ValueError(problema)
        cantidad = _leer_cantidad(cantidad, origen)
        devuelta, entregada = _variantes_del_cambio(origen, motivo, id_variante, cantidad)
        cambio = CambioPrenda.objects.create(
            id_empresa_id=origen.empresa_id,
            id_sucursal=origen.sucursal,
            id_cliente=cliente,
            id_orden_item=origen.orden_item,
            motivo=motivo,
            modalidad="DELIVERY",
            estado="SOLICITADO",
            id_variante_devuelta=devuelta,
            id_variante_entregada=entregada,
            cantidad=cantidad,
            observacion=(observacion or "").strip()[:255] or None,
            solicitado_por=usuario_cliente,
        )
        _auditar(usuario_cliente, "CAMBIO_SOLICITADO", cambio, f"solicitó un cambio del {origen.etiqueta}")
        return cambio

    @staticmethod
    @transaction.atomic
    def registrar_en_tienda(usuario, empresa_id, motivo, id_variante, cantidad=1,
                            id_venta_item=None, id_orden_item=None, condiciones_ok=False,
                            observacion=None):
        """El personal registra y completa un cambio en la tienda.

        empresa_id: empresa del usuario (None para el SUPER_ADMIN, que puede
        registrar en cualquiera).
        """
        origen = cargar_origen(id_venta_item=id_venta_item, id_orden_item=id_orden_item)
        if empresa_id is not None and origen.empresa_id != empresa_id:
            raise ValueError("La prenda de la venta no existe.")
        problema = motivo_no_elegible(origen, "TIENDA")
        if problema:
            raise ValueError(problema)
        if not condiciones_ok:
            raise ValueError("Confirma que la prenda devuelta está sin uso y con etiqueta.")
        cantidad = _leer_cantidad(cantidad, origen)
        devuelta, entregada = _variantes_del_cambio(origen, motivo, id_variante, cantidad)
        ahora = timezone.now()
        cambio = CambioPrenda.objects.create(
            id_empresa_id=origen.empresa_id,
            id_sucursal=origen.sucursal,
            id_cliente=origen.cliente,
            id_venta_item=origen.venta_item,
            id_orden_item=origen.orden_item,
            motivo=motivo,
            modalidad="TIENDA",
            estado="COMPLETADO",
            id_variante_devuelta=devuelta,
            id_variante_entregada=entregada,
            cantidad=cantidad,
            observacion=(observacion or "").strip()[:255] or None,
            condiciones_verificadas=True,
            solicitado_por=usuario,
            aprobado_por=usuario,
            completado_por=usuario,
            fecha_aprobacion=ahora,
            fecha_completado=ahora,
        )
        _salida_al_aprobar(cambio, usuario)
        _entrada_al_completar(cambio, usuario)
        _auditar(usuario, "CAMBIO_EN_TIENDA", cambio, f"registró un cambio en tienda del {origen.etiqueta}")
        return cambio

    @staticmethod
    def _bloquear(id_cambio):
        """Cambio bloqueado para modificarlo (dentro de una transacción)."""
        try:
            return CambioPrenda.objects.select_for_update(of=("self",)).select_related(
                "id_sucursal", "id_variante_devuelta", "id_variante_entregada"
            ).get(pk=id_cambio)
        except CambioPrenda.DoesNotExist:
            raise ValueError("Cambio no encontrado.")

    @staticmethod
    @transaction.atomic
    def aprobar(id_cambio, usuario, id_repartidor, fecha_programada):
        """El encargado aprueba: asigna repartidor y fecha de visita (máximo 48 h)."""
        cambio = CambioService._bloquear(id_cambio)
        if cambio.estado != "SOLICITADO":
            raise ValueError("Solo se puede aprobar un cambio solicitado.")
        repartidor = Usuario.objects.filter(
            pk=id_repartidor,
            estado="ACTIVO",
            roles__nombre="REPARTIDOR",
            id_empresa_id=cambio.id_empresa_id,
        ).first() if str(id_repartidor or "").isdigit() else None
        if repartidor is None:
            raise ValueError("Elige un repartidor activo de la empresa.")
        ahora = timezone.now()
        limite = ahora + timedelta(hours=PLAZO_ENTREGA_HORAS)
        if fecha_programada is None:
            raise ValueError("Indica la fecha y hora de la visita.")
        if timezone.is_naive(fecha_programada):
            fecha_programada = timezone.make_aware(fecha_programada)
        if fecha_programada < ahora - timedelta(minutes=5) or fecha_programada > limite:
            raise ValueError(
                f"La visita debe ser dentro de las próximas {PLAZO_ENTREGA_HORAS} horas "
                f"(hasta el {timezone.localtime(limite):%d/%m/%Y %H:%M})."
            )
        cambio.estado = "PROGRAMADO"
        cambio.id_repartidor = repartidor
        cambio.fecha_programada = fecha_programada
        cambio.fecha_limite = limite
        cambio.aprobado_por = usuario
        cambio.fecha_aprobacion = ahora
        cambio.save()
        _salida_al_aprobar(cambio, usuario)
        _auditar(
            usuario, "CAMBIO_APROBADO", cambio,
            f"aprobó el cambio y asignó a {repartidor.nombres} {repartidor.apellidos}",
        )
        return cambio

    @staticmethod
    @transaction.atomic
    def rechazar(id_cambio, usuario, motivo_rechazo):
        """Rechaza el cambio (si ya estaba aprobado, revierte el stock)."""
        cambio = CambioService._bloquear(id_cambio)
        if cambio.estado not in ("SOLICITADO", "PROGRAMADO", "EN_CAMINO"):
            raise ValueError("Este cambio ya no se puede rechazar.")
        motivo_rechazo = (motivo_rechazo or "").strip()
        if not motivo_rechazo:
            raise ValueError("Indica el motivo del rechazo.")
        if cambio.estado in ("PROGRAMADO", "EN_CAMINO"):
            _revertir_salida(cambio, usuario)
        cambio.estado = "RECHAZADO"
        cambio.motivo_rechazo = motivo_rechazo[:255]
        cambio.save(update_fields=["estado", "motivo_rechazo"])
        _auditar(usuario, "CAMBIO_RECHAZADO", cambio, f"rechazó el cambio ({cambio.motivo_rechazo})")
        return cambio

    @staticmethod
    @transaction.atomic
    def en_camino(id_cambio, usuario):
        """El repartidor sale a hacer el cambio."""
        cambio = CambioService._bloquear(id_cambio)
        if cambio.estado != "PROGRAMADO":
            raise ValueError("El cambio debe estar programado.")
        cambio.estado = "EN_CAMINO"
        cambio.fecha_en_camino = timezone.now()
        cambio.save(update_fields=["estado", "fecha_en_camino"])
        _auditar(usuario, "CAMBIO_EN_CAMINO", cambio, "salió a hacer el cambio")
        return cambio

    @staticmethod
    @transaction.atomic
    def completar(id_cambio, usuario, condiciones_ok):
        """El repartidor recogió la prenda devuelta y entregó la correcta."""
        cambio = CambioService._bloquear(id_cambio)
        if cambio.estado != "EN_CAMINO":
            raise ValueError("El cambio debe estar en camino.")
        if not condiciones_ok:
            raise ValueError(
                "Confirma que la prenda devuelta está sin uso y con etiqueta; si no lo está, "
                "rechaza el cambio."
            )
        cambio.estado = "COMPLETADO"
        cambio.condiciones_verificadas = True
        cambio.completado_por = usuario
        cambio.fecha_completado = timezone.now()
        cambio.save(update_fields=[
            "estado", "condiciones_verificadas", "completado_por", "fecha_completado",
        ])
        _entrada_al_completar(cambio, usuario)
        _auditar(usuario, "CAMBIO_COMPLETADO", cambio, "completó el cambio")
        return cambio