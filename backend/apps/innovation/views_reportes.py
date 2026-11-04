# backend/apps/innovation/views_reportes.py
#
# NUEVO (Fase 3 - CU13): reportes convencionales (SIN IA), disponibles en los
# tres planes (PLUS, PRO y ULTRA). El usuario elige el tipo de reporte y sus
# filtros en un formulario; el backend ejecuta la MISMA consulta controlada
# que usa el asistente con IA (consultas_admin), dentro de su empresa y
# sucursal, y guarda el resultado para mostrarlo y exportarlo (PDF, Excel y
# HTML) con el endpoint de exportación existente.
#
#   GET  /api/innovation/reportes/opciones/  tipos de reporte y valores de los filtros
#   POST /api/innovation/reportes/generar/   {"consulta": "...", "filtros": {...}}

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Categoria, Producto, Sucursal
from common.permissions import IsEncargadoSucursal
from common.utils import get_client_ip, log_audit

from . import consultas_admin as ca
from .models import ReporteAsistente

MAX_OPCIONES = 500

# Tipos de reporte del formulario, en el orden en que se muestran.
TIPOS_REPORTE = {
    "consultar_ventas": "Ventas por periodo",
    "comparativo_sucursales": "Comparativo entre sucursales",
    "productos_mas_vendidos": "Productos más vendidos",
    "categorias_mas_ingresos": "Categorías con más ingresos",
    "menor_existencia": "Productos con menor existencia",
    "consultar_inventario": "Inventario por sucursal",
    "devoluciones_y_cambios": "Devoluciones y cambios de prenda",
    "ventas_anuladas_y_conflictos": "Ventas sin conexión: conflictos y anuladas",
    "consultar_reservas": "Reservas",
    "precios_actuales": "Precios actuales",
    "consultar_entregas": "Entregas a domicilio",
    "empresas_y_sucursales": "Empresas y sucursales",
}

def _parametros(consulta):
    """{nombre: tipo JSON} de los filtros que acepta una consulta."""
    for herramienta in ca.HERRAMIENTAS_ADMIN:
        if herramienta["name"] == consulta:
            return {
                nombre: definicion.get("type", "string")
                for nombre, definicion in herramienta["parameters"]["properties"].items()
            }
    return {}

def _limpiar_filtros(consulta, filtros, super_admin):
    """Deja solo los filtros válidos de la consulta, con su tipo correcto.

    Lo desconocido se descarta; el parámetro 'empresa' solo lo puede usar el
    SUPER_ADMIN (al personal siempre se le aplica su propia empresa).
    """
    limpios = {}
    if not isinstance(filtros, dict):
        return limpios
    for nombre, tipo in _parametros(consulta).items():
        if nombre == "empresa" and not super_admin:
            continue
        valor = filtros.get(nombre)
        if valor in (None, ""):
            continue
        try:
            if tipo == "boolean":
                if not isinstance(valor, bool):
                    valor = str(valor).lower() in ("true", "1", "si")
                limpios[nombre] = valor
            elif tipo == "integer":
                limpios[nombre] = int(valor)
            else:
                limpios[nombre] = str(valor).strip()[:100]
        except (TypeError, ValueError):
            continue
    return limpios

def _nombre_empresa(objeto):
    """Nombre de la empresa de un registro (para filtrar opciones en la web)."""
    return objeto.id_empresa.nombre if objeto.id_empresa_id else None

class OpcionesReporteView(APIView):
    """Tipos de reporte disponibles y valores para sus filtros (dentro del alcance)."""

    permission_classes = [IsEncargadoSucursal]

    def get(self, request):
        """Devuelve tipos, filtros por tipo y opciones de empresa, sucursal, categoría y prenda."""
        usuario = request.user
        super_admin = ca._es_super_admin(usuario)
        with ca.en_empresa_de(usuario):
            sucursales = ca._por_empresa(
                Sucursal.objects.filter(estado="ACTIVA").select_related("id_empresa")
            ).order_by("id_empresa__nombre", "nombre")[:MAX_OPCIONES]
            categorias = ca._por_empresa(
                Categoria.objects.filter(estado=True).select_related("id_empresa")
            ).order_by("nombre")[:MAX_OPCIONES]
            productos = ca._por_empresa(
                Producto.objects.filter(estado="ACTIVO").select_related("id_empresa")
            ).order_by("nombre")[:MAX_OPCIONES]
            empresas = [e.nombre for e in ca._empresas_activas()] if super_admin else []
            fija = ca.alcance_sucursal(usuario)
            return Response(
                {
                    "tipos": [
                        {
                            "clave": clave,
                            "nombre": nombre,
                            "filtros": [
                                f for f in _parametros(clave) if super_admin or f != "empresa"
                            ],
                        }
                        for clave, nombre in TIPOS_REPORTE.items()
                    ],
                    "empresas": empresas,
                    "sucursales": [
                        {"nombre": s.nombre, "empresa": _nombre_empresa(s)}
                        for s in sucursales
                        if not fija or s.nombre == fija
                    ],
                    "categorias": [
                        {"nombre": c.nombre, "empresa": _nombre_empresa(c)} for c in categorias
                    ],
                    "productos": [
                        {"nombre": p.nombre, "empresa": _nombre_empresa(p)} for p in productos
                    ],
                    "sucursal_fija": fija,
                    "super_admin": super_admin,
                }
            )

class GenerarReporteView(APIView):
    """Genera un reporte convencional (sin IA) y lo guarda para verlo y exportarlo."""

    permission_classes = [IsEncargadoSucursal]

    def post(self, request):
        """Valida el tipo y los filtros, ejecuta la consulta y guarda el reporte."""
        datos = request.data if isinstance(request.data, dict) else {}
        consulta = datos.get("consulta")
        if consulta not in TIPOS_REPORTE:
            return Response(
                {"detail": "Elige un tipo de reporte válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        usuario = request.user
        filtros = _limpiar_filtros(consulta, datos.get("filtros"), ca._es_super_admin(usuario))
        resultado = ca.ejecutar(consulta, filtros, usuario)
        reporte = ReporteAsistente.objects.create(
            id_usuario=usuario,
            pregunta=f"Reporte convencional: {TIPOS_REPORTE[consulta]}",
            consulta=consulta,
            filtros=filtros,
            titulo=resultado["titulo"][:200],
            resultado=dict(resultado, respuesta=""),
        )
        log_audit(
            usuario=usuario,
            accion="REPORTE_GENERADO",
            tabla_afectada="reporte_asistente",
            registro_id=reporte.id_reporte,
            descripcion=f"Se generó el reporte convencional «{resultado['titulo']}»",
            direccion_ip=get_client_ip(request),
        )
        return Response(
            {
                "id_reporte": reporte.id_reporte,
                "consulta": consulta,
                "filtros": filtros,
                "resultado": resultado,
            },
            status=status.HTTP_201_CREATED,
        )