# backend/apps/inventory/views_traspasos.py
#
# NUEVO (Fase 3 - CU07): API de traspasos entre sucursales.
#
#   GET  /api/inventory/traspasos/?estado=SOLICITADO   lista visible para el usuario
#   POST /api/inventory/traspasos/                     solicitar
#        {id_sucursal_origen, id_sucursal_destino, observacion, desde_sugerencia,
#         lineas: [{id_variante, cantidad}]}
#   GET  /api/inventory/traspasos/<id>/                detalle
#   POST /api/inventory/traspasos/<id>/aprobar/
#   POST /api/inventory/traspasos/<id>/rechazar/       {motivo}
#   POST /api/inventory/traspasos/<id>/recibir/
#   POST /api/inventory/traspasos/<id>/cancelar/
#   GET  /api/inventory/traspasos/opciones/            sucursales y rol del usuario
#   GET  /api/inventory/traspasos/stock/?sucursal=<id> prendas con stock en una sucursal
#   GET  /api/inventory/traspasos/sugerencias/?empresa=<id>  sugerencias de la Analítica
#
# Las reglas (quién puede qué, stock, estados) están en traspasos.py.

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users_auth.models import Empresa
from apps.users_auth.suscripciones import requiere_funcion
from common.permissions import IsAdminEmpresa, IsEncargadoSucursal
from common.utils import get_client_ip, log_audit

from . import traspasos as reglas
from .models import StockItem

PERMISOS_TRASPASOS = [IsEncargadoSucursal]
PERMISOS_SUGERENCIAS = [IsAdminEmpresa, requiere_funcion("reportes_ia")]


def _fecha(valor):
    """Fecha ISO o None."""
    return valor.isoformat() if valor else None


def _sucursal(sucursal):
    """{id, nombre} de una sucursal."""
    return {"id": sucursal.id_sucursal, "nombre": sucursal.nombre}


def serializar(traspaso, usuario, con_detalle=True):
    """Datos de un traspaso para la web, con las acciones permitidas al usuario."""
    datos = {
        "id": traspaso.id_traspaso,
        "estado": traspaso.estado,
        "estado_display": traspaso.get_estado_display(),
        "empresa": {"id": traspaso.id_empresa_id, "nombre": traspaso.id_empresa.nombre},
        "origen": _sucursal(traspaso.id_sucursal_origen),
        "destino": _sucursal(traspaso.id_sucursal_destino),
        "observacion": traspaso.observacion,
        "desde_sugerencia": traspaso.desde_sugerencia,
        "motivo_rechazo": traspaso.motivo_rechazo,
        "solicitado_por": reglas.nombre_usuario(traspaso.id_usuario_solicita),
        "fecha_solicitud": _fecha(traspaso.fecha_solicitud),
        "aprobado_por": reglas.nombre_usuario(traspaso.id_usuario_aprueba),
        "fecha_aprobacion": _fecha(traspaso.fecha_aprobacion),
        "rechazado_por": reglas.nombre_usuario(traspaso.id_usuario_rechaza),
        "fecha_rechazo": _fecha(traspaso.fecha_rechazo),
        "recibido_por": reglas.nombre_usuario(traspaso.id_usuario_recibe),
        "fecha_recepcion": _fecha(traspaso.fecha_recepcion),
        "cancelado_por": reglas.nombre_usuario(traspaso.id_usuario_cancela),
        "fecha_cancelacion": _fecha(traspaso.fecha_cancelacion),
        "acciones": reglas.acciones(usuario, traspaso),
    }
    detalles = list(
        traspaso.detalles.select_related("id_variante__id_producto", "id_variante__id_talla", "id_variante__id_color")
    )
    datos["prendas"] = len(detalles)
    datos["unidades"] = sum(d.cantidad for d in detalles)
    if con_detalle:
        disponible = reglas.stock_de(traspaso.id_sucursal_origen_id, [d.id_variante_id for d in detalles])
        datos["detalles"] = [
            {
                "id_variante": d.id_variante_id,
                "prenda": d.id_variante.id_producto.nombre,
                "talla": d.id_variante.id_talla.nombre,
                "color": d.id_variante.id_color.nombre,
                "codigo": d.id_variante.codigo_producto,
                "cantidad": d.cantidad,
                "stock_origen": disponible.get(d.id_variante_id, 0),
            }
            for d in detalles
        ]
    return datos


def _error(exc):
    """Respuesta para los errores de las reglas."""
    codigo = status.HTTP_403_FORBIDDEN if isinstance(exc, reglas.SinPermiso) else status.HTTP_400_BAD_REQUEST
    return Response({"detail": str(exc)}, status=codigo)


def _auditar(request, traspaso, accion, descripcion):
    """Registro en la bitácora."""
    log_audit(
        usuario=request.user,
        accion=accion,
        tabla_afectada="traspaso",
        registro_id=traspaso.id_traspaso,
        descripcion=descripcion,
        direccion_ip=get_client_ip(request),
        empresa=traspaso.id_empresa_id,
    )


class TraspasosView(APIView):
    """Lista los traspasos visibles y registra solicitudes nuevas."""

    permission_classes = PERMISOS_TRASPASOS

    def get(self, request):
        """Traspasos visibles para el usuario (opcional ?estado=)."""
        qs = reglas.traspasos_visibles(request.user).order_by("-fecha_solicitud", "-id_traspaso")
        estado = request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)
        return Response([serializar(t, request.user, con_detalle=False) for t in qs[:200]])

    def post(self, request):
        """Registra una solicitud de traspaso."""
        datos = request.data
        try:
            traspaso = reglas.crear(
                request.user,
                datos.get("id_sucursal_origen"),
                datos.get("id_sucursal_destino"),
                datos.get("lineas"),
                datos.get("observacion"),
                datos.get("desde_sugerencia", False),
            )
        except (reglas.ErrorTraspaso, reglas.SinPermiso) as exc:
            return _error(exc)
        _auditar(
            request, traspaso, "TRASPASO_SOLICITADO",
            f"Solicitó el traspaso #{traspaso.id_traspaso} de {traspaso.id_sucursal_origen.nombre} "
            f"a {traspaso.id_sucursal_destino.nombre}",
        )
        traspaso = reglas.traspasos_visibles(request.user).get(pk=traspaso.pk)
        return Response(serializar(traspaso, request.user), status=status.HTTP_201_CREATED)


class TraspasoDetalleView(APIView):
    """Detalle de un traspaso visible para el usuario."""

    permission_classes = PERMISOS_TRASPASOS

    def get(self, request, id_traspaso):
        """Devuelve el traspaso con sus prendas."""
        traspaso = reglas.traspasos_visibles(request.user).filter(pk=id_traspaso).first()
        if traspaso is None:
            return Response({"detail": "Traspaso no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        return Response(serializar(traspaso, request.user))


class TraspasoAccionView(APIView):
    """Aprobar, rechazar, recibir o cancelar un traspaso."""

    permission_classes = PERMISOS_TRASPASOS
    accion = None
    TEXTOS = {
        "aprobar": ("TRASPASO_APROBADO", "Aprobó el traspaso #{id}: salió el stock de {origen}"),
        "rechazar": ("TRASPASO_RECHAZADO", "Rechazó el traspaso #{id}"),
        "recibir": ("TRASPASO_RECIBIDO", "Recibió el traspaso #{id} en {destino}"),
        "cancelar": ("TRASPASO_CANCELADO", "Canceló el traspaso #{id}"),
    }

    def post(self, request, id_traspaso):
        """Ejecuta la acción sobre un traspaso visible para el usuario."""
        if not reglas.traspasos_visibles(request.user).filter(pk=id_traspaso).exists():
            return Response({"detail": "Traspaso no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        try:
            if self.accion == "rechazar":
                traspaso = reglas.rechazar(request.user, id_traspaso, request.data.get("motivo"))
            else:
                traspaso = getattr(reglas, self.accion)(request.user, id_traspaso)
        except (reglas.ErrorTraspaso, reglas.SinPermiso) as exc:
            return _error(exc)
        accion, texto = self.TEXTOS[self.accion]
        _auditar(
            request, traspaso, accion,
            texto.format(
                id=traspaso.id_traspaso,
                origen=traspaso.id_sucursal_origen.nombre,
                destino=traspaso.id_sucursal_destino.nombre,
            ),
        )
        traspaso = reglas.traspasos_visibles(request.user).get(pk=traspaso.pk)
        return Response(serializar(traspaso, request.user))


class OpcionesTraspasoView(APIView):
    """Sucursales disponibles y datos del rol para el formulario."""

    permission_classes = PERMISOS_TRASPASOS

    def get(self, request):
        """Sucursales entre las que el usuario puede pedir traspasos."""
        usuario = request.user
        encargado = reglas.es_encargado(usuario)
        return Response({
            "super_admin": reglas.es_super_admin(usuario),
            "puede_aprobar": bool(reglas.roles_de(usuario) & reglas.ROLES_ADMIN),
            "encargado": encargado,
            "destino_fijo": usuario.id_sucursal_id if encargado else None,
            "sucursales": [
                {"id": s.id_sucursal, "nombre": s.nombre, "id_empresa": s.id_empresa_id,
                 "empresa": s.id_empresa.nombre if s.id_empresa else ""}
                for s in reglas.sucursales_permitidas(usuario).order_by("id_empresa__nombre", "nombre")
            ],
        })


class StockTraspasoView(APIView):
    """Prendas (talla y color) con stock en una sucursal, para elegir qué traspasar."""

    permission_classes = PERMISOS_TRASPASOS

    def get(self, request):
        """Stock disponible de la sucursal pedida (solo sucursales permitidas)."""
        sucursal = reglas.sucursales_permitidas(request.user).filter(pk=request.query_params.get("sucursal") or 0).first()
        if sucursal is None:
            return Response({"detail": "Sucursal no encontrada."}, status=status.HTTP_404_NOT_FOUND)
        items = (
            StockItem.objects.filter(id_sucursal=sucursal, estado=True, cantidad__gt=0)
            .select_related("id_variante__id_producto", "id_variante__id_talla", "id_variante__id_color")
            .order_by("id_variante__id_producto__nombre", "id_variante__id_talla__nombre")
        )
        return Response([
            {
                "id_variante": i.id_variante_id,
                "id_producto": i.id_variante.id_producto_id,
                "prenda": i.id_variante.id_producto.nombre,
                "talla": i.id_variante.id_talla.nombre,
                "color": i.id_variante.id_color.nombre,
                "codigo": i.id_variante.codigo_producto,
                "stock": i.cantidad,
            }
            for i in items
        ])


class SugerenciasTraspasoView(APIView):
    """Traspasos sugeridos por la predicción de demanda (Analítica, CU09)."""

    permission_classes = PERMISOS_SUGERENCIAS

    def get(self, request):
        """Sugerencias de la empresa del usuario (o la elegida por el SUPER_ADMIN)."""
        usuario = request.user
        if reglas.es_super_admin(usuario):
            valor = request.query_params.get("empresa")
            empresa = Empresa.objects.filter(pk=valor).first() if str(valor).isdigit() else None
            if empresa is None:
                return Response({"detail": "Elige una empresa."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            empresa = usuario.id_empresa
            if empresa is None:
                return Response({"detail": "Tu usuario no pertenece a una empresa."},
                                status=status.HTTP_403_FORBIDDEN)
        return Response({"empresa": {"id": empresa.id_empresa, "nombre": empresa.nombre},
                         "sugerencias": reglas.sugerencias(empresa)})