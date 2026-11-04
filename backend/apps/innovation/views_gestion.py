# backend/apps/innovation/views_gestion.py

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users_auth.suscripciones import requiere_funcion
from common.permissions import IsEncargadoSucursal
from common.utils import get_client_ip, log_audit

from .chatbot import MensajeInvalido
from .chatbot_admin import responder_gestion
from .exportadores import FormatoInvalido, exportar
from .llm import ServicioIANoDisponible
from .models import ReporteAsistente

MAX_REPORTES_LISTADO = 50

# NUEVO (SaaS - paso 5): el asistente de gestión y sus reportes solo están
# disponibles en planes que incluyen reportes con IA (PRO y ULTRA).
PERMISOS_ASISTENTE = [IsEncargadoSucursal, requiere_funcion("reportes_ia")]
# MODIFICADO (Fase 3 - CU13): ver y exportar un reporte guardado del propio
# usuario está en los tres planes, porque los reportes convencionales (sin
# IA, views_reportes.py) también se guardan aquí y se exportan igual.
PERMISOS_REPORTE = [IsEncargadoSucursal]

def _fecha_texto(momento):
    """Fecha y hora de Bolivia como dd/mm/aaaa hh:mm."""
    return timezone.localtime(momento).strftime("%d/%m/%Y %H:%M")

def _resultado_sin_respuesta(reporte):
    """Resultado guardado sin el texto de la respuesta, que se entrega aparte."""
    return {k: v for k, v in (reporte.resultado or {}).items() if k != "respuesta"}

def _reporte_del_usuario(request, id_reporte):
    """Reporte del usuario autenticado, o 404 si no existe o es de otra persona."""
    return get_object_or_404(ReporteAsistente, pk=id_reporte, id_usuario=request.user)

class AsistenteGestionView(APIView):
    """CU20 - El personal pregunta y recibe la respuesta con sus resultados."""

    permission_classes = PERMISOS_ASISTENTE

    def post(self, request):
        """Responde la pregunta del personal y registra en bitácora los reportes generados."""
        datos = request.data if isinstance(request.data, dict) else {}
        mensaje = datos.get("mensaje")
        if not isinstance(mensaje, str):
            mensaje = ""

        try:
            resultado = responder_gestion(request.user, mensaje)
        except MensajeInvalido as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ServicioIANoDisponible as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        ip = get_client_ip(request)
        for item in resultado["resultados"]:
            log_audit(
                usuario=request.user,
                accion="REPORTE_GENERADO",
                tabla_afectada="reporte_asistente",
                registro_id=item["id_reporte"],
                descripcion=(
                    f"El asistente de gestión generó el reporte "
                    f"«{item['resultado']['titulo']}»"
                ),
                direccion_ip=ip,
            )
        return Response(resultado)

class ReportesGestionView(APIView):
    """Reportes guardados del usuario, del más reciente al más antiguo."""

    permission_classes = PERMISOS_ASISTENTE

    def get(self, request):
        """Lista los últimos reportes del usuario."""
        reportes = ReporteAsistente.objects.filter(id_usuario=request.user).order_by(
            "-fecha_creacion", "-id_reporte"
        )[:MAX_REPORTES_LISTADO]
        return Response(
            [
                {
                    "id_reporte": r.id_reporte,
                    "fecha": _fecha_texto(r.fecha_creacion),
                    "pregunta": r.pregunta,
                    "titulo": r.titulo,
                    "consulta": r.consulta,
                }
                for r in reportes
            ]
        )

class ReporteDetalleView(APIView):
    """Un reporte guardado, completo, para volver a mostrarlo en pantalla."""

    permission_classes = PERMISOS_REPORTE

    def get(self, request, id_reporte):
        """Devuelve un reporte guardado del usuario."""
        reporte = _reporte_del_usuario(request, id_reporte)
        return Response(
            {
                "id_reporte": reporte.id_reporte,
                "fecha": _fecha_texto(reporte.fecha_creacion),
                "pregunta": reporte.pregunta,
                "consulta": reporte.consulta,
                "respuesta": (reporte.resultado or {}).get("respuesta", ""),
                "resultado": _resultado_sin_respuesta(reporte),
            }
        )

class ReporteExportarView(APIView):
    """Descarga un reporte guardado en PDF, Excel (xlsx) o HTML."""

    permission_classes = PERMISOS_REPORTE

    def get(self, request, id_reporte):
        """Exporta un reporte guardado en el formato pedido."""
        reporte = _reporte_del_usuario(request, id_reporte)
        formato = request.query_params.get("formato", "pdf")
        meta = {
            "pregunta": reporte.pregunta,
            "generado": _fecha_texto(reporte.fecha_creacion),
        }
        try:
            contenido, tipo_mime, nombre = exportar(
                formato, _resultado_sin_respuesta(reporte), meta
            )
        except FormatoInvalido as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_audit(
            usuario=request.user,
            accion="REPORTE_EXPORTADO",
            tabla_afectada="reporte_asistente",
            registro_id=reporte.id_reporte,
            descripcion=(
                f"Se exportó el reporte «{reporte.titulo}» en formato "
                f"{str(formato).upper()}"
            ),
            direccion_ip=get_client_ip(request),
        )
        respuesta = HttpResponse(contenido, content_type=tipo_mime)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        # Permite que la web lea el nombre del archivo desde JavaScript.
        respuesta["Access-Control-Expose-Headers"] = "Content-Disposition"
        return respuesta