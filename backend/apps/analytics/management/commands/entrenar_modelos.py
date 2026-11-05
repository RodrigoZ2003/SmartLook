# backend/apps/analytics/management/commands/entrenar_modelos.py
#
# NUEVO (Fase 3 - CU09): entrena los modelos de Machine Learning (demanda y
# segmentación) de una empresa o de todas las empresas activas. Es lo mismo
# que hace el botón "Reentrenar" del dashboard de Analítica.
#
# Uso:
#   python manage.py entrenar_modelos
#   python manage.py entrenar_modelos --empresa moda-andina

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.analytics.servicio_ml import entrenar_empresa
from apps.users_auth.models import Empresa


class Command(BaseCommand):
    """Entrena los modelos de ML por empresa."""

    help = "Entrena la predicción de demanda (3, 5 y 12 meses) y la segmentación de clientes."

    def add_arguments(self, parser):
        """Argumentos del comando."""
        parser.add_argument(
            "--empresa", help="Slug o id de la empresa. Si se omite, todas las empresas activas."
        )

    def handle(self, *args, **opciones):
        """Entrena cada empresa elegida y muestra sus métricas."""
        filtro = opciones.get("empresa")
        if filtro:
            condicion = Q(slug=filtro)
            if str(filtro).isdigit():
                condicion |= Q(id_empresa=int(filtro))
            empresas = list(Empresa.objects.filter(condicion))
            if not empresas:
                raise CommandError(f"No existe la empresa '{filtro}'.")
        else:
            empresas = list(Empresa.objects.filter(estado="ACTIVA").order_by("nombre"))
        for empresa in empresas:
            resumen = entrenar_empresa(empresa)
            self.stdout.write(self.style.SUCCESS(f"\n{resumen['empresa']} (corrida {resumen['corrida']})"))
            for d in resumen["demanda"]:
                if d["aviso"]:
                    self.stdout.write(f"  Demanda {d['ventana_meses']} meses: {d['aviso']}")
                    continue
                marca = "  <- vigente" if d["vigente"] else ""
                self.stdout.write(
                    f"  Demanda {d['ventana_meses']} meses: MAE={d['mae']} RMSE={d['rmse']} "
                    f"R2={d['r2']} (línea base MAE={d['mae_linea_base']}){marca}"
                )
            self.stdout.write(f"  Predicciones guardadas (próximas 4 semanas): {resumen['predicciones']}")
            seg = resumen["segmentacion"]
            if seg["k"] is None:
                self.stdout.write(f"  Segmentación: {seg['aviso']}")
                continue
            self.stdout.write(
                f"  Segmentación: {seg['clientes']} clientes, k={seg['k']}, silhouette por k={seg['silhouette']}"
            )
            for grupo in seg["resumen"]:
                self.stdout.write(
                    f"    {grupo['nombre']}: {grupo['clientes']} clientes, recencia media "
                    f"{grupo['recencia_media']} días, frecuencia {grupo['frecuencia_media']}, "
                    f"monto medio Bs {grupo['monto_medio']}"
                )
            if seg["aviso"]:
                self.stdout.write(self.style.WARNING(f"  Aviso: {seg['aviso']}"))