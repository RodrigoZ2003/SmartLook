# backend/apps/analytics/views.py
#
# NUEVO (Fase 3 - CU09): API de Analítica con Machine Learning.
#
#   GET  /api/analytics/dashboard/?empresa=<id>
#        Métricas de los modelos (3, 5 y 12 meses), predicción de demanda de
#        las próximas 4 semanas y segmentación de clientes de una empresa.
#   POST /api/analytics/reentrenar/   {"empresa": <id> | "todas"}
#        Vuelve a entrenar los modelos con los datos actuales.
#   GET  /api/analytics/exportar/?empresa=<id>&reporte=demanda|segmentos|modelos&formato=pdf|xlsx|html
#        Descarga el reporte en PDF, Excel o HTML.
#
# Acceso: SUPER_ADMIN y ADMIN_EMPRESA (no encargados ni cajeros), con plan que
# incluya IA (PRO o ULTRA). El SUPER_ADMIN elige la empresa (o "todas" al
# reentrenar); el ADMIN_EMPRESA solo ve y reentrena la suya: el parámetro
# empresa se ignora para él.

from collections import defaultdict

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.innovation.exportadores import FormatoInvalido, exportar
from apps.users_auth.models import Empresa
from apps.users_auth.suscripciones import requiere_funcion
from common.permissions import IsAdminEmpresa
from common.utils import get_client_ip, log_audit

from .models import EntrenamientoModelo, SegmentoCliente
from .servicio_ml import entrenar_empresa

PERMISOS_ANALITICA = [IsAdminEmpresa, requiere_funcion("reportes_ia")]
REPORTES = {
    "demanda": "Predicción de demanda",
    "segmentos": "Segmentación de clientes",
    "modelos": "Evaluación de los modelos",
}
NOMBRE_SEGMENTO = dict(SegmentoCliente.SEGMENTOS)
DESCRIPCION_SEGMENTO = {
    "VIP": "Compran seguido, gastan más y compraron hace poco.",
    "LEAL": "Compran con regularidad.",
    "OCASIONAL": "Compran pocas veces y gastan poco.",
    "RIESGO": "Antes compraban, pero hace tiempo que no vuelven.",
}


def _es_super_admin(usuario):
    """True si el usuario es el operador de la plataforma."""
    return usuario.roles.filter(nombre="SUPER_ADMIN").exists()


def _fecha_texto(valor):
    """Fecha y hora local en formato dd/mm/aaaa hh:mm."""
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else ""


def _empresa_de(request, valor):
    """Empresa que se consulta: la elegida (SUPER_ADMIN) o la del usuario.

    Devuelve (empresa, error_response). Para el SUPER_ADMIN sin empresa
    elegida se usa la primera empresa activa con modelos entrenados.
    """
    usuario = request.user
    if not _es_super_admin(usuario):
        if usuario.id_empresa_id is None:
            return None, Response({"detail": "Tu usuario no pertenece a una empresa."},
                                  status=status.HTTP_403_FORBIDDEN)
        return usuario.id_empresa, None
    if valor not in (None, ""):
        empresa = Empresa.objects.filter(pk=valor).first() if str(valor).isdigit() else None
        if empresa is None:
            return None, Response({"detail": "La empresa no existe."}, status=status.HTTP_404_NOT_FOUND)
        return empresa, None
    activas = Empresa.objects.filter(estado="ACTIVA").order_by("nombre")
    empresa = activas.filter(entrenamientos_ml__isnull=False).distinct().first() or activas.first()
    if empresa is None:
        return None, Response({"detail": "No hay empresas activas."}, status=status.HTTP_404_NOT_FOUND)
    return empresa, None


# --------------------------------------------------------------------------
# Armado de datos
# --------------------------------------------------------------------------

def _ventanas_demanda(empresa):
    """Entrenamientos de demanda de la última corrida (3, 5 y 12 meses)."""
    ultimo = (
        EntrenamientoModelo.objects.filter(id_empresa=empresa, tipo="DEMANDA")
        .order_by("-fecha_entrenamiento", "-id_entrenamiento").first()
    )
    if ultimo is None:
        return []
    return list(
        EntrenamientoModelo.objects.filter(
            id_empresa=empresa, tipo="DEMANDA", parametros__corrida=ultimo.parametros.get("corrida")
        ).order_by("ventana_meses")
    )


def _vigente(empresa, tipo):
    """Entrenamiento vigente de una empresa y tipo (o None)."""
    return (
        EntrenamientoModelo.objects.filter(id_empresa=empresa, tipo=tipo, vigente=True)
        .order_by("-fecha_entrenamiento").first()
    )


def _predicciones(vigente):
    """Predicciones del modelo vigente: semanas y filas por sucursal y prenda."""
    if vigente is None:
        return {"semanas": [], "filas": []}
    registros = vigente.predicciones.select_related("id_sucursal", "id_producto").order_by("semana_inicio")
    semanas = sorted({r.semana_inicio for r in registros})
    posicion = {s: i for i, s in enumerate(semanas)}
    filas = {}
    for r in registros:
        clave = (r.id_sucursal_id, r.id_producto_id)
        if clave not in filas:
            filas[clave] = {
                "sucursal": r.id_sucursal.nombre,
                "prenda": r.id_producto.nombre,
                "unidades": [0.0] * len(semanas),
            }
        filas[clave]["unidades"][posicion[r.semana_inicio]] = float(r.unidades_predichas)
    lista = []
    for fila in filas.values():
        fila["total"] = round(sum(fila["unidades"]), 2)
        lista.append(fila)
    lista.sort(key=lambda f: -f["total"])
    return {"semanas": [s.isoformat() for s in semanas], "filas": lista}


def _datos_ventana(entrenamiento):
    """Métricas de un entrenamiento de demanda para la web."""
    m = entrenamiento.metricas
    return {
        "id": entrenamiento.id_entrenamiento,
        "ventana_meses": entrenamiento.ventana_meses,
        "vigente": entrenamiento.vigente,
        "fecha": _fecha_texto(entrenamiento.fecha_entrenamiento),
        "desde": m.get("desde"),
        "hasta": m.get("hasta"),
        "filas_entrenamiento": entrenamiento.filas_entrenamiento,
        "filas_prueba": entrenamiento.filas_prueba,
        "mae": m.get("mae"),
        "rmse": m.get("rmse"),
        "r2": m.get("r2"),
        "mae_linea_base": m.get("mae_linea_base"),
        "aviso": m.get("aviso"),
        "importancias": m.get("importancias", []),
        "serie_prueba": m.get("serie_prueba", []),
    }


def _segmentacion(empresa):
    """Segmentación vigente (o el último intento con su aviso)."""
    entrenamiento = _vigente(empresa, "SEGMENTACION") or (
        EntrenamientoModelo.objects.filter(id_empresa=empresa, tipo="SEGMENTACION")
        .order_by("-fecha_entrenamiento").first()
    )
    if entrenamiento is None:
        return None
    m = entrenamiento.metricas
    clientes = [
        {
            "cliente": f"{s.id_cliente.id_usuario.nombres} {s.id_cliente.id_usuario.apellidos}".strip(),
            "correo": s.id_cliente.id_usuario.correo,
            "segmento": s.segmento,
            "nombre_segmento": NOMBRE_SEGMENTO[s.segmento],
            "recencia_dias": s.recencia_dias,
            "frecuencia": s.frecuencia,
            "monto": float(s.monto),
        }
        for s in entrenamiento.segmentos.select_related("id_cliente__id_usuario").order_by("segmento", "-monto")
    ]
    orden = list(NOMBRE_SEGMENTO)
    clientes.sort(key=lambda c: (orden.index(c["segmento"]), -c["monto"]))
    resumen = [dict(r, descripcion=DESCRIPCION_SEGMENTO[r["segmento"]]) for r in m.get("resumen", [])]
    return {
        "id": entrenamiento.id_entrenamiento,
        "fecha": _fecha_texto(entrenamiento.fecha_entrenamiento),
        "vigente": entrenamiento.vigente,
        "desde": m.get("desde"),
        "hasta": m.get("hasta"),
        "clientes_total": m.get("clientes", 0),
        "k": m.get("k"),
        "silhouette": m.get("silhouette", {}),
        "inercia": m.get("inercia", {}),
        "silhouette_k": m.get("silhouette_k"),
        "resumen": resumen,
        "aviso": m.get("aviso"),
        "clientes": clientes,
    }


def armar_dashboard(empresa):
    """Todo lo que muestra el dashboard de Analítica de una empresa."""
    ventanas = _ventanas_demanda(empresa)
    vigente = _vigente(empresa, "DEMANDA")
    return {
        "empresa": {"id": empresa.id_empresa, "nombre": empresa.nombre},
        "demanda": {
            "ventanas": [_datos_ventana(e) for e in ventanas],
            "vigente": _datos_ventana(vigente) if vigente else None,
            "predicciones": _predicciones(vigente),
        },
        "segmentacion": _segmentacion(empresa),
    }


# --------------------------------------------------------------------------
# Reportes exportables (mismo formato que los reportes de CU13)
# --------------------------------------------------------------------------

def _kpi(etiqueta, valor, tipo="numero"):
    """Indicador del reporte (si el valor no es un número se muestra como texto)."""
    if not isinstance(valor, (int, float)):
        tipo = "texto"
    return {"etiqueta": etiqueta, "valor": valor, "tipo": tipo}


def _col(nombre, tipo="texto"):
    """Columna de la tabla del reporte."""
    return {"nombre": nombre, "tipo": tipo}


def _semana_corta(iso):
    """'2026-11-02' -> 'Sem 02/11'."""
    return f"Sem {iso[8:10]}/{iso[5:7]}"


def _reporte_demanda(empresa, datos):
    """Resultado exportable de la predicción de demanda."""
    vigente = datos["demanda"]["vigente"]
    pred = datos["demanda"]["predicciones"]
    semanas = pred["semanas"]
    filas = [[f["sucursal"], f["prenda"], *f["unidades"], f["total"]] for f in pred["filas"]]
    por_prenda = defaultdict(float)
    for f in pred["filas"]:
        por_prenda[f["prenda"]] += f["total"]
    top = sorted(por_prenda.items(), key=lambda par: -par[1])[:10]
    notas = ["Unidades estimadas por el modelo RandomForest; son valores esperados, no pedidos confirmados."]
    if vigente is None:
        notas = ["Aún no hay un modelo de demanda entrenado para esta empresa."]
    subtitulo = (
        f"{empresa.nombre} · Modelo de {vigente['ventana_meses']} meses entrenado el {vigente['fecha']}"
        if vigente else empresa.nombre
    )
    return {
        "titulo": "Predicción de demanda - próximas 4 semanas",
        "subtitulo": subtitulo,
        "kpis": [
            _kpi("Unidades previstas", round(sum(f["total"] for f in pred["filas"]), 1)),
            _kpi("Prendas", len({f["prenda"] for f in pred["filas"]})),
            _kpi("Sucursales", len({f["sucursal"] for f in pred["filas"]})),
            _kpi("MAE del modelo", vigente["mae"] if vigente else "-"),
        ],
        "columnas": [_col("Sucursal"), _col("Prenda")]
        + [_col(_semana_corta(s), "numero") for s in semanas]
        + [_col("Total", "numero")],
        "filas": filas,
        "notas": notas,
        "grafico": {
            "tipo": "barh",
            "titulo": "Unidades previstas por prenda",
            "etiquetas": [p for p, _ in top],
            "series": [{"nombre": "Unidades", "datos": [round(v, 2) for _, v in top]}],
            "formato": "numero",
        } if top else None,
    }


def _reporte_segmentos(empresa, datos):
    """Resultado exportable de la segmentación de clientes."""
    seg = datos["segmentacion"] or {}
    resumen = seg.get("resumen", [])
    notas = [f"{r['nombre']}: {r['descripcion']}" for r in resumen]
    if seg.get("aviso"):
        notas.insert(0, seg["aviso"])
    if not seg:
        notas = ["Aún no hay una segmentación entrenada para esta empresa."]
    return {
        "titulo": "Segmentación de clientes (K-means sobre RFM)",
        "subtitulo": f"{empresa.nombre} · Entrenada el {seg.get('fecha', '-')}",
        "kpis": [
            _kpi("Clientes analizados", seg.get("clientes_total", 0)),
            _kpi("Grupos (k)", seg.get("k") or "-"),
            _kpi("Silhouette", seg.get("silhouette_k") if seg.get("silhouette_k") is not None else "-"),
        ],
        "columnas": [
            _col("Cliente"), _col("Correo"), _col("Segmento"), _col("Días desde la última compra", "numero"),
            _col("Compras", "numero"), _col("Monto", "dinero"),
        ],
        "filas": [
            [c["cliente"], c["correo"], c["nombre_segmento"], c["recencia_dias"], c["frecuencia"], c["monto"]]
            for c in seg.get("clientes", [])
        ],
        "notas": notas,
        "grafico": {
            "tipo": "doughnut",
            "titulo": "Clientes por segmento",
            "etiquetas": [r["nombre"] for r in resumen],
            "series": [{"nombre": "Clientes", "datos": [r["clientes"] for r in resumen]}],
            "formato": "numero",
        } if resumen else None,
    }


def _reporte_modelos(empresa, datos):
    """Resultado exportable con la evaluación de los modelos."""
    ventanas = [v for v in datos["demanda"]["ventanas"] if not v["aviso"]]
    seg = datos["segmentacion"] or {}
    filas = [
        [
            f"{v['ventana_meses']} meses", v["filas_entrenamiento"], v["filas_prueba"], v["mae"],
            v["rmse"], str(v["r2"]) if v["r2"] is not None else "-", v["mae_linea_base"],
            "Sí" if v["vigente"] else "No",
        ]
        for v in ventanas
    ]
    notas = [
        "Demanda: RandomForestRegressor; unidades por prenda, sucursal y semana. La prueba es el "
        "último 25% de las semanas. Línea base: promedio de las últimas 4 semanas. Queda vigente "
        "la ventana con menor MAE.",
    ]
    if seg.get("silhouette"):
        texto = ", ".join(f"k={k}: {v}" for k, v in seg["silhouette"].items())
        notas.append(f"Segmentación K-means: silhouette por cantidad de grupos ({texto}). Se usan {seg.get('k')} grupos.")
    for v in datos["demanda"]["ventanas"]:
        if v["aviso"]:
            notas.append(f"Ventana de {v['ventana_meses']} meses: {v['aviso']}")
    return {
        "titulo": "Evaluación de los modelos de Machine Learning",
        "subtitulo": empresa.nombre,
        "kpis": [
            _kpi("Ventanas evaluadas", len(ventanas)),
            _kpi("Ventana vigente", next((f"{v['ventana_meses']} meses" for v in ventanas if v["vigente"]), "-")),
            _kpi("Silhouette segmentación", seg.get("silhouette_k") if seg.get("silhouette_k") is not None else "-"),
        ],
        "columnas": [
            _col("Ventana"), _col("Filas de entrenamiento", "numero"), _col("Filas de prueba", "numero"),
            _col("MAE", "numero"), _col("RMSE", "numero"), _col("R²"), _col("MAE línea base", "numero"),
            _col("Vigente"),
        ],
        "filas": filas,
        "notas": notas,
        "grafico": {
            "tipo": "bar",
            "titulo": "Error (MAE) del modelo frente a la línea base",
            "etiquetas": [f"{v['ventana_meses']} meses" for v in ventanas],
            "series": [
                {"nombre": "Modelo", "datos": [v["mae"] for v in ventanas]},
                {"nombre": "Línea base", "datos": [v["mae_linea_base"] for v in ventanas]},
            ],
            "formato": "numero",
        } if ventanas else None,
    }


ARMADORES = {
    "demanda": _reporte_demanda,
    "segmentos": _reporte_segmentos,
    "modelos": _reporte_modelos,
}


# --------------------------------------------------------------------------
# Vistas
# --------------------------------------------------------------------------

class DashboardAnaliticaView(APIView):
    """Dashboard de Analítica (modelos, predicciones y segmentos) de una empresa."""

    permission_classes = PERMISOS_ANALITICA

    def get(self, request):
        """Devuelve los datos del dashboard."""
        empresa, error = _empresa_de(request, request.query_params.get("empresa"))
        if error:
            return error
        datos = armar_dashboard(empresa)
        super_admin = _es_super_admin(request.user)
        datos["super_admin"] = super_admin
        datos["empresas"] = (
            [{"id": e.id_empresa, "nombre": e.nombre} for e in Empresa.objects.filter(estado="ACTIVA").order_by("nombre")]
            if super_admin else []
        )
        return Response(datos)


class ReentrenarView(APIView):
    """Vuelve a entrenar los modelos de una empresa (o de todas, solo SUPER_ADMIN)."""

    permission_classes = PERMISOS_ANALITICA

    def post(self, request):
        """Entrena y devuelve el resumen de cada empresa."""
        valor = request.data.get("empresa")
        if _es_super_admin(request.user) and str(valor).lower() == "todas":
            empresas = list(Empresa.objects.filter(estado="ACTIVA").order_by("nombre"))
        else:
            empresa, error = _empresa_de(request, valor)
            if error:
                return error
            empresas = [empresa]
        resumenes = []
        for empresa in empresas:
            resumen = entrenar_empresa(empresa, request.user)
            resumenes.append(resumen)
            log_audit(
                usuario=request.user,
                accion="MODELOS_REENTRENADOS",
                tabla_afectada="ml_entrenamiento",
                registro_id=None,
                descripcion=f"Se reentrenaron los modelos de Machine Learning de {empresa.nombre}",
                direccion_ip=get_client_ip(request),
                empresa=empresa,
            )
        return Response({"resultados": resumenes}, status=status.HTTP_201_CREATED)


class ExportarAnaliticaView(APIView):
    """Descarga un reporte de Analítica en PDF, Excel o HTML."""

    permission_classes = PERMISOS_ANALITICA

    def get(self, request):
        """Genera el archivo del reporte pedido."""
        reporte = request.query_params.get("reporte", "demanda")
        if reporte not in ARMADORES:
            return Response({"detail": "Reporte no válido. Usa demanda, segmentos o modelos."},
                            status=status.HTTP_400_BAD_REQUEST)
        empresa, error = _empresa_de(request, request.query_params.get("empresa"))
        if error:
            return error
        resultado = ARMADORES[reporte](empresa, armar_dashboard(empresa))
        formato = request.query_params.get("formato", "pdf")
        meta = {"generado": _fecha_texto(timezone.now())}
        try:
            contenido, tipo_mime, nombre = exportar(formato, resultado, meta)
        except FormatoInvalido as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        log_audit(
            usuario=request.user,
            accion="REPORTE_EXPORTADO",
            tabla_afectada="ml_entrenamiento",
            registro_id=None,
            descripcion=f"Se exportó «{REPORTES[reporte]}» de {empresa.nombre} en formato {str(formato).upper()}",
            direccion_ip=get_client_ip(request),
            empresa=empresa,
        )
        respuesta = HttpResponse(contenido, content_type=tipo_mime)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Access-Control-Expose-Headers"] = "Content-Disposition"
        return respuesta