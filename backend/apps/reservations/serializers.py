# backend/apps/reservations/serializers.py
# MODIFICADO (Fase 2 - reservas con anticipo): pago (anticipo o total),
# saldo, vencimiento y nota de devolución (NR-000001) de la reserva.
# Paso 4: opciones de pago (anticipo o total) y lo que se devolvería al cancelar.
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from rest_framework import serializers
from apps.catalog.models import Sucursal, ProductoVariante
from .models import PORCENTAJE_RETENCION, FittingReservation, FittingReservationItem


def _centavos(valor):
    """Redondea a centavos (igual que apps/reservations/pagos.py)."""
    return Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class FittingReservationItemSerializer(serializers.ModelSerializer):
    variante = serializers.StringRelatedField(source="id_variante", read_only=True)
    id_variante = serializers.PrimaryKeyRelatedField(
        queryset=ProductoVariante.objects.all(), write_only=True
    )

    class Meta:
        model = FittingReservationItem
        # NUEVO (vínculo reserva-venta): "estado" (PENDIENTE/COMPRADO/
        # DEVUELTO) expuesto de solo lectura, para que web/mobile puedan
        # mostrar qué pasó con cada prenda de la reserva.
        # NUEVO (Fase 2 - reservas con anticipo): precio congelado al reservar.
        fields = ["id_item", "variante", "id_variante", "estado", "precio_unitario"]
        read_only_fields = ["estado", "precio_unitario"]


class FittingReservationSerializer(serializers.ModelSerializer):
    # BUG ENCONTRADO Y CORREGIDO (CU11): "cliente"/"sucursal" eran
    # StringRelatedField de solo lectura sin ningún campo escribible
    # equivalente - no había forma de crear una reserva desde afuera.
    cliente = serializers.StringRelatedField(source="id_cliente", read_only=True)
    sucursal = serializers.StringRelatedField(source="id_sucursal", read_only=True)
    # NUEVO (SaaS): tienda (empresa) de la reserva.
    id_empresa = serializers.IntegerField(source="id_empresa_id", read_only=True)
    empresa_nombre = serializers.CharField(source="id_empresa.nombre", read_only=True)
    # SaaS: solo sucursales activas de empresas activas (el cliente es
    # global y puede reservar en cualquier empresa).
    id_sucursal = serializers.PrimaryKeyRelatedField(
        queryset=Sucursal.objects.filter(estado="ACTIVA", id_empresa__estado="ACTIVA"),
        write_only=True,
    )
    # "items" no lleva source: coincide a propósito con el related_name="items"
    # puesto en FittingReservationItem.id_reserva.
    items = FittingReservationItemSerializer(many=True)
    # NUEVO (Fase 2 - reservas con anticipo): pago, saldo, vencimiento y nota.
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    tipo_pago_display = serializers.CharField(source="get_tipo_pago_display", read_only=True)
    saldo = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    numero_nota = serializers.CharField(read_only=True)
    porcentaje_retencion = serializers.SerializerMethodField()
    puede_cancelar = serializers.SerializerMethodField()
    puede_pagar = serializers.SerializerMethodField()
    opciones_pago = serializers.SerializerMethodField()
    cancelacion = serializers.SerializerMethodField()

    class Meta:
        model = FittingReservation
        fields = [
            "id_reserva",
            "id_empresa",
            "empresa_nombre",
            "cliente",
            "sucursal",
            "id_sucursal",
            "fecha_reserva",
            "hora_reserva",
            "estado",
            "estado_display",
            "fecha_creacion",
            "items",
            "tipo_pago",
            "tipo_pago_display",
            "porcentaje_anticipo",
            "monto_total",
            "monto_a_pagar",
            "monto_pagado",
            "saldo",
            "fecha_pago",
            "fecha_limite_pago",
            "fecha_vencimiento",
            "numero_nota",
            "porcentaje_retencion",
            "monto_retenido",
            "monto_devuelto",
            "referencia_reembolso",
            "motivo_cierre",
            "fecha_cierre",
            "puede_cancelar",
            "puede_pagar",
            "opciones_pago",
            "cancelacion",
        ]
        read_only_fields = [
            "estado", "tipo_pago", "porcentaje_anticipo", "monto_total", "monto_a_pagar",
            "monto_pagado", "fecha_pago", "fecha_limite_pago", "fecha_vencimiento",
            "monto_retenido", "monto_devuelto", "referencia_reembolso", "motivo_cierre",
            "fecha_cierre",
        ]

    def validate_items(self, value):
        """La reserva debe tener al menos una prenda."""
        if not value:
            raise serializers.ValidationError("La reserva debe incluir al menos una prenda.")
        return value

    def get_porcentaje_retencion(self, obj):
        """Porcentaje del precio total que se retiene si vence o se cancela."""
        return PORCENTAJE_RETENCION

    def get_puede_cancelar(self, obj):
        """True si la reserva sigue abierta (el cliente puede cancelarla)."""
        return obj.estado in ("PENDIENTE", "PENDIENTE_PAGO", "CONFIRMADA")

    def get_puede_pagar(self, obj):
        """True si la reserva espera el pago y todavía está dentro del plazo."""
        return bool(
            obj.estado == "PENDIENTE_PAGO"
            and (obj.fecha_limite_pago is None or timezone.now() <= obj.fecha_limite_pago)
        )

    def get_opciones_pago(self, obj):
        """Montos del anticipo (porcentaje de la empresa) y del total, si se puede pagar."""
        if not self.get_puede_pagar(obj) or obj.monto_total is None:
            return []
        porcentaje = obj.id_empresa.porcentaje_anticipo if obj.id_empresa_id else Decimal("50")
        return [
            {
                "tipo": "ANTICIPO",
                "porcentaje": porcentaje,
                "monto": _centavos(obj.monto_total * porcentaje / 100),
            },
            {"tipo": "TOTAL", "porcentaje": Decimal("100"), "monto": _centavos(obj.monto_total)},
        ]

    def get_cancelacion(self, obj):
        """Lo que se devolvería si el cliente cancela ahora (CU17): pagado menos el 10%."""
        if not self.get_puede_cancelar(obj):
            return None
        pagado = obj.monto_pagado or Decimal("0")
        retenido = Decimal("0")
        if pagado > 0:
            retenido = min(_centavos((obj.monto_total or 0) * PORCENTAJE_RETENCION / 100), pagado)
        return {"pagado": pagado, "retenido": retenido, "devuelto": pagado - retenido}

    def validate(self, attrs):
        """SaaS: todas las prendas deben ser de la misma empresa que la sucursal."""
        sucursal = attrs.get("id_sucursal")
        for item in attrs.get("items", []):
            variante = item["id_variante"]
            if variante.id_producto.id_empresa_id != sucursal.id_empresa_id:
                raise serializers.ValidationError(
                    {"items": f"'{variante}' no se vende en {sucursal.nombre}."}
                )
        return attrs

    def create(self, validated_data):
        """Crea la reserva (con la empresa de la sucursal) y sus prendas."""
        # "id_cliente" llega inyectado desde perform_create() en la vista
        # (serializer.save(id_cliente=...)), no lo manda el cliente.
        items_data = validated_data.pop("items")
        validated_data["id_empresa_id"] = validated_data["id_sucursal"].id_empresa_id
        reserva = FittingReservation.objects.create(**validated_data)
        for item in items_data:
            FittingReservationItem.objects.create(id_reserva=reserva, **item)
        return reserva