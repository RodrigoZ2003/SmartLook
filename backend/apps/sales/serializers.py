# backend/apps/sales/serializers.py
# MODIFICADO (Fase 2 - reservas con anticipo): el carrito y la venta POS
# muestran lo pagado al reservar y cobran solo el saldo de la reserva.
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from apps.catalog.models import ProductoVariante
from .models import (
    Cart, CartItem, Delivery, Order, OrderItem, PosSale, PosSaleItem,
    Devolucion, DevolucionItem, SyncOperacion, NotaDevolucionPos, CambioPrenda,
)
from .cambios import PLAZO_CAMBIO_DIAS
from .devoluciones import ESTADOS_ACTIVOS as ESTADOS_DEVOLUCION_ACTIVOS
from .devoluciones import PLAZO_DEVOLUCION_DIAS, PORCENTAJE_RETENCION

# Roles que pueden resolver las operaciones en conflicto (CU08).
ROLES_RESUELVEN_CONFLICTOS = ("SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL")


# NUEVO (Fase 2 - reservas con anticipo)
def _reservas_de(lineas):
    """Reservas distintas de las líneas (carrito o venta) que vienen de una reserva."""
    reservas = {}
    for linea in lineas:
        if linea.id_reserva_item_id:
            reserva = linea.id_reserva_item.id_reserva
            reservas[reserva.pk] = reserva
    return list(reservas.values())


def _pagado_al_reservar(lineas):
    """Lo que el cliente ya pagó al reservar las prendas de esas líneas."""
    return sum((reserva.monto_pagado or Decimal("0") for reserva in _reservas_de(lineas)), Decimal("0"))


class CartItemSerializer(serializers.ModelSerializer):
    variante = serializers.StringRelatedField(source="id_variante", read_only=True)
    id_variante = serializers.PrimaryKeyRelatedField(
        queryset=ProductoVariante.objects.all(), write_only=True
    )
    # MODIFICADO (Fase 2): la prenda reservada muestra su precio congelado.
    precio_unitario = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    reservado = serializers.SerializerMethodField()
    id_reserva = serializers.SerializerMethodField()
    puede_quitar = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = [
            "id_item",
            "variante",
            "id_variante",
            "cantidad",
            "precio_unitario",
            "subtotal",
            "reservado",
            "id_reserva",
            "puede_quitar",
            "fecha_agregado",
        ]

    def _precio(self, obj):
        """Precio de la línea: el congelado de la reserva o el actual."""
        if obj.id_reserva_item_id:
            from .services import precio_reservado
            return precio_reservado(obj.id_reserva_item)
        return obj.id_variante.precio

    def get_precio_unitario(self, obj):
        """Precio unitario de la línea."""
        return self._precio(obj)

    def get_subtotal(self, obj):
        """Subtotal de la línea del carrito."""
        return self._precio(obj) * obj.cantidad

    def get_reservado(self, obj):
        """True si la prenda viene de una reserva."""
        return obj.id_reserva_item_id is not None

    def get_id_reserva(self, obj):
        """Id de la reserva de origen, si la hay."""
        return obj.id_reserva_item.id_reserva_id if obj.id_reserva_item_id else None

    def get_puede_quitar(self, obj):
        """Una prenda de una reserva pagada no se quita: se cancela la reserva."""
        return not (obj.id_reserva_item_id and obj.id_reserva_item.id_reserva.monto_pagado)

class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(source="cartitem_set", many=True, read_only=True)
    # MODIFICADO (Fase 2): total = precio de las prendas menos lo pagado al reservar.
    subtotal_prendas = serializers.SerializerMethodField()
    pagado_reservas = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    # NUEVO (SaaS): tienda (empresa) del carrito; el cliente tiene uno por empresa.
    id_empresa = serializers.IntegerField(source="id_empresa_id", read_only=True)
    empresa_nombre = serializers.CharField(source="id_empresa.nombre", read_only=True)

    class Meta:
        model = Cart
        fields = [
            "id_carrito", "id_empresa", "empresa_nombre", "items", "estado",
            "subtotal_prendas", "pagado_reservas", "total", "fecha_actualizacion",
        ]

    def _lineas(self, obj):
        """Líneas del carrito con su variante y reserva (se cargan una vez)."""
        if not hasattr(obj, "_lineas_cache"):
            obj._lineas_cache = list(obj.cartitem_set.select_related(
                "id_variante", "id_reserva_item__id_reserva", "id_reserva_item__id_variante"
            ))
        return obj._lineas_cache

    def get_subtotal_prendas(self, obj):
        """Precio de todas las prendas del carrito."""
        from .services import precio_reservado
        return sum(
            (
                (precio_reservado(l.id_reserva_item) if l.id_reserva_item_id else l.id_variante.precio)
                * l.cantidad
                for l in self._lineas(obj)
            ),
            Decimal("0"),
        )

    def get_pagado_reservas(self, obj):
        """Lo que ya se pagó al reservar las prendas del carrito."""
        return _pagado_al_reservar(self._lineas(obj))

    def get_total(self, obj):
        """Lo que falta pagar (nunca negativo)."""
        return max(self.get_subtotal_prendas(obj) - self.get_pagado_reservas(obj), Decimal("0"))

class OrderItemSerializer(serializers.ModelSerializer):
    variante = serializers.StringRelatedField(source="id_variante")
    # NUEVO (CU05): último cambio de talla/color de esta prenda, si lo hay.
    cambio = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ["id_item", "variante", "cantidad", "precio_unitario", "subtotal", "cambio"]

    def get_cambio(self, obj):
        """Resumen del último cambio de la prenda (para "Mis pedidos")."""
        cambio = obj.cambios.select_related(
            "id_repartidor", "id_variante_devuelta", "id_variante_entregada"
        ).order_by("-fecha_solicitud").first()
        if cambio is None:
            return None
        return {
            "id_cambio": cambio.id_cambio,
            "numero_nota": cambio.numero_nota,
            "estado": cambio.estado,
            "estado_display": cambio.get_estado_display(),
            "mensaje_cliente": mensaje_para_cliente(cambio),
        }

class DeliverySerializer(serializers.ModelSerializer):
    repartidor = serializers.SerializerMethodField()

    class Meta:
        model = Delivery
        fields = [
            "id_delivery",
            "direccion",
            "referencia",
            "latitud",
            "longitud",
            "distancia_km",
            "costo_envio",
            "estado",
            "repartidor",
            "fecha_creacion",
            "fecha_preparacion",
            "fecha_en_camino",
            "fecha_entrega",
        ]

    def get_repartidor(self, obj):
        """Nombre del repartidor asignado."""
        r = obj.id_repartidor
        return f"{r.nombres} {r.apellidos}" if r else None

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(source="orderitem_set", many=True, read_only=True)
    sucursal = serializers.StringRelatedField(source="id_sucursal")
    delivery = serializers.SerializerMethodField()
    # NUEVO (devoluciones): para que "Mis pedidos" sepa distinguir un
    # pedido entregado normal de uno que ya se devolvió (total o parcial),
    # sin depender de Order.estado (que se queda en ENTREGADA para
    # siempre - es el historial real de la venta).
    devuelto = serializers.SerializerMethodField()
    tiene_devolucion = serializers.SerializerMethodField()
    # NUEVO (CU05): hasta cuándo se puede pedir un cambio con delivery.
    cambio_vence = serializers.SerializerMethodField()
    puede_solicitar_cambio = serializers.SerializerMethodField()
    # NUEVO (CU12): plazo de devolución y devoluciones del pedido.
    devolucion_vence = serializers.SerializerMethodField()
    puede_solicitar_devolucion = serializers.SerializerMethodField()
    devoluciones = serializers.SerializerMethodField()
    # NUEVO (SaaS): tienda (empresa) donde se hizo el pedido.
    id_empresa = serializers.IntegerField(source="id_empresa_id", read_only=True)
    empresa_nombre = serializers.CharField(source="id_empresa.nombre", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id_orden",
            "id_empresa",
            "empresa_nombre",
            "items",
            "total",
            "estado",
            "metodo_pago",
            "referencia_pago",
            "sucursal",
            "tipo_entrega",
            "costo_envio",
            "delivery",
            "devuelto",
            "tiene_devolucion",
            "cambio_vence",
            "puede_solicitar_cambio",
            "devolucion_vence",
            "puede_solicitar_devolucion",
            "devoluciones",
            "fecha_creacion",
        ]

    def get_cambio_vence(self, obj):
        """Fin del plazo para pedir un cambio con delivery (7 días desde la entrega)."""
        delivery = getattr(obj, "delivery", None)
        if obj.tipo_entrega != "DELIVERY" or obj.estado != "ENTREGADA" or not delivery:
            return None
        if not delivery.fecha_entrega:
            return None
        return delivery.fecha_entrega + timedelta(days=PLAZO_CAMBIO_DIAS)

    def get_puede_solicitar_cambio(self, obj):
        """True si el pedido está entregado y dentro del plazo de cambio."""
        vence = self.get_cambio_vence(obj)
        return bool(vence and timezone.now() <= vence)

    def get_delivery(self, obj):
        """Datos del delivery de la orden, si tiene."""
        delivery = getattr(obj, "delivery", None)
        return DeliverySerializer(delivery).data if delivery else None

    def get_tiene_devolucion(self, obj):
        """True si la orden tiene alguna devolución (sin contar las rechazadas)."""
        return obj.devoluciones.filter(estado__in=ESTADOS_DEVOLUCION_ACTIVOS).exists()

    def get_devuelto(self, obj):
        """True si se devolvieron (o se están devolviendo) todas las prendas de la orden."""
        total_comprado = obj.orderitem_set.aggregate(t=Sum("cantidad"))["t"] or 0
        total_devuelto = DevolucionItem.objects.filter(
            id_orden_item__id_orden=obj, id_devolucion__estado__in=ESTADOS_DEVOLUCION_ACTIVOS
        ).aggregate(t=Sum("cantidad"))["t"] or 0
        return total_comprado > 0 and total_devuelto >= total_comprado

    def get_devolucion_vence(self, obj):
        """Fin del plazo para pedir una devolución con recojo (7 días desde la entrega)."""
        delivery = getattr(obj, "delivery", None)
        if obj.tipo_entrega != "DELIVERY" or obj.estado != "ENTREGADA" or not delivery:
            return None
        if not delivery.fecha_entrega:
            return None
        return delivery.fecha_entrega + timedelta(days=PLAZO_DEVOLUCION_DIAS)

    def get_puede_solicitar_devolucion(self, obj):
        """True si el pedido está entregado, dentro del plazo y le quedan prendas por devolver."""
        vence = self.get_devolucion_vence(obj)
        return bool(vence and timezone.now() <= vence and not self.get_devuelto(obj))

    def get_devoluciones(self, obj):
        """Resumen de las devoluciones del pedido (para "Mis pedidos")."""
        return [
            {
                "id_devolucion": d.id_devolucion,
                "numero_nota": d.numero_nota,
                "estado": d.estado,
                "estado_display": d.get_estado_display(),
                "monto_reembolso": d.monto_reembolso,
                "es_anterior": d.es_anterior,
                "resumen_reembolso": resumen_reembolso(d),
                "mensaje_cliente": mensaje_devolucion_cliente(d),
            }
            for d in obj.devoluciones.select_related("id_repartidor").order_by("-fecha_creacion")
        ]

class PosSaleItemSerializer(serializers.ModelSerializer):
    variante = serializers.StringRelatedField(source="id_variante", read_only=True)
    reservado = serializers.SerializerMethodField()

    class Meta:
        model = PosSaleItem
        fields = [
            "id_item", "variante", "cantidad", "precio_unitario", "subtotal", "reservado",
            # NUEVO (CU08): precio del servidor y si la prenda quedó sin stock.
            "precio_lista", "sin_stock",
        ]

    def get_reservado(self, obj):
        """True si la prenda viene de una reserva."""
        return obj.id_reserva_item_id is not None

class PosSaleSerializer(serializers.ModelSerializer):
    sucursal = serializers.StringRelatedField(source="id_sucursal")
    usuario = serializers.StringRelatedField(source="id_usuario")
    items = PosSaleItemSerializer(many=True, read_only=True)
    # NUEVO (CU08): cliente opcional y estado de la venta.
    cliente = serializers.SerializerMethodField()
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    # NUEVO (Fase 2): lo que el cliente pagó al reservar (el total es solo el saldo).
    pagado_reservas = serializers.SerializerMethodField()

    class Meta:
        model = PosSale
        fields = [
            "id_venta", "sucursal", "usuario", "cliente", "items", "pagado_reservas", "total",
            "metodo_pago", "estado", "estado_display", "fecha_venta",
        ]

    def get_pagado_reservas(self, obj):
        """Lo que ya se pagó al reservar las prendas de la venta."""
        return _pagado_al_reservar(obj.items.select_related("id_reserva_item__id_reserva"))

    def get_cliente(self, obj):
        """Nombre y correo del cliente de la venta, si se indicó."""
        if not obj.id_cliente_id:
            return None
        u = obj.id_cliente.id_usuario
        return {"nombre": f"{u.nombres} {u.apellidos}", "correo": u.correo}

class DeliveryEntregaSerializer(serializers.ModelSerializer):
    orden = serializers.IntegerField(source="id_orden_id", read_only=True)
    cliente = serializers.SerializerMethodField()
    telefono_cliente = serializers.SerializerMethodField()
    sucursal = serializers.StringRelatedField(source="id_orden.id_sucursal")
    total_orden = serializers.DecimalField(
        source="id_orden.total", max_digits=10, decimal_places=2, read_only=True
    )
    estado_orden = serializers.CharField(source="id_orden.estado", read_only=True)
    prendas = serializers.SerializerMethodField()
    repartidor = serializers.SerializerMethodField()

    class Meta:
        model = Delivery
        fields = [
            "id_delivery",
            "orden",
            "cliente",
            "telefono_cliente",
            "sucursal",
            "total_orden",
            "estado_orden",
            "prendas",
            "direccion",
            "referencia",
            "latitud",
            "longitud",
            "distancia_km",
            "costo_envio",
            "estado",
            "id_repartidor",
            "repartidor",
            "fecha_creacion",
            "fecha_preparacion",
            "fecha_en_camino",
            "fecha_entrega",
        ]
        read_only_fields = fields

    def get_cliente(self, obj):
        """Nombre del cliente."""
        u = obj.id_orden.id_cliente.id_usuario
        return f"{u.nombres} {u.apellidos}"

    def get_telefono_cliente(self, obj):
        """Teléfono del cliente."""
        return obj.id_orden.id_cliente.id_usuario.telefono

    def get_prendas(self, obj):
        """Cantidad total de prendas de la orden."""
        return sum(item.cantidad for item in obj.id_orden.orderitem_set.all())

    def get_repartidor(self, obj):
        """Nombre del repartidor asignado."""
        r = obj.id_repartidor
        return f"{r.nombres} {r.apellidos}" if r else None

# NUEVO (Fase 2 - CU08): nota de devolución del efectivo de una venta en conflicto.
class NotaDevolucionPosSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField(source="id_usuario", read_only=True)

    class Meta:
        model = NotaDevolucionPos
        fields = [
            "id_nota", "id_venta", "monto_devuelto", "motivo", "detalle", "usuario",
            "fecha_creacion",
        ]
        read_only_fields = fields

# NUEVO (SaaS - paso 6): historial de operaciones sincronizadas sin conexión.
# MODIFICADO (Fase 2 - CU08): conflicto, venta registrada, resolución y nota.
class SyncOperacionSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField(source="id_usuario", read_only=True)
    id_venta = serializers.IntegerField(source="id_venta_id", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    tipo_conflicto_display = serializers.CharField(
        source="get_tipo_conflicto_display", read_only=True
    )
    resolucion_display = serializers.CharField(source="get_resolucion_display", read_only=True)
    revisada_por = serializers.StringRelatedField(read_only=True)
    sucursal = serializers.SerializerMethodField()
    venta = PosSaleSerializer(source="id_venta", read_only=True)
    nota_devolucion = serializers.SerializerMethodField()
    puede_resolver = serializers.SerializerMethodField()

    class Meta:
        model = SyncOperacion
        fields = [
            "id_operacion",
            "uuid",
            "tipo",
            "estado",
            "estado_display",
            "mensaje",
            "id_venta",
            "venta",
            "usuario",
            "sucursal",
            "datos",
            "fecha_operacion",
            "fecha_recepcion",
            "reintentos",
            "tipo_conflicto",
            "tipo_conflicto_display",
            "detalle_conflicto",
            "resolucion",
            "resolucion_display",
            "revisada_por",
            "fecha_revision",
            "nota_revision",
            "nota_devolucion",
            "puede_resolver",
        ]
        read_only_fields = fields

    def get_sucursal(self, obj):
        """Nombre de la sucursal de la venta (o el id enviado si se rechazó)."""
        if obj.id_venta_id:
            return obj.id_venta.id_sucursal.nombre
        datos = obj.datos if isinstance(obj.datos, dict) else {}
        id_sucursal = datos.get("id_sucursal")
        return f"Sucursal #{id_sucursal}" if id_sucursal else None

    def get_nota_devolucion(self, obj):
        """Nota de devolución del efectivo, si el conflicto se resolvió devolviendo."""
        if not obj.id_venta_id:
            return None
        nota = getattr(obj.id_venta, "nota_devolucion", None)
        return NotaDevolucionPosSerializer(nota).data if nota else None

    def get_puede_resolver(self, obj):
        """True si sigue en conflicto sin resolver y el usuario puede resolverla."""
        if obj.estado != "EN_CONFLICTO" or obj.fecha_revision is not None:
            return False
        request = self.context.get("request")
        if request is None:
            return False
        roles = getattr(request, "_roles_usuario", None)
        if roles is None:
            roles = set(request.user.roles.values_list("nombre", flat=True))
            request._roles_usuario = roles
        return bool(roles & set(ROLES_RESUELVEN_CONFLICTOS))


# NUEVO (Fase 2 - CU05): cambio de prenda por talla o color.
def mensaje_para_cliente(cambio):
    """Texto que ve el cliente según el estado del cambio (web y móvil)."""
    devuelta = cambio.id_variante_devuelta
    entregada = cambio.id_variante_entregada
    if cambio.estado == "SOLICITADO":
        return (
            f"Recibimos tu solicitud de cambio: devuelves {devuelta} y recibes {entregada}. "
            f"La tienda asignará un repartidor en breve."
        )
    if cambio.estado in ("PROGRAMADO", "EN_CAMINO"):
        repartidor = cambio.id_repartidor
        nombre = f"{repartidor.nombres} {repartidor.apellidos}" if repartidor else "El repartidor"
        cuando = timezone.localtime(cambio.fecha_programada) if cambio.fecha_programada else None
        texto_cuando = f" el {cuando:%d/%m/%Y} a las {cuando:%H:%M}" if cuando else ""
        prefijo = "está en camino" if cambio.estado == "EN_CAMINO" else f"pasará{texto_cuando}"
        return f"{nombre} {prefijo} para recoger tu {devuelta} y entregarte {entregada}."
    if cambio.estado == "COMPLETADO":
        return f"Cambio completado: recibiste {entregada} (nota {cambio.numero_nota})."
    return f"Cambio rechazado: {cambio.motivo_rechazo or 'sin motivo indicado'}."


def _nombre(usuario):
    """Nombre completo de un usuario (o None)."""
    return f"{usuario.nombres} {usuario.apellidos}" if usuario else None


class CambioPrendaSerializer(serializers.ModelSerializer):
    numero_nota = serializers.CharField(read_only=True)
    motivo_display = serializers.CharField(source="get_motivo_display", read_only=True)
    modalidad_display = serializers.CharField(source="get_modalidad_display", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    sucursal = serializers.CharField(source="id_sucursal.nombre", read_only=True)
    cliente = serializers.SerializerMethodField()
    origen = serializers.SerializerMethodField()
    prenda_devuelta = serializers.StringRelatedField(source="id_variante_devuelta", read_only=True)
    prenda_entregada = serializers.StringRelatedField(source="id_variante_entregada", read_only=True)
    precio = serializers.DecimalField(
        source="id_variante_entregada.precio", max_digits=10, decimal_places=2, read_only=True
    )
    repartidor = serializers.SerializerMethodField()
    solicitado_por = serializers.SerializerMethodField()
    aprobado_por = serializers.SerializerMethodField()
    completado_por = serializers.SerializerMethodField()
    entrega = serializers.SerializerMethodField()
    atrasado = serializers.SerializerMethodField()
    mensaje_cliente = serializers.SerializerMethodField()

    class Meta:
        model = CambioPrenda
        fields = [
            "id_cambio", "numero_nota", "motivo", "motivo_display", "modalidad",
            "modalidad_display", "estado", "estado_display", "id_sucursal", "sucursal",
            "cliente", "origen", "id_venta_item", "id_orden_item", "prenda_devuelta",
            "prenda_entregada", "precio", "cantidad", "observacion", "condiciones_verificadas",
            "id_repartidor", "repartidor", "fecha_programada", "fecha_limite", "atrasado",
            "entrega", "solicitado_por", "aprobado_por", "completado_por", "motivo_rechazo",
            "fecha_solicitud", "fecha_aprobacion", "fecha_en_camino", "fecha_completado",
            "mensaje_cliente",
        ]
        read_only_fields = fields

    def get_cliente(self, obj):
        """Nombre, correo y teléfono del cliente (si se conoce)."""
        if not obj.id_cliente_id:
            return None
        u = obj.id_cliente.id_usuario
        return {"nombre": _nombre(u), "correo": u.correo, "telefono": u.telefono}

    def get_origen(self, obj):
        """Venta o pedido de donde viene la prenda."""
        if obj.id_venta_item_id:
            return {"tipo": "VENTA", "numero": obj.id_venta_item.id_venta_id,
                    "etiqueta": f"Venta #{obj.id_venta_item.id_venta_id}"}
        if obj.id_orden_item_id:
            return {"tipo": "PEDIDO", "numero": obj.id_orden_item.id_orden_id,
                    "etiqueta": f"Pedido #{obj.id_orden_item.id_orden_id}"}
        return None

    def get_repartidor(self, obj):
        """Nombre del repartidor asignado."""
        return _nombre(obj.id_repartidor)

    def get_solicitado_por(self, obj):
        """Quién pidió o registró el cambio."""
        return _nombre(obj.solicitado_por)

    def get_aprobado_por(self, obj):
        """Quién aprobó el cambio."""
        return _nombre(obj.aprobado_por)

    def get_completado_por(self, obj):
        """Quién completó el cambio."""
        return _nombre(obj.completado_por)

    def get_entrega(self, obj):
        """Dirección del pedido con delivery (para el repartidor)."""
        if obj.modalidad != "DELIVERY" or not obj.id_orden_item_id:
            return None
        delivery = getattr(obj.id_orden_item.id_orden, "delivery", None)
        if delivery is None:
            return None
        return {
            "direccion": delivery.direccion,
            "referencia": delivery.referencia,
            "latitud": delivery.latitud,
            "longitud": delivery.longitud,
        }

    def get_atrasado(self, obj):
        """True si el repartidor no completó el cambio dentro de las 48 h."""
        return bool(
            obj.estado in ("PROGRAMADO", "EN_CAMINO")
            and obj.fecha_limite
            and timezone.now() > obj.fecha_limite
        )

    def get_mensaje_cliente(self, obj):
        """Texto del estado del cambio para el cliente."""
        return mensaje_para_cliente(obj)


# NUEVO (devoluciones)
# MODIFICADO (Fase 2 - CU12): devolución con reembolso, nota ND-000001 y
# recojo a domicilio. Se mantienen "orden", "cliente" (nombre) y "variante"
# de cada prenda para la lista anterior de la web y del móvil.
def _dinero(valor):
    """Monto en Bs con 2 decimales."""
    return f"{Decimal(valor or 0):.2f}"


def resumen_reembolso(devolucion):
    """Texto de la nota: lo pagado, lo que retiene la empresa y lo que se devuelve."""
    if devolucion.es_anterior:
        return "Devolución anterior al reembolso: no tiene montos registrados."
    partes = [f"Prendas devueltas: Bs {_dinero(devolucion.monto_prendas)}."]
    if devolucion.monto_retenido and devolucion.monto_retenido > 0:
        partes.append(
            f"La empresa se queda con el {PORCENTAJE_RETENCION:.0f}% "
            f"(Bs {_dinero(devolucion.monto_retenido)}) porque la prenda no tenía falla."
        )
    if devolucion.monto_envio and devolucion.monto_envio > 0:
        partes.append(f"Se devuelve el envío: Bs {_dinero(devolucion.monto_envio)}.")
    partes.append(
        f"Se le devuelve Bs {_dinero(devolucion.monto_reembolso)} "
        f"({devolucion.get_metodo_reembolso_display().lower()})."
    )
    return " ".join(partes)


def mensaje_devolucion_cliente(devolucion):
    """Texto que ve el cliente según el estado de la devolución (web y móvil)."""
    monto = f"Bs {_dinero(devolucion.monto_reembolso)}"
    if devolucion.es_anterior:
        return "Devolución registrada."
    if devolucion.estado == "SOLICITADA":
        return (
            f"Recibimos tu solicitud de devolución. Al recoger la prenda te devolveremos {monto}. "
            f"La tienda asignará un repartidor en breve."
        )
    if devolucion.estado in ("PROGRAMADA", "EN_CAMINO"):
        repartidor = devolucion.id_repartidor
        nombre = f"{repartidor.nombres} {repartidor.apellidos}" if repartidor else "El repartidor"
        if devolucion.estado == "EN_CAMINO":
            return f"{nombre} está en camino para recoger la prenda. Te devolveremos {monto}."
        cuando = timezone.localtime(devolucion.fecha_programada) if devolucion.fecha_programada else None
        texto_cuando = f" el {cuando:%d/%m/%Y} a las {cuando:%H:%M}" if cuando else ""
        return f"{nombre} pasará{texto_cuando} para recoger la prenda. Te devolveremos {monto}."
    if devolucion.estado == "COMPLETADA":
        if devolucion.metodo_reembolso == "STRIPE":
            return (
                f"Devolución completada: te devolvimos {monto} a tu tarjeta; puede tardar unos días "
                f"en verse (nota {devolucion.numero_nota})."
            )
        if devolucion.metodo_reembolso == "EFECTIVO":
            return f"Devolución completada: te devolvimos {monto} en efectivo (nota {devolucion.numero_nota})."
        return f"Devolución completada: te devolvemos {monto} (nota {devolucion.numero_nota})."
    return f"Devolución rechazada: {devolucion.motivo_rechazo or 'sin motivo indicado'}."


class DevolucionItemSerializer(serializers.ModelSerializer):
    variante = serializers.SerializerMethodField()
    motivo_display = serializers.CharField(source="get_motivo_display", read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = DevolucionItem
        fields = [
            "id_item", "id_orden_item", "id_venta_item", "variante", "cantidad", "motivo",
            "motivo_display", "precio_unitario", "subtotal", "porcentaje_retencion",
            "monto_retenido", "monto_reembolso", "repone_stock",
        ]

    def get_variante(self, obj):
        """Prenda devuelta (del pedido o de la venta)."""
        linea = obj.id_orden_item or obj.id_venta_item
        return str(linea.id_variante) if linea else None

    def get_subtotal(self, obj):
        """Precio pagado por las unidades devueltas."""
        if obj.precio_unitario is None:
            return None
        return _dinero(obj.precio_unitario * obj.cantidad)


class DevolucionSerializer(serializers.ModelSerializer):
    numero_nota = serializers.CharField(read_only=True)
    es_anterior = serializers.BooleanField(read_only=True)
    orden = serializers.IntegerField(source="id_orden_id", read_only=True)
    venta = serializers.IntegerField(source="id_venta_id", read_only=True)
    origen = serializers.SerializerMethodField()
    cliente = serializers.SerializerMethodField()
    cliente_contacto = serializers.SerializerMethodField()
    sucursal = serializers.SerializerMethodField()
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    modalidad_display = serializers.CharField(source="get_modalidad_display", read_only=True)
    metodo_reembolso_display = serializers.CharField(
        source="get_metodo_reembolso_display", read_only=True
    )
    items = DevolucionItemSerializer(many=True, read_only=True)
    repartidor = serializers.SerializerMethodField()
    solicitado_por = serializers.SerializerMethodField()
    aprobado_por = serializers.SerializerMethodField()
    completado_por = serializers.SerializerMethodField()
    entrega = serializers.SerializerMethodField()
    atrasado = serializers.SerializerMethodField()
    resumen_reembolso = serializers.SerializerMethodField()
    mensaje_cliente = serializers.SerializerMethodField()

    class Meta:
        model = Devolucion
        fields = [
            "id_devolucion", "numero_nota", "es_anterior", "orden", "venta", "origen", "cliente",
            "cliente_contacto", "sucursal", "estado", "estado_display", "modalidad",
            "modalidad_display", "items", "monto_prendas", "monto_retenido", "monto_envio",
            "monto_reembolso", "metodo_reembolso", "metodo_reembolso_display",
            "referencia_reembolso", "observacion", "condiciones_verificadas", "id_repartidor",
            "repartidor", "fecha_programada", "fecha_limite", "atrasado", "entrega",
            "solicitado_por", "aprobado_por", "completado_por", "motivo_rechazo",
            "fecha_creacion", "fecha_aprobacion", "fecha_en_camino", "fecha_completado",
            "resumen_reembolso", "mensaje_cliente",
        ]
        read_only_fields = fields

    def get_origen(self, obj):
        """Pedido o venta de donde vienen las prendas."""
        if obj.id_orden_id:
            return {"tipo": "PEDIDO", "numero": obj.id_orden_id, "etiqueta": f"Pedido #{obj.id_orden_id}"}
        if obj.id_venta_id:
            return {"tipo": "VENTA", "numero": obj.id_venta_id, "etiqueta": f"Venta #{obj.id_venta_id}"}
        return None

    def get_cliente(self, obj):
        """Nombre del cliente (o None si la venta no tiene cliente)."""
        return _nombre(obj.id_cliente.id_usuario) if obj.id_cliente_id else None

    def get_cliente_contacto(self, obj):
        """Nombre, correo y teléfono del cliente."""
        if not obj.id_cliente_id:
            return None
        u = obj.id_cliente.id_usuario
        return {"nombre": _nombre(u), "correo": u.correo, "telefono": u.telefono}

    def get_sucursal(self, obj):
        """Sucursal de la devolución (las anteriores, la de la orden)."""
        if obj.id_sucursal_id:
            return obj.id_sucursal.nombre
        if obj.id_orden_id and obj.id_orden.id_sucursal_id:
            return obj.id_orden.id_sucursal.nombre
        return None

    def get_repartidor(self, obj):
        """Nombre del repartidor asignado al recojo."""
        return _nombre(obj.id_repartidor)

    def get_solicitado_por(self, obj):
        """Quién pidió o registró la devolución."""
        return _nombre(obj.solicitado_por)

    def get_aprobado_por(self, obj):
        """Quién aprobó la devolución."""
        return _nombre(obj.aprobado_por)

    def get_completado_por(self, obj):
        """Quién completó la devolución."""
        return _nombre(obj.completado_por)

    def get_entrega(self, obj):
        """Dirección del pedido para el recojo a domicilio."""
        if obj.modalidad != "DELIVERY" or not obj.id_orden_id:
            return None
        delivery = getattr(obj.id_orden, "delivery", None)
        if delivery is None:
            return None
        return {
            "direccion": delivery.direccion,
            "referencia": delivery.referencia,
            "latitud": delivery.latitud,
            "longitud": delivery.longitud,
        }

    def get_atrasado(self, obj):
        """True si el repartidor no hizo el recojo dentro de las 48 h."""
        return bool(
            obj.estado in ("PROGRAMADA", "EN_CAMINO")
            and obj.fecha_limite
            and timezone.now() > obj.fecha_limite
        )

    def get_resumen_reembolso(self, obj):
        """Texto de la nota con lo retenido y lo que se devuelve."""
        return resumen_reembolso(obj)

    def get_mensaje_cliente(self, obj):
        """Texto del estado de la devolución para el cliente."""
        return mensaje_devolucion_cliente(obj)