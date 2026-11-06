# backend/apps/fidelidad/consultas.py
#
# NUEVO (Fase 3 - CU18): consultas del descuento por fidelidad para las
# pantallas (progreso del cliente y monitoreo del mes).
#
# Estado del cliente en una empresa durante un mes:
#   EN_PROGRESO -> todavía no llega a las compras requeridas.
#   DISPONIBLE  -> llegó y aún no usa el descuento (mes en curso).
#   USADO       -> ya usó el descuento (en un pedido web o en una venta POS).
#   VENCIDO     -> llegó en un mes pasado y no lo usó (se pierde).
# El conteo usa la regla vigente (los cambios de la regla aplican de inmediato).
from collections import Counter
from datetime import date

from apps.sales.models import Order, PosSale

from . import servicio
from .models import BeneficioFidelidad, ReglaFidelidad

ORDEN_ESTADOS = {"DISPONIBLE": 0, "EN_PROGRESO": 1, "USADO": 2, "VENCIDO": 3}
NOMBRES_ESTADO = {
    "EN_PROGRESO": "En progreso",
    "DISPONIBLE": "Descuento disponible",
    "USADO": "Descuento usado",
    "VENCIDO": "No lo usó (vencido)",
}


def leer_periodo(texto):
    """Día 1 del mes de un texto AAAA-MM; por defecto, el mes actual."""
    try:
        anio, mes = (int(parte) for parte in str(texto).split("-"))
        if 1 <= mes <= 12 and 2000 <= anio <= 2100:
            return date(anio, mes, 1)
    except (TypeError, ValueError):
        pass
    return servicio.periodo_de()


def regla_dict():
    """Regla vigente para las pantallas."""
    regla = ReglaFidelidad.vigente()
    usuario = regla.actualizado_por
    return {
        "compras_requeridas": regla.compras_requeridas,
        "porcentaje": float(regla.porcentaje),
        "activa": regla.activa,
        "fecha_actualizacion": regla.fecha_actualizacion,
        "actualizado_por": f"{usuario.nombres} {usuario.apellidos}" if usuario else None,
    }


def _uso(beneficio):
    """Dónde se usó el descuento ("Pedido #12" o "Venta #8")."""
    if beneficio is None or not beneficio.usado:
        return None
    if beneficio.id_orden_id:
        return f"Pedido #{beneficio.id_orden_id}"
    if beneficio.id_venta_id:
        return f"Venta #{beneficio.id_venta_id}"
    return None


def _pares_del_mes(periodo, empresa_id=None, id_cliente=None):
    """(cliente, empresa) con compras o beneficio en el mes."""
    inicio, fin = servicio.rango_mes(periodo)
    pedidos = Order.objects.filter(
        estado__in=servicio.ESTADOS_PEDIDO_PAGADO, fecha_creacion__gte=inicio, fecha_creacion__lt=fin,
        id_empresa__isnull=False,
    )
    ventas = PosSale.objects.filter(
        estado="REGISTRADA", fecha_venta__gte=inicio, fecha_venta__lt=fin,
        id_cliente__isnull=False, id_empresa__isnull=False,
    )
    beneficios = BeneficioFidelidad.objects.filter(periodo=periodo)
    if empresa_id is not None:
        pedidos, ventas = pedidos.filter(id_empresa_id=empresa_id), ventas.filter(id_empresa_id=empresa_id)
        beneficios = beneficios.filter(id_empresa_id=empresa_id)
    if id_cliente is not None:
        pedidos, ventas = pedidos.filter(id_cliente_id=id_cliente), ventas.filter(id_cliente_id=id_cliente)
        beneficios = beneficios.filter(id_cliente_id=id_cliente)
    pares = set(pedidos.values_list("id_cliente_id", "id_empresa_id"))
    pares |= set(ventas.values_list("id_cliente_id", "id_empresa_id"))
    pares |= set(beneficios.values_list("id_cliente_id", "id_empresa_id"))
    return pares


def fila(cliente_id, empresa_id, periodo, regla, beneficio=None):
    """Estado de un cliente en una empresa durante el mes."""
    compras = servicio.compras_del_mes(cliente_id, empresa_id, periodo)
    actual = periodo == servicio.periodo_de()
    llego = compras >= regla.compras_requeridas or (beneficio is not None and beneficio.fecha_alcanzado)
    if beneficio is not None and beneficio.usado:
        estado = "USADO"
    elif actual and regla.activa and compras >= regla.compras_requeridas:
        estado = "DISPONIBLE"
    elif not actual and llego:
        estado = "VENCIDO"
    else:
        estado = "EN_PROGRESO"
    return {
        "compras": compras,
        "requeridas": regla.compras_requeridas,
        "faltan": max(regla.compras_requeridas - compras, 0),
        "estado": estado,
        "estado_display": NOMBRES_ESTADO[estado],
        "fecha_alcanzado": beneficio.fecha_alcanzado if beneficio else None,
        "fecha_uso": beneficio.fecha_uso if beneficio and beneficio.usado else None,
        "porcentaje_usado": float(beneficio.porcentaje) if beneficio and beneficio.usado else None,
        "monto_descuento": float(beneficio.monto_descuento or 0) if beneficio and beneficio.usado else 0.0,
        "uso": _uso(beneficio),
    }


def monitoreo(periodo, empresa_id=None, id_cliente=None):
    """Clientes con compras en el mes, su progreso y lo descontado (empresa_id None = todas)."""
    from apps.users_auth.models import Cliente, Empresa

    regla = ReglaFidelidad.vigente()
    pares = _pares_del_mes(periodo, empresa_id, id_cliente)
    clientes = Cliente.objects.select_related("id_usuario").in_bulk({c for c, _ in pares})
    empresas = Empresa.objects.in_bulk({e for _, e in pares})
    beneficios = {
        (b.id_cliente_id, b.id_empresa_id): b
        for b in BeneficioFidelidad.objects.filter(periodo=periodo, id_cliente__in=clientes)
    }
    filas = []
    for cliente_id, empresa_id_fila in pares:
        cliente, empresa = clientes[cliente_id], empresas[empresa_id_fila]
        usuario = cliente.id_usuario
        datos = fila(cliente_id, empresa_id_fila, periodo, regla, beneficios.get((cliente_id, empresa_id_fila)))
        datos.update({
            "id_cliente": cliente_id,
            "cliente": f"{usuario.nombres} {usuario.apellidos}".strip(),
            "correo": usuario.correo,
            "id_empresa": empresa_id_fila,
            "empresa": empresa.nombre,
        })
        filas.append(datos)
    filas.sort(key=lambda f: (ORDEN_ESTADOS[f["estado"]], -f["compras"], f["cliente"].lower()))
    estados = Counter(f["estado"] for f in filas)
    return {
        "mes": f"{periodo:%Y-%m}",
        "vence": servicio.ultimo_dia(periodo),
        "regla": regla_dict(),
        "resumen": {
            "clientes": len(filas),
            "ganaron": estados["DISPONIBLE"] + estados["USADO"] + estados["VENCIDO"],
            "por_usar": estados["DISPONIBLE"],
            "usados": estados["USADO"],
            "vencidos": estados["VENCIDO"],
            "costo_descuentos": round(sum(f["monto_descuento"] for f in filas), 2),
        },
        "clientes": filas,
    }


def progreso_cliente(cliente, id_empresa=None):
    """Progreso del mes del cliente en cada empresa donde compró (o en una empresa)."""
    from apps.users_auth.models import Empresa

    periodo = servicio.periodo_de()
    regla = ReglaFidelidad.vigente()
    ids = {e for _, e in _pares_del_mes(periodo, id_cliente=cliente.pk)}
    if id_empresa is not None:
        ids = {id_empresa}
    empresas = Empresa.objects.in_bulk(ids)
    beneficios = {
        b.id_empresa_id: b
        for b in BeneficioFidelidad.objects.filter(periodo=periodo, id_cliente=cliente, id_empresa__in=ids)
    }
    filas = []
    for empresa_id, empresa in empresas.items():
        datos = fila(cliente.pk, empresa_id, periodo, regla, beneficios.get(empresa_id))
        datos.update({
            "id_empresa": empresa_id,
            "empresa": empresa.nombre,
            "disponible": datos["estado"] == "DISPONIBLE",
            "porcentaje": float(regla.porcentaje),
        })
        filas.append(datos)
    filas.sort(key=lambda f: (ORDEN_ESTADOS[f["estado"]], f["empresa"].lower()))
    return {
        "mes": f"{periodo:%Y-%m}",
        "vence": servicio.ultimo_dia(periodo),
        "regla": regla_dict(),
        "empresas": filas,
    }