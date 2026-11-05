# backend/apps/analytics/perfil_clientes.py
#
# NUEVO (Fase 3 - CU04): perfil de clientes por empresa.
# CORREGIDO (CU04): el SUPER_ADMIN ve TODOS los clientes registrados, aunque
# todavía no hayan comprado (aparecen con 0 compras).
#
# El cliente es global (puede comprar en cualquier empresa), pero cada empresa
# solo ve a SUS clientes: los que tienen al menos un pedido web (no pendiente),
# una venta en tienda con su correo o una reserva en esa empresa. Y de cada
# cliente solo ve lo que hizo en ella. El SUPER_ADMIN ve todos los clientes
# registrados (con o sin compras) y todo su historial, con el detalle por empresa.
#
# Cifras (iguales al resto del sistema):
#   compras        = pedidos web pagados (PAGADA, ENVIADA, ENTREGADA) + ventas
#                    en tienda no anuladas.
#   total_gastado  = total de esas compras - reembolsos de devoluciones completadas.

from collections import Counter, defaultdict
from decimal import Decimal

from apps.reservations.models import FittingReservation
from apps.sales.models import CambioPrenda, Devolucion, Order, OrderItem, PosSale, PosSaleItem
from apps.users_auth.models import Cliente

from .models import EntrenamientoModelo, SegmentoCliente

ESTADOS_PAGADOS = ("PAGADA", "ENVIADA", "ENTREGADA")
RESERVAS_SIN_PAGAR = ("PENDIENTE_PAGO",)
MAX_HISTORIAL = 150
TOP_PREFERENCIAS = 5
NOMBRE_SEGMENTO = dict(SegmentoCliente.SEGMENTOS)


def _filtro_empresa(qs, empresa_id, campo="id_empresa"):
    """Restringe a una empresa (None = todas, SUPER_ADMIN)."""
    return qs if empresa_id is None else qs.filter(**{campo: empresa_id})


def _pedidos(empresa_id, clientes=None):
    """Pedidos web pagados."""
    qs = Order.objects.filter(estado__in=ESTADOS_PAGADOS)
    if clientes is not None:
        qs = qs.filter(id_cliente__in=clientes)
    return _filtro_empresa(qs, empresa_id)


def _ventas(empresa_id, clientes=None):
    """Ventas en tienda con cliente y no anuladas."""
    qs = PosSale.objects.filter(id_cliente__isnull=False).exclude(estado="ANULADA")
    if clientes is not None:
        qs = qs.filter(id_cliente__in=clientes)
    return _filtro_empresa(qs, empresa_id)


def _reembolsos(empresa_id, clientes=None):
    """Devoluciones completadas (con su reembolso)."""
    qs = Devolucion.objects.filter(estado="COMPLETADA", id_cliente__isnull=False)
    if clientes is not None:
        qs = qs.filter(id_cliente__in=clientes)
    return _filtro_empresa(qs, empresa_id)


def ids_clientes(empresa_id):
    """Clientes con actividad en la empresa; todos los registrados si empresa_id es None."""
    if empresa_id is None:
        return set(Cliente.objects.values_list("id_cliente", flat=True))
    pedidos = _filtro_empresa(Order.objects.exclude(estado="PENDIENTE"), empresa_id)
    ventas = _filtro_empresa(PosSale.objects.filter(id_cliente__isnull=False), empresa_id)
    reservas = _filtro_empresa(
        FittingReservation.objects.exclude(estado__in=RESERVAS_SIN_PAGAR), empresa_id
    )
    ids = set(pedidos.values_list("id_cliente_id", flat=True))
    ids |= set(ventas.values_list("id_cliente_id", flat=True))
    ids |= set(reservas.values_list("id_cliente_id", flat=True))
    ids.discard(None)
    return ids


def _segmentos_vigentes(empresa_id, clientes):
    """{id_cliente: [{empresa, segmento, ...}]} de las segmentaciones vigentes."""
    vigentes = _filtro_empresa(
        EntrenamientoModelo.objects.filter(tipo="SEGMENTACION", vigente=True), empresa_id
    )
    resultado = defaultdict(list)
    for s in SegmentoCliente.objects.filter(
        id_entrenamiento__in=vigentes, id_cliente__in=clientes
    ).select_related("id_empresa", "id_entrenamiento").order_by("id_empresa__nombre"):
        resultado[s.id_cliente_id].append({
            "empresa": s.id_empresa.nombre,
            "segmento": s.segmento,
            "nombre": NOMBRE_SEGMENTO[s.segmento],
            "recencia_dias": s.recencia_dias,
            "frecuencia": s.frecuencia,
            "monto": float(s.monto),
            "fecha": s.id_entrenamiento.fecha_entrenamiento,
        })
    return resultado


def _nombre(cliente):
    """Nombre completo del cliente."""
    usuario = cliente.id_usuario
    return f"{usuario.nombres} {usuario.apellidos}".strip()


# --------------------------------------------------------------------------
# Lista
# --------------------------------------------------------------------------

def listar(empresa_id):
    """Clientes de la empresa con su resumen de compras."""
    ids = ids_clientes(empresa_id)
    if not ids:
        return []
    resumen = defaultdict(lambda: {"compras": 0, "total": Decimal("0"), "ultima": None, "empresas": set()})
    for cliente_id, total, fecha, empresa in _pedidos(empresa_id, ids).values_list(
        "id_cliente_id", "total", "fecha_creacion", "id_empresa__nombre"
    ):
        _sumar(resumen[cliente_id], total, fecha, empresa)
    for cliente_id, total, fecha, empresa in _ventas(empresa_id, ids).values_list(
        "id_cliente_id", "total", "fecha_venta", "id_empresa__nombre"
    ):
        _sumar(resumen[cliente_id], total, fecha, empresa)
    for cliente_id, monto in _reembolsos(empresa_id, ids).values_list("id_cliente_id", "monto_reembolso"):
        resumen[cliente_id]["total"] -= monto or Decimal("0")
    for cliente_id, empresa in _filtro_empresa(
        FittingReservation.objects.filter(id_cliente__in=ids).exclude(estado__in=RESERVAS_SIN_PAGAR),
        empresa_id,
    ).values_list("id_cliente_id", "id_empresa__nombre"):
        if empresa:
            resumen[cliente_id]["empresas"].add(empresa)
    segmentos = _segmentos_vigentes(empresa_id, ids)
    filas = []
    for cliente in Cliente.objects.filter(pk__in=ids).select_related("id_usuario"):
        datos = resumen[cliente.id_cliente]
        filas.append({
            "id": cliente.id_cliente,
            "nombre": _nombre(cliente),
            "correo": cliente.id_usuario.correo,
            "telefono": cliente.id_usuario.telefono,
            "estado": cliente.id_usuario.estado,
            "empresas": sorted(datos["empresas"]),
            "compras": datos["compras"],
            "total_gastado": float(max(datos["total"], Decimal("0"))),
            "ultima_compra": datos["ultima"],
            # Solo el segmento de las empresas donde de verdad es cliente.
            "segmentos": [{"empresa": s["empresa"], "segmento": s["segmento"], "nombre": s["nombre"]}
                          for s in segmentos.get(cliente.id_cliente, []) if s["empresa"] in datos["empresas"]],
        })
    filas.sort(key=lambda f: (-f["total_gastado"], f["nombre"].lower()))
    return filas


def _sumar(datos, total, fecha, empresa):
    """Acumula una compra en el resumen de un cliente."""
    datos["compras"] += 1
    datos["total"] += total or Decimal("0")
    if fecha and (datos["ultima"] is None or fecha > datos["ultima"]):
        datos["ultima"] = fecha
    if empresa:
        datos["empresas"].add(empresa)


# --------------------------------------------------------------------------
# Perfil
# --------------------------------------------------------------------------

def perfil(empresa_id, id_cliente):
    """Perfil completo del cliente en la empresa (o en todas). None si no es cliente de ella."""
    if id_cliente not in ids_clientes(empresa_id):
        return None
    cliente = Cliente.objects.select_related("id_usuario").get(pk=id_cliente)
    pedidos = list(_pedidos(empresa_id, [id_cliente]).select_related("id_sucursal", "id_empresa"))
    ventas = list(_ventas(empresa_id, [id_cliente]).select_related("id_sucursal", "id_empresa"))
    devoluciones = list(
        _filtro_empresa(Devolucion.objects.filter(id_cliente_id=id_cliente), empresa_id)
        .select_related("id_sucursal", "id_empresa")
    )
    cambios = list(
        _filtro_empresa(CambioPrenda.objects.filter(id_cliente_id=id_cliente), empresa_id)
        .select_related("id_sucursal", "id_empresa", "id_variante_devuelta__id_producto",
                        "id_variante_entregada__id_producto")
    )
    reservas = list(
        _filtro_empresa(
            FittingReservation.objects.filter(id_cliente_id=id_cliente).exclude(estado__in=RESERVAS_SIN_PAGAR),
            empresa_id,
        ).select_related("id_sucursal", "id_empresa")
    )
    reembolsado = sum((d.monto_reembolso or Decimal("0")) for d in devoluciones if d.estado == "COMPLETADA")
    compras = [(p.fecha_creacion, p.total, p.id_sucursal, p.id_empresa) for p in pedidos]
    compras += [(v.fecha_venta, v.total, v.id_sucursal, v.id_empresa) for v in ventas]
    fechas = sorted(c[0] for c in compras if c[0])
    bruto = sum((c[1] or Decimal("0")) for c in compras)
    sucursales = Counter(c[2].nombre for c in compras if c[2])
    usuario = cliente.id_usuario
    empresas = {
        x.id_empresa.nombre for x in pedidos + ventas + reservas + devoluciones + cambios if x.id_empresa_id
    }
    return {
        "cliente": {
            "id": cliente.id_cliente,
            "nombre": _nombre(cliente),
            "correo": usuario.correo,
            "telefono": usuario.telefono,
            "estado": usuario.estado,
            "fecha_registro": cliente.fecha_registro,
        },
        "resumen": {
            "compras": len(compras),
            "pedidos_web": len(pedidos),
            "ventas_tienda": len(ventas),
            "total_gastado": float(max(bruto - reembolsado, Decimal("0"))),
            "ticket_promedio": float(round(bruto / len(compras), 2)) if compras else 0.0,
            "primera_compra": fechas[0] if fechas else None,
            "ultima_compra": fechas[-1] if fechas else None,
            "sucursal_favorita": sucursales.most_common(1)[0][0] if sucursales else None,
            "reservas": len(reservas),
            "devoluciones": len(devoluciones),
            "monto_reembolsado": float(reembolsado),
            "cambios": len(cambios),
        },
        "preferencias": _preferencias(pedidos, ventas),
        # Solo el segmento de las empresas donde de verdad es cliente.
        "segmentos": [
            s for s in _segmentos_vigentes(empresa_id, [id_cliente]).get(id_cliente, []) if s["empresa"] in empresas
        ],
        "por_empresa": _por_empresa(compras) if empresa_id is None else [],
        "historial": _historial(pedidos, ventas, reservas, devoluciones, cambios),
    }


def _preferencias(pedidos, ventas):
    """Prendas, categorías, tallas y colores que más compra (en unidades)."""
    prendas, categorias, tallas, colores = Counter(), Counter(), Counter(), Counter()
    lineas = list(
        OrderItem.objects.filter(id_orden__in=pedidos).select_related(
            "id_variante__id_producto__id_categoria", "id_variante__id_talla", "id_variante__id_color"
        )
    ) + list(
        PosSaleItem.objects.filter(id_venta__in=ventas).select_related(
            "id_variante__id_producto__id_categoria", "id_variante__id_talla", "id_variante__id_color"
        )
    )
    for linea in lineas:
        variante = linea.id_variante
        unidades = linea.cantidad or 0
        prendas[variante.id_producto.nombre] += unidades
        categorias[variante.id_producto.id_categoria.nombre] += unidades
        tallas[variante.id_talla.nombre] += unidades
        colores[variante.id_color.nombre] += unidades

    def top(contador):
        return [{"nombre": nombre, "unidades": unidades} for nombre, unidades in contador.most_common(TOP_PREFERENCIAS)]

    return {
        "unidades": sum(prendas.values()),
        "prendas": top(prendas),
        "categorias": top(categorias),
        "tallas": top(tallas),
        "colores": top(colores),
    }


def _por_empresa(compras):
    """Compras y total por empresa (vista del SUPER_ADMIN)."""
    datos = defaultdict(lambda: {"compras": 0, "total": Decimal("0")})
    for _, total, _, empresa in compras:
        nombre = empresa.nombre if empresa else "Sin empresa"
        datos[nombre]["compras"] += 1
        datos[nombre]["total"] += total or Decimal("0")
    return sorted(
        ({"empresa": nombre, "compras": d["compras"], "total": float(d["total"])} for nombre, d in datos.items()),
        key=lambda f: -f["total"],
    )


def _historial(pedidos, ventas, reservas, devoluciones, cambios):
    """Todo lo que hizo el cliente, del más reciente al más antiguo."""
    eventos = []
    for p in pedidos:
        eventos.append({
            "tipo": "PEDIDO", "tipo_display": "Pedido web", "numero": p.id_orden, "fecha": p.fecha_creacion,
            "empresa": p.id_empresa.nombre if p.id_empresa else "", "sucursal": p.id_sucursal.nombre if p.id_sucursal else "",
            "estado": p.get_estado_display(), "monto": float(p.total),
            "detalle": "Delivery" if p.tipo_entrega == "DELIVERY" else "Retiro en sucursal",
        })
    for v in ventas:
        eventos.append({
            "tipo": "VENTA", "tipo_display": "Compra en tienda", "numero": v.id_venta, "fecha": v.fecha_venta,
            "empresa": v.id_empresa.nombre if v.id_empresa else "", "sucursal": v.id_sucursal.nombre,
            "estado": v.get_estado_display(), "monto": float(v.total), "detalle": v.get_metodo_pago_display(),
        })
    for r in reservas:
        eventos.append({
            "tipo": "RESERVA", "tipo_display": "Reserva", "numero": r.id_reserva, "fecha": r.fecha_creacion,
            "empresa": r.id_empresa.nombre if r.id_empresa else "", "sucursal": r.id_sucursal.nombre,
            "estado": r.get_estado_display(), "monto": float(r.monto_total) if r.monto_total is not None else None,
            "detalle": f"Para el {r.fecha_reserva:%d/%m/%Y}",
        })
    for d in devoluciones:
        eventos.append({
            "tipo": "DEVOLUCION", "tipo_display": "Devolución", "numero": d.id_devolucion, "fecha": d.fecha_creacion,
            "empresa": d.id_empresa.nombre if d.id_empresa else "", "sucursal": d.id_sucursal.nombre if d.id_sucursal else "",
            "estado": d.get_estado_display(),
            "monto": float(d.monto_reembolso) if d.monto_reembolso is not None else None,
            "detalle": f"Pedido #{d.id_orden_id}" if d.id_orden_id else (f"Venta #{d.id_venta_id}" if d.id_venta_id else ""),
        })
    for c in cambios:
        eventos.append({
            "tipo": "CAMBIO", "tipo_display": "Cambio de prenda", "numero": c.id_cambio, "fecha": c.fecha_solicitud,
            "empresa": c.id_empresa.nombre, "sucursal": c.id_sucursal.nombre, "estado": c.get_estado_display(),
            "monto": None, "detalle": c.get_motivo_display(),
        })
    eventos.sort(key=lambda e: e["fecha"].timestamp() if e["fecha"] else 0, reverse=True)
    return eventos[:MAX_HISTORIAL]