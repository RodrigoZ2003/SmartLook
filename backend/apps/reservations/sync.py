# backend/apps/reservations/sync.py
"""Sincronización de reservas hechas sin conexión (SaaS - A.5).

Flujo (mismo contrato que las ventas POS de apps/sales/sync.py):
1. Sin internet, la web (PWA) o el móvil guarda la reserva del cliente en
   su almacenamiento local con un UUID propio y el estado REGISTRADA.
2. Al reconectarse envía la cola a POST /api/reservations/reservas/sync/.
3. El servidor procesa cada operación por separado y responde:
   - SINCRONIZADA: la reserva se creó.
     MODIFICADO (Fase 2 - reservas con anticipo): queda "Pendiente de pago"
     con 3 horas para pagarse por Stripe (anticipo o total); recién al pagar
     se aparta la prenda. Si no paga a tiempo, vence y libera la prenda.
   - DUPLICADA:    ese UUID ya se había sincronizado; NO se crea otra
     reserva (idempotencia) y se devuelve la reserva original.
   - RECHAZADA:    no se pudo crear (sin stock en la sucursal, la fecha ya
     pasó, la sucursal ya no está disponible, etc.), con el motivo.
Cada operación queda registrada en SyncOperacion (tipo RESERVA) como
historial. Una operación rechazada no deja reserva ni movimientos de stock.
"""
import uuid as uuid_lib

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from apps.catalog.models import Sucursal
from apps.sales.models import SyncOperacion
from common.utils import log_audit

from .pagos import preparar_montos, verificar_disponibilidad
from .serializers import FittingReservationSerializer
from .services import ReservationStockError

MAX_RESERVAS_POR_LOTE = 100

class DatosInvalidos(Exception):
    """Los datos de la reserva enviada no son válidos."""

def _resultado(uuid, estado, mensaje=None, operacion=None):
    """Respuesta de una operación del lote."""
    reserva = operacion.id_reserva if operacion else None
    return {
        "uuid": str(uuid) if uuid else None,
        "estado": estado,
        "mensaje": mensaje,
        "id_reserva": reserva.id_reserva if reserva else None,
    }

def _resultado_existente(operacion):
    """Respuesta para un UUID que ya se había recibido (no se procesa otra vez)."""
    SyncOperacion.objects.filter(pk=operacion.pk).update(reintentos=F("reintentos") + 1)
    if operacion.estado == "SINCRONIZADA":
        return _resultado(
            operacion.uuid,
            "DUPLICADA",
            "Esta reserva ya se había sincronizado; no se registró de nuevo.",
            operacion,
        )
    return _resultado(operacion.uuid, operacion.estado, operacion.mensaje, operacion)

def _leer_uuid(valor):
    """UUID enviado por el dispositivo, o None si no es válido."""
    try:
        return uuid_lib.UUID(str(valor))
    except (TypeError, ValueError, AttributeError):
        return None

def _leer_fecha_operacion(valor):
    """Momento en que se hizo la reserva sin conexión (nunca en el futuro)."""
    if not valor:
        return None
    fecha = parse_datetime(str(valor))
    if fecha is None:
        return None
    if timezone.is_naive(fecha):
        fecha = timezone.make_aware(fecha)
    return min(fecha, timezone.now())

def _validar_horario(fecha_texto, hora_texto):
    """La fecha y la hora de la reserva no pueden haber pasado al sincronizar."""
    try:
        fecha = parse_date(str(fecha_texto))
        hora = parse_time(str(hora_texto))
    except ValueError:
        fecha, hora = None, None
    if fecha is None or hora is None:
        raise DatosInvalidos("Fecha u hora de la reserva inválida.")
    ahora = timezone.localtime()
    if fecha < ahora.date() or (fecha == ahora.date() and hora < ahora.time()):
        raise DatosInvalidos(
            "La fecha y hora elegidas ya pasaron cuando la reserva llegó al servidor."
        )

def _primer_error(errores):
    """Primer mensaje de error de un serializer (los errores pueden venir anidados)."""
    if isinstance(errores, dict):
        for valor in errores.values():
            return _primer_error(valor)
    if isinstance(errores, list):
        for valor in errores:
            mensaje = _primer_error(valor)
            if mensaje:
                return mensaje
        return None
    return str(errores) if errores else None

class SyncReservaService:
    """Procesa las reservas sin conexión que llegan desde los dispositivos."""

    @staticmethod
    def sincronizar(usuario, cliente, operaciones):
        """Procesa un lote de reservas; devuelve un resultado por operación, en orden."""
        return [
            SyncReservaService._procesar(usuario, cliente, operacion) for operacion in operaciones
        ]

    @staticmethod
    @transaction.atomic
    def _procesar(usuario, cliente, datos):
        """Crea una reserva sin conexión una sola vez por UUID."""
        if not isinstance(datos, dict):
            return _resultado(None, "RECHAZADA", "Formato de operación inválido.")
        uuid = _leer_uuid(datos.get("uuid"))
        if uuid is None:
            return _resultado(None, "RECHAZADA", "La operación no trae un UUID válido.")
        # 1) Idempotencia: si el UUID ya llegó antes, no se procesa otra vez.
        existente = SyncOperacion.objects.select_related("id_reserva").filter(uuid=uuid).first()
        if existente is not None:
            if existente.tipo != "RESERVA" or existente.id_usuario_id != usuario.pk:
                return _resultado(uuid, "RECHAZADA", "Ese UUID ya pertenece a otra operación.")
            return _resultado_existente(existente)
        # 2) La sucursal debe seguir activa (y su empresa también).
        id_sucursal = datos.get("id_sucursal")
        sucursal = None
        if str(id_sucursal).isdigit():
            sucursal = (
                Sucursal.objects.select_related("id_empresa")
                .filter(pk=id_sucursal, estado="ACTIVA", id_empresa__estado="ACTIVA")
                .first()
            )
        if sucursal is None:
            return _resultado(uuid, "RECHAZADA", "La sucursal elegida ya no está disponible.")
        items = datos.get("items") if isinstance(datos.get("items"), list) else []
        # 3) Se guarda la operación (el UUID es UNIQUE: un envío simultáneo
        #    del mismo UUID falla aquí y se responde como duplicado).
        try:
            with transaction.atomic():
                operacion = SyncOperacion.objects.create(
                    uuid=uuid,
                    tipo="RESERVA",
                    id_empresa_id=sucursal.id_empresa_id,
                    id_usuario=usuario,
                    datos={
                        "id_sucursal": sucursal.id_sucursal,
                        "fecha_reserva": datos.get("fecha_reserva"),
                        "hora_reserva": datos.get("hora_reserva"),
                        "items": items,
                    },
                    fecha_operacion=_leer_fecha_operacion(datos.get("fecha_operacion")),
                )
        except IntegrityError:
            return _resultado_existente(
                SyncOperacion.objects.select_related("id_reserva").get(uuid=uuid)
            )
        # 4) Se crea la reserva con las mismas reglas que una reserva en línea.
        try:
            _validar_horario(datos.get("fecha_reserva"), datos.get("hora_reserva"))
            serializer = FittingReservationSerializer(
                data={
                    "id_sucursal": sucursal.id_sucursal,
                    "fecha_reserva": datos.get("fecha_reserva"),
                    "hora_reserva": datos.get("hora_reserva"),
                    "items": [
                        {"id_variante": item.get("id_variante")}
                        for item in items
                        if isinstance(item, dict)
                    ],
                }
            )
            if not serializer.is_valid():
                raise DatosInvalidos(_primer_error(serializer.errors) or "Reserva inválida.")
            # Si alguna prenda no tiene stock se deshace la reserva completa.
            # MODIFICADO (Fase 2): no se descuenta stock; queda pendiente de
            # pago con 3 horas de plazo (el stock se aparta al pagar).
            with transaction.atomic():
                reserva = serializer.save(id_cliente=cliente)
                try:
                    verificar_disponibilidad(reserva)
                except ValueError as exc:
                    raise ReservationStockError(str(exc))
                preparar_montos(reserva)
        except (DatosInvalidos, ReservationStockError) as exc:
            operacion.estado = "RECHAZADA"
            operacion.mensaje = str(exc)[:255]
            operacion.save(update_fields=["estado", "mensaje"])
            return _resultado(uuid, "RECHAZADA", operacion.mensaje)
        operacion.estado = "SINCRONIZADA"
        operacion.id_reserva = reserva
        operacion.save(update_fields=["estado", "id_reserva"])
        log_audit(
            usuario=usuario,
            accion="RESERVA_CREADA",
            tabla_afectada="fitting_reservation",
            registro_id=reserva.id_reserva,
            descripcion=(
                f"{usuario.nombres} {usuario.apellidos} reservó {reserva.items.count()} "
                f"prenda(s) en {sucursal.nombre} sin conexión (sincronizada, pendiente "
                f"de pago) - Reserva #{reserva.id_reserva}"
            ),
        )
        return _resultado(
            uuid, "SINCRONIZADA",
            "Reserva registrada: tienes 3 horas para pagarla o vencerá.", operacion,
        )