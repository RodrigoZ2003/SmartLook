# apps/bi_reports/views.py
#
# Endpoint de KPIs del Dashboard, consumido tanto por la web como por mobile.
# SaaS: cada empresa ve solo sus indicadores; el SUPER_ADMIN ve los de toda
# la plataforma (o los de una empresa con ?empresa=<slug>).
# MODIFICADO (Fase 2): las ventas POS anuladas (conflicto resuelto devolviendo
# el efectivo, CU08) no cuentan, y se resta lo reembolsado en devoluciones
# completadas (CU12). Las reservas abiertas incluyen las pendientes de pago y
# las confirmadas (reservas con anticipo); los pedidos cuentan solo si se pagaron.

from datetime import date

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response

from common.permissions import IsAdminEmpresa, IsEncargadoSucursal
from common.tenancy import alcance_de, filtrar_queryset
from apps.users_auth.suscripciones import requiere_funcion
from apps.users_auth.models import Usuario
from apps.catalog.models import Producto, Sucursal, Proveedor
from apps.inventory.models import StockItem
from apps.sales.models import Devolucion, PosSale, Order
from apps.reservations.models import FittingReservation

# NUEVO (Fase 2): estados que cuentan en los indicadores.
ESTADOS_PEDIDO_PAGADO = ["PAGADA", "ENVIADA", "ENTREGADA"]
ESTADOS_RESERVA_ABIERTA = ["PENDIENTE", "PENDIENTE_PAGO", "CONFIRMADA"]

class DashboardKpisView(APIView):
    """
    KPIs agregados para la pantalla de Dashboard (web y mobile).
    Solo admin/staff (no clientes) - mismos datos para ambas plataformas,
    un solo lugar de cálculo.
    """
    permission_classes = [IsAdminEmpresa]

    def _total_clientes(self, request):
        """Clientes activos: todos (SUPER_ADMIN) o los que compraron/reservaron en la empresa.

        Los clientes son globales a la plataforma, así que una empresa cuenta
        como suyos a los que tienen al menos un pedido o una reserva en ella.
        """
        clientes = Usuario.objects.filter(roles__nombre="CLIENTE", estado="ACTIVO")
        alcance = alcance_de(request)
        if alcance.super_admin and not alcance.slug_filtro:
            return clientes.count()
        if alcance.super_admin:
            campo, valor = "id_empresa__slug", alcance.slug_filtro
        elif alcance.empresa_id is None:
            return 0
        else:
            campo, valor = "id_empresa", alcance.empresa_id
        return clientes.filter(
            Q(**{f"cliente__order__{campo}": valor})
            | Q(**{f"cliente__fittingreservation__{campo}": valor})
        ).distinct().count()

    def get(self, request):
        """Calcula los indicadores dentro del alcance de empresa del usuario."""
        total_clientes = self._total_clientes(request)

        productos = filtrar_queryset(Producto.objects.filter(estado="ACTIVO"), request)
        sucursales = filtrar_queryset(Sucursal.objects.filter(estado="ACTIVA"), request)
        proveedores = filtrar_queryset(Proveedor.objects.filter(estado="ACTIVO"), request)
        stock = filtrar_queryset(StockItem.objects.filter(estado=True), request)
        # MODIFICADO (Fase 2): sin ventas anuladas ni pedidos sin pagar.
        ventas_pos = filtrar_queryset(PosSale.objects.exclude(estado="ANULADA"), request)
        ordenes = filtrar_queryset(Order.objects.filter(estado__in=ESTADOS_PEDIDO_PAGADO), request)
        devoluciones_pos = filtrar_queryset(
            Devolucion.objects.filter(estado="COMPLETADA", id_venta__isnull=False), request
        )
        reservas = filtrar_queryset(FittingReservation.objects.all(), request)

        stock_total = stock.aggregate(total=Sum("cantidad"))["total"] or 0

        # Se compara contra un umbral fijo (5) en vez de comparar la
        # cantidad contra el stock_minimo de cada item (eso requeriría
        # F() para comparar dos columnas del mismo modelo) - se mantiene
        # simple para esta primera versión del dashboard.
        productos_stock_bajo = stock.filter(cantidad__lte=5).count()

        monto_bruto = ventas_pos.aggregate(total=Sum("total"))["total"] or 0
        monto_devoluciones = devoluciones_pos.aggregate(total=Sum("monto_reembolso"))["total"] or 0
        monto_total_ventas = monto_bruto - monto_devoluciones

        return Response({
            "total_clientes": total_clientes,
            "total_productos": productos.count(),
            "total_sucursales": sucursales.count(),
            "total_proveedores": proveedores.count(),
            "stock_total": stock_total,
            "productos_stock_bajo": productos_stock_bajo,
            "total_ventas_pos": ventas_pos.count(),
            "monto_total_ventas": str(monto_total_ventas),
            # NUEVO (Fase 2): lo devuelto en caja por devoluciones (ya restado arriba).
            "monto_devoluciones": str(monto_devoluciones),
            "total_ordenes": ordenes.count(),
            "reservas_pendientes": reservas.filter(estado__in=ESTADOS_RESERVA_ABIERTA).count(),
        })

def _fecha_param(request, nombre, defecto):
    """Lee una fecha AAAA-MM-DD de los parámetros de la URL."""
    valor = request.query_params.get(nombre)
    if not valor:
        return defecto
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({nombre: "Usa el formato AAAA-MM-DD."})

class ComparativoSucursalesView(APIView):
    """NUEVO (SaaS - paso 5): reporte comparativo entre sucursales (sin IA).

    Disponible en los 3 planes (PLUS, PRO y ULTRA). Compara, para cada
    sucursal de la empresa, las ventas en caja, las órdenes web pagadas, las
    reservas y el stock, en un periodo (?desde=AAAA-MM-DD&hasta=AAAA-MM-DD,
    por defecto el mes actual). El SUPER_ADMIN puede elegir ?empresa=<slug>.
    """

    permission_classes = [IsEncargadoSucursal, requiere_funcion("comparativo_sucursales")]

    def get(self, request):
        """Devuelve una fila por sucursal con sus indicadores del periodo."""
        hoy = timezone.localdate()
        desde = _fecha_param(request, "desde", hoy.replace(day=1))
        hasta = _fecha_param(request, "hasta", hoy)
        if desde > hasta:
            desde, hasta = hasta, desde

        sucursales = filtrar_queryset(
            Sucursal.objects.select_related("id_empresa").order_by("id_empresa__nombre", "nombre"),
            request,
        )
        filas = []
        for sucursal in sucursales:
            # MODIFICADO (Fase 2): sin ventas anuladas y restando los reembolsos.
            pos = PosSale.objects.filter(
                id_sucursal=sucursal, fecha_venta__date__range=(desde, hasta)
            ).exclude(estado="ANULADA").aggregate(cantidad=Count("id_venta"), total=Sum("total"))
            web = Order.objects.filter(
                id_sucursal=sucursal,
                estado__in=ESTADOS_PEDIDO_PAGADO,
                fecha_creacion__date__range=(desde, hasta),
            ).aggregate(cantidad=Count("id_orden"), total=Sum("total"))
            devuelto = Devolucion.objects.filter(
                id_sucursal=sucursal,
                estado="COMPLETADA",
                fecha_completado__date__range=(desde, hasta),
            ).aggregate(total=Sum("monto_reembolso"))["total"] or 0
            reservas = FittingReservation.objects.filter(
                id_sucursal=sucursal, fecha_reserva__range=(desde, hasta)
            ).count()
            stock = StockItem.objects.filter(id_sucursal=sucursal, estado=True).aggregate(
                total=Sum("cantidad")
            )["total"] or 0
            total_pos = pos["total"] or 0
            total_web = web["total"] or 0
            filas.append({
                "id_sucursal": sucursal.id_sucursal,
                "sucursal": sucursal.nombre,
                "empresa": sucursal.id_empresa.nombre if sucursal.id_empresa else None,
                "ventas_pos": pos["cantidad"],
                "total_pos": str(total_pos),
                "ordenes_web": web["cantidad"],
                "total_web": str(total_web),
                "total_devoluciones": str(devuelto),
                "total_vendido": str(total_pos + total_web - devuelto),
                "reservas": reservas,
                "stock_unidades": stock,
            })
        filas.sort(key=lambda f: float(f["total_vendido"]), reverse=True)
        return Response({
            "desde": str(desde),
            "hasta": str(hasta),
            "sucursales": filas,
        })