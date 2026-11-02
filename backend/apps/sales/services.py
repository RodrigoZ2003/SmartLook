# backend/apps/sales/services.py
# MODIFICADO (Fase 2 - reservas con anticipo): en el checkout y en el POS, las
# prendas de una reserva pagada cobran solo el SALDO (precio total congelado
# menos lo pagado al reservar) y la reserva se retira COMPLETA (todas sus
# prendas pendientes juntas). Se quitó la devolución automática anterior
# (DevolucionService), reemplazada por apps/sales/devoluciones.py (CU12).
from decimal import Decimal

from django.db import transaction
from apps.inventory.services import StockService
from apps.inventory.models import StockItem
from apps.catalog.models import ProductoVariante
from common.utils import log_audit
from .models import Cart, Delivery, Order, OrderItem, PosSale, PosSaleItem
from .integrations.stripe_payment import crear_intento_pago, verificar_pago, PagoRechazadoError
from .integrations.envio import cotizar, EnvioError


def precio_reservado(item_reserva):
    """Precio de una prenda reservada: el congelado al reservar o, si no tiene, el actual."""
    if item_reserva.precio_unitario is not None:
        return item_reserva.precio_unitario
    return item_reserva.id_variante.precio


def validar_retiro_completo(items_reserva):
    """Agrupa las prendas reservadas por reserva y valida que se retire cada una completa.

    items_reserva: FittingReservationItem que se van a cobrar.
    Devuelve el saldo total a cobrar por esas reservas: precio total
    congelado menos lo pagado al reservar (las reservas anteriores sin pago
    cobran el precio de sus prendas).
    """
    reservas = {}
    for item in items_reserva:
        reservas.setdefault(item.id_reserva_id, (item.id_reserva, set()))[1].add(item.pk)
    total = Decimal("0")
    for reserva, elegidas in reservas.values():
        if reserva.estado != "CONFIRMADA":
            raise ValueError(
                f"La reserva #{reserva.id_reserva} no está confirmada "
                f"({reserva.get_estado_display().lower()})."
            )
        pendientes = set(reserva.items.filter(estado="PENDIENTE").values_list("pk", flat=True))
        if pendientes != elegidas:
            raise ValueError(
                f"La reserva #{reserva.id_reserva} se retira completa: incluye todas sus prendas."
            )
        if reserva.monto_total is not None:
            total += reserva.saldo
        else:
            total += sum(
                precio_reservado(item) for item in reserva.items.select_related("id_variante")
                if item.pk in elegidas
            )
    return total


class CartService:
    """NUEVO (SaaS): el cliente es global, así que tiene un carrito activo por empresa."""

    @staticmethod
    def obtener_carrito(cliente, empresa):
        """Devuelve (o crea) el carrito ACTIVO del cliente para una empresa.

        Si el cliente tiene un carrito activo vacío sin empresa (creado al
        abrir "Mi carrito" antes de agregar prendas), se reutiliza y se le
        asigna la empresa, para no dejar carritos huérfanos.
        """
        cart = Cart.objects.filter(
            id_cliente=cliente, estado="ACTIVO", id_empresa=empresa
        ).order_by("-fecha_actualizacion").first()
        if cart:
            return cart
        cart = Cart.objects.filter(
            id_cliente=cliente, estado="ACTIVO", id_empresa__isnull=True
        ).first()
        if cart and not cart.cartitem_set.exists():
            cart.id_empresa = empresa
            cart.save(update_fields=["id_empresa"])
            return cart
        return Cart.objects.create(id_cliente=cliente, estado="ACTIVO", id_empresa=empresa)

    @staticmethod
    def carrito_de_sucursal(cliente, sucursal, bloquear=False):
        """Carrito ACTIVO del cliente con prendas de la empresa de esa sucursal (o None)."""
        queryset = Cart.objects.filter(
            id_cliente=cliente, estado="ACTIVO", id_empresa_id=sucursal.id_empresa_id
        )
        if bloquear:
            queryset = queryset.select_for_update()
        return queryset.order_by("-fecha_actualizacion").first()

class CheckoutService:
    @staticmethod
    def iniciar_checkout(cliente, sucursal, tipo_entrega="RETIRO", entrega=None):
        """
        tipo_entrega: "RETIRO" (el cliente recoge en la sucursal) o "DELIVERY".
        entrega (solo DELIVERY): {"direccion", "referencia", "latitud", "longitud"}.
        El costo de envío se calcula aquí, en el servidor.
        """
        if tipo_entrega not in ("RETIRO", "DELIVERY"):
            raise ValueError("Tipo de entrega inválido.")

        if sucursal.estado != "ACTIVA" or sucursal.id_empresa.estado != "ACTIVA":
            raise ValueError("La sucursal elegida no está disponible.")

        # SaaS: se paga el carrito de la empresa dueña de la sucursal elegida.
        cart = CartService.carrito_de_sucursal(cliente, sucursal)
        if not cart or not cart.cartitem_set.exists():
            raise ValueError(
                f"No tienes prendas de {sucursal.id_empresa.nombre} en tu carrito."
            )

        items = list(cart.cartitem_set.select_related(
            "id_variante", "id_reserva_item__id_reserva", "id_reserva_item__id_variante"
        ))

        for item in items:
            if item.id_reserva_item_id:
                continue
            stock = StockItem.objects.filter(
                id_sucursal=sucursal, id_variante=item.id_variante
            ).first()
            if not stock or stock.cantidad < item.cantidad:
                raise ValueError(
                    f"Stock insuficiente de '{item.id_variante}' en {sucursal.nombre}."
                )

        # MODIFICADO (Fase 2): las prendas reservadas cobran solo el saldo de su
        # reserva (que se retira completa); las demás, su precio actual.
        saldo_reservas = validar_retiro_completo(
            [item.id_reserva_item for item in items if item.id_reserva_item_id]
        )
        subtotal = saldo_reservas + sum(
            item.id_variante.precio * item.cantidad for item in items if not item.id_reserva_item_id
        )
        costo_envio = Decimal("0.00")
        cotizacion = None

        if tipo_entrega == "DELIVERY":
            entrega = entrega or {}
            direccion = (entrega.get("direccion") or "").strip()
            if not direccion:
                raise ValueError("Debe indicar la dirección de entrega.")
            try:
                latitud = float(entrega.get("latitud"))
                longitud = float(entrega.get("longitud"))
            except (TypeError, ValueError):
                raise ValueError("Debe indicar la ubicación de entrega.")
            if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
                raise ValueError("La ubicación de entrega no es válida.")
            try:
                cotizacion = cotizar(
                    sucursal, latitud, longitud, sum(item.cantidad for item in items)
                )
            except EnvioError as e:
                raise ValueError(str(e))
            costo_envio = cotizacion["costo_envio"]

        total = subtotal + costo_envio
        if total <= 0:
            raise ValueError("No hay saldo por pagar: la reserva ya está pagada; retírala en la tienda.")

        try:
            payment_intent_id, client_secret = crear_intento_pago(total)
        except PagoRechazadoError as e:
            raise ValueError(f"No se pudo iniciar el pago: {e}")

        with transaction.atomic():
            order = Order.objects.create(
                id_cliente=cliente,
                id_sucursal=sucursal,
                id_empresa_id=sucursal.id_empresa_id,
                total=total,
                estado="PENDIENTE",
                metodo_pago="TARJETA",
                referencia_pago=payment_intent_id,
                tipo_entrega=tipo_entrega,
                costo_envio=costo_envio,
            )
            if cotizacion:
                Delivery.objects.create(
                    id_orden=order,
                    direccion=direccion,
                    referencia=(entrega.get("referencia") or "").strip() or None,
                    latitud=Decimal(str(round(latitud, 6))),
                    longitud=Decimal(str(round(longitud, 6))),
                    distancia_km=cotizacion["distancia_km"],
                    costo_envio=costo_envio,
                )
        return order, client_secret

    @staticmethod
    @transaction.atomic
    def confirmar_pago(cliente, referencia_pago):
        """Verifica el pago con Stripe y convierte el carrito de esa empresa en la orden."""
        order = Order.objects.select_for_update().filter(
            id_cliente=cliente, referencia_pago=referencia_pago, estado="PENDIENTE"
        ).first()
        if not order:
            raise ValueError("No se encontró una orden pendiente con esa referencia.")

        try:
            verificar_pago(referencia_pago)
        except PagoRechazadoError as e:
            raise ValueError(f"Pago rechazado: {e}")

        cart = CartService.carrito_de_sucursal(cliente, order.id_sucursal, bloquear=True)
        if not cart or not cart.cartitem_set.exists():
            raise ValueError("El carrito ya no tiene items para completar la orden.")

        items = list(cart.cartitem_set.select_related(
            "id_variante", "id_reserva_item__id_reserva", "id_reserva_item__id_variante"
        ))
        validar_retiro_completo([item.id_reserva_item for item in items if item.id_reserva_item_id])

        items_reserva_comprados = []
        for item in items:
            # MODIFICADO (Fase 2): la prenda reservada guarda su precio congelado.
            precio = (
                precio_reservado(item.id_reserva_item) if item.id_reserva_item_id
                else item.id_variante.precio
            )
            OrderItem.objects.create(
                id_orden=order,
                id_variante=item.id_variante,
                cantidad=item.cantidad,
                precio_unitario=precio,
                subtotal=precio * item.cantidad,
            )
            if item.id_reserva_item_id:
                items_reserva_comprados.append(item.id_reserva_item)
            else:
                StockService.registrar_movimiento(
                    sucursal=order.id_sucursal,
                    variante=item.id_variante,
                    usuario=cliente.id_usuario,
                    tipo="SALIDA",
                    cantidad=item.cantidad,
                    motivo=f"Venta digital - Orden #{order.id_orden}",
                )

        order.estado = "PAGADA"
        order.save()
        cart.estado = "CONVERTIDO"
        cart.save()

        if items_reserva_comprados:
            from apps.reservations.services import ReservationStockService
            ReservationStockService.resolver_reserva_por_venta(
                items_reserva_comprados, cliente.id_usuario
            )

        log_audit(
            usuario=cliente.id_usuario,
            accion="COMPRA_DIGITAL",
            tabla_afectada="orders",
            registro_id=order.id_orden,
            descripcion=(
                f"{cliente.id_usuario.nombres} {cliente.id_usuario.apellidos} "
                f"realizó una compra digital en {order.id_sucursal.nombre} - "
                f"Orden #{order.id_orden} - Bs {order.total}"
            ),
        )
        return order

class PosSaleService:
    @staticmethod
    @transaction.atomic
    def registrar_venta(cajero, sucursal, items_data, metodo_pago):
        """
        CU16 - Registra una venta presencial. items_data: lista de
        {"id_variante": <int>, "cantidad": <int>} para prendas normales,
        o {"id_reserva_item": <int>, "cantidad": 1} para prendas que
        vienen de una reserva confirmada.

        MODIFICADO (Fase 2): de una reserva pagada se cobra solo el saldo y
        se retira completa (todas sus prendas pendientes en la misma venta).
        """
        if not items_data:
            raise ValueError("La venta debe tener al menos una prenda.")

        from apps.reservations.models import FittingReservationItem
        from apps.reservations.services import ReservationStockService

        variantes = {}
        reserva_items = {}
        for item in items_data:
            id_reserva_item = item.get("id_reserva_item")
            if id_reserva_item:
                try:
                    ri = FittingReservationItem.objects.select_related(
                        "id_variante", "id_reserva"
                    ).get(pk=id_reserva_item, estado="PENDIENTE")
                except FittingReservationItem.DoesNotExist:
                    raise ValueError(
                        f"La prenda reservada con id {id_reserva_item} no existe o ya se resolvió."
                    )
                if ri.id_reserva.id_sucursal_id != sucursal.id_sucursal:
                    raise ValueError(
                        f"La reserva #{ri.id_reserva_id} no corresponde a {sucursal.nombre}."
                    )
                reserva_items[id_reserva_item] = ri
                continue

            try:
                # SaaS: solo prendas de la empresa dueña de la sucursal.
                variante = ProductoVariante.objects.get(
                    pk=item["id_variante"],
                    id_producto__id_empresa_id=sucursal.id_empresa_id,
                )
            except ProductoVariante.DoesNotExist:
                raise ValueError(f"La prenda con id {item['id_variante']} no existe.")
            variantes[variante.id_variante] = variante

            stock = StockItem.objects.filter(id_sucursal=sucursal, id_variante=variante).first()
            if not stock or stock.cantidad < item["cantidad"]:
                raise ValueError(f"Stock insuficiente de '{variante}' en {sucursal.nombre}.")

        def _variante_de(item):
            """Variante de una línea de la venta (normal o de reserva)."""
            if item.get("id_reserva_item"):
                return reserva_items[item["id_reserva_item"]].id_variante
            return variantes[item["id_variante"]]

        saldo_reservas = validar_retiro_completo(list(reserva_items.values()))
        total = saldo_reservas + sum(
            _variante_de(item).precio * item.get("cantidad", 1)
            for item in items_data
            if not item.get("id_reserva_item")
        )

        venta = PosSale.objects.create(
            id_sucursal=sucursal,
            id_usuario=cajero,
            total=total,
            metodo_pago=metodo_pago,
        )

        items_reserva_comprados = []
        for item in items_data:
            variante = _variante_de(item)
            id_reserva_item = item.get("id_reserva_item")
            cantidad = item.get("cantidad", 1)

            precio = (
                precio_reservado(reserva_items[id_reserva_item]) if id_reserva_item
                else variante.precio
            )
            PosSaleItem.objects.create(
                id_venta=venta,
                id_variante=variante,
                cantidad=cantidad,
                precio_unitario=precio,
                subtotal=precio * cantidad,
                id_reserva_item=reserva_items.get(id_reserva_item) if id_reserva_item else None,
            )

            if id_reserva_item:
                items_reserva_comprados.append(reserva_items[id_reserva_item])
            else:
                StockService.registrar_movimiento(
                    sucursal=sucursal,
                    variante=variante,
                    usuario=cajero,
                    tipo="SALIDA",
                    cantidad=cantidad,
                    motivo=f"Venta presencial - Venta #{venta.id_venta}",
                )

        if items_reserva_comprados:
            ReservationStockService.resolver_reserva_por_venta(items_reserva_comprados, cajero)

        log_audit(
            usuario=cajero,
            accion="VENTA_PRESENCIAL",
            tabla_afectada="pos_sale",
            registro_id=venta.id_venta,
            descripcion=(
                f"{cajero.nombres} {cajero.apellidos} registró una venta "
                f"presencial en {sucursal.nombre} - Venta #{venta.id_venta} - "
                f"Bs {venta.total} ({metodo_pago})"
            ),
        )
        return venta