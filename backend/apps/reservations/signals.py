"""Señales de las reservas.

NUEVO (Fase 2 - corrección): cuando una reserva se cierra (COMPLETADA,
CANCELADA o VENCIDA) sus prendas se quitan de los carritos activos del
cliente. Antes, al cobrar el saldo en el Punto de Venta (o completarla a
mano) la prenda quedaba en el carrito: no se podía pagar ("la reserva no
está confirmada") ni quitar (estaba pagada al reservar).
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FittingReservation

ESTADOS_CERRADOS = ("COMPLETADA", "CANCELADA", "VENCIDA")


@receiver(post_save, sender=FittingReservation)
def quitar_del_carrito_al_cerrar(sender, instance, **kwargs):
    """Borra de los carritos ACTIVO las prendas de una reserva ya cerrada."""
    if instance.estado not in ESTADOS_CERRADOS:
        return
    from apps.sales.models import CartItem

    CartItem.objects.filter(
        id_reserva_item__id_reserva=instance,
        id_carrito__estado="ACTIVO",
    ).delete()