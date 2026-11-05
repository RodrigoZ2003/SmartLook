# backend/apps/inventory/models.py
#
# MODIFICADO (Fase 3 - CU07): traspasos de prendas entre sucursales de una
# misma empresa (Traspaso y DetalleTraspaso). Estados:
#   SOLICITADO  -> lo pide el ADMIN_EMPRESA, el encargado de la sucursal
#                  destino o el SUPER_ADMIN.
#   EN_TRANSITO -> aprobado por el ADMIN_EMPRESA o el SUPER_ADMIN; en ese
#                  momento sale el stock de la sucursal origen (SALIDA).
#   RECIBIDO    -> el destino lo recibe completo; entra el stock (ENTRADA).
#   RECHAZADO   -> solo mientras está SOLICITADO, con motivo obligatorio.
#   CANCELADO   -> el solicitante (o un administrador) lo cancela mientras
#                  está SOLICITADO.
from django.db import models
from apps.catalog.models import Sucursal, ProductoVariante
from apps.users_auth.models import Empresa, Usuario

class StockItem(models.Model):
    id_stock = models.AutoField(primary_key=True)
    id_sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, db_column="id_sucursal")
    id_variante = models.ForeignKey(ProductoVariante, on_delete=models.CASCADE, db_column="id_variante")
    cantidad = models.IntegerField(default=0)
    stock_minimo = models.IntegerField(default=5)
    stock_maximo = models.IntegerField(default=100)
    estado = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    # NUEVO (SaaS): empresa dueña del stock. Se guarda directo (además de
    # venir por la sucursal) para filtrar consultas de inventario por
    # empresa sin JOIN adicional (RNF09).
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="stock_items",
    )

    class Meta:
        db_table = "stock_item"
        unique_together = ("id_sucursal", "id_variante")
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"

    def save(self, *args, **kwargs):
        """Hereda la empresa de la sucursal si no se indicó una."""
        if self.id_empresa_id is None and self.id_sucursal_id:
            self.id_empresa_id = self.id_sucursal.id_empresa_id
        super().save(*args, **kwargs)

    def __str__(self):
        """Representación legible del stock."""
        return f"{self.id_sucursal.nombre} - {self.id_variante} - {self.cantidad}"

class InventoryMovement(models.Model):
    id_movimiento = models.AutoField(primary_key=True)
    id_sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, db_column="id_sucursal")
    id_variante = models.ForeignKey(ProductoVariante, on_delete=models.CASCADE, db_column="id_variante")
    id_usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, db_column="id_usuario")
    tipo_movimiento = models.CharField(
        max_length=20,
        choices=[
            ("ENTRADA", "Entrada"),
            ("SALIDA", "Salida"),
            ("AJUSTE", "Ajuste"),
        ],
    )
    cantidad = models.IntegerField()
    motivo = models.CharField(max_length=255, null=True, blank=True)
    fecha_movimiento = models.DateTimeField(auto_now_add=True)
    # NUEVO (SaaS): empresa del movimiento (heredada de la sucursal).
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="movimientos_inventario",
    )

    class Meta:
        db_table = "inventory_movement"
        verbose_name = "Movimiento de Inventario"
        verbose_name_plural = "Movimientos de Inventario"

    def save(self, *args, **kwargs):
        """Hereda la empresa de la sucursal si no se indicó una."""
        if self.id_empresa_id is None and self.id_sucursal_id:
            self.id_empresa_id = self.id_sucursal.id_empresa_id
        super().save(*args, **kwargs)

    def __str__(self):
        """Representación legible del movimiento."""
        return f"{self.tipo_movimiento} - {self.id_variante} - {self.cantidad}"


class Traspaso(models.Model):
    """Traspaso de prendas de una sucursal a otra de la misma empresa."""

    ESTADOS = [
        ("SOLICITADO", "Solicitado"),
        ("EN_TRANSITO", "En tránsito"),
        ("RECIBIDO", "Recibido"),
        ("RECHAZADO", "Rechazado"),
        ("CANCELADO", "Cancelado"),
    ]

    id_traspaso = models.AutoField(primary_key=True)
    id_empresa = models.ForeignKey(
        Empresa, on_delete=models.RESTRICT, db_column="id_empresa", related_name="traspasos"
    )
    id_sucursal_origen = models.ForeignKey(
        Sucursal, on_delete=models.RESTRICT, db_column="id_sucursal_origen", related_name="traspasos_salida"
    )
    id_sucursal_destino = models.ForeignKey(
        Sucursal, on_delete=models.RESTRICT, db_column="id_sucursal_destino", related_name="traspasos_entrada"
    )
    estado = models.CharField(max_length=20, choices=ESTADOS, default="SOLICITADO")
    # Nota opcional de quien solicita (por qué se necesita).
    observacion = models.CharField(max_length=255, null=True, blank=True)
    # True si se creó desde una sugerencia de la Analítica (CU09).
    desde_sugerencia = models.BooleanField(default=False)
    motivo_rechazo = models.CharField(max_length=255, null=True, blank=True)

    id_usuario_solicita = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, db_column="id_usuario_solicita",
        related_name="traspasos_solicitados",
    )
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    id_usuario_aprueba = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_usuario_aprueba",
        related_name="traspasos_aprobados",
    )
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    id_usuario_rechaza = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_usuario_rechaza",
        related_name="traspasos_rechazados",
    )
    fecha_rechazo = models.DateTimeField(null=True, blank=True)
    id_usuario_recibe = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_usuario_recibe",
        related_name="traspasos_recibidos",
    )
    fecha_recepcion = models.DateTimeField(null=True, blank=True)
    id_usuario_cancela = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_usuario_cancela",
        related_name="traspasos_cancelados",
    )
    fecha_cancelacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "traspaso"
        verbose_name = "Traspaso"
        verbose_name_plural = "Traspasos"
        indexes = [
            models.Index(fields=["id_empresa", "estado"], name="traspaso_empresa_estado_idx"),
        ]

    def __str__(self):
        """Representación legible del traspaso."""
        return f"Traspaso {self.id_traspaso}: {self.id_sucursal_origen} -> {self.id_sucursal_destino}"


class DetalleTraspaso(models.Model):
    """Prenda (talla y color) y cantidad de un traspaso."""

    id_detalle = models.AutoField(primary_key=True)
    id_traspaso = models.ForeignKey(
        Traspaso, on_delete=models.CASCADE, db_column="id_traspaso", related_name="detalles"
    )
    id_variante = models.ForeignKey(
        ProductoVariante, on_delete=models.RESTRICT, db_column="id_variante", related_name="traspasos"
    )
    cantidad = models.PositiveIntegerField()

    class Meta:
        db_table = "detalle_traspaso"
        verbose_name = "Detalle de traspaso"
        verbose_name_plural = "Detalles de traspasos"
        unique_together = ("id_traspaso", "id_variante")

    def __str__(self):
        """Representación legible del detalle."""
        return f"{self.id_variante} x {self.cantidad}"