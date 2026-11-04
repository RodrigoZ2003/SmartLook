# backend/apps/users_auth/migrations/0012_notificacion.py
# NUEVO (Fase 2 - CU16): centro de notificaciones.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users_auth", "0011_empresa_porcentaje_anticipo"),
    ]

    operations = [
        migrations.CreateModel(
            name="Notificacion",
            fields=[
                ("id_notificacion", models.AutoField(primary_key=True, serialize=False)),
                ("tipo", models.CharField(choices=[
                    ("RESERVA", "Reserva"),
                    ("PEDIDO", "Pedido"),
                    ("DELIVERY", "Delivery"),
                    ("DEVOLUCION", "Devolución"),
                    ("CAMBIO", "Cambio de prenda"),
                    ("CONFLICTO", "Venta en conflicto"),
                ], max_length=20)),
                ("titulo", models.CharField(max_length=150)),
                ("mensaje", models.CharField(max_length=500)),
                ("enlace", models.CharField(blank=True, max_length=200, null=True)),
                ("clave", models.CharField(blank=True, max_length=120, null=True)),
                ("leida", models.BooleanField(default=False)),
                ("fecha_creacion", models.DateTimeField(auto_now_add=True)),
                ("fecha_lectura", models.DateTimeField(blank=True, null=True)),
                ("id_empresa", models.ForeignKey(
                    blank=True,
                    db_column="id_empresa",
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="notificaciones",
                    to="users_auth.empresa",
                )),
                ("id_usuario", models.ForeignKey(
                    db_column="id_usuario",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="notificaciones",
                    to="users_auth.usuario",
                )),
            ],
            options={
                "verbose_name": "Notificación",
                "verbose_name_plural": "Notificaciones",
                "db_table": "notificacion",
                "indexes": [
                    models.Index(fields=["id_usuario", "leida"], name="notif_usuario_leida_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("clave__isnull", False)),
                        fields=("id_usuario", "clave"),
                        name="notif_usuario_clave_uniq",
                    ),
                ],
            },
        ),
    ]