# backend/apps/innovation/consultas_admin.py
#
# Consultas controladas del asistente de gestión y de los reportes (CU13).
# La IA solo elige la consulta y sus parámetros; aquí se validan y se
# ejecutan SIEMPRE dentro de la empresa (y sucursal) del usuario autenticado.
# Ninguna consulta escribe en la base de datos.
#
# MODIFICADO (Fase 3 - CU13):
# - Ventas netas, iguales al dashboard: sin ventas POS anuladas y restando lo
#   reembolsado en devoluciones completadas. Las ventas sin conexión en
#   conflicto se cuentan (el efectivo se recibió) y se avisan en una nota.
# - Filtros por categoría y por prenda; agrupación por semana, mes y categoría.
# - Reportes nuevos: comparativo de sucursales por meses, categorías con más
#   ingresos, menor existencia, devoluciones y cambios de prenda, ventas
#   anuladas y conflictos sin conexión, precios actuales, empresas y sucursales.
# - Reservas con todos sus estados (pendiente de pago, confirmada, vencida...).
# - Cada resultado trae "grafico" (o None) para dibujarlo en la web y en las
#   exportaciones.
# - Los reportes por prenda o categoría avisan cuántas ventas pagadas no
#   tienen prendas registradas (no se pueden desglosar).

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.catalog.models import Categoria, Producto, ProductoVariante, Sucursal
from apps.users_auth.models import Empresa
from apps.inventory.models import StockItem
from apps.reservations.models import FittingReservation
from apps.sales.models import (
    CambioPrenda,
    Delivery,
    Devolucion,
    DevolucionItem,
    Order,
    OrderItem,
    PosSale,
    PosSaleItem,
    SyncOperacion,
)

from .herramientas_cliente import (
    _coincide,
    _entero,
    _norm,
    _orden_talla,
    _palabras_utiles,
    _resolver,
    _tokens,
)
from .models import ARTryOnSession

logger = logging.getLogger(__name__)

# SaaS: empresa cuyos datos puede consultar el asistente en la petición
# actual. None = todas (SUPER_ADMIN). Por defecto SIN_ALCANCE, que no coincide
# con ninguna empresa: si alguien olvida fijar el alcance, la consulta devuelve
# vacío en lugar de mezclar datos de otras empresas.
SIN_ALCANCE = 0
_empresa_actual = ContextVar("empresa_actual", default=SIN_ALCANCE)

ESTADOS_PAGADOS = ("PAGADA", "ENVIADA", "ENTREGADA")
MAX_FILAS = 500
LIMITE_TOP = 10
MAX_TOP = 50
MAX_BARRAS = 15
MESES_COMPARATIVO = 3
MAX_MESES = 12
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
CANAL_POS = "Punto de venta"
CANAL_WEB = "Web / App"

ESTADOS_ENTREGA = {
    "PENDIENTE": "Pendiente",
    "EN_PREPARACION": "En preparación",
    "EN_CAMINO": "En camino",
    "ENTREGADO": "Entregado",
}
KPI_ENTREGA = {
    "PENDIENTE": "Pendientes",
    "EN_PREPARACION": "En preparación",
    "EN_CAMINO": "En camino",
    "ENTREGADO": "Entregadas",
}
# MODIFICADO (Fase 3): todos los estados de la reserva con anticipo.
ESTADOS_RESERVA = {
    "PENDIENTE_PAGO": "Pendiente de pago",
    "CONFIRMADA": "Confirmada",
    "COMPLETADA": "Completada",
    "CANCELADA": "Cancelada",
    "VENCIDA": "Vencida",
    "PENDIENTE": "Pendiente (sin pago, anterior)",
}
KPI_RESERVA = {
    "PENDIENTE_PAGO": "Pendientes de pago",
    "CONFIRMADA": "Confirmadas",
    "COMPLETADA": "Completadas",
    "CANCELADA": "Canceladas",
    "VENCIDA": "Vencidas",
    "PENDIENTE": "Pendientes (anteriores)",
}
TIPOS_PAGO_RESERVA = {"ANTICIPO": "Anticipo", "TOTAL": "Pago total"}
ESTADOS_DEVOLUCION = dict(Devolucion.ESTADOS)
ESTADOS_CAMBIO = dict(CambioPrenda.ESTADOS)
MOTIVOS_DEVOLUCION = dict(DevolucionItem.MOTIVOS)
MOTIVOS_CAMBIO = dict(CambioPrenda.MOTIVOS)
# Etapas comunes de devoluciones y cambios (para el gráfico comparado).
ETAPAS = (
    ("SOLICIT", "Solicitado"),
    ("PROGRAM", "Programado"),
    ("EN_CAMINO", "En camino"),
    ("COMPLET", "Completado"),
    ("RECHAZ", "Rechazado"),
)
SITUACIONES_CONFLICTO = {
    "PENDIENTE": "Pendiente de revisión",
    "CONFIRMADA": "Confirmada",
    "ANULADA": "Anulada (efectivo devuelto)",
}
TIPOS_CONFLICTO = dict(SyncOperacion.TIPOS_CONFLICTO)

ALIAS_PERIODO = {
    "hoy": "hoy",
    "ayer": "ayer",
    "semana": "semana",
    "esta semana": "semana",
    "semana_pasada": "semana_pasada",
    "semana pasada": "semana_pasada",
    "mes": "mes",
    "este mes": "mes",
    "mes_pasado": "mes_pasado",
    "mes pasado": "mes_pasado",
    "anio": "anio",
    "ano": "anio",
    "este ano": "anio",
    "todo": "todo",
    "siempre": "todo",
    "historico": "todo",
}
ALIAS_AGRUPAR = {
    "dia": "dia",
    "dias": "dia",
    "diario": "dia",
    "semana": "semana",
    "semanas": "semana",
    "semanal": "semana",
    "mes": "mes",
    "meses": "mes",
    "mensual": "mes",
    "sucursal": "sucursal",
    "sucursales": "sucursal",
    "metodo": "metodo",
    "metodo_pago": "metodo",
    "metodo de pago": "metodo",
    "pago": "metodo",
    "canal": "canal",
    "canales": "canal",
    "empresa": "empresa",
    "empresas": "empresa",
    "tienda": "empresa",
    "tiendas": "empresa",
    "categoria": "categoria",
    "categorias": "categoria",
}
GRUPOS_VENTAS = {
    "dia": "Día",
    "semana": "Semana",
    "mes": "Mes",
    "sucursal": "Sucursal",
    "metodo": "Método de pago",
    "canal": "Canal",
    "empresa": "Empresa",
    "categoria": "Categoría",
}
# Tipo de gráfico de las ventas según la agrupación.
GRAFICO_VENTAS = {
    "dia": "line",
    "semana": "line",
    "mes": "bar",
    "sucursal": "bar",
    "empresa": "bar",
    "categoria": "bar",
    "metodo": "doughnut",
    "canal": "doughnut",
}

class ConsultaInvalida(Exception):
    """La consulta pedida no existe o no se pudo ejecutar."""

# ---------------------------------------------------------------- utilidades
def _fmt(d):
    """Fecha en formato dd/mm/aaaa."""
    return d.strftime("%d/%m/%Y")

def _fecha(valor):
    """Convierte 'AAAA-MM-DD' en date, o None si no es una fecha válida."""
    try:
        return date.fromisoformat(str(valor).strip()[:10])
    except (TypeError, ValueError):
        return None

def _verdadero(valor):
    """Interpreta true/'si'/1 como verdadero (los modelos a veces mandan texto)."""
    if isinstance(valor, bool):
        return valor
    return _norm(valor) in ("true", "si", "sí", "1", "yes")

def _dinero(valor):
    """Monto como float con dos decimales."""
    return round(float(valor or 0), 2)

def _rango(args, defecto="hoy", hoy=None):
    """Devuelve (desde, hasta, etiqueta) según periodo, desde y hasta.

    None en desde o hasta significa sin límite. Con 'desde'/'hasta' explícitos
    se ignora 'periodo'.
    """
    hoy = hoy or timezone.localdate()
    desde, hasta = _fecha(args.get("desde")), _fecha(args.get("hasta"))
    if desde or hasta:
        if desde and hasta and desde > hasta:
            desde, hasta = hasta, desde
        if desde and hasta:
            etiqueta = f"del {_fmt(desde)} al {_fmt(hasta)}"
        elif desde:
            etiqueta = f"desde el {_fmt(desde)}"
        else:
            etiqueta = f"hasta el {_fmt(hasta)}"
        return desde, hasta, etiqueta

    periodo = ALIAS_PERIODO.get(_norm(args.get("periodo")), defecto)
    if periodo == "ayer":
        ayer = hoy - timedelta(days=1)
        return ayer, ayer, f"ayer ({_fmt(ayer)})"
    if periodo == "semana":
        lunes = hoy - timedelta(days=hoy.weekday())
        return lunes, hoy, f"esta semana ({_fmt(lunes)} al {_fmt(hoy)})"
    if periodo == "semana_pasada":
        lunes = hoy - timedelta(days=hoy.weekday() + 7)
        domingo = lunes + timedelta(days=6)
        return lunes, domingo, f"la semana pasada ({_fmt(lunes)} al {_fmt(domingo)})"
    if periodo == "mes":
        primero = hoy.replace(day=1)
        return primero, hoy, f"este mes ({_fmt(primero)} al {_fmt(hoy)})"
    if periodo == "mes_pasado":
        fin = hoy.replace(day=1) - timedelta(days=1)
        inicio = fin.replace(day=1)
        return inicio, fin, f"el mes pasado ({_fmt(inicio)} al {_fmt(fin)})"
    if periodo == "anio":
        inicio = hoy.replace(month=1, day=1)
        return inicio, hoy, f"este año ({_fmt(inicio)} al {_fmt(hoy)})"
    if periodo == "todo":
        return None, None, "todo el historial"
    return hoy, hoy, f"hoy ({_fmt(hoy)})"

def _entre(qs, campo, desde, hasta):
    """Filtra un queryset por la fecha (hora de Bolivia) de un campo datetime."""
    if desde:
        qs = qs.filter(**{f"{campo}__date__gte": desde})
    if hasta:
        qs = qs.filter(**{f"{campo}__date__lte": hasta})
    return qs

def _sumar_meses(dia, n):
    """Primer día del mes que está n meses después (o antes) del de 'dia'."""
    total = dia.year * 12 + dia.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)

def _nombre_mes(anio, mes):
    """Nombre corto del mes, p. ej. 'Nov 2026'."""
    return f"{MESES[mes - 1][:3].capitalize()} {anio}"

def _periodo_de(fecha, agrupar):
    """(clave ordenable, etiqueta) del día, semana o mes de una fecha."""
    if agrupar == "semana":
        lunes = fecha - timedelta(days=fecha.weekday())
        return lunes, f"Semana del {_fmt(lunes)}"
    if agrupar == "mes":
        return (fecha.year, fecha.month), _nombre_mes(fecha.year, fecha.month)
    return fecha, _fmt(fecha)

def _estado(valor, catalogo):
    """Clave del estado (p. ej. 'EN_CAMINO') que corresponde al texto, o None."""
    if not _norm(valor):
        return None
    etiqueta = _resolver(valor, list(catalogo.values()))
    for clave, nombre in catalogo.items():
        if nombre == etiqueta:
            return clave
    return None

def empresa_del_usuario(usuario):
    """Id de la empresa que el usuario puede consultar (None = todas, SUPER_ADMIN)."""
    if usuario.roles.filter(nombre="SUPER_ADMIN").exists():
        return None
    return usuario.id_empresa_id or SIN_ALCANCE

@contextmanager
def en_empresa_de(usuario):
    """Fija, mientras dure el bloque, la empresa que el asistente puede consultar."""
    token = _empresa_actual.set(empresa_del_usuario(usuario))
    try:
        yield
    finally:
        _empresa_actual.reset(token)

def _por_empresa(qs, campo="id_empresa"):
    """Restringe un queryset a la empresa del alcance actual."""
    empresa_id = _empresa_actual.get()
    if empresa_id is None:
        return qs
    return qs.filter(**{campo: empresa_id})

def _todas_las_empresas():
    """True si la consulta abarca todas las empresas (SUPER_ADMIN sin filtro)."""
    return _empresa_actual.get() is None

def _nombre_empresa(objeto):
    """Nombre de la empresa de un registro (o 'Sin empresa')."""
    return objeto.id_empresa.nombre if objeto.id_empresa_id else "Sin empresa"

def _nombre_sucursal(sucursal):
    """Nombre de la sucursal; con todas las empresas se agrega la empresa."""
    if sucursal is None:
        return "Sin sucursal"
    if _todas_las_empresas() and sucursal.id_empresa_id:
        return f"{sucursal.nombre} ({sucursal.id_empresa.nombre})"
    return sucursal.nombre

def _es_super_admin(usuario):
    """True si el usuario es el operador de la plataforma (SUPER_ADMIN)."""
    return usuario.roles.filter(nombre="SUPER_ADMIN").exists()

def _empresas_activas():
    """Empresas activas de la plataforma, ordenadas por nombre."""
    return list(Empresa.objects.filter(estado="ACTIVA").order_by("nombre"))

def contexto_plataforma(usuario):
    """Texto que explica al asistente la plataforma, las empresas y sus sucursales.

    El SUPER_ADMIN conoce todas las empresas con sus sucursales; el personal
    de una empresa solo conoce la suya (no se le revelan las demás).
    """
    def _sucursales_de(empresa):
        """Sucursales activas de una empresa, separadas por comas."""
        nombres = Sucursal.objects.filter(id_empresa=empresa, estado="ACTIVA").order_by(
            "nombre"
        ).values_list("nombre", flat=True)
        return ", ".join(nombres) or "sin sucursales"

    base = (
        "SmartLook es una PLATAFORMA SaaS (no es una tienda): varias empresas de ropa "
        "la usan para vender, y cada empresa tiene sus propias sucursales, prendas, "
        "stock y ventas, separados de las demás.\n"
    )
    if _es_super_admin(usuario):
        lineas = [f"- {e.nombre}: {_sucursales_de(e)}" for e in _empresas_activas()]
        return base + (
            "Hablas con el ADMINISTRADOR DE LA PLATAFORMA: puede consultar cualquier "
            "empresa o todas juntas. Si menciona una empresa, pásala en el parámetro "
            "'empresa'; si no menciona ninguna, la consulta abarca todas. Para comparar "
            "empresas usa consultar_ventas con agrupar_por='empresa'.\n"
            "Empresas y sus sucursales:\n" + "\n".join(lineas)
        )
    empresa = usuario.id_empresa
    if empresa is None:
        return base + "El usuario no pertenece a ninguna empresa: no tiene datos que consultar."
    return base + (
        f"Hablas con el personal de la empresa {empresa.nombre}. Solo puedes consultar "
        f"datos de {empresa.nombre}. Si pregunta por otra empresa o por toda la "
        "plataforma, responde que no tiene acceso a esa información "
        "y no reveles qué otras empresas existen.\n"
        f"Sucursales de {empresa.nombre}: {_sucursales_de(empresa)}."
    )

def _resolver_empresa(valor, usuario):
    """Devuelve (id_empresa, nombre, nota) para el parámetro 'empresa' de una consulta.

    - SUPER_ADMIN: busca la empresa por nombre; si no existe, consulta todas
      y devuelve una nota.
    - Personal de empresa: solo puede ser su propia empresa; si pide otra,
      devuelve una nota de acceso denegado (y la consulta queda vacía).
    """
    if not _norm(valor):
        return None, None, None
    empresas = _empresas_activas()
    nombres = [e.nombre for e in empresas]
    real = _resolver(valor, nombres)
    if _es_super_admin(usuario):
        if real is None:
            return None, None, (
                f"No existe la empresa «{valor}»; se muestran todas. "
                f"Empresas: {', '.join(nombres)}."
            )
        empresa = next(e for e in empresas if e.nombre == real)
        return empresa.id_empresa, empresa.nombre, None
    propia = usuario.id_empresa
    if propia is not None and real == propia.nombre:
        return propia.id_empresa, propia.nombre, None
    return SIN_ALCANCE, None, (
        "No tienes acceso a datos de otras empresas; solo puedes consultar "
        f"{propia.nombre if propia else 'tu empresa'}."
    )

def _nombres_sucursales():
    """Nombres de las sucursales activas de la empresa del alcance actual."""
    return list(
        _por_empresa(Sucursal.objects.filter(estado="ACTIVA"))
        .order_by("nombre")
        .values_list("nombre", flat=True)
    )

def alcance_sucursal(usuario):
    """Nombre de la única sucursal que el usuario puede consultar, o None.

    SaaS: un ENCARGADO_SUCURSAL con sucursal asignada solo consulta esa
    sucursal. Administradores y encargados sin sucursal asignada ven todas
    las sucursales de su empresa.
    """
    roles = set(usuario.roles.values_list("nombre", flat=True))
    if roles & {"SUPER_ADMIN", "ADMIN_EMPRESA"}:
        return None
    if "ENCARGADO_SUCURSAL" in roles and usuario.id_sucursal_id:
        return usuario.id_sucursal.nombre
    return None

def _sucursal(args, usuario):
    """Devuelve (sucursal, nota): la sucursal a consultar y un aviso si aplica."""
    fija = alcance_sucursal(usuario)
    if fija:
        return fija, None
    valor = args.get("sucursal")
    if not _norm(valor):
        return None, None
    nombres = _nombres_sucursales()
    real = _resolver(valor, nombres)
    if real is None:
        return None, (
            f"No existe la sucursal «{valor}»; se muestran todas. "
            f"Sucursales: {', '.join(nombres)}."
        )
    return real, None

def _filtros(args):
    """Filtros de categoría y prenda validados contra las tablas reales.

    Devuelve (filtro, notas). filtro = {"categoria", "prendas", "texto",
    "invalido"}: "prendas" es el conjunto de id de producto que coinciden con
    el texto (None = sin filtro). Si la categoría o la prenda no existen,
    "invalido" es True y el reporte sale vacío con una nota que lo explica
    (no se muestran datos de otras prendas como si fueran las pedidas).
    """
    filtro = {"categoria": None, "prendas": None, "texto": None, "invalido": False}
    notas = []
    valor = args.get("categoria")
    if _norm(valor):
        nombres = sorted(
            set(_por_empresa(Categoria.objects.filter(estado=True)).values_list("nombre", flat=True))
        )
        real = _resolver(valor, nombres)
        if real is None:
            filtro["invalido"] = True
            notas.append(
                f"No existe la categoría «{valor}». Categorías: {', '.join(nombres) or 'ninguna'}."
            )
        else:
            filtro["categoria"] = real
    texto = args.get("producto") or args.get("texto")
    palabras = _palabras_utiles(texto)
    if palabras:
        candidatos = []
        productos = _por_empresa(Producto.objects.all()).only("id_producto", "nombre", "tipo_prenda")
        for p in productos:
            tokens = set(_tokens(f"{p.nombre} {p.tipo_prenda or ''}"))
            puntos = sum(1 for palabra in palabras if palabra in tokens)
            if puntos:
                candidatos.append((puntos, p.id_producto))
        filtro["texto"] = str(texto).strip()
        if not candidatos:
            filtro["invalido"] = True
            notas.append(f"No encontré ninguna prenda que coincida con «{texto}».")
        else:
            mejor = max(puntos for puntos, _ in candidatos)
            filtro["prendas"] = {pid for puntos, pid in candidatos if puntos == mejor}
    return filtro, notas

def _con_filtro_de_prendas(filtro):
    """True si hay filtro de categoría o de prenda (se suma por prenda vendida)."""
    return bool(filtro and (filtro["categoria"] or filtro["prendas"] is not None))

def _extra_filtros(filtro):
    """Textos del subtítulo para los filtros de categoría y prenda."""
    extra = []
    if filtro and filtro["categoria"]:
        extra.append(f"Categoría: {filtro['categoria']}")
    if filtro and filtro["texto"]:
        extra.append(f"Prenda: {filtro['texto']}")
    return extra

def _subtitulo(etiqueta, sucursal, extra=None):
    """Línea de contexto del resultado: periodo, sucursal y otros filtros."""
    partes = []
    if etiqueta:
        partes.append(f"Periodo: {etiqueta}")
    partes.append(f"Sucursal: {sucursal}" if sucursal else "Todas las sucursales")
    if extra:
        partes.extend(extra)
    return " · ".join(partes)

def _grafico(tipo, titulo, etiquetas, series, formato="numero"):
    """Datos de un gráfico: tipo bar, barh, line o doughnut; None si no hay datos."""
    if not etiquetas:
        return None
    return {
        "tipo": tipo,
        "titulo": titulo,
        "etiquetas": [str(e) for e in etiquetas],
        "series": [
            {"nombre": nombre, "datos": [round(float(x or 0), 2) for x in datos]}
            for nombre, datos in series
        ],
        "formato": formato,
    }

def _resultado(titulo, subtitulo, kpis, columnas, filas, notas=None, grafico=None):
    """Arma el resultado uniforme, recortando las filas al máximo permitido."""
    notas = list(notas or [])
    if len(filas) > MAX_FILAS:
        notas.append(
            f"Se muestran las primeras {MAX_FILAS} filas de {len(filas)}. "
            "Acota el periodo o la sucursal para ver el resto."
        )
        filas = filas[:MAX_FILAS]
    return {
        "titulo": titulo,
        "subtitulo": subtitulo,
        "kpis": kpis,
        "columnas": columnas,
        "filas": filas,
        "notas": notas,
        "grafico": grafico,
    }

def _kpi(etiqueta, valor, tipo="numero"):
    """Un indicador destacado del resultado."""
    return {"etiqueta": etiqueta, "valor": valor, "tipo": tipo}

def _col(nombre, tipo="texto"):
    """Una columna de la tabla del resultado."""
    return {"nombre": nombre, "tipo": tipo}

def _fecha_local(momento):
    """Fecha (hora de Bolivia) de un datetime."""
    return timezone.localtime(momento).date()

# ---------------------------------------------------------------- inventario
def _cargar_stock(sucursal):
    """Una fila por variante y sucursal, con su cantidad y su mínimo."""
    stocks = _por_empresa(StockItem.objects.filter(
        estado=True, id_variante__id_producto__estado="ACTIVO"
    )).select_related(
        "id_sucursal__id_empresa",
        "id_variante__id_producto__id_categoria",
        "id_variante__id_talla",
        "id_variante__id_color",
    )
    if sucursal:
        stocks = stocks.filter(id_sucursal__nombre=sucursal)
    filas = []
    for s in stocks:
        v = s.id_variante
        p = v.id_producto
        filas.append(
            {
                "id_producto": p.id_producto,
                "prenda": p.nombre,
                "categoria": p.id_categoria.nombre,
                "talla": v.id_talla.nombre,
                "color": v.id_color.nombre,
                "sucursal": _nombre_sucursal(s.id_sucursal),
                "cantidad": s.cantidad,
                "minimo": s.stock_minimo,
                "tokens": set(
                    _tokens(
                        " ".join(
                            [
                                p.nombre,
                                p.tipo_prenda or "",
                                p.id_categoria.nombre,
                                v.id_color.nombre,
                                v.id_talla.nombre,
                            ]
                        )
                    )
                ),
            }
        )
    return filas

def _estado_stock(fila):
    """Agotado, Bajo (en o bajo su mínimo) u OK."""
    if fila["cantidad"] <= 0:
        return "Agotado"
    if fila["cantidad"] <= fila["minimo"]:
        return "Bajo"
    return "OK"

def _grafico_por_sucursal(filas, titulo):
    """Barras con las unidades en stock de cada sucursal (si hay más de una)."""
    por_sucursal = {}
    for f in filas:
        por_sucursal[f["sucursal"]] = por_sucursal.get(f["sucursal"], 0) + f["cantidad"]
    if len(por_sucursal) < 2:
        return None
    orden = sorted(por_sucursal.items(), key=lambda x: -x[1])[:MAX_BARRAS]
    return _grafico(
        "bar", titulo, [k for k, _ in orden], [("Unidades", [v for _, v in orden])]
    )

def _armar_inventario(filas, args, sucursal, notas):
    """Filtra y resume el stock según texto, categoría, talla, color y estado."""
    texto = _palabras_utiles(args.get("texto"))
    talla = _norm(args.get("talla"))
    color = args.get("color")
    categoria = args.get("categoria")
    solo_bajo = _verdadero(args.get("solo_bajo_stock"))

    elegidas = []
    for f in filas:
        if talla and _norm(f["talla"]) != talla:
            continue
        if _norm(color) and not _coincide(color, f["color"]):
            continue
        if _norm(categoria) and not _coincide(categoria, f["categoria"]):
            continue
        if solo_bajo and _estado_stock(f) == "OK":
            continue
        puntos = sum(1 for p in texto if p in f["tokens"]) if texto else 0
        if texto and puntos == 0:
            continue
        elegidas.append((puntos, f))
    if texto and elegidas:
        mejor = max(p for p, _ in elegidas)
        elegidas = [(p, f) for p, f in elegidas if p == mejor]

    elegidas = [f for _, f in elegidas]
    elegidas.sort(
        key=lambda f: (
            _norm(f["prenda"]),
            _norm(f["sucursal"]),
            _orden_talla(f["talla"]),
            _norm(f["color"]),
        )
    )
    filas_tabla = [
        [
            f["prenda"],
            f["categoria"],
            f["talla"],
            f["color"],
            f["sucursal"],
            f["cantidad"],
            f["minimo"],
            _estado_stock(f),
        ]
        for f in elegidas
    ]
    kpis = [
        _kpi("Unidades en stock", sum(f["cantidad"] for f in elegidas)),
        _kpi("Variantes listadas", len(elegidas)),
        _kpi("Con stock bajo", sum(1 for f in elegidas if _estado_stock(f) == "Bajo")),
        _kpi("Agotadas", sum(1 for f in elegidas if _estado_stock(f) == "Agotado")),
    ]
    extra = []
    if _norm(args.get("texto")):
        extra.append(f"Prenda: {args.get('texto')}")
    if _norm(categoria):
        extra.append(f"Categoría: {categoria}")
    if solo_bajo:
        extra.append("Solo stock bajo")
    if not elegidas:
        notas = list(notas) + ["No hay variantes que coincidan con esos filtros."]
    return _resultado(
        "Inventario",
        _subtitulo(None, sucursal, extra),
        kpis,
        [
            _col("Prenda"),
            _col("Categoría"),
            _col("Talla"),
            _col("Color"),
            _col("Sucursal"),
            _col("Cantidad", "numero"),
            _col("Mínimo", "numero"),
            _col("Estado"),
        ],
        filas_tabla,
        notas,
        _grafico_por_sucursal(elegidas, "Unidades en stock por sucursal"),
    )

def consultar_inventario(args, usuario):
    """Stock por prenda y sucursal: cuánto queda, qué está bajo o agotado."""
    sucursal, nota = _sucursal(args, usuario)
    return _armar_inventario(_cargar_stock(sucursal), args, sucursal, [nota] if nota else [])

def menor_existencia(args, usuario):
    """NUEVO (CU13): variantes con menos unidades en stock (de menor a mayor)."""
    sucursal, nota = _sucursal(args, usuario)
    filtro, notas = _filtros(args)
    notas = ([nota] if nota else []) + notas
    limite = _entero(args.get("limite"), LIMITE_TOP, 1, MAX_TOP)
    filas = [] if filtro["invalido"] else _cargar_stock(sucursal)
    if filtro["categoria"]:
        filas = [f for f in filas if f["categoria"] == filtro["categoria"]]
    if filtro["prendas"] is not None:
        filas = [f for f in filas if f["id_producto"] in filtro["prendas"]]
    filas.sort(key=lambda f: (f["cantidad"], f["cantidad"] - f["minimo"], _norm(f["prenda"])))
    ranking = filas[:limite]

    kpis = [
        _kpi("Variantes revisadas", len(filas)),
        _kpi("Agotadas", sum(1 for f in filas if _estado_stock(f) == "Agotado")),
        _kpi("Con stock bajo", sum(1 for f in filas if _estado_stock(f) == "Bajo")),
        _kpi("Unidades en el top", sum(f["cantidad"] for f in ranking)),
    ]
    if not ranking:
        notas.append("No hay stock registrado con esos filtros.")
    etiquetas = [
        f"{f['prenda']} {f['talla']}/{f['color']} · {f['sucursal']}" for f in ranking[:MAX_BARRAS]
    ]
    return _resultado(
        f"Prendas con menor existencia (top {limite})",
        _subtitulo(None, sucursal, _extra_filtros(filtro)),
        kpis,
        [
            _col("Puesto", "numero"),
            _col("Prenda"),
            _col("Categoría"),
            _col("Talla"),
            _col("Color"),
            _col("Sucursal"),
            _col("Cantidad", "numero"),
            _col("Mínimo", "numero"),
            _col("Estado"),
        ],
        [
            [
                i,
                f["prenda"],
                f["categoria"],
                f["talla"],
                f["color"],
                f["sucursal"],
                f["cantidad"],
                f["minimo"],
                _estado_stock(f),
            ]
            for i, f in enumerate(ranking, start=1)
        ],
        notas,
        _grafico(
            "barh",
            "Unidades disponibles",
            etiquetas,
            [("Unidades", [f["cantidad"] for f in ranking[:MAX_BARRAS]])],
        ),
    )

# ---------------------------------------------------------------- ventas netas
def _movimiento(tipo, clave, canal, empresa, fecha, sucursal, metodo, total, **extra):
    """Un movimiento de venta (monto positivo) o de devolución (monto negativo)."""
    fila = {
        "tipo": tipo,
        "clave": clave,
        "canal": canal,
        "empresa": empresa,
        "fecha": fecha,
        "sucursal": sucursal,
        "metodo": metodo,
        "total": total,
        "categoria": None,
        "prenda": None,
        "unidades": 0,
        "conflicto": False,
    }
    fila.update(extra)
    return fila

def _movimientos_por_venta(desde, hasta, sucursal, canal):
    """Ventas POS (sin anuladas), pedidos pagados y reembolsos, por venta completa."""
    filas = []
    if canal in (None, "pos"):
        qs = _por_empresa(
            PosSale.objects.exclude(estado="ANULADA").select_related(
                "id_sucursal__id_empresa", "id_empresa"
            )
        )
        qs = _entre(qs, "fecha_venta", desde, hasta)
        if sucursal:
            qs = qs.filter(id_sucursal__nombre=sucursal)
        for v in qs:
            filas.append(
                _movimiento(
                    "venta", ("pos", v.id_venta), CANAL_POS, _nombre_empresa(v),
                    _fecha_local(v.fecha_venta), _nombre_sucursal(v.id_sucursal),
                    v.get_metodo_pago_display(), _dinero(v.total),
                    conflicto=v.estado == "EN_CONFLICTO",
                )
            )
    if canal in (None, "web"):
        qs = _por_empresa(
            Order.objects.filter(estado__in=ESTADOS_PAGADOS).select_related(
                "id_sucursal__id_empresa", "id_empresa"
            )
        )
        qs = _entre(qs, "fecha_creacion", desde, hasta)
        if sucursal:
            qs = qs.filter(id_sucursal__nombre=sucursal)
        for o in qs:
            filas.append(
                _movimiento(
                    "venta", ("web", o.id_orden), CANAL_WEB, _nombre_empresa(o),
                    _fecha_local(o.fecha_creacion), _nombre_sucursal(o.id_sucursal),
                    o.get_metodo_pago_display() if o.metodo_pago else "Sin método",
                    _dinero(o.total),
                )
            )
    qs = _por_empresa(
        Devolucion.objects.filter(estado="COMPLETADA", fecha_completado__isnull=False)
        .select_related("id_sucursal__id_empresa", "id_empresa", "id_venta", "id_orden")
    )
    qs = _entre(qs, "fecha_completado", desde, hasta)
    if canal == "pos":
        qs = qs.filter(id_venta__isnull=False)
    elif canal == "web":
        qs = qs.filter(id_orden__isnull=False)
    if sucursal:
        qs = qs.filter(id_sucursal__nombre=sucursal)
    for d in qs:
        origen = d.id_venta if d.id_venta_id else d.id_orden
        metodo = "Sin método"
        if origen is not None and origen.metodo_pago:
            metodo = origen.get_metodo_pago_display()
        filas.append(
            _movimiento(
                "devolucion", ("dev", d.id_devolucion),
                CANAL_POS if d.id_venta_id else CANAL_WEB, _nombre_empresa(d),
                _fecha_local(d.fecha_completado), _nombre_sucursal(d.id_sucursal),
                metodo, -_dinero(d.monto_reembolso),
            )
        )
    return filas

def _filtrar_lineas(qs, filtro, prefijo):
    """Aplica los filtros de categoría y prenda a líneas de venta o pedido."""
    if filtro and filtro["categoria"]:
        qs = qs.filter(**{f"{prefijo}id_variante__id_producto__id_categoria__nombre": filtro["categoria"]})
    if filtro and filtro["prendas"] is not None:
        qs = qs.filter(**{f"{prefijo}id_variante__id_producto__in": filtro["prendas"]})
    return qs

def _movimientos_por_prenda(desde, hasta, sucursal, canal, filtro):
    """Líneas vendidas (POS sin anuladas y pedidos pagados) y prendas devueltas."""
    filas = []
    relacion_prenda = "id_variante__id_producto__id_categoria"
    if canal in (None, "pos"):
        qs = _por_empresa(
            PosSaleItem.objects.exclude(id_venta__estado="ANULADA").select_related(
                "id_venta__id_sucursal__id_empresa", "id_venta__id_empresa", relacion_prenda
            ),
            "id_venta__id_empresa",
        )
        qs = _filtrar_lineas(_entre(qs, "id_venta__fecha_venta", desde, hasta), filtro, "")
        if sucursal:
            qs = qs.filter(id_venta__id_sucursal__nombre=sucursal)
        for it in qs:
            v, p = it.id_venta, it.id_variante.id_producto
            filas.append(
                _movimiento(
                    "venta", ("pos", v.id_venta), CANAL_POS, _nombre_empresa(v),
                    _fecha_local(v.fecha_venta), _nombre_sucursal(v.id_sucursal),
                    v.get_metodo_pago_display(), _dinero(it.subtotal),
                    categoria=p.id_categoria.nombre, prenda=p.nombre,
                    unidades=it.cantidad, conflicto=v.estado == "EN_CONFLICTO",
                )
            )
    if canal in (None, "web"):
        qs = _por_empresa(
            OrderItem.objects.filter(id_orden__estado__in=ESTADOS_PAGADOS).select_related(
                "id_orden__id_sucursal__id_empresa", "id_orden__id_empresa", relacion_prenda
            ),
            "id_orden__id_empresa",
        )
        qs = _filtrar_lineas(_entre(qs, "id_orden__fecha_creacion", desde, hasta), filtro, "")
        if sucursal:
            qs = qs.filter(id_orden__id_sucursal__nombre=sucursal)
        for it in qs:
            o, p = it.id_orden, it.id_variante.id_producto
            filas.append(
                _movimiento(
                    "venta", ("web", o.id_orden), CANAL_WEB, _nombre_empresa(o),
                    _fecha_local(o.fecha_creacion), _nombre_sucursal(o.id_sucursal),
                    o.get_metodo_pago_display() if o.metodo_pago else "Sin método",
                    _dinero(it.subtotal),
                    categoria=p.id_categoria.nombre, prenda=p.nombre, unidades=it.cantidad,
                )
            )
    qs = _por_empresa(
        DevolucionItem.objects.filter(
            id_devolucion__estado="COMPLETADA", id_devolucion__fecha_completado__isnull=False
        ).select_related(
            "id_devolucion__id_sucursal__id_empresa",
            "id_devolucion__id_empresa",
            "id_devolucion__id_venta",
            "id_devolucion__id_orden",
            f"id_venta_item__{relacion_prenda}",
            f"id_orden_item__{relacion_prenda}",
        ),
        "id_devolucion__id_empresa",
    )
    qs = _entre(qs, "id_devolucion__fecha_completado", desde, hasta)
    if canal == "pos":
        qs = qs.filter(id_venta_item__isnull=False)
    elif canal == "web":
        qs = qs.filter(id_orden_item__isnull=False)
    if sucursal:
        qs = qs.filter(id_devolucion__id_sucursal__nombre=sucursal)
    if filtro and filtro["categoria"]:
        campo = "id_variante__id_producto__id_categoria__nombre"
        qs = qs.filter(
            Q(**{f"id_venta_item__{campo}": filtro["categoria"]})
            | Q(**{f"id_orden_item__{campo}": filtro["categoria"]})
        )
    if filtro and filtro["prendas"] is not None:
        qs = qs.filter(
            Q(id_venta_item__id_variante__id_producto__in=filtro["prendas"])
            | Q(id_orden_item__id_variante__id_producto__in=filtro["prendas"])
        )
    for di in qs:
        linea = di.id_venta_item or di.id_orden_item
        if linea is None:
            continue
        d, p = di.id_devolucion, linea.id_variante.id_producto
        origen = d.id_venta if d.id_venta_id else d.id_orden
        metodo = "Sin método"
        if origen is not None and origen.metodo_pago:
            metodo = origen.get_metodo_pago_display()
        filas.append(
            _movimiento(
                "devolucion", ("dev", d.id_devolucion),
                CANAL_POS if di.id_venta_item_id else CANAL_WEB, _nombre_empresa(d),
                _fecha_local(d.fecha_completado), _nombre_sucursal(d.id_sucursal),
                metodo, -_dinero(di.monto_reembolso),
                categoria=p.id_categoria.nombre, prenda=p.nombre, unidades=-di.cantidad,
            )
        )
    return filas

def _cargar_movimientos(rango, sucursal, canal=None, filtro=None, por_prenda=False):
    """Movimientos del periodo: por venta completa o, con filtros, por prenda."""
    desde, hasta, _ = rango
    if por_prenda or _con_filtro_de_prendas(filtro):
        return _movimientos_por_prenda(desde, hasta, sucursal, canal, filtro)
    return _movimientos_por_venta(desde, hasta, sucursal, canal)

def _totales(movimientos):
    """(ventas distintas, vendido, devuelto, neto) de una lista de movimientos."""
    ventas = {m["clave"] for m in movimientos if m["tipo"] == "venta"}
    vendido = round(sum(m["total"] for m in movimientos if m["tipo"] == "venta"), 2)
    devuelto = round(-sum(m["total"] for m in movimientos if m["tipo"] == "devolucion"), 2)
    return len(ventas), vendido, devuelto, round(vendido - devuelto, 2)

def _nota_conflictos(movimientos):
    """Aviso de ventas sin conexión en conflicto incluidas en el total."""
    en_conflicto = {}
    for m in movimientos:
        if m["tipo"] == "venta" and m["conflicto"]:
            en_conflicto[m["clave"]] = en_conflicto.get(m["clave"], 0) + m["total"]
    if not en_conflicto:
        return []
    monto = round(sum(en_conflicto.values()), 2)
    return [
        f"Incluye {len(en_conflicto)} venta(s) sin conexión en conflicto por Bs {monto:.2f}, "
        "pendientes de revisión (el efectivo ya se recibió)."
    ]

def _nota_sin_detalle(rango, sucursal, canal=None):
    """Aviso de ventas pagadas sin prendas registradas (no se pueden desglosar).

    Solo lee: cuenta los pedidos pagados y ventas POS del periodo que no
    tienen líneas de prendas, para explicar por qué un reporte por prenda o
    categoría suma menos que el reporte de ventas.
    """
    desde, hasta, _ = rango
    cantidad, monto = 0, 0.0
    if canal in (None, "web"):
        qs = _por_empresa(Order.objects.filter(estado__in=ESTADOS_PAGADOS, orderitem__isnull=True))
        qs = _entre(qs, "fecha_creacion", desde, hasta)
        if sucursal:
            qs = qs.filter(id_sucursal__nombre=sucursal)
        datos = qs.aggregate(n=Count("id_orden", distinct=True), total=Sum("total"))
        cantidad += datos["n"] or 0
        monto += float(datos["total"] or 0)
    if canal in (None, "pos"):
        qs = _por_empresa(PosSale.objects.exclude(estado="ANULADA").filter(items__isnull=True))
        qs = _entre(qs, "fecha_venta", desde, hasta)
        if sucursal:
            qs = qs.filter(id_sucursal__nombre=sucursal)
        datos = qs.aggregate(n=Count("id_venta", distinct=True), total=Sum("total"))
        cantidad += datos["n"] or 0
        monto += float(datos["total"] or 0)
    if not cantidad:
        return []
    return [
        f"{cantidad} venta(s) pagada(s) por Bs {monto:.2f} no tienen detalle de prendas "
        "y no entran en este reporte (sí cuentan en el reporte de ventas)."
    ]

def _armar_ventas(movimientos, agrupar, etiqueta, sucursal, canal, filtro, notas, detalle=None):
    """Ventas netas agrupadas por día, semana, mes, sucursal, método, canal, empresa o categoría."""
    grupos, etiquetas = {}, {}
    for m in movimientos:
        if agrupar in ("dia", "semana", "mes"):
            clave, texto = _periodo_de(m["fecha"], agrupar)
        else:
            clave = m[agrupar] or "Sin dato"
            texto = clave
        etiquetas[clave] = texto
        grupos.setdefault(clave, []).append(m)

    resumen = {clave: _totales(lista) for clave, lista in grupos.items()}
    if agrupar in ("dia", "semana", "mes"):
        orden = sorted(resumen.items(), key=lambda x: x[0])
    else:
        orden = sorted(resumen.items(), key=lambda x: -x[1][3])
    filas = [[etiquetas[k], n, vendido, devuelto, neto] for k, (n, vendido, devuelto, neto) in orden]

    cantidad, vendido, devuelto, neto = _totales(movimientos)
    kpis = [
        _kpi("Total neto", neto, "dinero"),
        _kpi("Total vendido", vendido, "dinero"),
        _kpi("Devoluciones", devuelto, "dinero"),
        _kpi("Ventas realizadas", cantidad),
        _kpi("Ticket promedio", round(vendido / cantidad, 2) if cantidad else 0, "dinero"),
    ]
    if canal is None:
        for nombre in (CANAL_POS, CANAL_WEB):
            del_canal = [m for m in movimientos if m["canal"] == nombre]
            kpis.append(_kpi(f"{nombre} (neto)", _totales(del_canal)[3], "dinero"))

    extra = []
    if canal:
        extra.append("Canal: " + (CANAL_POS if canal == "pos" else CANAL_WEB))
    extra.extend(_extra_filtros(filtro))
    extra.append(f"Agrupado por: {GRUPOS_VENTAS[agrupar].lower()}")
    notas = list(notas) + _nota_conflictos(movimientos)
    if movimientos and movimientos[0]["prenda"] is not None:
        notas.append("Se suman solo las prendas vendidas (sin costo de envío).")
        notas.extend(detalle or [])
    if not movimientos:
        notas.append("No hay ventas registradas en ese periodo.")

    visibles = orden if agrupar in ("dia", "semana", "mes") else orden[:MAX_BARRAS]
    grafico = _grafico(
        GRAFICO_VENTAS[agrupar],
        f"Ventas netas por {GRUPOS_VENTAS[agrupar].lower()} (Bs)",
        [etiquetas[k] for k, _ in visibles],
        [("Neto (Bs)", [v[3] for _, v in visibles])],
        "dinero",
    )
    return _resultado(
        "Ventas",
        _subtitulo(etiqueta, sucursal, extra),
        kpis,
        [
            _col(GRUPOS_VENTAS[agrupar]),
            _col("Ventas", "numero"),
            _col("Vendido (Bs)", "dinero"),
            _col("Devuelto (Bs)", "dinero"),
            _col("Neto (Bs)", "dinero"),
        ],
        filas,
        notas,
        grafico,
    )

def _canal(valor):
    """'pos' o 'web' según el texto, o None para ambos."""
    v = _norm(valor)
    if v in ("pos", "punto de venta", "presencial", "caja", "tienda"):
        return "pos"
    if v in ("web", "app", "online", "digital", "internet", "movil"):
        return "web"
    return None

def consultar_ventas(args, usuario):
    """Ventas netas por periodo, sucursal, canal, categoría y prenda."""
    rango = _rango(args, "mes")
    sucursal, nota = _sucursal(args, usuario)
    canal = _canal(args.get("canal"))
    filtro, notas = _filtros(args)
    agrupar = ALIAS_AGRUPAR.get(_norm(args.get("agrupar_por")), "dia")
    movimientos, detalle = [], []
    por_prenda = agrupar == "categoria" or _con_filtro_de_prendas(filtro)
    if not filtro["invalido"]:
        movimientos = _cargar_movimientos(rango, sucursal, canal, filtro, por_prenda=por_prenda)
        if por_prenda:
            detalle = _nota_sin_detalle(rango, sucursal, canal)
    return _armar_ventas(
        movimientos, agrupar, rango[2], sucursal, canal, filtro,
        ([nota] if nota else []) + notas, detalle,
    )

def _por_prenda(movimientos):
    """{prenda: [unidades netas, monto neto]} de movimientos por prenda."""
    por_prenda = {}
    for m in movimientos:
        acumulado = por_prenda.setdefault(m["prenda"], [0, 0.0])
        acumulado[0] += m["unidades"]
        acumulado[1] += m["total"]
    return por_prenda

def productos_mas_vendidos(args, usuario):
    """Ranking de prendas por unidades vendidas (netas de devoluciones)."""
    rango = _rango(args, "mes")
    sucursal, nota = _sucursal(args, usuario)
    filtro, notas = _filtros(args)
    notas = ([nota] if nota else []) + notas
    limite = _entero(args.get("limite"), LIMITE_TOP, 1, MAX_TOP)
    movimientos = [] if filtro["invalido"] else _cargar_movimientos(
        rango, sucursal, None, filtro, por_prenda=True
    )
    por_prenda = {k: v for k, v in _por_prenda(movimientos).items() if v[0] > 0}
    ranking = sorted(por_prenda.items(), key=lambda x: (-x[1][0], -x[1][1], x[0]))[:limite]

    kpis = [
        _kpi("Prendas distintas vendidas", len(por_prenda)),
        _kpi("Unidades vendidas (netas)", sum(u for u, _ in por_prenda.values())),
        _kpi("Total neto", round(sum(t for _, t in por_prenda.values()), 2), "dinero"),
    ]
    if not ranking:
        notas.append("No hay ventas de prendas en ese periodo.")
    notas.extend(_nota_conflictos(movimientos))
    if not filtro["invalido"]:
        notas.extend(_nota_sin_detalle(rango, sucursal))
    return _resultado(
        f"Prendas más vendidas (top {limite})",
        _subtitulo(rango[2], sucursal, _extra_filtros(filtro)),
        kpis,
        [_col("Puesto", "numero"), _col("Prenda"), _col("Unidades", "numero"), _col("Total (Bs)", "dinero")],
        [[i, nombre, u, round(t, 2)] for i, (nombre, (u, t)) in enumerate(ranking, start=1)],
        notas,
        _grafico(
            "barh",
            "Unidades vendidas",
            [nombre for nombre, _ in ranking[:MAX_BARRAS]],
            [("Unidades", [u for _, (u, _t) in ranking[:MAX_BARRAS]])],
        ),
    )

def categorias_mas_ingresos(args, usuario):
    """NUEVO (CU13): categorías ordenadas por ingresos netos del periodo."""
    rango = _rango(args, "mes")
    sucursal, nota = _sucursal(args, usuario)
    filtro, notas = _filtros({"categoria": args.get("categoria")})
    notas = ([nota] if nota else []) + notas
    movimientos = [] if filtro["invalido"] else _cargar_movimientos(
        rango, sucursal, _canal(args.get("canal")), filtro, por_prenda=True
    )
    por_categoria = {}
    for m in movimientos:
        acumulado = por_categoria.setdefault(m["categoria"], [0, 0.0])
        acumulado[0] += m["unidades"]
        acumulado[1] += m["total"]
    total = sum(t for _, t in por_categoria.values())
    orden = sorted(por_categoria.items(), key=lambda x: -x[1][1])
    filas = [
        [i, nombre, u, round(t, 2), round(t * 100 / total, 1) if total else 0]
        for i, (nombre, (u, t)) in enumerate(orden, start=1)
    ]
    kpis = [
        _kpi("Ingresos netos", round(total, 2), "dinero"),
        _kpi("Categorías con ventas", len(por_categoria)),
        _kpi("Unidades vendidas (netas)", sum(u for u, _ in por_categoria.values())),
    ]
    if orden:
        kpis.append(_kpi("Categoría líder", orden[0][0], "texto"))
    else:
        notas.append("No hay ventas de prendas en ese periodo.")
    visibles = orden[:MAX_BARRAS]
    return _resultado(
        "Categorías con más ingresos",
        _subtitulo(rango[2], sucursal, _extra_filtros(filtro)),
        kpis,
        [
            _col("Puesto", "numero"),
            _col("Categoría"),
            _col("Unidades", "numero"),
            _col("Ingresos (Bs)", "dinero"),
            _col("% del total", "numero"),
        ],
        filas,
        notas + _nota_conflictos(movimientos)
        + ([] if filtro["invalido"] else _nota_sin_detalle(rango, sucursal, _canal(args.get("canal")))),
        _grafico(
            "doughnut" if len(visibles) <= 8 else "bar",
            "Ingresos netos por categoría (Bs)",
            [k for k, _ in visibles],
            [("Ingresos (Bs)", [round(v[1], 2) for _, v in visibles])],
            "dinero",
        ),
    )

def comparativo_sucursales(args, usuario):
    """NUEVO (CU13): ventas netas de cada sucursal mes a mes (últimos N meses)."""
    hoy = timezone.localdate()
    sucursal, nota = _sucursal(args, usuario)
    filtro, notas = _filtros(args)
    notas = ([nota] if nota else []) + notas
    if _fecha(args.get("desde")) or _fecha(args.get("hasta")):
        rango = _rango(args, "mes")
        inicio = (rango[0] or _sumar_meses(hoy, -(MAX_MESES - 1))).replace(day=1)
        fin = rango[1] or hoy
        rango = (inicio, fin, rango[2])
    else:
        meses = _entero(args.get("meses"), MESES_COMPARATIVO, 1, MAX_MESES)
        inicio, fin = _sumar_meses(hoy, -(meses - 1)), hoy
        rango = (inicio, fin, f"últimos {meses} meses ({_fmt(inicio)} al {_fmt(fin)})")
    lista_meses = []
    actual = inicio.replace(day=1)
    while actual <= fin and len(lista_meses) < MAX_MESES:
        lista_meses.append((actual.year, actual.month))
        actual = _sumar_meses(actual, 1)
    if len(lista_meses) == MAX_MESES and actual <= fin:
        notas.append(f"Se muestran como máximo {MAX_MESES} meses.")
        fin = actual - timedelta(days=1)
        rango = (inicio, fin, rango[2])

    movimientos = [] if filtro["invalido"] else _cargar_movimientos(
        rango, sucursal, None, filtro
    )
    sucursales = _por_empresa(
        Sucursal.objects.filter(estado="ACTIVA").select_related("id_empresa")
    ).order_by("id_empresa__nombre", "nombre")
    if sucursal:
        sucursales = sucursales.filter(nombre=sucursal)
    tabla = {_nombre_sucursal(s): {m: 0.0 for m in lista_meses} for s in sucursales}
    for m in movimientos:
        clave = (m["fecha"].year, m["fecha"].month)
        fila = tabla.setdefault(m["sucursal"], {mes: 0.0 for mes in lista_meses})
        if clave in fila:
            fila[clave] += m["total"]
    nombres_meses = [_nombre_mes(a, m) for a, m in lista_meses]
    orden = sorted(tabla.items(), key=lambda x: -sum(x[1].values()))
    filas = [
        [nombre] + [round(valores[mes], 2) for mes in lista_meses] + [round(sum(valores.values()), 2)]
        for nombre, valores in orden
    ]
    total = round(sum(sum(v.values()) for v in tabla.values()), 2)
    kpis = [
        _kpi("Total neto", total, "dinero"),
        _kpi("Sucursales comparadas", len(tabla)),
        _kpi("Meses", len(lista_meses)),
    ]
    if orden and total:
        kpis.append(_kpi("Sucursal líder", orden[0][0], "texto"))
    if not movimientos:
        notas.append("No hay ventas registradas en ese periodo.")
    notas.extend(_nota_conflictos(movimientos))
    if _con_filtro_de_prendas(filtro):
        notas.extend(_nota_sin_detalle(rango, sucursal))
    return _resultado(
        "Comparativo de ventas entre sucursales",
        _subtitulo(rango[2], sucursal, _extra_filtros(filtro)),
        kpis,
        [_col("Sucursal")] + [_col(f"{n} (Bs)", "dinero") for n in nombres_meses]
        + [_col("Total (Bs)", "dinero")],
        filas,
        notas,
        _grafico(
            "bar",
            "Ventas netas por sucursal y mes (Bs)",
            nombres_meses,
            [(nombre, [valores[mes] for mes in lista_meses]) for nombre, valores in orden[:MAX_BARRAS]],
            "dinero",
        ),
    )

# ---------------------------------------------------------------- entregas
def _cargar_entregas(rango, sucursal):
    """Entregas a domicilio del periodo, con su pedido y sucursal."""
    desde, hasta, _ = rango
    qs = _por_empresa(
        Delivery.objects.select_related("id_orden__id_sucursal__id_empresa"),
        "id_orden__id_empresa",
    )
    qs = _entre(qs, "fecha_creacion", desde, hasta)
    if sucursal:
        qs = qs.filter(id_orden__id_sucursal__nombre=sucursal)
    filas = []
    for d in qs:
        orden = d.id_orden
        filas.append(
            {
                "pedido": d.id_orden_id,
                "fecha": _fecha_local(d.fecha_creacion),
                "estado": d.estado,
                "sucursal": _nombre_sucursal(orden.id_sucursal),
                "distancia": float(d.distancia_km),
                "costo": _dinero(d.costo_envio),
            }
        )
    return filas

def _armar_entregas(filas, args, etiqueta, sucursal, notas):
    """Cantidad de entregas por estado y detalle de cada una."""
    estado = _estado(args.get("estado"), ESTADOS_ENTREGA)
    notas = list(notas)
    if _norm(args.get("estado")) and estado is None:
        notas.append(
            f"No existe el estado «{args.get('estado')}»; se muestran todos. "
            f"Estados: {', '.join(ESTADOS_ENTREGA.values())}."
        )
    elegidas = [f for f in filas if estado is None or f["estado"] == estado]
    elegidas.sort(key=lambda f: (f["fecha"], f["pedido"]), reverse=True)

    kpis = [_kpi("Entregas", len(elegidas))]
    conteo = {clave: sum(1 for f in elegidas if f["estado"] == clave) for clave in KPI_ENTREGA}
    for clave, nombre in KPI_ENTREGA.items():
        kpis.append(_kpi(nombre, conteo[clave]))
    kpis.append(_kpi("Costo de envíos", round(sum(f["costo"] for f in elegidas), 2), "dinero"))

    extra = [f"Estado: {ESTADOS_ENTREGA[estado]}"] if estado else []
    if not elegidas:
        notas.append("No hay entregas en ese periodo.")
    con_datos = [c for c in KPI_ENTREGA if conteo[c]]
    return _resultado(
        "Entregas a domicilio",
        _subtitulo(etiqueta, sucursal, extra),
        kpis,
        [
            _col("Pedido", "numero"),
            _col("Fecha"),
            _col("Estado"),
            _col("Sucursal"),
            _col("Distancia (km)", "numero"),
            _col("Costo envío (Bs)", "dinero"),
        ],
        [
            [
                f["pedido"],
                _fmt(f["fecha"]),
                ESTADOS_ENTREGA.get(f["estado"], f["estado"]),
                f["sucursal"],
                f["distancia"],
                f["costo"],
            ]
            for f in elegidas
        ],
        notas,
        _grafico(
            "doughnut",
            "Entregas por estado",
            [ESTADOS_ENTREGA[c] for c in con_datos],
            [("Entregas", [conteo[c] for c in con_datos])],
        ),
    )

def consultar_entregas(args, usuario):
    """Entregas a domicilio por periodo, estado y sucursal."""
    rango = _rango(args, "hoy")
    sucursal, nota = _sucursal(args, usuario)
    filas = _cargar_entregas(rango, sucursal)
    return _armar_entregas(filas, args, rango[2], sucursal, [nota] if nota else [])

# ---------------------------------------------------------------- reservas
def _cargar_reservas(rango, sucursal):
    """Reservas de prendas cuya fecha reservada cae en el periodo."""
    desde, hasta, _ = rango
    qs = _por_empresa(
        FittingReservation.objects.select_related("id_sucursal__id_empresa").prefetch_related("items")
    )
    if desde:
        qs = qs.filter(fecha_reserva__gte=desde)
    if hasta:
        qs = qs.filter(fecha_reserva__lte=hasta)
    if sucursal:
        qs = qs.filter(id_sucursal__nombre=sucursal)
    return [
        {
            "reserva": r.id_reserva,
            "fecha": r.fecha_reserva,
            "hora": r.hora_reserva.strftime("%H:%M"),
            "sucursal": _nombre_sucursal(r.id_sucursal),
            "estado": r.estado,
            "pago": TIPOS_PAGO_RESERVA.get(r.tipo_pago, "-"),
            "prendas": len(r.items.all()),
            "total": _dinero(r.monto_total),
            "pagado": _dinero(r.monto_pagado),
            "retenido": _dinero(r.monto_retenido),
        }
        for r in qs
    ]

def _armar_reservas(filas, args, etiqueta, sucursal, notas):
    """Cantidad de reservas por estado, montos y detalle de cada una."""
    estado = _estado(args.get("estado"), ESTADOS_RESERVA)
    notas = list(notas)
    if _norm(args.get("estado")) and estado is None:
        notas.append(
            f"No existe el estado «{args.get('estado')}»; se muestran todos. "
            f"Estados: {', '.join(ESTADOS_RESERVA.values())}."
        )
    elegidas = [f for f in filas if estado is None or f["estado"] == estado]
    elegidas.sort(key=lambda f: (f["fecha"], f["hora"]))

    conteo = {clave: sum(1 for f in elegidas if f["estado"] == clave) for clave in ESTADOS_RESERVA}
    kpis = [_kpi("Reservas", len(elegidas))]
    for clave, nombre in KPI_RESERVA.items():
        if conteo[clave] or clave in ("CONFIRMADA", "COMPLETADA"):
            kpis.append(_kpi(nombre, conteo[clave]))
    kpis.append(_kpi("Monto pagado", round(sum(f["pagado"] for f in elegidas), 2), "dinero"))
    kpis.append(_kpi("Monto retenido", round(sum(f["retenido"] for f in elegidas), 2), "dinero"))

    extra = [f"Estado: {ESTADOS_RESERVA[estado]}"] if estado else []
    if not elegidas:
        notas.append("No hay reservas en ese periodo.")
    con_datos = [c for c in ESTADOS_RESERVA if conteo[c]]
    return _resultado(
        "Reservas de prendas",
        _subtitulo(etiqueta, sucursal, extra),
        kpis,
        [
            _col("Reserva", "numero"),
            _col("Fecha"),
            _col("Hora"),
            _col("Sucursal"),
            _col("Estado"),
            _col("Pago"),
            _col("Prendas", "numero"),
            _col("Total (Bs)", "dinero"),
            _col("Pagado (Bs)", "dinero"),
            _col("Retenido (Bs)", "dinero"),
        ],
        [
            [
                f["reserva"],
                _fmt(f["fecha"]),
                f["hora"],
                f["sucursal"],
                ESTADOS_RESERVA.get(f["estado"], f["estado"]),
                f["pago"],
                f["prendas"],
                f["total"],
                f["pagado"],
                f["retenido"],
            ]
            for f in elegidas
        ],
        notas,
        _grafico(
            "doughnut",
            "Reservas por estado",
            [ESTADOS_RESERVA[c] for c in con_datos],
            [("Reservas", [conteo[c] for c in con_datos])],
        ),
    )

def consultar_reservas(args, usuario):
    """Reservas de prendas por periodo, estado y sucursal."""
    rango = _rango(args, "mes")
    sucursal, nota = _sucursal(args, usuario)
    filas = _cargar_reservas(rango, sucursal)
    return _armar_reservas(filas, args, rango[2], sucursal, [nota] if nota else [])

# ---------------------------------------------------------------- devoluciones y cambios
def _etapa(estado):
    """Etapa común (Solicitado, Programado...) de un estado de devolución o cambio."""
    for prefijo, nombre in ETAPAS:
        if estado.startswith(prefijo):
            return nombre
    return estado

def devoluciones_y_cambios(args, usuario):
    """NUEVO (CU13): devoluciones (CU12) y cambios de prenda (CU05) del periodo."""
    rango = _rango(args, "mes")
    desde, hasta, _ = rango
    sucursal, nota = _sucursal(args, usuario)
    notas = [nota] if nota else []
    tipo = _norm(args.get("tipo"))
    ver_devoluciones = not tipo.startswith("cambio")
    ver_cambios = not tipo.startswith("devol")

    filas = []
    if ver_devoluciones:
        qs = _por_empresa(
            Devolucion.objects.select_related("id_sucursal__id_empresa").prefetch_related("items")
        )
        qs = _entre(qs, "fecha_creacion", desde, hasta)
        if sucursal:
            qs = qs.filter(id_sucursal__nombre=sucursal)
        for d in qs:
            items = list(d.items.all())
            motivo = MOTIVOS_DEVOLUCION.get(items[0].motivo, items[0].motivo) if items else "-"
            origen = f"Venta POS #{d.id_venta_id}" if d.id_venta_id else f"Pedido #{d.id_orden_id}"
            filas.append(
                {
                    "tipo": "Devolución",
                    "numero": d.numero_nota,
                    "fecha": _fecha_local(d.fecha_creacion),
                    "sucursal": _nombre_sucursal(d.id_sucursal),
                    "origen": origen,
                    "motivo": motivo,
                    "estado": d.estado,
                    "estado_texto": ESTADOS_DEVOLUCION.get(d.estado, d.estado),
                    "prendas": sum(i.cantidad for i in items),
                    "monto": _dinero(d.monto_reembolso) if d.estado == "COMPLETADA" else 0.0,
                }
            )
    if ver_cambios:
        qs = _por_empresa(CambioPrenda.objects.select_related("id_sucursal__id_empresa"))
        qs = _entre(qs, "fecha_solicitud", desde, hasta)
        if sucursal:
            qs = qs.filter(id_sucursal__nombre=sucursal)
        for c in qs:
            if c.id_venta_item_id:
                origen = "Venta POS"
            elif c.id_orden_item_id:
                origen = "Pedido"
            else:
                origen = "-"
            filas.append(
                {
                    "tipo": "Cambio de prenda",
                    "numero": f"CP-{c.id_cambio:06d}",
                    "fecha": _fecha_local(c.fecha_solicitud),
                    "sucursal": _nombre_sucursal(c.id_sucursal),
                    "origen": origen,
                    "motivo": MOTIVOS_CAMBIO.get(c.motivo, c.motivo),
                    "estado": c.estado,
                    "estado_texto": ESTADOS_CAMBIO.get(c.estado, c.estado),
                    "prendas": c.cantidad,
                    "monto": 0.0,
                }
            )
    filas.sort(key=lambda f: (f["fecha"], f["numero"]), reverse=True)

    devoluciones = [f for f in filas if f["tipo"] == "Devolución"]
    cambios = [f for f in filas if f["tipo"] != "Devolución"]
    kpis = []
    if ver_devoluciones:
        kpis += [
            _kpi("Devoluciones", len(devoluciones)),
            _kpi("Devoluciones completadas", sum(1 for f in devoluciones if f["estado"] == "COMPLETADA")),
            _kpi("Reembolsado", round(sum(f["monto"] for f in devoluciones), 2), "dinero"),
        ]
    if ver_cambios:
        kpis += [
            _kpi("Cambios de prenda", len(cambios)),
            _kpi("Cambios completados", sum(1 for f in cambios if f["estado"] == "COMPLETADO")),
        ]
    kpis.append(_kpi("Rechazados", sum(1 for f in filas if f["estado"].startswith("RECHAZ"))))
    if not filas:
        notas.append("No hay devoluciones ni cambios en ese periodo.")
    if ver_cambios and cambios:
        notas.append("Los cambios de prenda no generan reembolso (se entrega otra prenda).")

    etapas = [nombre for _, nombre in ETAPAS]
    series = []
    if ver_devoluciones:
        series.append(
            ("Devoluciones", [sum(1 for f in devoluciones if _etapa(f["estado"]) == e) for e in etapas])
        )
    if ver_cambios:
        series.append(
            ("Cambios", [sum(1 for f in cambios if _etapa(f["estado"]) == e) for e in etapas])
        )
    titulo = "Devoluciones y cambios de prenda"
    if not ver_cambios:
        titulo = "Devoluciones"
    elif not ver_devoluciones:
        titulo = "Cambios de prenda"
    return _resultado(
        titulo,
        _subtitulo(rango[2], sucursal),
        kpis,
        [
            _col("Tipo"),
            _col("Número"),
            _col("Fecha"),
            _col("Sucursal"),
            _col("Origen"),
            _col("Motivo"),
            _col("Estado"),
            _col("Prendas", "numero"),
            _col("Reembolso (Bs)", "dinero"),
        ],
        [
            [
                f["tipo"], f["numero"], _fmt(f["fecha"]), f["sucursal"], f["origen"],
                f["motivo"], f["estado_texto"], f["prendas"], f["monto"],
            ]
            for f in filas
        ],
        notas,
        _grafico("bar", "Solicitudes por estado", etapas, series) if filas else None,
    )

# ---------------------------------------------------------------- ventas sin conexión
def _situacion(operacion):
    """Situación de una venta sin conexión con conflicto."""
    if operacion.estado == "EN_CONFLICTO":
        return "PENDIENTE"
    if operacion.resolucion == "DEVUELTA":
        return "ANULADA"
    return "CONFIRMADA"

def ventas_anuladas_y_conflictos(args, usuario):
    """NUEVO (CU13): ventas sin conexión con conflicto (CU08) y las anuladas."""
    rango = _rango(args, "mes")
    desde, hasta, _ = rango
    sucursal, nota = _sucursal(args, usuario)
    notas = [nota] if nota else []
    situacion = _estado(args.get("situacion"), SITUACIONES_CONFLICTO)
    if _norm(args.get("situacion")) and situacion is None:
        notas.append(
            f"No existe la situación «{args.get('situacion')}»; se muestran todas. "
            f"Situaciones: {', '.join(SITUACIONES_CONFLICTO.values())}."
        )

    base = _entre(
        _por_empresa(SyncOperacion.objects.filter(tipo="VENTA_POS")), "fecha_recepcion", desde, hasta
    )
    if sucursal:
        base = base.filter(id_venta__id_sucursal__nombre=sucursal)
    rechazadas = base.filter(estado="RECHAZADA").count()
    conflictos = base.filter(tipo_conflicto__isnull=False).select_related(
        "id_venta__id_sucursal__id_empresa"
    )
    filas = []
    for op in conflictos:
        clave = _situacion(op)
        if situacion and clave != situacion:
            continue
        venta = op.id_venta
        filas.append(
            {
                "venta": venta.id_venta if venta else None,
                "fecha": _fecha_local(op.fecha_operacion or op.fecha_recepcion),
                "sucursal": _nombre_sucursal(venta.id_sucursal) if venta else "Sin sucursal",
                "conflicto": TIPOS_CONFLICTO.get(op.tipo_conflicto, op.tipo_conflicto),
                "situacion": clave,
                "monto": _dinero(venta.total) if venta else 0.0,
            }
        )
    filas.sort(key=lambda f: (f["fecha"], f["venta"] or 0), reverse=True)

    conteo = {c: sum(1 for f in filas if f["situacion"] == c) for c in SITUACIONES_CONFLICTO}
    kpis = [
        _kpi("Ventas con conflicto", len(filas)),
        _kpi("Pendientes de revisión", conteo["PENDIENTE"]),
        _kpi("Confirmadas", conteo["CONFIRMADA"]),
        _kpi("Anuladas", conteo["ANULADA"]),
        _kpi(
            "Efectivo devuelto",
            round(sum(f["monto"] for f in filas if f["situacion"] == "ANULADA"), 2),
            "dinero",
        ),
        _kpi("Operaciones rechazadas al sincronizar", rechazadas),
    ]
    extra = [f"Situación: {SITUACIONES_CONFLICTO[situacion]}"] if situacion else []
    if not filas:
        notas.append("No hay ventas sin conexión con conflicto en ese periodo.")
    con_datos = [c for c in SITUACIONES_CONFLICTO if conteo[c]]
    return _resultado(
        "Ventas sin conexión: conflictos y anuladas",
        _subtitulo(rango[2], sucursal, extra),
        kpis,
        [
            _col("Venta", "numero"),
            _col("Fecha"),
            _col("Sucursal"),
            _col("Conflicto"),
            _col("Situación"),
            _col("Monto (Bs)", "dinero"),
        ],
        [
            [
                f["venta"], _fmt(f["fecha"]), f["sucursal"], f["conflicto"],
                SITUACIONES_CONFLICTO[f["situacion"]], f["monto"],
            ]
            for f in filas
        ],
        notas,
        _grafico(
            "doughnut",
            "Ventas con conflicto por situación",
            [SITUACIONES_CONFLICTO[c] for c in con_datos],
            [("Ventas", [conteo[c] for c in con_datos])],
        ),
    )

# ---------------------------------------------------------------- precios
def precios_actuales(args, usuario):
    """NUEVO (CU13): precio actual de cada prenda (mínimo y máximo de sus variantes)."""
    filtro, notas = _filtros(args)
    talla = _norm(args.get("talla"))
    color = args.get("color")
    variantes = _por_empresa(
        ProductoVariante.objects.filter(id_producto__estado="ACTIVO")
        .exclude(estado="INACTIVO")
        .select_related("id_producto__id_categoria", "id_producto__id_empresa", "id_talla", "id_color"),
        "id_producto__id_empresa",
    )
    if filtro["categoria"]:
        variantes = variantes.filter(id_producto__id_categoria__nombre=filtro["categoria"])
    if filtro["prendas"] is not None:
        variantes = variantes.filter(id_producto__in=filtro["prendas"])
    if filtro["invalido"]:
        variantes = []
    por_prenda = {}
    for v in variantes:
        if talla and _norm(v.id_talla.nombre) != talla:
            continue
        if _norm(color) and not _coincide(color, v.id_color.nombre):
            continue
        p = v.id_producto
        nombre = p.nombre
        if _todas_las_empresas() and p.id_empresa_id:
            nombre = f"{p.nombre} ({p.id_empresa.nombre})"
        fila = por_prenda.setdefault(
            p.id_producto, {"prenda": nombre, "categoria": p.id_categoria.nombre, "precios": []}
        )
        fila["precios"].append(float(v.precio))
    filas = sorted(por_prenda.values(), key=lambda f: (_norm(f["categoria"]), _norm(f["prenda"])))
    todos = [precio for f in filas for precio in f["precios"]]
    kpis = [
        _kpi("Prendas", len(filas)),
        _kpi("Variantes", len(todos)),
        _kpi("Precio promedio", round(sum(todos) / len(todos), 2) if todos else 0, "dinero"),
        _kpi("Más barato", round(min(todos), 2) if todos else 0, "dinero"),
        _kpi("Más caro", round(max(todos), 2) if todos else 0, "dinero"),
    ]
    extra = _extra_filtros(filtro)
    if talla:
        extra.append(f"Talla: {args.get('talla')}")
    if _norm(color):
        extra.append(f"Color: {color}")
    if not filas:
        notas.append("No hay prendas activas con esos filtros.")
    return _resultado(
        "Precios actuales",
        " · ".join(["Catálogo vigente"] + extra),
        kpis,
        [
            _col("Prenda"),
            _col("Categoría"),
            _col("Variantes", "numero"),
            _col("Precio mínimo (Bs)", "dinero"),
            _col("Precio máximo (Bs)", "dinero"),
        ],
        [
            [f["prenda"], f["categoria"], len(f["precios"]), min(f["precios"]), max(f["precios"])]
            for f in filas
        ],
        notas,
    )

# ---------------------------------------------------------------- empresas y sucursales
def _texto_estado(objeto):
    """Estado legible de un registro (con o sin choices en el modelo)."""
    mostrar = getattr(objeto, "get_estado_display", None)
    return mostrar() if mostrar else str(objeto.estado).capitalize()

def empresas_y_sucursales(args, usuario):
    """NUEVO (CU13): empresas de la plataforma (SUPER_ADMIN) o sucursales de la empresa."""
    rango = _rango(args, "todo")
    desde, hasta, etiqueta = rango
    if _todas_las_empresas():
        empresas = Empresa.objects.select_related("suscripcion__id_plan").annotate(
            activas=Count("sucursales", filter=Q(sucursales__estado="ACTIVA"))
        ).order_by("-fecha_creacion")
        empresas = _entre(empresas, "fecha_creacion", desde, hasta)
        filas = []
        for e in empresas:
            try:
                suscripcion = e.suscripcion
            except ObjectDoesNotExist:
                suscripcion = None
            vence = "-"
            if suscripcion and suscripcion.fecha_vencimiento:
                vence = _fmt(suscripcion.fecha_vencimiento)
            filas.append(
                [
                    e.nombre,
                    _fmt(_fecha_local(e.fecha_creacion)),
                    _texto_estado(e),
                    suscripcion.id_plan.nombre if suscripcion else "Sin plan",
                    _texto_estado(suscripcion) if suscripcion else "-",
                    vence,
                    e.activas,
                ]
            )
        kpis = [
            _kpi("Empresas", len(filas)),
            _kpi("Empresas activas", sum(1 for e in empresas if e.estado == "ACTIVA")),
            _kpi("Sucursales activas", sum(f[6] for f in filas)),
        ]
        visibles = sorted(filas, key=lambda f: -f[6])[:MAX_BARRAS]
        return _resultado(
            "Empresas de la plataforma",
            f"Registradas: {etiqueta}",
            kpis,
            [
                _col("Empresa"),
                _col("Registro"),
                _col("Estado"),
                _col("Plan"),
                _col("Suscripción"),
                _col("Vence"),
                _col("Sucursales activas", "numero"),
            ],
            filas,
            [] if filas else ["No hay empresas registradas en ese periodo."],
            _grafico(
                "bar", "Sucursales activas por empresa",
                [f[0] for f in visibles], [("Sucursales", [f[6] for f in visibles])],
            ),
        )

    sucursales = _por_empresa(Sucursal.objects.select_related("id_ciudad")).order_by("-fecha_creacion")
    sucursales = _entre(sucursales, "fecha_creacion", desde, hasta)
    filas = [
        [
            s.nombre,
            s.id_ciudad.nombre,
            s.direccion,
            _fmt(s.fecha_apertura) if s.fecha_apertura else "-",
            _fmt(_fecha_local(s.fecha_creacion)),
            s.get_estado_display(),
        ]
        for s in sucursales
    ]
    kpis = [
        _kpi("Sucursales", len(filas)),
        _kpi("Activas", sum(1 for s in sucursales if s.estado == "ACTIVA")),
    ]
    return _resultado(
        "Sucursales de la empresa",
        f"Registradas: {etiqueta}",
        kpis,
        [
            _col("Sucursal"),
            _col("Ciudad"),
            _col("Dirección"),
            _col("Apertura"),
            _col("Registro"),
            _col("Estado"),
        ],
        filas,
        [] if filas else ["No hay sucursales registradas en ese periodo."],
    )

# ---------------------------------------------------------------- vestidor
def _cargar_pruebas(rango):
    """Pruebas en el vestidor virtual por prenda en el periodo."""
    desde, hasta, _ = rango
    qs = _por_empresa(ARTryOnSession.objects.all(), "id_producto__id_empresa")
    qs = _entre(qs, "fecha_sesion", desde, hasta)
    agregados = qs.values("id_producto__nombre").annotate(pruebas=Count("id_sesion"))
    return [
        {"prenda": r["id_producto__nombre"], "pruebas": int(r["pruebas"])}
        for r in agregados
    ]

def _armar_pruebas(filas, args, etiqueta, notas):
    """Prendas más probadas en el vestidor virtual."""
    limite = _entero(args.get("limite"), LIMITE_TOP, 1, MAX_TOP)
    ranking = sorted(filas, key=lambda f: (-f["pruebas"], f["prenda"]))[:limite]
    kpis = [
        _kpi("Pruebas realizadas", sum(f["pruebas"] for f in filas)),
        _kpi("Prendas probadas", len(filas)),
    ]
    if not ranking:
        notas = list(notas) + ["No hay pruebas en el vestidor virtual en ese periodo."]
    return _resultado(
        f"Uso del vestidor virtual (top {limite})",
        _subtitulo(etiqueta, None),
        kpis,
        [_col("Puesto", "numero"), _col("Prenda"), _col("Pruebas", "numero")],
        [[i, f["prenda"], f["pruebas"]] for i, f in enumerate(ranking, start=1)],
        notas,
        _grafico(
            "barh", "Pruebas por prenda",
            [f["prenda"] for f in ranking[:MAX_BARRAS]],
            [("Pruebas", [f["pruebas"] for f in ranking[:MAX_BARRAS]])],
        ),
    )

def uso_vestidor_virtual(args, usuario):
    """Prendas más probadas en el vestidor virtual (realidad aumentada)."""
    rango = _rango(args, "mes")
    return _armar_pruebas(_cargar_pruebas(rango), args, rango[2], [])

# ---------------------------------------------------------------- resumen
def resumen_general(args, usuario):
    """Indicadores clave del periodo: ventas netas, entregas, reservas, stock y más."""
    rango = _rango(args, "hoy")
    sucursal, nota = _sucursal(args, usuario)
    movimientos = _cargar_movimientos(rango, sucursal)
    entregas = _cargar_entregas(rango, sucursal)
    reservas = _cargar_reservas(rango, sucursal)
    stock = _cargar_stock(sucursal)
    pruebas = _cargar_pruebas(rango)
    notas = ([nota] if nota else []) + _nota_conflictos(movimientos)

    cantidad, vendido, devuelto, neto = _totales(movimientos)
    bajo = sum(1 for f in stock if _estado_stock(f) == "Bajo")
    agotadas = sum(1 for f in stock if _estado_stock(f) == "Agotado")
    pendientes = sum(1 for f in entregas if f["estado"] != "ENTREGADO")
    abiertas = sum(1 for f in reservas if f["estado"] in ("PENDIENTE_PAGO", "CONFIRMADA"))
    filas = [
        ["Total neto (Bs)", neto],
        ["Total vendido (Bs)", vendido],
        ["Devoluciones (Bs)", devuelto],
        ["Ventas realizadas", cantidad],
        ["Entregas a domicilio", len(entregas)],
        ["Entregas sin completar", pendientes],
        ["Reservas", len(reservas)],
        ["Reservas abiertas (por pagar o confirmadas)", abiertas],
        ["Unidades en stock", sum(f["cantidad"] for f in stock)],
        ["Variantes con stock bajo", bajo],
        ["Variantes agotadas", agotadas],
        ["Pruebas en el vestidor virtual", sum(f["pruebas"] for f in pruebas)],
    ]
    kpis = [
        _kpi("Total neto", neto, "dinero"),
        _kpi("Ventas realizadas", cantidad),
        _kpi("Entregas", len(entregas)),
        _kpi("Reservas", len(reservas)),
        _kpi("Stock bajo o agotado", bajo + agotadas),
    ]
    return _resultado(
        "Resumen general",
        _subtitulo(rango[2], sucursal),
        kpis,
        [_col("Indicador"), _col("Valor", "numero")],
        filas,
        notas,
    )

# ---------------------------------------------------------------- definición
_PERIODO = {
    "type": "string",
    "description": (
        "hoy, ayer, semana, semana_pasada, mes, mes_pasado, anio o todo. "
        "Se ignora si das desde/hasta."
    ),
}
_DESDE = {"type": "string", "description": "Fecha inicial AAAA-MM-DD (opcional)."}
_HASTA = {"type": "string", "description": "Fecha final AAAA-MM-DD (opcional)."}
_SUCURSAL = {
    "type": "string",
    "description": "Nombre (o parte) de la sucursal. Omítelo para todas.",
}
_CATEGORIA = {"type": "string", "description": "Categoría de prenda, ej. Poleras. Omítelo para todas."}
_PRODUCTO = {"type": "string", "description": "Nombre de una prenda, ej. polera oversize. Omítelo para todas."}
_LIMITE = {"type": "integer", "description": "Cuántas filas mostrar (1 a 50)."}

HERRAMIENTAS_ADMIN = [
    {
        "name": "consultar_ventas",
        "description": (
            "Ventas netas (punto de venta y web, sin anuladas y restando devoluciones) por "
            "periodo. Agrupa por dia, semana, mes, sucursal, metodo, canal, categoria o "
            "empresa. Úsala para 'ventas de septiembre por sucursal', 'gráfico de ventas "
            "por semana', ingresos o ticket promedio. Filtra por categoría o prenda."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "sucursal": _SUCURSAL,
                "categoria": _CATEGORIA,
                "producto": _PRODUCTO,
                "canal": {"type": "string", "description": "pos (punto de venta) o web. Omítelo para ambos."},
                "agrupar_por": {
                    "type": "string",
                    "description": (
                        "dia, semana, mes, sucursal, metodo, canal, categoria o empresa "
                        "(empresa solo para el administrador de la plataforma)."
                    ),
                },
            },
        },
    },
    {
        "name": "comparativo_sucursales",
        "description": (
            "Compara las ventas netas de las sucursales mes a mes, con gráfico. Úsala para "
            "'compará las sucursales en los últimos 3 meses' o 'qué sucursal vende más'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "meses": {"type": "integer", "description": "Cuántos meses hacia atrás, incluido el actual (1 a 12). Por defecto 3."},
                "desde": _DESDE,
                "hasta": _HASTA,
                "sucursal": _SUCURSAL,
                "categoria": _CATEGORIA,
                "producto": _PRODUCTO,
            },
        },
    },
    {
        "name": "productos_mas_vendidos",
        "description": "Ranking de las prendas más vendidas (unidades netas y monto) en un periodo.",
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "sucursal": _SUCURSAL,
                "categoria": _CATEGORIA,
                "limite": _LIMITE,
            },
        },
    },
    {
        "name": "categorias_mas_ingresos",
        "description": "Categorías ordenadas por ingresos netos, con su porcentaje del total.",
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "sucursal": _SUCURSAL,
                "canal": {"type": "string", "description": "pos o web. Omítelo para ambos."},
            },
        },
    },
    {
        "name": "menor_existencia",
        "description": (
            "Prendas (talla y color por sucursal) con MENOS unidades en stock, de menor a "
            "mayor. Úsala para 'productos con menor existencia' o 'qué se está acabando'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sucursal": _SUCURSAL,
                "categoria": _CATEGORIA,
                "producto": _PRODUCTO,
                "limite": _LIMITE,
            },
        },
    },
    {
        "name": "consultar_inventario",
        "description": (
            "Stock por prenda y sucursal: cuánto queda, qué está bajo o agotado. Úsala "
            "para preguntas de inventario, existencias de una prenda o 'cuánto me queda'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Nombre o tipo de prenda, ej. polera oversize."},
                "categoria": _CATEGORIA,
                "talla": {"type": "string", "description": "Talla exacta, ej. M."},
                "color": {"type": "string", "description": "Un color, ej. negro."},
                "sucursal": _SUCURSAL,
                "solo_bajo_stock": {
                    "type": "boolean",
                    "description": "true para listar solo lo agotado o bajo su mínimo.",
                },
            },
        },
    },
    {
        "name": "devoluciones_y_cambios",
        "description": (
            "Devoluciones (con reembolso) y cambios de prenda (otra talla o color) del "
            "periodo: cantidad por estado, motivos y monto reembolsado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "description": "devoluciones, cambios o ambos (por defecto ambos)."},
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "sucursal": _SUCURSAL,
            },
        },
    },
    {
        "name": "ventas_anuladas_y_conflictos",
        "description": (
            "Ventas hechas SIN CONEXIÓN que llegaron con conflicto (precio distinto o sin "
            "stock): pendientes de revisión, confirmadas y anuladas (efectivo devuelto)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "situacion": {
                    "type": "string",
                    "description": "pendiente de revisión, confirmada o anulada. Omítelo para todas.",
                },
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "sucursal": _SUCURSAL,
            },
        },
    },
    {
        "name": "consultar_reservas",
        "description": (
            "Reservas de prendas con anticipo o pago total: cantidad por estado (pendiente "
            "de pago, confirmada, completada, cancelada, vencida), lo pagado y lo retenido."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "estado": {
                    "type": "string",
                    "description": "pendiente de pago, confirmada, completada, cancelada o vencida.",
                },
                "sucursal": _SUCURSAL,
            },
        },
    },
    {
        "name": "precios_actuales",
        "description": "Precio actual de las prendas del catálogo (mínimo y máximo de sus variantes).",
        "parameters": {
            "type": "object",
            "properties": {
                "producto": _PRODUCTO,
                "categoria": _CATEGORIA,
                "talla": {"type": "string", "description": "Talla exacta, ej. M."},
                "color": {"type": "string", "description": "Un color, ej. negro."},
            },
        },
    },
    {
        "name": "consultar_entregas",
        "description": (
            "Entregas a domicilio (delivery): cantidad por estado y detalle. Úsala para "
            "'cuántos envíos', entregas pendientes, en camino o entregadas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "estado": {
                    "type": "string",
                    "description": "pendiente, en preparación, en camino o entregado.",
                },
                "sucursal": _SUCURSAL,
            },
        },
    },
    {
        "name": "empresas_y_sucursales",
        "description": (
            "Empresas registradas en la plataforma con su plan (solo administrador de la "
            "plataforma) o sucursales de la empresa. Úsala para 'empresas nuevas', "
            "'sucursales nuevas este mes' o 'qué sucursales tengo'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": {
                    "type": "string",
                    "description": "Periodo de registro (mes, anio...). Omítelo para todas.",
                },
                "desde": _DESDE,
                "hasta": _HASTA,
            },
        },
    },
    {
        "name": "uso_vestidor_virtual",
        "description": "Prendas más probadas en el vestidor virtual (realidad aumentada).",
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "limite": _LIMITE,
            },
        },
    },
    {
        "name": "resumen_general",
        "description": (
            "Resumen de indicadores clave del periodo: ventas netas, devoluciones, entregas, "
            "reservas, stock bajo y vestidor. Úsala para preguntas generales del negocio."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "periodo": _PERIODO,
                "desde": _DESDE,
                "hasta": _HASTA,
                "sucursal": _SUCURSAL,
            },
        },
    },
]

# SaaS: todas las consultas aceptan el nombre de la empresa. Solo el
# SUPER_ADMIN puede elegir cualquiera; al personal se le limita a la suya.
for _herramienta in HERRAMIENTAS_ADMIN:
    _herramienta["parameters"]["properties"]["empresa"] = {
        "type": "string",
        "description": (
            "Nombre de la empresa a consultar. Solo lo usa el administrador de la "
            "plataforma; omítelo para consultar todas (o la propia empresa)."
        ),
    }

CONSULTAS = {
    "consultar_ventas": consultar_ventas,
    "comparativo_sucursales": comparativo_sucursales,
    "productos_mas_vendidos": productos_mas_vendidos,
    "categorias_mas_ingresos": categorias_mas_ingresos,
    "menor_existencia": menor_existencia,
    "consultar_inventario": consultar_inventario,
    "devoluciones_y_cambios": devoluciones_y_cambios,
    "ventas_anuladas_y_conflictos": ventas_anuladas_y_conflictos,
    "consultar_reservas": consultar_reservas,
    "precios_actuales": precios_actuales,
    "consultar_entregas": consultar_entregas,
    "empresas_y_sucursales": empresas_y_sucursales,
    "uso_vestidor_virtual": uso_vestidor_virtual,
    "resumen_general": resumen_general,
}

def ejecutar(nombre, argumentos, usuario):
    """Ejecuta una consulta de gestión y devuelve su resultado uniforme."""
    funcion = CONSULTAS.get(nombre)
    if funcion is None:
        raise ConsultaInvalida(f"Consulta desconocida: {nombre}")
    args = argumentos if isinstance(argumentos, dict) else {}
    # SaaS: toda consulta corre dentro del alcance de empresa del usuario.
    with en_empresa_de(usuario):
        id_empresa, nombre_empresa, nota = _resolver_empresa(args.get("empresa"), usuario)
        if id_empresa is None:
            resultado = funcion(args, usuario)
        else:
            token = _empresa_actual.set(id_empresa)
            try:
                resultado = funcion(args, usuario)
            finally:
                _empresa_actual.reset(token)
        return _con_empresa(resultado, usuario, nombre_empresa, nota)

def _con_empresa(resultado, usuario, nombre_empresa, nota):
    """Agrega al subtítulo la empresa consultada y, si la hay, la nota de acceso."""
    if nombre_empresa:
        etiqueta = f"Empresa: {nombre_empresa}"
    elif _es_super_admin(usuario):
        etiqueta = "Todas las empresas"
    elif usuario.id_empresa_id:
        etiqueta = f"Empresa: {usuario.id_empresa.nombre}"
    else:
        etiqueta = None
    if etiqueta:
        resultado["subtitulo"] = f"{etiqueta} · {resultado['subtitulo']}"
    if nota:
        resultado["notas"] = [nota] + list(resultado["notas"])
    return resultado

def resumen_para_modelo(resultado, max_filas=12):
    """Versión compacta del resultado para que la IA redacte la respuesta."""
    columnas = [c["nombre"] for c in resultado["columnas"]]
    return {
        "titulo": resultado["titulo"],
        "subtitulo": resultado["subtitulo"],
        "indicadores": {k["etiqueta"]: k["valor"] for k in resultado["kpis"]},
        "total_filas": len(resultado["filas"]),
        "primeras_filas": [
            dict(zip(columnas, fila)) for fila in resultado["filas"][:max_filas]
        ],
        "notas": resultado["notas"],
    }