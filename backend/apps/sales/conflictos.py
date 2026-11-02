"""CU08 - Conflictos de las ventas POS hechas sin conexión (Fase 2).

Una venta hecha sin conexión se registra SIEMPRE con lo que el cajero
cobró en la tienda. Al sincronizar se compara con el servidor:

- Conflicto de PRECIO: el precio cobrado sin conexión no es el precio
  actual de la prenda. La venta se registra con el precio cobrado y queda
  EN_CONFLICTO, con la diferencia por prenda.
- Conflicto de STOCK: el servidor ya no tiene unidades suficientes (por
  ejemplo, otra caja vendió la última unidad). La venta se registra igual
  (el efectivo ya se recibió), pero esas prendas NO descuentan stock hasta
  que el personal resuelva el conflicto.

Resolución (la vista valida que sea ADMIN_EMPRESA, ENCARGADO_SUCURSAL o
SUPER_ADMIN):
- CONFIRMAR: la venta queda válida. Las prendas sin stock ajustan el
  inventario a max(0, stock actual - cantidad vendida), porque la prenda sí
  existía en la tienda. Si solo hubo diferencia de precio, equivale a
  marcarla como revisada.
- DEVOLVER: se devuelve el efectivo al cliente. La venta queda ANULADA, las
  prendas que sí descontaron stock vuelven al inventario y se genera la
  nota de devolución con el monto devuelto.
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ProductoVariante
from apps.inventory.models import StockItem
from apps.inventory.services import StockService
from common.utils import log_audit

from .models import NotaDevolucionPos, PosSale, PosSaleItem, SyncOperacion

CENTAVOS = Decimal("0.01")
ACCIONES = ("CONFIRMAR", "DEVOLVER")


def leer_precio(valor):
    """Precio enviado por el dispositivo como Decimal de 2 decimales (None si no vino)."""
    if valor is None or valor == "":
        return None
    try:
        precio = Decimal(str(valor)).quantize(CENTAVOS)
    except (InvalidOperation, ValueError):
        raise ValueError("Precio de prenda inválido.")
    if precio < 0:
        raise ValueError("El precio de una prenda no puede ser negativo.")
    return precio


def tipo_de_conflicto(detalle):
    """PRECIO, STOCK o PRECIO_Y_STOCK según los conflictos detectados."""
    tipos = {conflicto["tipo"] for conflicto in detalle}
    if not tipos:
        return None
    if tipos == {"PRECIO", "STOCK"}:
        return "PRECIO_Y_STOCK"
    return tipos.pop()


def resumen_conflicto(detalle):
    """Texto corto del conflicto para el mensaje de la operación."""
    precios = [c for c in detalle if c["tipo"] == "PRECIO"]
    sin_stock = [c for c in detalle if c["tipo"] == "STOCK"]
    partes = []
    if precios:
        diferencia = sum(Decimal(c["diferencia"]) for c in precios)
        partes.append(
            f"precio distinto en {len(precios)} prenda(s) (diferencia Bs {diferencia})"
        )
    if sin_stock:
        partes.append(f"sin stock suficiente en {len(sin_stock)} prenda(s)")
    return "Venta registrada en conflicto: " + " y ".join(partes) + "."


class ConflictoService:
    """Registra las ventas sin conexión detectando conflictos y los resuelve."""

    @staticmethod
    @transaction.atomic
    def registrar_venta_offline(usuario, sucursal, items_data, metodo_pago,
                                cliente=None, fecha_venta=None):
        """Registra una venta POS hecha sin conexión.

        items_data: lista de {"id_variante", "cantidad", "precio_unitario"}
        (precio_unitario es el cobrado sin conexión, Decimal o None) o
        {"id_reserva_item", "cantidad": 1} para prendas de una reserva.
        Lanza ValueError si los datos no son válidos (la operación se
        rechaza). Devuelve (venta, detalle_conflicto); el detalle vacío
        significa que la venta se registró sin conflictos.
        """
        from apps.reservations.models import FittingReservationItem
        from apps.reservations.services import ReservationStockService

        if not items_data:
            raise ValueError("La venta debe tener al menos una prenda.")

        # 1) Valida las prendas (deben ser de la empresa de la sucursal).
        lineas = []
        ids_variantes = set()
        for item in items_data:
            id_reserva_item = item.get("id_reserva_item")
            if id_reserva_item:
                try:
                    reserva_item = FittingReservationItem.objects.select_related(
                        "id_variante", "id_reserva"
                    ).get(pk=id_reserva_item, estado="PENDIENTE")
                except FittingReservationItem.DoesNotExist:
                    raise ValueError(
                        f"La prenda reservada con id {id_reserva_item} no existe o ya se resolvió."
                    )
                if reserva_item.id_reserva.id_sucursal_id != sucursal.id_sucursal:
                    raise ValueError(
                        f"La reserva #{reserva_item.id_reserva_id} no corresponde a {sucursal.nombre}."
                    )
                lineas.append({
                    "variante": reserva_item.id_variante,
                    "cantidad": 1,
                    "precio": reserva_item.id_variante.precio,
                    "precio_offline": None,
                    "reserva_item": reserva_item,
                    "sin_stock": False,
                })
                continue
            try:
                variante = ProductoVariante.objects.select_related("id_producto").get(
                    pk=item["id_variante"],
                    id_producto__id_empresa_id=sucursal.id_empresa_id,
                )
            except ProductoVariante.DoesNotExist:
                raise ValueError(f"La prenda con id {item['id_variante']} no existe.")
            precio_offline = item.get("precio_unitario")
            lineas.append({
                "variante": variante,
                "cantidad": item["cantidad"],
                "precio": precio_offline if precio_offline is not None else variante.precio,
                "precio_offline": precio_offline,
                "reserva_item": None,
                "sin_stock": False,
            })
            ids_variantes.add(variante.id_variante)

        # 2) Bloquea el stock de esas prendas: si dos cajas sincronizan la
        #    última unidad al mismo tiempo, la segunda espera y ve el stock real.
        disponibles = {
            stock.id_variante_id: stock.cantidad
            for stock in StockItem.objects.select_for_update().filter(
                id_sucursal=sucursal, id_variante_id__in=ids_variantes
            )
        }

        # 3) Detecta los conflictos de precio y de stock.
        detalle = []
        for linea in lineas:
            if linea["reserva_item"] is not None:
                continue
            variante = linea["variante"]
            cantidad = linea["cantidad"]
            precio_offline = linea["precio_offline"]
            if precio_offline is not None and precio_offline != variante.precio:
                detalle.append({
                    "tipo": "PRECIO",
                    "id_variante": variante.id_variante,
                    "prenda": str(variante),
                    "cantidad": cantidad,
                    "precio_offline": str(precio_offline),
                    "precio_servidor": str(variante.precio),
                    "diferencia": str((precio_offline - variante.precio) * cantidad),
                })
            disponible = disponibles.get(variante.id_variante, 0)
            if disponible >= cantidad:
                disponibles[variante.id_variante] = disponible - cantidad
            else:
                linea["sin_stock"] = True
                detalle.append({
                    "tipo": "STOCK",
                    "id_variante": variante.id_variante,
                    "prenda": str(variante),
                    "cantidad": cantidad,
                    "stock_disponible": disponible,
                })

        # 4) Registra la venta con lo cobrado sin conexión.
        total = sum(linea["precio"] * linea["cantidad"] for linea in lineas)
        venta = PosSale.objects.create(
            id_sucursal=sucursal,
            id_usuario=usuario,
            total=total,
            metodo_pago=metodo_pago,
            id_cliente=cliente,
            estado="EN_CONFLICTO" if detalle else "REGISTRADA",
        )
        items_reserva_comprados = []
        for linea in lineas:
            variante = linea["variante"]
            PosSaleItem.objects.create(
                id_venta=venta,
                id_variante=variante,
                cantidad=linea["cantidad"],
                precio_unitario=linea["precio"],
                subtotal=linea["precio"] * linea["cantidad"],
                id_reserva_item=linea["reserva_item"],
                precio_lista=variante.precio,
                sin_stock=linea["sin_stock"],
            )
            if linea["reserva_item"] is not None:
                items_reserva_comprados.append(linea["reserva_item"])
            elif not linea["sin_stock"]:
                StockService.registrar_movimiento(
                    sucursal=sucursal,
                    variante=variante,
                    usuario=usuario,
                    tipo="SALIDA",
                    cantidad=linea["cantidad"],
                    motivo=f"Venta presencial sin conexión - Venta #{venta.id_venta}",
                )
        if items_reserva_comprados:
            ReservationStockService.resolver_reserva_por_venta(items_reserva_comprados, usuario)

        # La venta conserva la hora en que se hizo sin conexión (reportes correctos).
        if fecha_venta:
            PosSale.objects.filter(pk=venta.pk).update(fecha_venta=fecha_venta)
            venta.fecha_venta = fecha_venta

        estado_texto = " (en conflicto)" if detalle else ""
        log_audit(
            usuario=usuario,
            accion="VENTA_PRESENCIAL_OFFLINE",
            tabla_afectada="pos_sale",
            registro_id=venta.id_venta,
            descripcion=(
                f"{usuario.nombres} {usuario.apellidos} sincronizó una venta presencial "
                f"hecha sin conexión en {sucursal.nombre} - Venta #{venta.id_venta} - "
                f"Bs {venta.total} ({metodo_pago}){estado_texto}"
            ),
        )
        return venta, detalle

    @staticmethod
    @transaction.atomic
    def resolver(id_operacion, usuario, accion, nota=None):
        """Resuelve una operación EN_CONFLICTO (CONFIRMAR o DEVOLVER).

        Lanza ValueError si la acción no es válida o la operación ya se
        resolvió. Devuelve la operación actualizada.
        """
        if accion not in ACCIONES:
            raise ValueError("Acción inválida: usa CONFIRMAR o DEVOLVER.")
        try:
            operacion = SyncOperacion.objects.select_for_update().get(pk=id_operacion)
        except SyncOperacion.DoesNotExist:
            raise ValueError("Operación no encontrada.")
        if operacion.estado != "EN_CONFLICTO":
            raise ValueError("Solo se pueden resolver operaciones en conflicto.")
        if operacion.fecha_revision is not None:
            raise ValueError("Esta operación ya fue resuelta.")
        if operacion.id_venta_id is None:
            raise ValueError("La operación no tiene una venta asociada.")

        venta = PosSale.objects.select_for_update(of=("self",)).select_related(
            "id_sucursal"
        ).get(pk=operacion.id_venta_id)
        sucursal = venta.id_sucursal
        nota = (nota or "").strip()[:255] or None
        items = list(venta.items.select_related("id_variante__id_producto"))

        if accion == "CONFIRMAR":
            for item in items:
                if not item.sin_stock:
                    continue
                actual = StockItem.objects.select_for_update().filter(
                    id_sucursal=sucursal, id_variante=item.id_variante
                ).values_list("cantidad", flat=True).first() or 0
                nuevo = max(0, actual - item.cantidad)
                StockService.registrar_movimiento(
                    sucursal=sucursal,
                    variante=item.id_variante,
                    usuario=usuario,
                    tipo="AJUSTE",
                    cantidad=nuevo,
                    motivo=(
                        f"Conflicto sin conexión confirmado - Venta #{venta.id_venta} "
                        f"(stock {actual} -> {nuevo})"
                    ),
                )
            venta.estado = "REGISTRADA"
            resolucion = "CONFIRMADA"
            texto = "confirmó"
        else:
            for item in items:
                if item.sin_stock:
                    continue
                StockService.registrar_movimiento(
                    sucursal=sucursal,
                    variante=item.id_variante,
                    usuario=usuario,
                    tipo="ENTRADA",
                    cantidad=item.cantidad,
                    motivo=f"Devolución de efectivo - Venta #{venta.id_venta} anulada",
                )
            venta.estado = "ANULADA"
            NotaDevolucionPos.objects.create(
                id_venta=venta,
                id_operacion=operacion,
                monto_devuelto=venta.total,
                motivo=nota or "Devolución del efectivo por conflicto de una venta sin conexión.",
                detalle=[
                    {
                        "prenda": str(item.id_variante),
                        "cantidad": item.cantidad,
                        "precio_unitario": str(item.precio_unitario),
                        "subtotal": str(item.subtotal),
                        "vuelve_al_stock": not item.sin_stock,
                    }
                    for item in items
                ],
                id_usuario=usuario,
                id_empresa_id=venta.id_empresa_id,
            )
            resolucion = "DEVUELTA"
            texto = f"devolvió Bs {venta.total} en efectivo y anuló"

        venta.save(update_fields=["estado"])
        operacion.resolucion = resolucion
        operacion.revisada_por = usuario
        operacion.fecha_revision = timezone.now()
        operacion.nota_revision = nota
        operacion.save(update_fields=["resolucion", "revisada_por", "fecha_revision", "nota_revision"])

        log_audit(
            usuario=usuario,
            accion="CONFLICTO_RESUELTO",
            tabla_afectada="pos_sale",
            registro_id=venta.id_venta,
            descripcion=(
                f"{usuario.nombres} {usuario.apellidos} {texto} la venta sin conexión "
                f"#{venta.id_venta} en {sucursal.nombre} (conflicto: {operacion.tipo_conflicto})"
            ),
            empresa=venta.id_empresa_id,
        )
        return operacion