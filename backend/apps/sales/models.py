# backend/apps/sales/models.py
from django.db import models
from apps.users_auth.models import Empresa, Usuario, Cliente
from apps.catalog.models import Sucursal, ProductoVariante
from apps.reservations.models import FittingReservation, FittingReservationItem


class Cart(models.Model):
    id_carrito = models.AutoField(primary_key=True)
    id_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, db_column="id_cliente")
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    estado = models.CharField(
        max_length=20,
        default="ACTIVO",
        choices=[("ACTIVO", "Activo"), ("ABANDONADO", "Abandonado"), ("CONVERTIDO", "Convertido")],
    )
    # NUEVO (SaaS): empresa del carrito. Como el cliente es global, cada
    # carrito pertenece a la empresa cuyos productos contiene (la asigna la
    # vista al crearlo; un cliente puede tener un carrito por empresa).
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="carritos",
    )

    class Meta:
        db_table = "cart"
        verbose_name = "Carrito"
        verbose_name_plural = "Carritos"


class CartItem(models.Model):
    id_item = models.AutoField(primary_key=True)
    id_carrito = models.ForeignKey(Cart, on_delete=models.CASCADE, db_column="id_carrito")
    id_variante = models.ForeignKey(ProductoVariante, on_delete=models.CASCADE, db_column="id_variante")
    cantidad = models.IntegerField(default=1)
    id_reserva_item = models.ForeignKey(
        FittingReservationItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        unique=True,
        db_column="id_reserva_item",
        related_name="cart_item",
    )
    fecha_agregado = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cart_item"
        verbose_name = "Item de Carrito"
        verbose_name_plural = "Items de Carrito"


class Order(models.Model):
    id_orden = models.AutoField(primary_key=True)
    id_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, db_column="id_cliente")
    id_sucursal = models.ForeignKey(Sucursal, on_delete=models.RESTRICT, db_column="id_sucursal", null=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(
        max_length=20,
        default="PENDIENTE",
        choices=[
            ("PENDIENTE", "Pendiente"),
            ("PAGADA", "Pagada"),
            ("ENVIADA", "Enviada"),
            ("ENTREGADA", "Entregada"),
            ("CANCELADA", "Cancelada"),
        ],
    )
    metodo_pago = models.CharField(
        max_length=20,
        default="TARJETA",
        choices=[("TARJETA", "Tarjeta"), ("QR", "QR")],
    )
    referencia_pago = models.CharField(max_length=100, null=True, blank=True)
    tipo_entrega = models.CharField(
        max_length=20,
        default="RETIRO",
        choices=[("RETIRO", "Retiro en sucursal"), ("DELIVERY", "Delivery a domicilio")],
    )
    costo_envio = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    # NUEVO (SaaS): empresa de la orden (heredada de la sucursal que la
    # atiende). Sus items, su delivery y sus devoluciones la heredan de aquí.
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="ordenes",
    )

    class Meta:
        db_table = "orders"
        verbose_name = "Orden"
        verbose_name_plural = "Órdenes"

    def save(self, *args, **kwargs):
        """Hereda la empresa de la sucursal si no se indicó una."""
        if self.id_empresa_id is None and self.id_sucursal_id:
            self.id_empresa_id = self.id_sucursal.id_empresa_id
        super().save(*args, **kwargs)


class Delivery(models.Model):
    id_delivery = models.AutoField(primary_key=True)
    id_orden = models.OneToOneField(
        Order, on_delete=models.CASCADE, db_column="id_orden", related_name="delivery"
    )
    direccion = models.CharField(max_length=250)
    referencia = models.CharField(max_length=250, null=True, blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6)
    longitud = models.DecimalField(max_digits=9, decimal_places=6)
    distancia_km = models.DecimalField(max_digits=6, decimal_places=2)
    costo_envio = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(
        max_length=20,
        default="PENDIENTE",
        choices=[
            ("PENDIENTE", "Pendiente"),
            ("EN_PREPARACION", "En preparación"),
            ("EN_CAMINO", "En camino"),
            ("ENTREGADO", "Entregado"),
        ],
    )
    id_repartidor = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_repartidor",
        related_name="entregas_asignadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_preparacion = models.DateTimeField(null=True, blank=True)
    fecha_en_camino = models.DateTimeField(null=True, blank=True)
    fecha_entrega = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "delivery"
        verbose_name = "Delivery"
        verbose_name_plural = "Deliveries"

    def __str__(self):
        """Representación legible del delivery."""
        return f"Delivery {self.id_delivery} - Orden {self.id_orden_id}"


class OrderItem(models.Model):
    id_item = models.AutoField(primary_key=True)
    id_orden = models.ForeignKey(Order, on_delete=models.CASCADE, db_column="id_orden")
    id_variante = models.ForeignKey(ProductoVariante, on_delete=models.CASCADE, db_column="id_variante")
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "order_item"
        verbose_name = "Item de Orden"
        verbose_name_plural = "Items de Orden"


class PosSale(models.Model):
    # NUEVO (Fase 2 - CU08): estado de la venta presencial.
    #   REGISTRADA   -> venta normal (en línea, o sin conexión sin problemas).
    #   EN_CONFLICTO -> venta sin conexión con precio distinto o sin stock;
    #                   espera que el personal la confirme o devuelva el efectivo.
    #   ANULADA      -> se devolvió el efectivo (tiene nota de devolución).
    ESTADOS = [
        ("REGISTRADA", "Registrada"),
        ("EN_CONFLICTO", "En conflicto"),
        ("ANULADA", "Anulada"),
    ]
    id_venta = models.AutoField(primary_key=True)
    id_sucursal = models.ForeignKey(Sucursal, on_delete=models.RESTRICT, db_column="id_sucursal")
    id_usuario = models.ForeignKey(Usuario, on_delete=models.RESTRICT, db_column="id_usuario")
    total = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(
        max_length=20,
        choices=[
            ("EFECTIVO", "Efectivo"),
            ("TARJETA", "Tarjeta"),
            ("QR", "QR"),
        ],
    )
    fecha_venta = models.DateTimeField(auto_now_add=True)
    # NUEVO (SaaS): empresa de la venta POS (heredada de la sucursal).
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="ventas_pos",
    )
    # NUEVO (Fase 2 - CU08): cliente opcional de la venta presencial.
    id_cliente = models.ForeignKey(
        Cliente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_cliente",
        related_name="ventas_pos",
    )
    estado = models.CharField(max_length=20, choices=ESTADOS, default="REGISTRADA")

    class Meta:
        db_table = "pos_sale"
        verbose_name = "Venta POS"
        verbose_name_plural = "Ventas POS"

    def save(self, *args, **kwargs):
        """Hereda la empresa de la sucursal si no se indicó una."""
        if self.id_empresa_id is None and self.id_sucursal_id:
            self.id_empresa_id = self.id_sucursal.id_empresa_id
        super().save(*args, **kwargs)


class PosSaleItem(models.Model):
    id_item = models.AutoField(primary_key=True)
    id_venta = models.ForeignKey(PosSale, on_delete=models.CASCADE, db_column="id_venta", related_name="items")
    id_variante = models.ForeignKey(ProductoVariante, on_delete=models.CASCADE, db_column="id_variante")
    cantidad = models.IntegerField()
    # Precio realmente cobrado (sin conexión puede no ser el precio actual).
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    id_reserva_item = models.ForeignKey(
        FittingReservationItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        unique=True,
        db_column="id_reserva_item",
        related_name="pos_sale_item",
    )
    # NUEVO (Fase 2 - CU08): precio de la prenda en el servidor al sincronizar.
    precio_lista = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # NUEVO (Fase 2 - CU08): True si al sincronizar no había stock suficiente
    # (la prenda no descontó stock hasta resolver el conflicto).
    sin_stock = models.BooleanField(default=False)

    class Meta:
        db_table = "pos_sale_item"
        verbose_name = "Item de Venta POS"
        verbose_name_plural = "Items de Venta POS"


# NUEVO (devoluciones): el cliente devuelve prendas de un pedido con
# delivery ya entregado. Mismo patrón cabecera/detalle que Order/OrderItem.
# MODIFICADO (Fase 2 - CU12): la devolución se separa del cambio de talla o
# color (CU05) y ahora reembolsa el dinero con nota de devolución (ND-000001):
#   - Origen: un pedido en línea (id_orden) o una venta POS (id_venta).
#   - Modalidad TIENDA (la registra el personal y se completa en el momento)
#     o DELIVERY (el cliente la solicita, el encargado asigna repartidor y
#     fecha de recojo en 48 h, el repartidor recoge y verifica la prenda).
#   - Reembolso: 100% si la culpa es de la tienda (prenda dañada o le llegó
#     otra prenda, más el envío); 90% si el cliente ya no la quiere (la
#     empresa retiene el 10% y no se devuelve el envío).
#   - Se reembolsa al completar: Stripe si el pedido se pagó con tarjeta en
#     línea, efectivo en caja si fue una venta POS.
# Las devoluciones anteriores (sin monto) quedan como historial de lectura.
class Devolucion(models.Model):
    MODALIDADES = [("TIENDA", "En tienda"), ("DELIVERY", "Con recojo a domicilio")]
    ESTADOS = [
        ("SOLICITADA", "Solicitada"),
        ("PROGRAMADA", "Recojo programado"),
        ("EN_CAMINO", "Repartidor en camino"),
        ("COMPLETADA", "Completada"),
        ("RECHAZADA", "Rechazada"),
    ]
    METODOS_REEMBOLSO = [
        ("STRIPE", "Reembolso a la tarjeta"),
        ("EFECTIVO", "Efectivo en caja"),
        ("MANUAL", "Registrado manualmente"),
    ]
    id_devolucion = models.AutoField(primary_key=True)
    id_orden = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_column="id_orden",
        related_name="devoluciones",
    )
    # NUEVO (CU12): devolución de una venta POS.
    id_venta = models.ForeignKey(
        PosSale,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_column="id_venta",
        related_name="devoluciones",
    )
    id_cliente = models.ForeignKey(
        Cliente, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_cliente"
    )
    estado = models.CharField(max_length=20, choices=ESTADOS, default="SOLICITADA")
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    # NUEVO (SaaS): empresa de la devolución (heredada de la orden o de la venta).
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="devoluciones",
    )
    # NUEVO (CU12): sucursal que recibe la prenda y paga el reembolso.
    id_sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_sucursal",
        related_name="devoluciones",
    )
    modalidad = models.CharField(max_length=20, choices=MODALIDADES, null=True, blank=True)
    # NUEVO (CU12): montos de la nota (Bs).
    monto_prendas = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_retenido = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_envio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_reembolso = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    metodo_reembolso = models.CharField(
        max_length=20, choices=METODOS_REEMBOLSO, null=True, blank=True
    )
    referencia_reembolso = models.CharField(max_length=100, null=True, blank=True)
    observacion = models.CharField(max_length=255, null=True, blank=True)
    # La prenda llegó en las condiciones del motivo (lo verifica el personal o el repartidor).
    condiciones_verificadas = models.BooleanField(default=False)
    id_repartidor = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_repartidor",
        related_name="devoluciones_asignadas",
    )
    fecha_programada = models.DateTimeField(null=True, blank=True)
    fecha_limite = models.DateTimeField(null=True, blank=True)
    solicitado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="solicitado_por",
        related_name="devoluciones_solicitadas",
    )
    aprobado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="aprobado_por",
        related_name="devoluciones_aprobadas",
    )
    completado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="completado_por",
        related_name="devoluciones_completadas",
    )
    motivo_rechazo = models.CharField(max_length=255, null=True, blank=True)
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    fecha_en_camino = models.DateTimeField(null=True, blank=True)
    fecha_completado = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "devolucion"
        verbose_name = "Devolución"
        verbose_name_plural = "Devoluciones"
        indexes = [
            models.Index(fields=["id_empresa", "estado"], name="devol_empresa_estado_idx"),
        ]

    def save(self, *args, **kwargs):
        """Hereda la empresa y la sucursal de la orden o de la venta."""
        origen = self.id_orden if self.id_orden_id else (self.id_venta if self.id_venta_id else None)
        if origen is not None:
            if self.id_empresa_id is None:
                self.id_empresa_id = origen.id_empresa_id
            if self.id_sucursal_id is None:
                self.id_sucursal_id = origen.id_sucursal_id
        super().save(*args, **kwargs)

    @property
    def numero_nota(self):
        """Número de la nota de devolución (ND-000001)."""
        return f"ND-{self.id_devolucion:06d}" if self.id_devolucion else None

    @property
    def es_anterior(self):
        """True para las devoluciones anteriores al CU12 (sin montos)."""
        return self.monto_reembolso is None

    def __str__(self):
        """Representación legible de la devolución."""
        origen = f"Orden {self.id_orden_id}" if self.id_orden_id else f"Venta {self.id_venta_id}"
        return f"Devolución {self.numero_nota} - {origen}"


class DevolucionItem(models.Model):
    # Motivos vigentes (CU12) y anteriores (solo lectura del historial).
    MOTIVOS = [
        ("PRODUCTO_DANADO", "Llegó dañada o con defecto"),
        ("ERROR_TIENDA", "Le llegó otra prenda"),
        ("NO_LA_QUIERO", "Ya no la quiere / no le gustó"),
        ("TALLA_INCORRECTA", "Talla incorrecta (anterior)"),
        ("COLOR_INCORRECTO", "Color incorrecto (anterior)"),
        ("OTRO", "Otro (anterior)"),
    ]
    id_item = models.AutoField(primary_key=True)
    id_devolucion = models.ForeignKey(
        Devolucion, on_delete=models.CASCADE, db_column="id_devolucion", related_name="items"
    )
    id_orden_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_column="id_orden_item",
        related_name="devoluciones",
    )
    # NUEVO (CU12): línea de la venta POS devuelta.
    id_venta_item = models.ForeignKey(
        PosSaleItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_column="id_venta_item",
        related_name="devoluciones",
    )
    cantidad = models.IntegerField()
    motivo = models.CharField(max_length=30, choices=MOTIVOS)
    # NUEVO (CU12): precio pagado, porcentaje retenido y monto a devolver de la línea.
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    porcentaje_retencion = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    monto_retenido = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_reembolso = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # False si la prenda está dañada (no vuelve al stock).
    repone_stock = models.BooleanField(default=True)

    class Meta:
        db_table = "devolucion_item"
        verbose_name = "Item de Devolución"
        verbose_name_plural = "Items de Devolución"


# NUEVO (SaaS - paso 6): operaciones hechas SIN CONEXIÓN que el dispositivo
# envía al reconectarse. Cada operación trae un UUID generado en el
# dispositivo: si llega dos veces (reintento, red inestable), se reconoce
# por ese UUID y NO se registra de nuevo (idempotencia). Queda como
# historial, incluidas las rechazadas y las que quedaron en conflicto.
# NUEVO (SaaS - A.5): también registra las reservas de prendas que el
# cliente hizo sin conexión (tipo RESERVA, con la reserva creada).
# NUEVO (Fase 2 - CU08): estado EN_CONFLICTO con su detalle y su resolución.
class SyncOperacion(models.Model):
    TIPOS = [("VENTA_POS", "Venta presencial"), ("RESERVA", "Reserva de prendas")]
    ESTADOS = [
        ("RECIBIDA", "Recibida"),
        ("SINCRONIZADA", "Sincronizada"),
        ("RECHAZADA", "Rechazada"),
        ("EN_CONFLICTO", "En conflicto"),
    ]
    TIPOS_CONFLICTO = [
        ("PRECIO", "Precio distinto"),
        ("STOCK", "Sin stock suficiente"),
        ("PRECIO_Y_STOCK", "Precio distinto y sin stock"),
    ]
    RESOLUCIONES = [
        ("CONFIRMADA", "Confirmada"),
        ("DEVUELTA", "Efectivo devuelto"),
    ]
    id_operacion = models.AutoField(primary_key=True)
    # UUID generado en el dispositivo (clave de idempotencia).
    uuid = models.UUIDField(unique=True)
    tipo = models.CharField(max_length=30, choices=TIPOS, default="VENTA_POS")
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        db_column="id_empresa",
        related_name="operaciones_sync",
    )
    id_usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_usuario",
        related_name="operaciones_sync",
    )
    # Datos tal como los envió el dispositivo (sucursal, método de pago, prendas).
    datos = models.JSONField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default="RECIBIDA")
    # Motivo del rechazo o resumen del conflicto.
    mensaje = models.CharField(max_length=255, null=True, blank=True)
    # Venta creada al sincronizar (SINCRONIZADA o EN_CONFLICTO).
    id_venta = models.OneToOneField(
        PosSale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_venta",
        related_name="operacion_sync",
    )
    # NUEVO (SaaS - A.5): reserva creada al sincronizar (solo tipo RESERVA).
    id_reserva = models.OneToOneField(
        FittingReservation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_reserva",
        related_name="operacion_sync",
    )
    # Momento en que se hizo la operación en el dispositivo (sin conexión).
    fecha_operacion = models.DateTimeField(null=True, blank=True)
    fecha_recepcion = models.DateTimeField(auto_now_add=True)
    # Cuántas veces llegó repetida (reintentos ya procesados).
    reintentos = models.PositiveIntegerField(default=0)
    # NUEVO (Fase 2 - CU08): conflicto detectado y su resolución.
    tipo_conflicto = models.CharField(max_length=20, choices=TIPOS_CONFLICTO, null=True, blank=True)
    # Lista por prenda: tipo, prenda, cantidad, precios, diferencia, stock disponible.
    detalle_conflicto = models.JSONField(null=True, blank=True)
    resolucion = models.CharField(max_length=20, choices=RESOLUCIONES, null=True, blank=True)
    revisada_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="revisada_por",
        related_name="conflictos_revisados",
    )
    fecha_revision = models.DateTimeField(null=True, blank=True)
    nota_revision = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "sync_operacion"
        verbose_name = "Operación sincronizada"
        verbose_name_plural = "Operaciones sincronizadas"
        indexes = [
            models.Index(fields=["id_empresa", "estado"], name="sync_op_empresa_estado_idx")
        ]

    def __str__(self):
        """Representación legible de la operación."""
        return f"{self.tipo} {self.uuid} ({self.estado})"


# NUEVO (Fase 2 - CU08): nota de devolución del efectivo de una venta POS
# hecha sin conexión que quedó en conflicto y se resolvió devolviendo el
# dinero al cliente (la venta queda ANULADA).
class NotaDevolucionPos(models.Model):
    id_nota = models.AutoField(primary_key=True)
    id_venta = models.OneToOneField(
        PosSale,
        on_delete=models.CASCADE,
        db_column="id_venta",
        related_name="nota_devolucion",
    )
    id_operacion = models.ForeignKey(
        SyncOperacion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_operacion",
        related_name="notas_devolucion",
    )
    monto_devuelto = models.DecimalField(max_digits=10, decimal_places=2)
    motivo = models.CharField(max_length=255)
    # Prendas de la venta y si volvieron al stock.
    detalle = models.JSONField(default=list)
    id_usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_usuario",
        related_name="notas_devolucion_pos",
    )
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        db_column="id_empresa",
        related_name="notas_devolucion_pos",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "nota_devolucion_pos"
        verbose_name = "Nota de devolución POS"
        verbose_name_plural = "Notas de devolución POS"

    def __str__(self):
        """Representación legible de la nota."""
        return f"Nota {self.id_nota} - Venta {self.id_venta_id} (Bs {self.monto_devuelto})"


# NUEVO (Fase 2 - CU05): cambio de prenda por talla o color, con plazo y
# nota de devolución. Dos motivos:
#   ERROR_TIENDA -> al cliente le llegó otra talla/color de la que compró;
#                   devuelve la que le llegó y recibe la que compró.
#   NO_LE_QUEDA  -> recibió lo que compró, pero quiere otra talla/color
#                   de la misma prenda y al mismo precio.
# Dos modalidades:
#   TIENDA   -> el personal lo registra y se completa en el momento.
#   DELIVERY -> el cliente lo solicita, el encargado lo aprueba asignando
#               repartidor y fecha de visita (máximo 48 h) y el repartidor
#               recoge la prenda devuelta y entrega la correcta.
# El cambio completado es la nota de devolución (número NC-000001).
class CambioPrenda(models.Model):
    MOTIVOS = [
        ("ERROR_TIENDA", "Le llegó otra talla o color"),
        ("NO_LE_QUEDA", "No le quedó, quiere otra talla o color"),
    ]
    MODALIDADES = [("TIENDA", "En tienda"), ("DELIVERY", "Con delivery")]
    ESTADOS = [
        ("SOLICITADO", "Solicitado"),
        ("PROGRAMADO", "Programado"),
        ("EN_CAMINO", "En camino"),
        ("COMPLETADO", "Completado"),
        ("RECHAZADO", "Rechazado"),
    ]
    id_cambio = models.AutoField(primary_key=True)
    id_empresa = models.ForeignKey(
        Empresa, on_delete=models.RESTRICT, db_column="id_empresa", related_name="cambios_prenda"
    )
    id_sucursal = models.ForeignKey(
        Sucursal, on_delete=models.RESTRICT, db_column="id_sucursal", related_name="cambios_prenda"
    )
    id_cliente = models.ForeignKey(
        Cliente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_cliente",
        related_name="cambios_prenda",
    )
    # Origen: una línea de venta POS o una línea de pedido (una de las dos).
    id_venta_item = models.ForeignKey(
        PosSaleItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_venta_item",
        related_name="cambios",
    )
    id_orden_item = models.ForeignKey(
        OrderItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_orden_item",
        related_name="cambios",
    )
    motivo = models.CharField(max_length=20, choices=MOTIVOS)
    modalidad = models.CharField(max_length=20, choices=MODALIDADES)
    estado = models.CharField(max_length=20, choices=ESTADOS, default="SOLICITADO")
    # Prenda que el cliente devuelve y prenda que recibe.
    id_variante_devuelta = models.ForeignKey(
        ProductoVariante,
        on_delete=models.RESTRICT,
        db_column="id_variante_devuelta",
        related_name="cambios_devuelta",
    )
    id_variante_entregada = models.ForeignKey(
        ProductoVariante,
        on_delete=models.RESTRICT,
        db_column="id_variante_entregada",
        related_name="cambios_entregada",
    )
    cantidad = models.PositiveIntegerField(default=1)
    observacion = models.CharField(max_length=255, null=True, blank=True)
    # La prenda devuelta está sin uso y con etiqueta (lo verifica el personal o el repartidor).
    condiciones_verificadas = models.BooleanField(default=False)
    id_repartidor = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_repartidor",
        related_name="cambios_asignados",
    )
    fecha_programada = models.DateTimeField(null=True, blank=True)
    # Aprobación + 48 h: hasta cuándo el repartidor debe hacer el cambio.
    fecha_limite = models.DateTimeField(null=True, blank=True)
    solicitado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="solicitado_por",
        related_name="cambios_solicitados",
    )
    aprobado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="aprobado_por",
        related_name="cambios_aprobados",
    )
    completado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="completado_por",
        related_name="cambios_completados",
    )
    motivo_rechazo = models.CharField(max_length=255, null=True, blank=True)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    fecha_en_camino = models.DateTimeField(null=True, blank=True)
    fecha_completado = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cambio_prenda"
        verbose_name = "Cambio de prenda"
        verbose_name_plural = "Cambios de prenda"
        indexes = [
            models.Index(fields=["id_empresa", "estado"], name="cambio_empresa_estado_idx"),
            models.Index(fields=["id_empresa", "fecha_solicitud"], name="cambio_empresa_fecha_idx"),
        ]

    @property
    def numero_nota(self):
        """Número de la nota de devolución del cambio (NC-000001)."""
        return f"NC-{self.id_cambio:06d}" if self.id_cambio else None

    def __str__(self):
        """Representación legible del cambio."""
        return f"Cambio {self.numero_nota} ({self.estado})"