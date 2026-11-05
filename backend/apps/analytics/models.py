# backend/apps/analytics/models.py
#
# NUEVO (Fase 3 - CU09): analítica con Machine Learning.
#
# Tablas SEPARADAS de las ventas reales (prefijo ml_):
#   - CompraSimulada / DetalleCompraSimulada: datos sintéticos para entrenar.
#     Son compras simuladas de los clientes REALES, en las sucursales y
#     prendas REALES de cada empresa. No aparecen en ventas, reportes ni
#     dashboard: solo las usan los modelos.
#   - EntrenamientoModelo: cada entrenamiento (demanda o segmentación), con
#     su ventana de datos (3, 5 o 12 meses), parámetros y métricas.
#   - PrediccionDemanda: unidades que se espera vender por prenda, sucursal y
#     semana (modelo supervisado).
#   - SegmentoCliente: grupo de cada cliente real en una empresa (modelo no
#     supervisado: VIP, leal, ocasional o en riesgo).
# Todo es por empresa (tenant).

from django.db import models

from apps.catalog.models import Producto, Sucursal
from apps.users_auth.models import Cliente, Empresa, Usuario


class CompraSimulada(models.Model):
    """Compra simulada (dato sintético) de un cliente real en una sucursal real."""

    id_compra = models.AutoField(primary_key=True)
    id_empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, db_column="id_empresa", related_name="compras_simuladas"
    )
    id_sucursal = models.ForeignKey(
        Sucursal, on_delete=models.CASCADE, db_column="id_sucursal", related_name="compras_simuladas"
    )
    id_cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column="id_cliente", related_name="compras_simuladas"
    )
    fecha = models.DateField()
    total = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ml_compra_simulada"
        verbose_name = "Compra simulada (ML)"
        verbose_name_plural = "Compras simuladas (ML)"
        indexes = [
            models.Index(fields=["id_empresa", "fecha"], name="ml_compra_empresa_fecha_idx"),
        ]

    def __str__(self):
        """Representación legible de la compra simulada."""
        return f"Compra simulada {self.id_compra} - {self.fecha}"


class DetalleCompraSimulada(models.Model):
    """Prenda y cantidad de una compra simulada."""

    id_detalle = models.AutoField(primary_key=True)
    id_compra = models.ForeignKey(
        CompraSimulada, on_delete=models.CASCADE, db_column="id_compra", related_name="detalles"
    )
    id_producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, db_column="id_producto", related_name="ventas_simuladas"
    )
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "ml_detalle_compra_simulada"
        verbose_name = "Detalle de compra simulada (ML)"
        verbose_name_plural = "Detalles de compras simuladas (ML)"

    def __str__(self):
        """Representación legible del detalle."""
        return f"{self.id_producto_id} x {self.cantidad}"


class EntrenamientoModelo(models.Model):
    """Un entrenamiento de un modelo de ML para una empresa, con sus métricas."""

    TIPOS = [
        ("DEMANDA", "Predicción de demanda (supervisado)"),
        ("SEGMENTACION", "Segmentación de clientes (no supervisado)"),
    ]

    id_entrenamiento = models.AutoField(primary_key=True)
    id_empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, db_column="id_empresa", related_name="entrenamientos_ml"
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    # Meses de historial usados para entrenar (3, 5 o 12).
    ventana_meses = models.PositiveSmallIntegerField()
    algoritmo = models.CharField(max_length=60)
    parametros = models.JSONField(default=dict)
    # MAE, RMSE, R², silhouette por k, importancia de variables, series para
    # los gráficos de evaluación, etc.
    metricas = models.JSONField(default=dict)
    filas_entrenamiento = models.PositiveIntegerField(default=0)
    filas_prueba = models.PositiveIntegerField(default=0)
    # El entrenamiento vigente de cada empresa y tipo es el que usa el sistema.
    vigente = models.BooleanField(default=False)
    id_usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_usuario"
    )
    fecha_entrenamiento = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ml_entrenamiento"
        verbose_name = "Entrenamiento de modelo (ML)"
        verbose_name_plural = "Entrenamientos de modelos (ML)"
        indexes = [
            models.Index(fields=["id_empresa", "tipo", "vigente"], name="ml_entren_empresa_tipo_idx"),
        ]

    def __str__(self):
        """Representación legible del entrenamiento."""
        return f"{self.get_tipo_display()} - {self.ventana_meses} meses - {self.fecha_entrenamiento:%d/%m/%Y}"


class PrediccionDemanda(models.Model):
    """Unidades que se espera vender de una prenda en una sucursal en una semana."""

    id_prediccion = models.AutoField(primary_key=True)
    id_entrenamiento = models.ForeignKey(
        EntrenamientoModelo, on_delete=models.CASCADE, db_column="id_entrenamiento",
        related_name="predicciones",
    )
    id_empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, db_column="id_empresa", related_name="predicciones_ml"
    )
    id_sucursal = models.ForeignKey(
        Sucursal, on_delete=models.CASCADE, db_column="id_sucursal", related_name="predicciones_ml"
    )
    id_producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, db_column="id_producto", related_name="predicciones_ml"
    )
    # Lunes de la semana predicha.
    semana_inicio = models.DateField()
    unidades_predichas = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "ml_prediccion_demanda"
        verbose_name = "Predicción de demanda (ML)"
        verbose_name_plural = "Predicciones de demanda (ML)"
        unique_together = ("id_entrenamiento", "id_sucursal", "id_producto", "semana_inicio")

    def __str__(self):
        """Representación legible de la predicción."""
        return f"{self.id_producto_id} en {self.id_sucursal_id}: {self.unidades_predichas}"


class SegmentoCliente(models.Model):
    """Grupo de un cliente real dentro de una empresa (resultado de K-means sobre RFM)."""

    SEGMENTOS = [
        ("VIP", "Clientes VIP"),
        ("LEAL", "Clientes leales"),
        ("OCASIONAL", "Clientes ocasionales"),
        ("RIESGO", "Clientes en riesgo"),
    ]

    id_segmento = models.AutoField(primary_key=True)
    id_entrenamiento = models.ForeignKey(
        EntrenamientoModelo, on_delete=models.CASCADE, db_column="id_entrenamiento",
        related_name="segmentos",
    )
    id_empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, db_column="id_empresa", related_name="segmentos_ml"
    )
    id_cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column="id_cliente", related_name="segmentos_ml"
    )
    segmento = models.CharField(max_length=20, choices=SEGMENTOS)
    # Variables RFM del cliente en la empresa.
    recencia_dias = models.PositiveIntegerField()
    frecuencia = models.PositiveIntegerField()
    monto = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "ml_segmento_cliente"
        verbose_name = "Segmento de cliente (ML)"
        verbose_name_plural = "Segmentos de clientes (ML)"
        unique_together = ("id_entrenamiento", "id_cliente")

    def __str__(self):
        """Representación legible del segmento."""
        return f"{self.id_cliente_id}: {self.get_segmento_display()}"