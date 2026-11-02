# backend/apps/reservations/management/commands/vencer_reservas.py
"""Vence las reservas cuyo plazo pasó (Fase 2 - reservas con anticipo).

Render gratis no tiene tareas programadas, así que el vencimiento también se
procesa al usar el sistema (lista de reservas, login, POS). Este comando lo
hace a mano para la demo:

    python manage.py vencer_reservas
    python manage.py vencer_reservas --empresa fashionstore
"""
from django.core.management.base import BaseCommand, CommandError

from apps.reservations.pagos import ReservaPagoService
from apps.users_auth.models import Empresa


class Command(BaseCommand):
    help = "Vence las reservas sin pagar a tiempo o sin retirar a la semana (con reembolso menos el 10%)."

    def add_arguments(self, parser):
        """Opción --empresa <slug> para procesar una sola empresa."""
        parser.add_argument("--empresa", help="Slug de la empresa (por defecto, todas).")

    def handle(self, *args, **opciones):
        """Procesa los vencimientos e informa cuántas reservas vencieron."""
        empresa_id = None
        if opciones.get("empresa"):
            empresa = Empresa.objects.filter(slug=opciones["empresa"]).first()
            if empresa is None:
                raise CommandError(f"No existe la empresa '{opciones['empresa']}'.")
            empresa_id = empresa.id_empresa
        vencidas = ReservaPagoService.procesar_vencimientos(empresa_id=empresa_id)
        self.stdout.write(self.style.SUCCESS(f"Reservas vencidas: {vencidas}"))