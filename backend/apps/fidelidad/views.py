# backend/apps/fidelidad/views.py
#
# NUEVO (Fase 3 - CU18): API del descuento por fidelidad.
#
#   GET  /api/fidelidad/regla/        regla vigente (SUPER_ADMIN y ADMIN_EMPRESA)
#   PUT  /api/fidelidad/regla/        cambia la regla (solo SUPER_ADMIN)
#        {"compras_requeridas": 5, "porcentaje": 50, "activa": true}
#   GET  /api/fidelidad/monitoreo/?mes=AAAA-MM[&id_cliente=<id>][&id_empresa=<id>]
#        clientes del mes con su progreso y lo descontado. ADMIN_EMPRESA: su
#        empresa; SUPER_ADMIN: todas (o una con id_empresa).
#   GET  /api/fidelidad/mi-progreso/[?id_empresa=<id>]   (cliente)
#   GET  /api/fidelidad/pos/?correo=<correo>&id_sucursal=<id>  (personal de caja)
#        si el cliente tiene el descuento en la empresa de la sucursal.
from decimal import Decimal, InvalidOperation

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Sucursal
from apps.users_auth.models import Cliente
from common.permissions import IsAdminEmpresa, IsCajero, IsCliente, IsSuperAdmin
from common.tenancy import filtrar_queryset
from common.utils import log_audit

from . import consultas, servicio
from .models import ReglaFidelidad

MAX_COMPRAS = 50


def _es_super_admin(usuario):
    """True si el usuario es SUPER_ADMIN."""
    return usuario.roles.filter(nombre="SUPER_ADMIN").exists()


def _entero(valor):
    """Entero de un texto o None."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


class ReglaFidelidadView(APIView):
    """Regla global del descuento por fidelidad."""

    def get_permissions(self):
        """Ver: SUPER_ADMIN y ADMIN_EMPRESA. Cambiar: solo SUPER_ADMIN."""
        if self.request.method == "GET":
            return [IsAdminEmpresa()]
        return [IsSuperAdmin()]

    def get(self, request):
        """Regla vigente."""
        return Response(consultas.regla_dict())

    def put(self, request):
        """Cambia compras requeridas, porcentaje y si está activa (aplica de inmediato)."""
        compras = _entero(request.data.get("compras_requeridas"))
        if compras is None or not 1 <= compras <= MAX_COMPRAS:
            return Response({"error": f"Las compras requeridas deben estar entre 1 y {MAX_COMPRAS}."}, status=400)
        try:
            porcentaje = Decimal(str(request.data.get("porcentaje"))).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            porcentaje = None
        if porcentaje is None or not Decimal("1") <= porcentaje <= Decimal("100"):
            return Response({"error": "El porcentaje debe estar entre 1 y 100."}, status=400)
        activa = request.data.get("activa")
        if not isinstance(activa, bool):
            return Response({"error": "Indica si la regla está activa."}, status=400)

        regla = ReglaFidelidad.vigente()
        regla.compras_requeridas = compras
        regla.porcentaje = porcentaje
        regla.activa = activa
        regla.actualizado_por = request.user
        regla.save()
        ganaron = servicio.verificar_mes_actual() if activa else 0
        log_audit(
            usuario=request.user,
            accion="REGLA_FIDELIDAD",
            tabla_afectada="regla_fidelidad",
            registro_id=regla.pk,
            descripcion=(
                f"{request.user.nombres} {request.user.apellidos} cambió la regla de fidelidad: "
                f"{regla}. Clientes que ganaron el descuento al cambiarla: {ganaron}."
            ),
        )
        datos = consultas.regla_dict()
        datos["ganaron_ahora"] = ganaron
        return Response(datos)


class MonitoreoFidelidadView(APIView):
    """Clientes del mes con su progreso, beneficios usados y lo descontado."""

    permission_classes = [IsAdminEmpresa]

    def get(self, request):
        """ADMIN_EMPRESA: su empresa. SUPER_ADMIN: todas o una (id_empresa)."""
        super_admin = _es_super_admin(request.user)
        empresa_id = _entero(request.query_params.get("id_empresa")) if super_admin else (
            request.user.id_empresa_id or 0
        )
        periodo = consultas.leer_periodo(request.query_params.get("mes"))
        datos = consultas.monitoreo(periodo, empresa_id, _entero(request.query_params.get("id_cliente")))
        datos["super_admin"] = super_admin
        return Response(datos)


class MiProgresoView(APIView):
    """Progreso del mes del cliente en cada empresa donde compró."""

    permission_classes = [IsCliente]

    def get(self, request):
        """Con ?id_empresa=<id> devuelve solo esa empresa (para el carrito)."""
        cliente = Cliente.objects.filter(id_usuario=request.user).first()
        if cliente is None:
            return Response({"error": "Tu usuario no tiene ficha de cliente."}, status=400)
        return Response(consultas.progreso_cliente(cliente, _entero(request.query_params.get("id_empresa"))))


class ClientePosView(APIView):
    """Si el cliente (por su correo) tiene el descuento en la empresa de la sucursal."""

    permission_classes = [IsCajero]

    def get(self, request):
        """Respuesta para el POS web antes de cobrar."""
        correo = (request.query_params.get("correo") or "").strip()
        if not correo:
            return Response({"error": "Indica el correo del cliente."}, status=400)
        sucursal = filtrar_queryset(Sucursal.objects.select_related("id_empresa"), request).filter(
            pk=_entero(request.query_params.get("id_sucursal"))
        ).first()
        if sucursal is None:
            return Response({"error": "Sucursal no encontrada."}, status=404)
        cliente = Cliente.objects.select_related("id_usuario").filter(
            id_usuario__correo__iexact=correo
        ).first()
        if cliente is None:
            return Response({"error": f"No existe un cliente con el correo {correo}."}, status=404)
        datos = servicio.estado(cliente, sucursal.id_empresa)
        usuario = cliente.id_usuario
        datos["cliente"] = f"{usuario.nombres} {usuario.apellidos}".strip()
        datos["correo"] = usuario.correo
        return Response(datos)