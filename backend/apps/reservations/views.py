# backend/apps/reservations/views.py
# NUEVO (SaaS - A.5): POST reservas/sync/ recibe las reservas que el cliente
# hizo sin conexión (ver apps/reservations/sync.py).
# MODIFICADO (Fase 2 - reservas con anticipo): la reserva se paga por Stripe
# (anticipo o total) y recién ahí se aparta la prenda; vence a la semana de
# la fecha reservada y el cliente puede cancelarla (CU17) con reembolso menos
# el 10% (ver apps/reservations/pagos.py).
# MODIFICADO (arreglo RF02): un grupo con VER_RESERVAS o GESTIONAR_RESERVAS
# también ve las reservas de su empresa como personal de tienda.
from collections import Counter
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from common.permissions import IsEncargadoSucursal, IsCliente
from common.privilegios import tiene_alguno
from common.tenancy import alcance_de, filtrar_queryset
from common.utils import log_audit
from apps.users_auth.models import Cliente
from .models import FittingReservation
from .pagos import ReservaPagoService, preparar_montos, verificar_disponibilidad
from .serializers import FittingReservationSerializer
from .services import ReservationStockService
from .sync import MAX_RESERVAS_POR_LOTE, SyncReservaService

ROLES_PERSONAL_RESERVAS = ["SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL", "CAJERO"]


class FittingReservationViewSet(ModelViewSet):
    """Reservas de prendas.

    GET  /api/reservations/reservas/                  -> lista (vence las que pasaron su plazo)
    POST /api/reservations/reservas/                  -> crea la reserva (cliente)
         {"id_sucursal", "fecha_reserva", "hora_reserva", "items": [{"id_variante"}],
          "tipo_pago": "ANTICIPO" | "TOTAL"}
         Queda PENDIENTE_PAGO (3 horas para pagar) y devuelve "pago" con el
         client_secret de Stripe si se indicó tipo_pago.
    POST /api/reservations/reservas/<id>/iniciar-pago/ {"tipo_pago"}  (cliente)
    POST /api/reservations/reservas/<id>/pagar/        {"referencia_pago"} (cliente)
         Verifica el pago, aparta las prendas y deja la reserva CONFIRMADA.
    POST /api/reservations/reservas/<id>/cancelar/     {"motivo"} (CU17)
         El cliente cancela: se libera la prenda y se devuelve lo pagado
         menos el 10% del precio total. El personal solo cancela reservas sin pago.
    POST /api/reservations/reservas/sync/              -> reservas hechas sin conexión
    """

    serializer_class = FittingReservationSerializer

    def get_permissions(self):
        """Crear, pagar y sincronizar reservas: solo clientes; lo demás, cualquier autenticado."""
        if self.action in ("create", "sincronizar", "iniciar_pago", "pagar"):
            return [IsCliente()]
        return [IsAuthenticated()]

    def _es_personal(self):
        """True si el usuario es personal de tienda (no cliente), por su rol o por un grupo."""
        usuario = self.request.user
        return usuario.roles.filter(nombre__in=ROLES_PERSONAL_RESERVAS).exists() or tiene_alguno(
            usuario, "VER_RESERVAS", "GESTIONAR_RESERVAS"
        )

    def _cliente(self):
        """Ficha de cliente del usuario (o None)."""
        return Cliente.objects.filter(id_usuario=self.request.user).first()

    def get_queryset(self):
        """El personal ve las reservas de su empresa; el cliente, las suyas (de cualquier empresa)."""
        queryset = FittingReservation.objects.select_related(
            "id_sucursal", "id_empresa", "id_cliente__id_usuario"
        ).prefetch_related("items__id_variante").order_by("-fecha_creacion")
        if self._es_personal():
            # SaaS: solo reservas hechas en sucursales de su empresa.
            queryset = filtrar_queryset(queryset, self.request)
            estado = self.request.query_params.get("estado")
            sucursal = self.request.query_params.get("sucursal")
            if estado:
                queryset = queryset.filter(estado=estado)
            if sucursal:
                queryset = queryset.filter(id_sucursal_id=sucursal)
            return queryset
        if alcance_de(self.request).es_personal:
            return queryset.none()
        cliente = self._cliente()
        if cliente is None:
            return queryset.none()
        return queryset.filter(id_cliente=cliente)

    def list(self, request, *args, **kwargs):
        """Antes de listar, vence las reservas cuyo plazo ya pasó (no hay tareas programadas)."""
        if self._es_personal():
            alcance = alcance_de(request)
            empresa_id = None if alcance.super_admin else request.user.id_empresa_id
            ReservaPagoService.procesar_vencimientos(empresa_id=empresa_id)
        else:
            cliente = self._cliente()
            if cliente is not None:
                ReservaPagoService.procesar_vencimientos(cliente=cliente)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Crea la reserva esperando el pago (y el cobro en Stripe si se eligió tipo de pago)."""
        cliente = self._cliente()
        if cliente is None:
            return Response({"error": "Tu usuario no tiene ficha de cliente."}, status=400)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reserva = serializer.save(id_cliente=cliente)
        try:
            verificar_disponibilidad(reserva)
        except ValueError as e:
            reserva.delete()
            return Response({"error": str(e)}, status=400)
        preparar_montos(reserva)
        log_audit(
            usuario=cliente.id_usuario,
            accion="RESERVA_CREADA",
            tabla_afectada="fitting_reservation",
            registro_id=reserva.id_reserva,
            descripcion=(
                f"{cliente.id_usuario.nombres} {cliente.id_usuario.apellidos} "
                f"reservó {reserva.items.count()} prenda(s) en "
                f"{reserva.id_sucursal.nombre} - Reserva #{reserva.id_reserva} "
                f"(pendiente de pago, Bs {reserva.monto_total})"
            ),
        )
        pago = None
        tipo_pago = request.data.get("tipo_pago")
        if tipo_pago:
            try:
                reserva, client_secret = ReservaPagoService.iniciar_pago(
                    reserva.pk, cliente, tipo_pago
                )
            except ValueError as e:
                return Response({"error": str(e)}, status=400)
            pago = {
                "client_secret": client_secret,
                "referencia_pago": reserva.referencia_pago,
                "monto": reserva.monto_a_pagar,
            }
        data = self.get_serializer(self.get_queryset().get(pk=reserva.pk)).data
        data["pago"] = pago
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="iniciar-pago")
    def iniciar_pago(self, request, pk=None):
        """Crea el cobro en Stripe por el anticipo o el total (reservas pendientes de pago)."""
        reserva = self.get_object()
        try:
            reserva, client_secret = ReservaPagoService.iniciar_pago(
                reserva.pk, self._cliente(), request.data.get("tipo_pago")
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return Response({
            "reserva": self.get_serializer(self.get_queryset().get(pk=reserva.pk)).data,
            "pago": {
                "client_secret": client_secret,
                "referencia_pago": reserva.referencia_pago,
                "monto": reserva.monto_a_pagar,
            },
        })

    @action(detail=True, methods=["post"])
    def pagar(self, request, pk=None):
        """Confirma el pago hecho con Stripe: aparta las prendas y confirma la reserva."""
        reserva = self.get_object()
        referencia = request.data.get("referencia_pago")
        if not referencia:
            return Response({"error": "Falta la referencia de pago."}, status=400)
        try:
            reserva = ReservaPagoService.confirmar_pago(reserva.pk, self._cliente(), referencia)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return Response(self.get_serializer(self.get_queryset().get(pk=reserva.pk)).data)

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        """CU17: cancela la reserva; si está pagada, devuelve lo pagado menos el 10%."""
        reserva = self.get_object()
        if self._es_personal() and reserva.monto_pagado:
            return Response(
                {"error": "Una reserva pagada solo la puede cancelar el cliente (con reembolso)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            reserva = ReservaPagoService.cancelar(reserva.pk, request.user, request.data.get("motivo"))
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(self.get_queryset().get(pk=reserva.pk)).data)

    @action(detail=True, methods=["post"], permission_classes=[IsEncargadoSucursal])
    def confirmar(self, request, pk=None):
        """Confirma manualmente una reserva pendiente."""
        reserva = self.get_object()
        if reserva.estado != "PENDIENTE":
            return Response(
                {"error": "Solo se puede confirmar una reserva pendiente."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reserva.estado = "CONFIRMADA"
        reserva.save()
        ReservationStockService.confirmar_reserva(reserva)
        log_audit(
            usuario=request.user,
            accion="RESERVA_CONFIRMADA",
            tabla_afectada="fitting_reservation",
            registro_id=reserva.id_reserva,
            descripcion=(
                f"{request.user.nombres} {request.user.apellidos} confirmó la "
                f"Reserva #{reserva.id_reserva} del cliente {reserva.id_cliente}"
            ),
        )
        return Response(self.get_serializer(reserva).data)

    @action(detail=True, methods=["post"], permission_classes=[IsEncargadoSucursal])
    def completar(self, request, pk=None):
        """Marca la reserva como completada (solo si no queda saldo por cobrar)."""
        reserva = self.get_object()
        # MODIFICADO (Fase 2): una reserva con saldo se completa al cobrarlo en el POS.
        if reserva.estado != "CONFIRMADA":
            return Response(
                {"error": "Solo se puede completar una reserva confirmada."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if reserva.saldo:
            return Response(
                {"error": f"Falta cobrar el saldo (Bs {reserva.saldo}): cóbralo en el Punto de Venta."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reserva.estado = "COMPLETADA"
        reserva.save()
        log_audit(
            usuario=request.user,
            accion="RESERVA_COMPLETADA",
            tabla_afectada="fitting_reservation",
            registro_id=reserva.id_reserva,
            descripcion=(
                f"{request.user.nombres} {request.user.apellidos} completó la "
                f"Reserva #{reserva.id_reserva} del cliente {reserva.id_cliente}"
            ),
        )
        return Response(self.get_serializer(reserva).data)

    # NUEVO (SaaS - A.5): reservas hechas sin conexión.
    @action(detail=False, methods=["post"], url_path="sync")
    def sincronizar(self, request):
        """Registra las reservas que el cliente guardó sin conexión.
        Body: {"operaciones": [{
            "uuid": "<uuid generado en el dispositivo>",
            "fecha_operacion": "2026-10-27T15:30:00-04:00",
            "id_sucursal": <int>,
            "fecha_reserva": "2026-10-30",
            "hora_reserva": "16:00",
            "items": [{"id_variante": <int>}]
        }]}
        Respuesta: un resultado por operación con estado SINCRONIZADA,
        DUPLICADA o RECHAZADA, y el resumen. MODIFICADO (Fase 2): la reserva
        sincronizada queda "Pendiente de pago" con 3 horas para pagarse.
        """
        operaciones = request.data.get("operaciones") if isinstance(request.data, dict) else None
        if not isinstance(operaciones, list) or not operaciones:
            return Response({"error": "Envía la lista de operaciones."}, status=400)
        if len(operaciones) > MAX_RESERVAS_POR_LOTE:
            return Response(
                {"error": f"Máximo {MAX_RESERVAS_POR_LOTE} operaciones por envío."},
                status=400,
            )
        cliente = Cliente.objects.filter(id_usuario=request.user).first()
        if cliente is None:
            return Response({"error": "Solo un cliente puede sincronizar reservas."}, status=403)
        resultados = SyncReservaService.sincronizar(request.user, cliente, operaciones)
        resumen = Counter(resultado["estado"] for resultado in resultados)
        return Response({
            "resultados": resultados,
            "resumen": {
                "SINCRONIZADA": resumen.get("SINCRONIZADA", 0),
                "DUPLICADA": resumen.get("DUPLICADA", 0),
                "RECHAZADA": resumen.get("RECHAZADA", 0),
            },
        })