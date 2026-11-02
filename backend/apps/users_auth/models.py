# backend/apps/users_auth/models.py
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Rol(models.Model):
    id_rol = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=255, null=True, blank=True)
    estado = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "roles"
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self):
        """Representación legible del rol."""
        return self.nombre


class Permiso(models.Model):
    id_permiso = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.CharField(max_length=255, null=True, blank=True)
    estado = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "permisos"
        verbose_name = "Permiso"
        verbose_name_plural = "Permisos"

    def __str__(self):
        """Representación legible del permiso."""
        return self.nombre


class RolPermiso(models.Model):
    id_rol = models.ForeignKey(Rol, on_delete=models.CASCADE, db_column="id_rol")
    id_permiso = models.ForeignKey(Permiso, on_delete=models.CASCADE, db_column="id_permiso")
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rol_permiso"
        unique_together = ("id_rol", "id_permiso")
        verbose_name = "Rol-Permiso"
        verbose_name_plural = "Roles-Permisos"


# NUEVO (2do parcial - SaaS multitenant): la Empresa es el TENANT.
# Cada empresa contratante tiene sus propias sucursales, personal,
# productos, inventario, reservas y ventas. Una sucursal NO es un tenant:
# varias sucursales pertenecen a una misma empresa.
class Empresa(models.Model):
    id_empresa = models.AutoField(primary_key=True)
    # Identificador único público (no secuencial) para exponer en APIs y
    # en el token JWT sin revelar cuántas empresas existen.
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    nombre = models.CharField(max_length=150, unique=True)
    # Código corto y legible de la tienda (ej. "moda-andina"), útil para
    # URLs y para identificar la empresa sin exponer su id interno.
    slug = models.SlugField(max_length=60, unique=True)
    nit = models.CharField(max_length=30, null=True, blank=True)
    correo_contacto = models.CharField(max_length=150, null=True, blank=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    # NUEVO (SaaS): logotipo de la empresa, se muestra como su foto de perfil.
    # Se guarda la imagen en base64 ("data:image/png;base64,...") dentro de la
    # base de datos, porque el disco de Render no conserva archivos subidos.
    # La web la reduce a 256 px antes de enviarla (pesa pocos KB).
    logo = models.TextField(null=True, blank=True)
    # NUEVO (Fase 2 - reservas con anticipo): porcentaje del total que el
    # cliente paga al reservar cuando elige pagar con anticipo (por defecto
    # 50%). El resto lo paga al retirar en tienda o en el checkout.
    porcentaje_anticipo = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    estado = models.CharField(
        max_length=20,
        default="ACTIVA",
        choices=[
            ("ACTIVA", "Activa"),
            ("SUSPENDIDA", "Suspendida"),
            ("INACTIVA", "Inactiva"),
        ],
    )
    # Administrador responsable de la empresa (usuario con rol
    # ADMIN_EMPRESA). Se define como texto "Usuario" porque la clase
    # Usuario se declara más abajo en este mismo archivo.
    id_administrador = models.ForeignKey(
        "Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_administrador",
        related_name="empresas_administradas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "empresa"
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"

    def __str__(self):
        """Representación legible de la empresa."""
        return self.nombre


class Usuario(models.Model):
    id_usuario = models.AutoField(primary_key=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    correo = models.CharField(max_length=150, unique=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    password_hash = models.TextField()
    estado = models.CharField(
        max_length=20,
        default="ACTIVO",
        choices=[
            ("ACTIVO", "Activo"),
            ("INACTIVO", "Inactivo"),
            ("BLOQUEADO", "Bloqueado"),
        ],
    )
    ultimo_acceso = models.DateTimeField(null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    roles = models.ManyToManyField(Rol, through="UsuarioRol", related_name="usuarios")
    # NUEVO (SaaS): empresa a la que pertenece el usuario. Queda vacío para
    # SUPER_ADMIN (operador de la plataforma) y para CLIENTE (cuenta global
    # que puede comprar en cualquier empresa).
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="usuarios",
    )
    # NUEVO (SaaS): sucursal asignada a un empleado (encargado, cajero,
    # repartidor). Se referencia como "catalog.Sucursal" para no crear una
    # importación circular entre users_auth y catalog.
    id_sucursal = models.ForeignKey(
        "catalog.Sucursal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_sucursal",
        related_name="empleados",
    )

    class Meta:
        db_table = "usuarios"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    @property
    def is_authenticated(self):
        """Indica a DRF que el usuario está autenticado."""
        return True

    def clean(self):
        """Valida que la sucursal asignada pertenezca a la empresa del usuario."""
        if (
            self.id_sucursal_id
            and self.id_sucursal.id_empresa_id != self.id_empresa_id
        ):
            raise ValidationError(
                {"id_sucursal": "La sucursal no pertenece a la empresa del usuario."}
            )

    def __str__(self):
        """Representación legible del usuario."""
        return f"{self.nombres} {self.apellidos}"


class UsuarioRol(models.Model):
    id_usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, db_column="id_usuario")
    id_rol = models.ForeignKey(Rol, on_delete=models.CASCADE, db_column="id_rol")
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "usuario_rol"
        unique_together = ("id_usuario", "id_rol")
        verbose_name = "Usuario-Rol"
        verbose_name_plural = "Usuarios-Roles"


# NOTA (SaaS): el cliente es GLOBAL a la plataforma, no pertenece a una
# empresa. Con una sola cuenta puede comprar y reservar en cualquier
# empresa y sucursal. El aislamiento entre empresas se aplica sobre sus
# operaciones (carrito, orden, reserva, devolución), que sí guardan la
# empresa donde se realizaron.
class Cliente(models.Model):
    id_cliente = models.AutoField(primary_key=True)
    id_usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, db_column="id_usuario")
    direccion = models.CharField(max_length=250, null=True, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clientes"
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self):
        """Representación legible del cliente."""
        return f"Cliente: {self.id_usuario.nombres} {self.id_usuario.apellidos}"


class Bitacora(models.Model):
    id_bitacora = models.AutoField(primary_key=True)
    id_usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, db_column="id_usuario"
    )
    accion = models.CharField(max_length=50)
    tabla_afectada = models.CharField(max_length=100, null=True, blank=True)
    registro_id = models.IntegerField(null=True, blank=True)
    descripcion = models.TextField(null=True, blank=True)
    datos_anterior = models.JSONField(null=True, blank=True)
    datos_nuevo = models.JSONField(null=True, blank=True)
    direccion_ip = models.CharField(max_length=50, null=True, blank=True)
    fecha_evento = models.DateTimeField(auto_now_add=True)
    # NUEVO (SaaS): empresa del evento, para que cada empresa vea solo su
    # propia bitácora. Vacío en eventos del SUPER_ADMIN, de clientes o anónimos.
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_empresa",
        related_name="bitacoras",
    )

    class Meta:
        db_table = "bitacora"
        verbose_name = "Bitácora"
        verbose_name_plural = "Bitácoras"
        indexes = [
            models.Index(fields=["id_usuario"]),
            models.Index(fields=["fecha_evento"]),
            models.Index(fields=["tabla_afectada"]),
        ]

    def save(self, *args, **kwargs):
        """Hereda la empresa del usuario que generó el evento."""
        if self.id_empresa_id is None and self.id_usuario_id:
            self.id_empresa_id = self.id_usuario.id_empresa_id
        super().save(*args, **kwargs)

    def __str__(self):
        """Representación legible del evento de bitácora."""
        return f"{self.accion} - {self.tabla_afectada}"


# NUEVO (SaaS - paso 5): planes que la plataforma ofrece a las empresas
# (PLUS, PRO, ULTRA). Precios, periodos, límites y funcionalidades se
# configuran aquí (admin de Django o API del SUPER_ADMIN), no en el código.
# En los límites, vacío (null) significa ILIMITADO.
class PlanSuscripcion(models.Model):
    PERIODOS = [
        ("MENSUAL", "Mensual"),
        ("SEMESTRAL", "Semestral"),
        ("ANUAL", "Anual"),
    ]
    DIAS_POR_PERIODO = {"MENSUAL": 30, "SEMESTRAL": 182, "ANUAL": 365}
    id_plan = models.AutoField(primary_key=True)
    # Código fijo para identificar el plan en el código (PLUS, PRO, ULTRA).
    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=255, null=True, blank=True)
    # Precio del periodo completo en dólares (cobro simulado con Stripe test).
    precio_usd = models.DecimalField(max_digits=10, decimal_places=2)
    periodo = models.CharField(max_length=20, choices=PERIODOS, default="MENSUAL")
    max_sucursales = models.PositiveIntegerField(null=True, blank=True)
    max_personal = models.PositiveIntegerField(null=True, blank=True)
    max_productos = models.PositiveIntegerField(null=True, blank=True)
    delivery = models.BooleanField(default=False)
    vestidor_virtual = models.BooleanField(default=False)
    chatbot_clientes = models.BooleanField(default=False)
    # Asistente de gestión con IA y sus reportes (PDF/Excel/HTML).
    reportes_ia = models.BooleanField(default=False)
    # Reporte comparativo entre sucursales (sin IA, en el dashboard).
    comparativo_sucursales = models.BooleanField(default=True)
    modo_offline = models.BooleanField(default=True)
    estado = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "plan_suscripcion"
        verbose_name = "Plan de suscripción"
        verbose_name_plural = "Planes de suscripción"

    @property
    def dias_periodo(self):
        """Días que dura un periodo pagado del plan."""
        return self.DIAS_POR_PERIODO.get(self.periodo, 30)

    def __str__(self):
        """Representación legible del plan."""
        return self.nombre


# NUEVO (SaaS - paso 5): suscripción de cada empresa (una por empresa).
class Suscripcion(models.Model):
    id_suscripcion = models.AutoField(primary_key=True)
    id_empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        db_column="id_empresa",
        related_name="suscripcion",
    )
    id_plan = models.ForeignKey(
        PlanSuscripcion,
        on_delete=models.RESTRICT,
        db_column="id_plan",
        related_name="suscripciones",
    )
    fecha_inicio = models.DateField(default=timezone.localdate)
    # Se calcula sola (inicio + duración del periodo del plan) si se deja vacía.
    fecha_vencimiento = models.DateField(blank=True)
    estado = models.CharField(
        max_length=20,
        default="ACTIVA",
        choices=[
            ("ACTIVA", "Activa"),
            ("VENCIDA", "Vencida"),
            ("CANCELADA", "Cancelada"),
        ],
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "suscripcion"
        verbose_name = "Suscripción"
        verbose_name_plural = "Suscripciones"

    @property
    def vigente(self):
        """True si la suscripción está activa y no pasó su fecha de vencimiento."""
        return self.estado == "ACTIVA" and self.fecha_vencimiento >= timezone.localdate()

    @property
    def dias_restantes(self):
        """Días que faltan para el vencimiento (negativo si ya venció)."""
        return (self.fecha_vencimiento - timezone.localdate()).days

    def save(self, *args, **kwargs):
        """Si no se indicó vencimiento, dura un periodo del plan desde su inicio."""
        if self.fecha_vencimiento is None:
            self.fecha_vencimiento = self.fecha_inicio + timedelta(days=self.id_plan.dias_periodo)
        super().save(*args, **kwargs)

    def __str__(self):
        """Representación legible de la suscripción."""
        return f"{self.id_empresa} - {self.id_plan} (vence {self.fecha_vencimiento})"


# NUEVO (SaaS - paso 5): cada pago de renovación o cambio de plan. Se cobra
# con Stripe en modo test (sin dinero real) y queda como historial.
class PagoSuscripcion(models.Model):
    id_pago = models.AutoField(primary_key=True)
    id_empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        db_column="id_empresa",
        related_name="pagos_suscripcion",
    )
    id_plan = models.ForeignKey(
        PlanSuscripcion,
        on_delete=models.RESTRICT,
        db_column="id_plan",
        related_name="pagos",
    )
    id_usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="id_usuario",
        related_name="pagos_suscripcion",
    )
    monto_usd = models.DecimalField(max_digits=10, decimal_places=2)
    monto_bob = models.DecimalField(max_digits=10, decimal_places=2)
    tipo_cambio = models.DecimalField(max_digits=8, decimal_places=2)
    referencia_pago = models.CharField(max_length=100, unique=True)
    estado = models.CharField(
        max_length=20,
        default="PENDIENTE",
        choices=[
            ("PENDIENTE", "Pendiente"),
            ("PAGADO", "Pagado"),
            ("FALLIDO", "Fallido"),
        ],
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_pago = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pago_suscripcion"
        verbose_name = "Pago de suscripción"
        verbose_name_plural = "Pagos de suscripción"

    def __str__(self):
        """Representación legible del pago."""
        return f"Pago {self.id_pago} - {self.id_empresa} - {self.id_plan} ({self.estado})"