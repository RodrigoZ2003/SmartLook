# backend/apps/analytics/management/commands/generar_datos_ml.py
#
# NUEVO (Fase 3 - CU09): genera datos sintéticos para entrenar los modelos de
# Machine Learning.
#
# Crea compras SIMULADAS de los clientes REALES (cuentas de cliente activas),
# en las sucursales activas y prendas activas REALES de cada empresa, durante
# los últimos N meses (12 por defecto), con temporadas.
#
# Solo escribe en las tablas ml_compra_simulada y ml_detalle_compra_simulada.
# No toca ventas, pedidos, reservas, stock, clientes ni ningún dato real.
#
# Es idempotente: si la empresa ya tiene datos simulados, no hace nada; con
# --reemplazar borra SOLO los datos simulados de esa empresa y los vuelve a
# generar. Con la misma --semilla se obtienen siempre los mismos datos.
#
# Uso:
#   python manage.py generar_datos_ml
#   python manage.py generar_datos_ml --empresa moda-andina
#   python manage.py generar_datos_ml --empresa moda-andina --reemplazar

import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Q

from apps.analytics.models import CompraSimulada, DetalleCompraSimulada
from apps.catalog.models import Producto, ProductoVariante, Sucursal
from apps.users_auth.models import Cliente, Empresa

# Factor de ventas de cada mes (1 = mes normal): fin de año, invierno y
# carnaval venden más; enero, marzo y abril menos.
FACTOR_MES = {
    1: 0.85, 2: 1.00, 3: 0.90, 4: 0.90, 5: 1.00, 6: 1.15,
    7: 1.20, 8: 0.95, 9: 0.95, 10: 1.00, 11: 1.20, 12: 1.60,
}

# Meses en los que se vende más una prenda según su temporada.
MESES_INVIERNO = {5, 6, 7, 8}
MESES_VERANO = {10, 11, 12, 1, 2}

# Comportamiento de compra de cada perfil de cliente (oculto: el modelo de
# segmentación debe descubrir los grupos solo con los datos).
#   peso: proporción de clientes con ese perfil.
#   compras_mes: compras promedio por mes mientras el cliente está activo.
#   prendas: mínimo y máximo de prendas distintas por compra.
#   deja_de_comprar: días antes de hoy en que dejó de comprar (None = sigue).
PERFILES = {
    "VIP": {"peso": 0.10, "compras_mes": 2.5, "prendas": (2, 4), "deja_de_comprar": None},
    "LEAL": {"peso": 0.25, "compras_mes": 1.0, "prendas": (1, 3), "deja_de_comprar": None},
    "OCASIONAL": {"peso": 0.40, "compras_mes": 0.3, "prendas": (1, 2), "deja_de_comprar": None},
    "RIESGO": {"peso": 0.25, "compras_mes": 1.2, "prendas": (1, 3), "deja_de_comprar": (100, 200)},
}

# Con pocos clientes, el reparto al azar podía dejar un perfil sin nadie: se
# asegura al menos un cliente de cada perfil y el resto se reparte por peso.
ORDEN_PERFILES = ["VIP", "RIESGO", "LEAL", "OCASIONAL"]

# Peso de cada día de la semana (lunes=0 ... domingo=6): fin de semana más.
PESO_DIA = [0.8, 0.8, 0.9, 1.0, 1.2, 1.6, 1.3]

# Probabilidad de que el cliente compre en su sucursal habitual.
PROB_SUCURSAL_HABITUAL = 0.75

DOS_DECIMALES = Decimal("0.01")


def _restar_meses(fecha, meses):
    """Misma fecha (o el último día válido) N meses antes."""
    mes = fecha.month - meses
    anio = fecha.year
    while mes <= 0:
        mes += 12
        anio -= 1
    dia = min(fecha.day, 28)
    return date(anio, mes, dia)


def _repartir_perfiles(cantidad, azar):
    """Perfil de cada cliente: uno de cada perfil y el resto según su peso."""
    nombres = list(PERFILES)
    pesos = [PERFILES[p]["peso"] for p in nombres]
    lista = ORDEN_PERFILES[:cantidad]
    lista += azar.choices(nombres, weights=pesos, k=cantidad - len(lista))
    azar.shuffle(lista)
    return lista


def _factor_temporada(nombre_temporada, mes):
    """Factor extra de una prenda según su temporada y el mes."""
    nombre = (nombre_temporada or "").lower()
    if "invierno" in nombre or "otoño" in nombre or "otono" in nombre:
        return 1.8 if mes in MESES_INVIERNO else 0.6
    if "verano" in nombre or "primavera" in nombre:
        return 1.8 if mes in MESES_VERANO else 0.6
    return 1.0


class Command(BaseCommand):
    """Genera compras simuladas (solo tablas ML) para entrenar los modelos."""

    help = (
        "Genera compras simuladas de los clientes reales en las prendas y "
        "sucursales reales de cada empresa (solo tablas ml_*)."
    )

    def add_arguments(self, parser):
        """Argumentos del comando."""
        parser.add_argument(
            "--empresa", help="Slug o id de la empresa. Si se omite, todas las empresas activas."
        )
        parser.add_argument(
            "--meses", type=int, default=12, help="Meses de historial a simular (1 a 24, por defecto 12)."
        )
        parser.add_argument(
            "--semilla", type=int, default=2026, help="Semilla aleatoria (mismos datos con la misma semilla)."
        )
        parser.add_argument(
            "--reemplazar", action="store_true",
            help="Borra los datos simulados de la empresa y los vuelve a generar.",
        )

    def handle(self, *args, **opciones):
        """Genera los datos de cada empresa elegida."""
        meses = opciones["meses"]
        if meses < 1 or meses > 24:
            raise CommandError("--meses debe estar entre 1 y 24.")
        empresas = self._empresas(opciones.get("empresa"))
        clientes = list(
            Cliente.objects.filter(id_usuario__estado="ACTIVO").order_by("id_cliente")
        )
        if not clientes:
            raise CommandError("No hay clientes activos: no se puede simular compras.")
        hoy = date.today()
        desde = _restar_meses(hoy, meses)
        for empresa in empresas:
            existentes = CompraSimulada.objects.filter(id_empresa=empresa)
            if existentes.exists() and not opciones["reemplazar"]:
                self.stdout.write(self.style.WARNING(
                    f"{empresa.nombre}: ya tiene datos simulados (usa --reemplazar para regenerarlos)."
                ))
                continue
            with transaction.atomic():
                borradas = existentes.count()
                existentes.delete()
                resumen = self._generar_empresa(
                    empresa, clientes, desde, hoy, opciones["semilla"]
                )
            if resumen is None:
                continue
            texto_borradas = f" (reemplazó {borradas})" if borradas else ""
            self.stdout.write(self.style.SUCCESS(
                f"{empresa.nombre}: {resumen['compras']} compras simuladas{texto_borradas}, "
                f"{resumen['detalles']} líneas, {resumen['unidades']} prendas vendidas, "
                f"{resumen['clientes']} clientes, {resumen['productos']} prendas del catálogo, "
                f"{resumen['sucursales']} sucursales, del {desde:%d/%m/%Y} al {hoy:%d/%m/%Y}."
            ))

    def _empresas(self, filtro):
        """Empresas a procesar según --empresa."""
        if not filtro:
            return list(Empresa.objects.filter(estado="ACTIVA").order_by("nombre"))
        condicion = Q(slug=filtro)
        if str(filtro).isdigit():
            condicion |= Q(id_empresa=int(filtro))
        empresa = Empresa.objects.filter(condicion).first()
        if empresa is None:
            raise CommandError(f"No existe la empresa '{filtro}'.")
        return [empresa]

    def _catalogo(self, empresa):
        """Prendas activas de la empresa con su precio promedio y temporada."""
        precios = dict(
            ProductoVariante.objects.filter(id_producto__id_empresa=empresa)
            .exclude(estado="INACTIVO")
            .values("id_producto")
            .annotate(precio=Avg("precio"))
            .values_list("id_producto", "precio")
        )
        productos = (
            Producto.objects.filter(id_empresa=empresa, estado="ACTIVO")
            .select_related("id_temporada")
            .order_by("id_producto")
        )
        catalogo = []
        for producto in productos:
            precio = precios.get(producto.id_producto)
            if not precio:
                continue
            temporada = producto.id_temporada.nombre if producto.id_temporada else ""
            catalogo.append({
                "id": producto.id_producto,
                "precio": Decimal(precio).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP),
                "temporada": temporada,
            })
        return catalogo

    def _generar_empresa(self, empresa, clientes, desde, hoy, semilla):
        """Crea las compras simuladas de una empresa y devuelve un resumen."""
        sucursales = list(
            Sucursal.objects.filter(id_empresa=empresa, estado="ACTIVA")
            .order_by("id_sucursal")
            .values_list("id_sucursal", flat=True)
        )
        catalogo = self._catalogo(empresa)
        if not sucursales or not catalogo:
            self.stdout.write(self.style.WARNING(
                f"{empresa.nombre}: sin sucursales activas o sin prendas con precio; se omite."
            ))
            return None

        azar = random.Random(semilla * 1000 + empresa.id_empresa)
        np_azar = np.random.default_rng(semilla * 1000 + empresa.id_empresa)
        # Popularidad de cada prenda: unas pocas se venden mucho más que el resto.
        popularidad = [azar.paretovariate(1.5) for _ in catalogo]
        pesos_mes = {}
        for mes in range(1, 13):
            pesos_mes[mes] = [
                popularidad[i] * _factor_temporada(prenda["temporada"], mes)
                for i, prenda in enumerate(catalogo)
            ]
        perfiles = _repartir_perfiles(len(clientes), azar)

        compras = []
        lineas_por_compra = []
        for cliente, nombre_perfil in zip(clientes, perfiles):
            perfil = PERFILES[nombre_perfil]
            sucursal_habitual = azar.choice(sucursales)
            fin = hoy - timedelta(days=1)
            if perfil["deja_de_comprar"]:
                fin = hoy - timedelta(days=azar.randint(*perfil["deja_de_comprar"]))
            # Cada cliente compra un poco más o menos que el promedio de su perfil.
            ritmo = perfil["compras_mes"] * azar.uniform(0.7, 1.3)
            semana = desde - timedelta(days=desde.weekday())
            while semana <= fin:
                tasa = ritmo / 4.345 * FACTOR_MES[semana.month]
                for _ in range(int(np_azar.poisson(tasa))):
                    dia = azar.choices(range(7), weights=PESO_DIA)[0]
                    fecha = semana + timedelta(days=dia)
                    if fecha < desde or fecha > fin:
                        continue
                    sucursal = sucursal_habitual
                    if azar.random() > PROB_SUCURSAL_HABITUAL:
                        sucursal = azar.choice(sucursales)
                    cantidad_prendas = min(azar.randint(*perfil["prendas"]), len(catalogo))
                    elegidas = set()
                    while len(elegidas) < cantidad_prendas:
                        elegidas.add(azar.choices(range(len(catalogo)), weights=pesos_mes[fecha.month])[0])
                    lineas = []
                    total = Decimal("0")
                    for indice in sorted(elegidas):
                        prenda = catalogo[indice]
                        cantidad = 1 if azar.random() < 0.8 else 2
                        subtotal = prenda["precio"] * cantidad
                        total += subtotal
                        lineas.append((prenda["id"], cantidad, prenda["precio"], subtotal))
                    compras.append(CompraSimulada(
                        id_empresa=empresa,
                        id_sucursal_id=sucursal,
                        id_cliente=cliente,
                        fecha=fecha,
                        total=total,
                    ))
                    lineas_por_compra.append(lineas)
                semana += timedelta(days=7)

        creadas = CompraSimulada.objects.bulk_create(compras, batch_size=1000)
        detalles = []
        for compra, lineas in zip(creadas, lineas_por_compra):
            for id_producto, cantidad, precio, subtotal in lineas:
                detalles.append(DetalleCompraSimulada(
                    id_compra=compra,
                    id_producto_id=id_producto,
                    cantidad=cantidad,
                    precio_unitario=precio,
                    subtotal=subtotal,
                ))
        DetalleCompraSimulada.objects.bulk_create(detalles, batch_size=2000)
        return {
            "compras": len(creadas),
            "detalles": len(detalles),
            "unidades": sum(d.cantidad for d in detalles),
            "clientes": len({c.id_cliente_id for c in creadas}),
            "productos": len(catalogo),
            "sucursales": len(sucursales),
        }