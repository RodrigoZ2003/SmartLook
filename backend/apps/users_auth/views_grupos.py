"""Permisos del usuario que inició sesión (arreglo RF02).

GET /api/auth/mis-privilegios/ -> {"privilegios": [...]}
La web y el móvil los vuelven a pedir al abrir el panel, para que un cambio
hecho en "Permisos por rol" se note sin cerrar sesión.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.privilegios import privilegios_de


class MisPrivilegiosView(APIView):
    """Permisos actuales del rol del usuario."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Devuelve los permisos marcados para el rol del usuario."""
        return Response({"privilegios": sorted(privilegios_de(request.user))})