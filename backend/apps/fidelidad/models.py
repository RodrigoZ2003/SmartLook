# backend/apps/fidelidad/models.py
#
# NUEVO (Fase 3 - CU18): descuento por fidelidad.
#
# Regla global (la configura el SUPER_ADMIN): al llegar a "compras_requeridas"
# compras pagadas en una empresa durante el mes calendario (hora de Bolivia),
# la siguiente compra sin reservas en esa empresa tiene "porcentaje" de
# descuento en las prendas (el envío se cobra completo). Una vez por mes; se
# reinicia el día 1. Los cambios de la regla aplican de inmediato.
#
# El descuento aplicado se guarda en BeneficioFidelidad (vinculado al pedido
# web o a la venta POS), así las tablas de pedidos y ventas no cambian.
from decimal import Decimal

from django.db import models

from apps.users_auth.models import Cliente, Empresa, Usuario


class ReglaFidelidad(models.Model):
    """Regla única del sistema: cuántas compras al mes y qué porcentaje."""

    id_regla = models.AutoField(primary_key=True)
    compras_requeridas = models.PositiveSmallIntegerField(default=5)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("50.00"))
    activa = models.BooleanField(default=True)
    actualizado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="actualizado_por",
        related_name="reglas_fidelidad",
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "regla_fidelidad"
        verbose_name = "Regla de fidelidad"
        verbose_name_plural = "Reglas de fidelidad"

    @classmethod
    def vigente(cls):
        """Regla del sistema (se crea con 5 compras / 50% / activa la primera vez)."""
        regla, _ = cls.objects.get_or_create(pk=1)
        return regla

    def __str__(self):
        """Representación legible de la regla."""
        estado = "activa" if self.activa else "inactiva"
        return f"{self.compras_requeridas} compras = {self.porcentaje}% ({estado})"


class BeneficioFidelidad(models.Model):
    """Beneficio de un cliente en una empresa durante un mes (periodo = día 1 del mes).

    fecha_alcanzado: cuándo llegó a las compras requeridas (se le notificó).
    fecha_uso: cuándo usó el descuento, en un pedido web (id_orden) o en una
    venta POS (id_venta), con el porcentaje y el monto descontado.
    """

    id_beneficio = models.AutoField(primary_key=True)
    id_cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column="id_cliente", related_name="beneficios_fidelidad"
    )
    id_empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, db_column="id_empresa", related_name="beneficios_fidelidad"
    )
    periodo = models.DateField()
    fecha_alcanzado = models.DateTimeField(null=True, blank=True)
    fecha_uso = models.DateTimeField(null=True, blank=True)
    id_orden = models.OneToOneField(
        "sales.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_orden",
        related_name="beneficio_fidelidad",
    )
    id_venta = models.OneToOneField(
        "sales.PosSale",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_venta",
        related_name="beneficio_fidelidad",
    )
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    monto_descuento = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "beneficio_fidelidad"
        verbose_name = "Beneficio de fidelidad"
        verbose_name_plural = "Beneficios de fidelidad"
        constraints = [
            models.UniqueConstraint(
                fields=["id_cliente", "id_empresa", "periodo"], name="beneficio_cliente_empresa_mes_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["id_empresa", "periodo"], name="beneficio_empresa_mes_idx"),
        ]

    @property
    def usado(self):
        """True si el cliente ya usó el descuento de ese mes."""
        return self.fecha_uso is not None

    def __str__(self):
        """Representación legible del beneficio."""
        return f"Cliente {self.id_cliente_id} - Empresa {self.id_empresa_id} - {self.periodo:%m/%Y}"