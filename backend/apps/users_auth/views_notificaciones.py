# backend/apps/users_auth/views_notificaciones.py
"""API del centro de notificaciones (Fase 2 - CU16).

Rutas (bajo /api/auth/):
    GET  notificaciones/                -> avisos del usuario, del más reciente al más antiguo
                                           (?no_leidas=1 solo los no leídos)
    GET  notificaciones/contador/       -> {"no_leidas": <n>} para el número de la campana
    POST notificaciones/<id>/leer/      -> marca un aviso como leído
    POST notificaciones/leer-todas/     -> marca todos como leídos

Cada usuario ve solo sus avisos. Antes de responder se generan los
recordatorios de reservas que vencen en menos de un día (no hay tareas
programadas en el servidor).
"""
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Notificacion
from .notificaciones import generar_recordatorios


class NotificacionSerializer(serializers.ModelSerializer):
    """Aviso de la campana."""

    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = Notificacion
        fields = [
            "id_notificacion", "tipo", "tipo_display", "titulo", "mensaje", "enlace",
            "leida", "fecha_creacion", "fecha_lectura",
        ]
        read_only_fields = fields


class NotificacionViewSet(ReadOnlyModelViewSet):
    """Avisos del usuario autenticado."""

    serializer_class = NotificacionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Solo los avisos del usuario (opcional ?no_leidas=1)."""
        queryset = Notificacion.objects.filter(id_usuario=self.request.user).order_by("-fecha_creacion")
        if self.request.query_params.get("no_leidas") in ("1", "true"):
            queryset = queryset.filter(leida=False)
        return queryset

    def list(self, request, *args, **kwargs):
        """Genera los recordatorios pendientes y lista los avisos."""
        generar_recordatorios(request.user)
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def contador(self, request):
        """Cantidad de avisos sin leer (para la campana)."""
        generar_recordatorios(request.user)
        no_leidas = Notificacion.objects.filter(id_usuario=request.user, leida=False).count()
        return Response({"no_leidas": no_leidas})

    @action(detail=True, methods=["post"])
    def leer(self, request, pk=None):
        """Marca el aviso como leído."""
        notificacion = self.get_object()
        if not notificacion.leida:
            notificacion.leida = True
            notificacion.fecha_lectura = timezone.now()
            notificacion.save(update_fields=["leida", "fecha_lectura"])
        return Response(self.get_serializer(notificacion).data)

    @action(detail=False, methods=["post"], url_path="leer-todas")
    def leer_todas(self, request):
        """Marca todos los avisos del usuario como leídos."""
        marcadas = Notificacion.objects.filter(id_usuario=request.user, leida=False).update(
            leida=True, fecha_lectura=timezone.now()
        )
        return Response({"marcadas": marcadas, "no_leidas": 0})