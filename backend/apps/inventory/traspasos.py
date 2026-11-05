# backend/apps/inventory/traspasos.py
#
# NUEVO (Fase 3 - CU07): reglas de los traspasos de prendas entre sucursales.
#
# Quién hace qué (siempre dentro de la misma empresa):
#   Solicitar : SUPER_ADMIN, ADMIN_EMPRESA (cualquier par de sucursales de su
#               empresa) o ENCARGADO_SUCURSAL (solo hacia su sucursal).
#   Aprobar   : SUPER_ADMIN o ADMIN_EMPRESA. Sale el stock del origen (SALIDA)
#               y el traspaso queda EN_TRANSITO. Si el stock ya no alcanza, no
#               se aprueba (todo o nada).
#   Rechazar  : SUPER_ADMIN o ADMIN_EMPRESA, solo SOLICITADO, motivo obligatorio.
#   Recibir   : SUPER_ADMIN, ADMIN_EMPRESA o el encargado de la sucursal
#               destino. Completo (sin recepción parcial): entra el stock (ENTRADA).
#   Cancelar  : quien lo solicitó, SUPER_ADMIN o ADMIN_EMPRESA, solo SOLICITADO.
#
# Visibilidad: SUPER_ADMIN todos; ADMIN_EMPRESA los de su empresa; encargado
# los que salen de su sucursal o llegan a ella. Lo ajeno no existe (404).
# Notificaciones (campana): nueva solicitud -> SUPER_ADMIN y ADMIN_EMPRESA de
# la empresa; aprobado o rechazado -> quien lo solicitó, si es administrador
# (el encargado no recibe avisos, igual que en el resto del sistema).

import math
from collections import defaultdict

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.catalog.models import ProductoVariante, Sucursal
from apps.users_auth.notificaciones import administradores, notificar

from .models import DetalleTraspaso, StockItem, Traspaso
from .services import StockService

ENLACE_TRASPASOS = "/inventory/traspasos"
ESTADOS_ABIERTOS = ("SOLICITADO", "EN_TRANSITO")
ROLES_ADMIN = {"SUPER_ADMIN", "ADMIN_EMPRESA"}
MAX_LINEAS = 50


class ErrorTraspaso(Exception):
    """Operación no permitida o datos inválidos (se responde 400)."""


class SinPermiso(Exception):
    """El usuario no puede hacer esa acción sobre el traspaso (se responde 403)."""


# --------------------------------------------------------------------------
# Roles y alcance
# --------------------------------------------------------------------------

def roles_de(usuario):
    """Nombres de los roles del usuario."""
    if not hasattr(usuario, "_roles_traspaso"):
        usuario._roles_traspaso = set(usuario.roles.values_list("nombre", flat=True))
    return usuario._roles_traspaso


def es_super_admin(usuario):
    """True si es el operador de la plataforma."""
    return "SUPER_ADMIN" in roles_de(usuario)


def es_admin_de(usuario, empresa_id):
    """SUPER_ADMIN, o ADMIN_EMPRESA de esa empresa."""
    roles = roles_de(usuario)
    return "SUPER_ADMIN" in roles or ("ADMIN_EMPRESA" in roles and usuario.id_empresa_id == empresa_id)


def es_encargado(usuario):
    """True si es encargado de sucursal (y no administrador)."""
    roles = roles_de(usuario)
    return "ENCARGADO_SUCURSAL" in roles and not roles & ROLES_ADMIN


def traspasos_visibles(usuario):
    """Traspasos que el usuario puede ver."""
    qs = Traspaso.objects.select_related(
        "id_empresa", "id_sucursal_origen", "id_sucursal_destino", "id_usuario_solicita",
        "id_usuario_aprueba", "id_usuario_rechaza", "id_usuario_recibe", "id_usuario_cancela",
    )
    roles = roles_de(usuario)
    if "SUPER_ADMIN" in roles:
        return qs
    if usuario.id_empresa_id is None:
        return qs.none()
    qs = qs.filter(id_empresa_id=usuario.id_empresa_id)
    if "ADMIN_EMPRESA" in roles:
        return qs
    if "ENCARGADO_SUCURSAL" in roles and usuario.id_sucursal_id:
        return qs.filter(
            Q(id_sucursal_origen_id=usuario.id_sucursal_id) | Q(id_sucursal_destino_id=usuario.id_sucursal_id)
        )
    return qs.none()


def sucursales_permitidas(usuario):
    """Sucursales activas entre las que el usuario puede pedir traspasos."""
    qs = Sucursal.objects.filter(estado="ACTIVA").select_related("id_empresa")
    if es_super_admin(usuario):
        return qs
    if usuario.id_empresa_id is None:
        return qs.none()
    return qs.filter(id_empresa_id=usuario.id_empresa_id)


def acciones(usuario, traspaso):
    """Qué puede hacer el usuario con el traspaso en su estado actual."""
    admin = es_admin_de(usuario, traspaso.id_empresa_id)
    solicitado = traspaso.estado == "SOLICITADO"
    return {
        "aprobar": admin and solicitado,
        "rechazar": admin and solicitado,
        "cancelar": solicitado and (admin or traspaso.id_usuario_solicita_id == usuario.pk),
        "recibir": traspaso.estado == "EN_TRANSITO" and (
            admin or (es_encargado(usuario) and usuario.id_sucursal_id == traspaso.id_sucursal_destino_id)
        ),
    }


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def nombre_usuario(usuario):
    """Nombre completo de un usuario (o vacío)."""
    return f"{usuario.nombres} {usuario.apellidos}".strip() if usuario else ""


def nombre_variante(variante):
    """'Polera básica - M - Negro'."""
    return f"{variante.id_producto.nombre} - {variante.id_talla.nombre} - {variante.id_color.nombre}"


def stock_de(sucursal_id, variante_ids):
    """{id_variante: unidades} en una sucursal."""
    filas = StockItem.objects.filter(
        id_sucursal_id=sucursal_id, id_variante_id__in=variante_ids, estado=True
    ).values_list("id_variante_id", "cantidad")
    return {variante: cantidad for variante, cantidad in filas}


def _avisar_admins(traspaso, titulo, mensaje, clave, excepto=None):
    """Aviso a SUPER_ADMIN y ADMIN_EMPRESA de la empresa (menos quien hizo la acción)."""
    usuarios = [u for u in administradores(traspaso.id_empresa_id) if excepto is None or u.pk != excepto.pk]
    notificar(usuarios, "TRASPASO", titulo, mensaje, ENLACE_TRASPASOS, traspaso.id_empresa_id, clave)


def _avisar_solicitante(traspaso, titulo, mensaje, clave, actor):
    """Aviso a quien solicitó, solo si es administrador y no fue él quien actuó."""
    solicitante = traspaso.id_usuario_solicita
    if solicitante is None or solicitante.pk == actor.pk or not roles_de(solicitante) & ROLES_ADMIN:
        return
    notificar([solicitante], "TRASPASO", titulo, mensaje, ENLACE_TRASPASOS, traspaso.id_empresa_id, clave)


def _bloquear(traspaso_id):
    """Vuelve a leer el traspaso bloqueándolo (evita aprobar o recibir dos veces).

    Solo se bloquea la fila del traspaso (of=self): PostgreSQL no permite
    FOR UPDATE sobre el lado nulable de un JOIN (el usuario que solicitó).
    """
    return (
        Traspaso.objects.select_for_update(of=("self",))
        .select_related("id_sucursal_origen", "id_sucursal_destino", "id_usuario_solicita")
        .get(pk=traspaso_id)
    )


# --------------------------------------------------------------------------
# Acciones
# --------------------------------------------------------------------------

def _leer_lineas(lineas, empresa_id):
    """Valida las líneas [{id_variante, cantidad}] y devuelve [(variante, cantidad)]."""
    if not isinstance(lineas, list) or not lineas:
        raise ErrorTraspaso("Agrega al menos una prenda al traspaso.")
    if len(lineas) > MAX_LINEAS:
        raise ErrorTraspaso(f"Un traspaso puede tener como máximo {MAX_LINEAS} prendas.")
    pedidas = {}
    for linea in lineas:
        try:
            variante_id = int(linea.get("id_variante"))
            cantidad = int(linea.get("cantidad"))
        except (AttributeError, TypeError, ValueError):
            raise ErrorTraspaso("Cada prenda debe tener id_variante y cantidad válidos.")
        if cantidad <= 0:
            raise ErrorTraspaso("La cantidad de cada prenda debe ser mayor a cero.")
        if variante_id in pedidas:
            raise ErrorTraspaso("Una misma prenda (talla y color) aparece dos veces.")
        pedidas[variante_id] = cantidad
    variantes = {
        v.id_variante: v
        for v in ProductoVariante.objects.filter(
            id_variante__in=pedidas, id_producto__id_empresa_id=empresa_id
        ).select_related("id_producto", "id_talla", "id_color")
    }
    if len(variantes) != len(pedidas):
        raise ErrorTraspaso("Alguna prenda no existe o no pertenece a la empresa.")
    return [(variantes[vid], cantidad) for vid, cantidad in pedidas.items()]


def _verificar_stock(origen, lineas):
    """Error si alguna prenda no tiene stock suficiente en el origen."""
    disponible = stock_de(origen.id_sucursal, [v.id_variante for v, _ in lineas])
    faltantes = [
        f"{nombre_variante(v)} (hay {disponible.get(v.id_variante, 0)}, se piden {cantidad})"
        for v, cantidad in lineas
        if disponible.get(v.id_variante, 0) < cantidad
    ]
    if faltantes:
        raise ErrorTraspaso(f"Stock insuficiente en {origen.nombre}: " + "; ".join(faltantes) + ".")


def crear(usuario, origen_id, destino_id, lineas, observacion=None, desde_sugerencia=False):
    """Registra una solicitud de traspaso y avisa a los administradores."""
    roles = roles_de(usuario)
    if not roles & (ROLES_ADMIN | {"ENCARGADO_SUCURSAL"}):
        raise SinPermiso("No tienes permiso para solicitar traspasos.")
    sucursales = sucursales_permitidas(usuario)
    origen = sucursales.filter(pk=origen_id).first()
    destino = sucursales.filter(pk=destino_id).first()
    if origen is None or destino is None:
        raise ErrorTraspaso("Elige una sucursal de origen y una de destino activas de tu empresa.")
    if origen.pk == destino.pk:
        raise ErrorTraspaso("La sucursal de origen y la de destino deben ser distintas.")
    if origen.id_empresa_id != destino.id_empresa_id:
        raise ErrorTraspaso("Solo se puede traspasar entre sucursales de la misma empresa.")
    if es_encargado(usuario) and destino.pk != usuario.id_sucursal_id:
        raise SinPermiso("Como encargado solo puedes pedir traspasos hacia tu sucursal.")
    detalle = _leer_lineas(lineas, origen.id_empresa_id)
    _verificar_stock(origen, detalle)
    with transaction.atomic():
        traspaso = Traspaso.objects.create(
            id_empresa_id=origen.id_empresa_id,
            id_sucursal_origen=origen,
            id_sucursal_destino=destino,
            observacion=(observacion or "").strip()[:255] or None,
            desde_sugerencia=bool(desde_sugerencia),
            id_usuario_solicita=usuario,
        )
        DetalleTraspaso.objects.bulk_create([
            DetalleTraspaso(id_traspaso=traspaso, id_variante=v, cantidad=c) for v, c in detalle
        ])
    unidades = sum(c for _, c in detalle)
    _avisar_admins(
        traspaso,
        f"Nuevo traspaso #{traspaso.id_traspaso} por aprobar",
        f"{nombre_usuario(usuario)} pide {unidades} prenda(s) de {origen.nombre} para {destino.nombre}.",
        f"traspaso-{traspaso.id_traspaso}-SOLICITADO",
        excepto=usuario,
    )
    return traspaso


def aprobar(usuario, traspaso_id):
    """Aprueba: sale el stock del origen y queda EN_TRANSITO (todo o nada)."""
    with transaction.atomic():
        traspaso = _bloquear(traspaso_id)
        if not es_admin_de(usuario, traspaso.id_empresa_id):
            raise SinPermiso("Solo el administrador de la empresa o el SUPER_ADMIN pueden aprobar.")
        if traspaso.estado != "SOLICITADO":
            raise ErrorTraspaso(f"El traspaso ya está {traspaso.get_estado_display().lower()}.")
        lineas = [
            (d.id_variante, d.cantidad)
            for d in traspaso.detalles.select_related("id_variante__id_producto", "id_variante__id_talla",
                                                      "id_variante__id_color")
        ]
        _verificar_stock(traspaso.id_sucursal_origen, lineas)
        motivo = f"Traspaso #{traspaso.id_traspaso} a {traspaso.id_sucursal_destino.nombre}"
        for variante, cantidad in lineas:
            try:
                StockService.registrar_movimiento(
                    traspaso.id_sucursal_origen, variante, usuario, "SALIDA", cantidad, motivo
                )
            except ValueError as exc:
                raise ErrorTraspaso(f"{nombre_variante(variante)}: {exc}")
        traspaso.estado = "EN_TRANSITO"
        traspaso.id_usuario_aprueba = usuario
        traspaso.fecha_aprobacion = timezone.now()
        traspaso.save(update_fields=["estado", "id_usuario_aprueba", "fecha_aprobacion"])
    _avisar_solicitante(
        traspaso,
        f"Traspaso #{traspaso.id_traspaso} aprobado",
        f"Las prendas salieron de {traspaso.id_sucursal_origen.nombre} y van en camino a "
        f"{traspaso.id_sucursal_destino.nombre}.",
        f"traspaso-{traspaso.id_traspaso}-EN_TRANSITO",
        usuario,
    )
    return traspaso


def rechazar(usuario, traspaso_id, motivo):
    """Rechaza una solicitud (solo SOLICITADO, con motivo)."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorTraspaso("Escribe el motivo del rechazo.")
    with transaction.atomic():
        traspaso = _bloquear(traspaso_id)
        if not es_admin_de(usuario, traspaso.id_empresa_id):
            raise SinPermiso("Solo el administrador de la empresa o el SUPER_ADMIN pueden rechazar.")
        if traspaso.estado != "SOLICITADO":
            raise ErrorTraspaso("Solo se puede rechazar un traspaso que está solicitado.")
        traspaso.estado = "RECHAZADO"
        traspaso.motivo_rechazo = motivo[:255]
        traspaso.id_usuario_rechaza = usuario
        traspaso.fecha_rechazo = timezone.now()
        traspaso.save(update_fields=["estado", "motivo_rechazo", "id_usuario_rechaza", "fecha_rechazo"])
    _avisar_solicitante(
        traspaso,
        f"Traspaso #{traspaso.id_traspaso} rechazado",
        f"Motivo: {traspaso.motivo_rechazo}",
        f"traspaso-{traspaso.id_traspaso}-RECHAZADO",
        usuario,
    )
    return traspaso


def recibir(usuario, traspaso_id):
    """El destino recibe todo: entra el stock y queda RECIBIDO."""
    with transaction.atomic():
        traspaso = _bloquear(traspaso_id)
        if not acciones(usuario, traspaso)["recibir"]:
            if traspaso.estado != "EN_TRANSITO":
                raise ErrorTraspaso("Solo se puede recibir un traspaso que está en tránsito.")
            raise SinPermiso("Solo la sucursal destino, el administrador o el SUPER_ADMIN pueden recibirlo.")
        motivo = f"Traspaso #{traspaso.id_traspaso} desde {traspaso.id_sucursal_origen.nombre}"
        for detalle in traspaso.detalles.select_related("id_variante__id_producto"):
            StockService.registrar_movimiento(
                traspaso.id_sucursal_destino, detalle.id_variante, usuario, "ENTRADA", detalle.cantidad, motivo
            )
        traspaso.estado = "RECIBIDO"
        traspaso.id_usuario_recibe = usuario
        traspaso.fecha_recepcion = timezone.now()
        traspaso.save(update_fields=["estado", "id_usuario_recibe", "fecha_recepcion"])
    return traspaso


def cancelar(usuario, traspaso_id):
    """Cancela una solicitud que todavía no fue aprobada."""
    with transaction.atomic():
        traspaso = _bloquear(traspaso_id)
        if traspaso.estado != "SOLICITADO":
            raise ErrorTraspaso("Solo se puede cancelar un traspaso que está solicitado.")
        if not acciones(usuario, traspaso)["cancelar"]:
            raise SinPermiso("Solo quien lo solicitó o un administrador pueden cancelarlo.")
        traspaso.estado = "CANCELADO"
        traspaso.id_usuario_cancela = usuario
        traspaso.fecha_cancelacion = timezone.now()
        traspaso.save(update_fields=["estado", "id_usuario_cancela", "fecha_cancelacion"])
    return traspaso


# --------------------------------------------------------------------------
# Sugerencias a partir de la predicción de demanda (CU09)
# --------------------------------------------------------------------------

def sugerencias(empresa):
    """Traspasos sugeridos: prendas cuya demanda prevista (4 semanas) supera el stock.

    Para cada prenda y sucursal con faltante, busca otra sucursal de la misma
    empresa a la que le sobre (stock menos su propia demanda prevista) y
    sugiere llevar lo que falta, hasta lo que sobra. Se omiten las prendas
    que ya tienen un traspaso abierto hacia esa sucursal.
    """
    from apps.analytics.models import EntrenamientoModelo, PrediccionDemanda

    vigente = EntrenamientoModelo.objects.filter(id_empresa=empresa, tipo="DEMANDA", vigente=True).first()
    if vigente is None:
        return []
    demanda = defaultdict(float)
    for fila in PrediccionDemanda.objects.filter(id_entrenamiento=vigente).values(
        "id_sucursal_id", "id_producto_id"
    ).annotate(total=Sum("unidades_predichas")):
        demanda[(fila["id_sucursal_id"], fila["id_producto_id"])] = float(fila["total"])
    sucursales = {s.id_sucursal: s for s in Sucursal.objects.filter(id_empresa=empresa, estado="ACTIVA")}
    stock = defaultdict(int)
    for fila in StockItem.objects.filter(id_sucursal_id__in=sucursales, estado=True).values(
        "id_sucursal_id", "id_variante__id_producto_id"
    ).annotate(total=Sum("cantidad")):
        stock[(fila["id_sucursal_id"], fila["id_variante__id_producto_id"])] = int(fila["total"] or 0)
    abiertos = set(
        DetalleTraspaso.objects.filter(
            id_traspaso__id_empresa=empresa, id_traspaso__estado__in=ESTADOS_ABIERTOS
        ).values_list("id_traspaso__id_sucursal_destino_id", "id_variante__id_producto_id")
    )
    productos = {p for _, p in demanda} | {p for _, p in stock}
    sobrante = {}
    faltantes = []
    for producto in productos:
        for sucursal in sucursales:
            necesidad = math.ceil(demanda.get((sucursal, producto), 0.0))
            diferencia = stock.get((sucursal, producto), 0) - necesidad
            if diferencia > 0:
                sobrante[(sucursal, producto)] = diferencia
            elif diferencia < 0 and necesidad > 0 and (sucursal, producto) not in abiertos:
                faltantes.append((sucursal, producto, -diferencia, necesidad))
    faltantes.sort(key=lambda f: -f[2])
    resultado = []
    for destino, producto, falta, necesidad in faltantes:
        candidatos = [(s, sobra) for (s, p), sobra in sobrante.items() if p == producto and s != destino and sobra > 0]
        if not candidatos:
            continue
        origen, sobra = max(candidatos, key=lambda c: c[1])
        cantidad = min(falta, sobra)
        sobrante[(origen, producto)] -= cantidad
        resultado.append({
            "id_producto": producto,
            "id_sucursal_origen": origen,
            "id_sucursal_destino": destino,
            "demanda_prevista": necesidad,
            "stock_destino": stock.get((destino, producto), 0),
            "stock_origen": stock.get((origen, producto), 0),
            "cantidad_sugerida": cantidad,
        })
    if not resultado:
        return []
    nombres = dict(
        ProductoVariante.objects.filter(id_producto_id__in={r["id_producto"] for r in resultado})
        .values_list("id_producto_id", "id_producto__nombre")
    )
    variantes = defaultdict(list)
    for item in StockItem.objects.filter(
        id_sucursal_id__in={r["id_sucursal_origen"] for r in resultado},
        id_variante__id_producto_id__in={r["id_producto"] for r in resultado},
        estado=True, cantidad__gt=0,
    ).select_related("id_variante__id_talla", "id_variante__id_color").order_by("-cantidad"):
        variantes[(item.id_sucursal_id, item.id_variante.id_producto_id)].append({
            "id_variante": item.id_variante_id,
            "talla": item.id_variante.id_talla.nombre,
            "color": item.id_variante.id_color.nombre,
            "stock_origen": item.cantidad,
        })
    for r in resultado:
        r["producto"] = nombres.get(r["id_producto"], "")
        r["sucursal_origen"] = sucursales[r["id_sucursal_origen"]].nombre
        r["sucursal_destino"] = sucursales[r["id_sucursal_destino"]].nombre
        r["variantes"] = variantes[(r["id_sucursal_origen"], r["id_producto"])]
    return resultado