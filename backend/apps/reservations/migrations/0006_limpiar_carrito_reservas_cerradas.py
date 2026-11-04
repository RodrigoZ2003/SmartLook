"""Quita de los carritos activos las prendas de reservas ya cerradas.

Corrige los carritos que quedaron con prendas de reservas COMPLETADAS,
CANCELADAS o VENCIDAS (por ejemplo, cobradas en el Punto de Venta), que no
se podían pagar ni quitar. Desde ahora lo hace la señal de reservations.
"""
from django.db import migrations

ESTADOS_CERRADOS = ("COMPLETADA", "CANCELADA", "VENCIDA")


def limpiar(apps, schema_editor):
    """Borra los CartItem de carritos ACTIVO vinculados a reservas cerradas."""
    CartItem = apps.get_model("sales", "CartItem")
    CartItem.objects.filter(
        id_reserva_item__id_reserva__estado__in=ESTADOS_CERRADOS,
        id_carrito__estado="ACTIVO",
    ).delete()


class Migration(migrations.Migration):
    """Migración de datos (no cambia tablas)."""

    dependencies = [
        ("reservations", "0005_reserva_anticipo"),
        ("sales", "0005_cartitem_id_reserva_item_possaleitem_id_reserva_item"),
    ]

    operations = [
        migrations.RunPython(limpiar, migrations.RunPython.noop),
    ]