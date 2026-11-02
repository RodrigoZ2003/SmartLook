# backend/apps/reservations/models.py
from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone

from apps.users_auth.models import Empresa, Usuario, Cliente
from apps.catalog.models import Sucursal, ProductoVariante

# NUEVO (Fase 2 - reservas con anticipo): la reserva vence 1 semana después
# de la fecha y hora reservadas; la reserva hecha sin conexión tiene 3 horas
# para pagarse; si vence o se cancela se retiene el 10% del precio total.
DIAS_VENCIMIENTO = 7
HORAS_PAGO_OFFLINE = 3
PORCENTAJE_RETENCION = 10


class FittingReservation(models.Model):
    # MODIFICADO (Fase 2 - reservas con anticipo):
    #   PENDIENTE      -> reserva anterior a esta fase (sin pago). Vence a la
    #                     semana y solo se libera la prenda.
    #   PENDIENTE_PAGO -> creada (en línea o sincronizada sin conexión),
    #                     esperando el pago por Stripe. No aparta stock.
    #   CONFIRMADA     -> pagada (anticipo o total): la prenda queda apartada.
    #   COMPLETADA     -> se retiró en tienda o se pidió por delivery.
    #   CANCELADA      -> la canceló el cliente (CU17).
    #   VENCIDA        -> pasó el plazo sin retirar o sin pagar.
    ESTADOS = [
        ("PENDIENTE", "Pendiente"),
        ("PENDIENTE_PAGO", "Pendiente de pago"),
        ("CONFIRMADA", "Confirmada"),
        ("COMPLETADA", "Completada"),
        ("CANCELADA", "Cancelada"),
        ("VENCIDA", "Vencida"),
    ]
    TIPOS_PAGO = [
        ("ANTICIPO", "Anticipo"),
        ("TOTAL", "Pago total"),
    ]
    id_reserva = models.AutoField(primary_key=True)
    id_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, db_column="id_cliente")
    id_sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, db_column="id_sucursal")
    # NOTA (CU11): "id_variante" se quitó de aquí. Antes una reserva solo
    # podía llevar UNA prenda. El enunciado (RF09) exige que el cliente
    # pueda reservar varias prendas a la vez, así que ahora esa relación
    # vive en FittingReservationItem (mismo patrón que Cart/CartItem en
    # la app sales).
    fecha_reserva = models.DateField()
    hora_reserva = models.TimeField()
    estado = models.CharField(max_length=20, default="PENDIENTE_PAGO", choices=ESTADOS)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    # NUEVO (SaaS): empresa de la reserva (heredada de la sucursal). Las
    # prendas de la reserva (FittingReservationItem) la heredan de aquí.
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="reservas",
    )
    # NUEVO (Fase 2 - reservas con anticipo): pago por Stripe al reservar.
    tipo_pago = models.CharField(max_length=20, choices=TIPOS_PAGO, null=True, blank=True)
    porcentaje_anticipo = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # Precio total de las prendas (queda fijo al reservar).
    monto_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # Lo que se cobra al reservar (anticipo o total) y lo que ya se pagó.
    monto_a_pagar = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    referencia_pago = models.CharField(max_length=100, null=True, blank=True)
    fecha_pago = models.DateTimeField(null=True, blank=True)
    # Reserva sin conexión: hasta cuándo puede pagarse (3 horas).
    fecha_limite_pago = models.DateTimeField(null=True, blank=True)
    # Fecha y hora reservadas + 1 semana.
    fecha_vencimiento = models.DateTimeField(null=True, blank=True)
    # Nota de devolución al vencer o cancelar (pagado, retenido, devuelto).
    monto_retenido = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_devuelto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    referencia_reembolso = models.CharField(max_length=100, null=True, blank=True)
    motivo_cierre = models.CharField(max_length=255, null=True, blank=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fitting_reservation"
        verbose_name = "Reserva de Probador"
        verbose_name_plural = "Reservas de Probador"
        indexes = [
            models.Index(fields=["estado", "fecha_vencimiento"], name="reserva_estado_vence_idx"),
        ]

    def save(self, *args, **kwargs):
        """Hereda la empresa de la sucursal y calcula el vencimiento si falta."""
        if self.id_empresa_id is None and self.id_sucursal_id:
            self.id_empresa_id = self.id_sucursal.id_empresa_id
        if self.fecha_vencimiento is None and self.fecha_reserva and self.hora_reserva:
            self.fecha_vencimiento = self.calcular_vencimiento()
        super().save(*args, **kwargs)

    def calcular_vencimiento(self):
        """Fecha y hora reservadas + 1 semana (en la zona horaria del sistema)."""
        reservada = timezone.make_aware(
            datetime.combine(self.fecha_reserva, self.hora_reserva),
            timezone.get_current_timezone(),
        )
        return reservada + timedelta(days=DIAS_VENCIMIENTO)

    @property
    def saldo(self):
        """Lo que falta pagar al retirar (precio total menos lo pagado)."""
        if self.monto_total is None:
            return None
        return max(self.monto_total - (self.monto_pagado or 0), 0)

    @property
    def numero_nota(self):
        """Número de la nota de devolución (NR-000001), si la reserva tiene una."""
        if self.monto_devuelto is None:
            return None
        return f"NR-{self.id_reserva:06d}"

    def __str__(self):
        """Representación legible de la reserva."""
        return f"Reserva {self.id_reserva} - {self.id_cliente}"


class FittingReservationItem(models.Model):
    id_item = models.AutoField(primary_key=True)
    # related_name="items" explícito a propósito: el serializer expone el
    # campo "items" y necesita que el acceso inverso se llame exactamente
    # así (el mismo tipo de bug que corregimos en catalog/serializers.py
    # con "productovariante_set" vs "variantes" - esta vez lo dejamos bien
    # desde el modelo, sin depender de un "source" en el serializer).
    id_reserva = models.ForeignKey(
        FittingReservation, on_delete=models.CASCADE, db_column="id_reserva", related_name="items"
    )
    id_variante = models.ForeignKey(ProductoVariante, on_delete=models.CASCADE, db_column="id_variante")
    # NUEVO (vínculo reserva-venta): estado individual de la prenda dentro
    # de la reserva. Antes solo existía el estado global de la reserva
    # completa - ahora, si el cliente decide comprar solo algunas de las
    # prendas que reservó, cada una se resuelve por separado:
    #   PENDIENTE -> todavía no se compró ni se devolvió.
    #   COMPRADO  -> se pagó (en caja o digital); su stock ya estaba
    #                descontado desde que se creó la reserva.
    #   DEVUELTO  -> el cliente no la compró; se repuso su stock.
    estado = models.CharField(
        max_length=20,
        default="PENDIENTE",
        choices=[
            ("PENDIENTE", "Pendiente"),
            ("COMPRADO", "Comprado"),
            ("DEVUELTO", "Devuelto"),
        ],
    )
    # NUEVO (Fase 2 - reservas con anticipo): precio de la prenda al reservar
    # (queda fijo aunque luego cambie el precio del catálogo).
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "fitting_reservation_item"
        verbose_name = "Prenda de Reserva"
        verbose_name_plural = "Prendas de Reserva"

    def __str__(self):
        """Representación legible de la prenda reservada."""
        return f"Item {self.id_item} - Reserva {self.id_reserva_id}"