# backend/apps/analytics/views_clientes.py
#
# NUEVO (Fase 3 - CU04): API del perfil de clientes por empresa.
#
#   GET /api/analytics/clientes/        clientes de la empresa con su resumen
#   GET /api/analytics/clientes/<id>/   perfil del cliente en la empresa
#
# Acceso: SUPER_ADMIN (todos los clientes, todas las empresas) y ADMIN_EMPRESA
# (solo los clientes con actividad en su empresa y solo lo que hicieron en
# ella). Encargado, cajero, repartidor y cliente reciben 403. Un cliente sin
# actividad en la empresa del administrador responde 404.

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsAdminEmpresa

from . import perfil_clientes


def _empresa_del(usuario):
    """None para el SUPER_ADMIN (todas); la empresa del ADMIN_EMPRESA; 0 si no tiene."""
    if usuario.roles.filter(nombre="SUPER_ADMIN").exists():
        return None
    return usuario.id_empresa_id or 0


class ClientesEmpresaView(APIView):
    """Clientes con actividad en la empresa del administrador (o todos)."""

    permission_classes = [IsAdminEmpresa]

    def get(self, request):
        """Lista con compras, total gastado, última compra y segmento."""
        empresa_id = _empresa_del(request.user)
        return Response({
            "super_admin": empresa_id is None,
            "clientes": perfil_clientes.listar(empresa_id),
        })


class PerfilClienteView(APIView):
    """Perfil de un cliente en la empresa del administrador (o en todas)."""

    permission_classes = [IsAdminEmpresa]

    def get(self, request, id_cliente):
        """Datos, resumen, preferencias, segmento e historial del cliente."""
        empresa_id = _empresa_del(request.user)
        datos = perfil_clientes.perfil(empresa_id, id_cliente)
        if datos is None:
            return Response({"detail": "Cliente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        datos["super_admin"] = empresa_id is None
        return Response(datos)