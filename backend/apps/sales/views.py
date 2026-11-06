# backend/apps/sales/views.py
# MODIFICADO (Fase 3 - CU18): descuento por fidelidad en la cotización del
# delivery y en la venta POS (el POS web envía aplicar_fidelidad=true).
# MODIFICADO (arreglo RF02): los privilegios de grupo cuentan como personal de
# tienda en entregas (VER/GESTIONAR_ENTREGAS), cambios (GESTIONAR_CAMBIOS) y
# devoluciones (VER/GESTIONAR_DEVOLUCIONES).
from collections import Counter

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from common.permissions import IsCajero, IsCliente, IsEncargadoSucursal, IsRepartidor
from common.privilegios import tiene_alguno
from common.tenancy import alcance_de, filtrar_queryset
from common.utils import log_audit
from apps.users_auth.models import Cliente, Empresa, Usuario
from apps.catalog.models import Sucursal
from apps.users_auth.suscripciones import requiere_funcion
from .models import (
    Cart, CartItem, Delivery, Order, OrderItem, PosSale, Devolucion, SyncOperacion, CambioPrenda,
)
from .serializers import (
    CambioPrendaSerializer,
    CartSerializer,
    CartItemSerializer,
    OrderSerializer,
    PosSaleSerializer,
    DeliveryEntregaSerializer,
    DevolucionSerializer,
    SyncOperacionSerializer,
)
from .sync import MAX_OPERACIONES_POR_LOTE, SyncService
from .conflictos import ConflictoService
from .cambios import (
    CambioService, OrigenCambio, alternativas, cargar_origen, motivo_no_elegible,
)
from .services import CartService, CheckoutService, PosSaleService
from .devoluciones import (
    PORCENTAJE_RETENCION, DevolucionService, cargar_compra, leer_items, metodo_de_reembolso,
)
from .devoluciones import calcular as calcular_devolucion
from .integrations.envio import cotizar, EnvioError
from apps.fidelidad import servicio as fidelidad
from rest_framework.permissions import IsAuthenticated

def _sucursal_activa(sucursal_id):
    """Sucursal ACTIVA de una empresa ACTIVA (el cliente puede comprar en cualquiera)."""
    return Sucursal.objects.select_related("id_empresa").get(
        pk=sucursal_id, estado="ACTIVA", id_empresa__estado="ACTIVA"
    )

class CartViewSet(ReadOnlyModelViewSet):
    """Carritos del cliente. SaaS: tiene un carrito ACTIVO por cada empresa."""

    serializer_class = CartSerializer
    permission_classes = [IsCliente]

    def get_queryset(self):
        """Carritos del cliente autenticado."""
        cliente = Cliente.objects.get(id_usuario=self.request.user)
        return Cart.objects.filter(id_cliente=cliente).select_related("id_empresa")

    @action(detail=False, methods=["get"])
    def actual(self, request):
        """Carrito activo a mostrar.

        Con ?id_empresa=<id> devuelve el de esa empresa. Sin parámetro devuelve
        el último carrito activo usado (compatibilidad con web/móvil actuales).
        """
        cliente = Cliente.objects.get(id_usuario=request.user)
        id_empresa = request.query_params.get("id_empresa")
        if id_empresa:
            empresa = None
            if str(id_empresa).isdigit():
                empresa = Empresa.objects.filter(pk=id_empresa, estado="ACTIVA").first()
            if empresa is None:
                return Response({"error": "Empresa no encontrada."}, status=404)
            return Response(self.get_serializer(CartService.obtener_carrito(cliente, empresa)).data)

        activos = Cart.objects.filter(id_cliente=cliente, estado="ACTIVO").order_by(
            "-fecha_actualizacion"
        )
        # Primero el último carrito con prendas; si no hay, cualquiera activo.
        cart = activos.filter(cartitem__isnull=False).first() or activos.first()
        if cart is None:
            cart = Cart.objects.create(id_cliente=cliente, estado="ACTIVO")
        return Response(self.get_serializer(cart).data)

    @action(detail=False, methods=["get"])
    def activos(self, request):
        """NUEVO (SaaS): todos los carritos activos con prendas, uno por empresa."""
        cliente = Cliente.objects.get(id_usuario=request.user)
        carritos = (
            Cart.objects.filter(id_cliente=cliente, estado="ACTIVO", cartitem__isnull=False)
            .select_related("id_empresa")
            .distinct()
            .order_by("-fecha_actualizacion")
        )
        return Response(self.get_serializer(carritos, many=True).data)

    @action(detail=False, methods=["post"])
    def checkout(self, request):
        """Inicia el pago del carrito de la empresa dueña de la sucursal elegida."""
        cliente = Cliente.objects.get(id_usuario=request.user)
        sucursal_id = request.data.get("id_sucursal")

        if not sucursal_id:
            return Response({"error": "Debe indicar la sucursal de entrega/retiro."}, status=400)
        try:
            sucursal = _sucursal_activa(sucursal_id)
        except Sucursal.DoesNotExist:
            return Response({"error": "Sucursal no encontrada."}, status=400)

        tipo_entrega = request.data.get("tipo_entrega", "RETIRO")
        entrega = {
            "direccion": request.data.get("direccion"),
            "referencia": request.data.get("referencia"),
            "latitud": request.data.get("latitud"),
            "longitud": request.data.get("longitud"),
        }

        try:
            order, client_secret = CheckoutService.iniciar_checkout(
                cliente, sucursal, tipo_entrega, entrega
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        return Response({
            "orden": OrderSerializer(order).data,
            "client_secret": client_secret,
        }, status=201)

    @action(detail=False, methods=["post"])
    def confirmar_pago(self, request):
        """Confirma el pago de una orden pendiente del cliente."""
        cliente = Cliente.objects.get(id_usuario=request.user)
        referencia_pago = request.data.get("referencia_pago")

        if not referencia_pago:
            return Response({"error": "Falta la referencia de pago."}, status=400)

        try:
            order = CheckoutService.confirmar_pago(cliente, referencia_pago)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        return Response(OrderSerializer(order).data, status=200)

    @action(detail=False, methods=["post"], url_path="cotizar-envio")
    def cotizar_envio(self, request):
        """Cotiza el delivery del carrito de la empresa dueña de la sucursal."""
        cliente = Cliente.objects.get(id_usuario=request.user)
        sucursal_id = request.data.get("id_sucursal")
        latitud = request.data.get("latitud")
        longitud = request.data.get("longitud")

        if not sucursal_id or latitud is None or longitud is None:
            return Response({"error": "Debe indicar sucursal, latitud y longitud."}, status=400)
        try:
            sucursal = _sucursal_activa(sucursal_id)
            latitud = float(latitud)
            longitud = float(longitud)
        except Sucursal.DoesNotExist:
            return Response({"error": "Sucursal no encontrada."}, status=400)
        except (TypeError, ValueError):
            return Response({"error": "La ubicación indicada no es válida."}, status=400)
        if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
            return Response({"error": "La ubicación indicada no es válida."}, status=400)

        cart = CartService.carrito_de_sucursal(cliente, sucursal)
        items = list(cart.cartitem_set.select_related("id_variante")) if cart else []
        if not items:
            return Response(
                {"error": f"No tienes prendas de {sucursal.id_empresa.nombre} en tu carrito."},
                status=400,
            )

        cantidad_prendas = sum(item.cantidad for item in items)
        subtotal = sum(item.id_variante.precio * item.cantidad for item in items)
        try:
            cotizacion = cotizar(sucursal, latitud, longitud, cantidad_prendas)
        except EnvioError as e:
            return Response({"error": str(e)}, status=400)
        # NUEVO (CU18): descuento por fidelidad sobre las prendas (el envío no se descuenta).
        descuento, _, _ = fidelidad.calcular_descuento(
            cliente, sucursal.id_empresa, subtotal,
            tiene_reservas=any(item.id_reserva_item_id for item in items),
        )

        return Response({
            "distancia_km": cotizacion["distancia_km"],
            "costo_envio": cotizacion["costo_envio"],
            "subtotal_productos": subtotal,
            "descuento_fidelidad": descuento,
            "total": subtotal - descuento + cotizacion["costo_envio"],
            "fuente_distancia": cotizacion["fuente_distancia"],
        })

class CartItemViewSet(ModelViewSet):
    serializer_class = CartItemSerializer
    permission_classes = [IsCliente]

    def get_queryset(self):
        """Prendas de todos los carritos activos del cliente."""
        cliente = Cliente.objects.get(id_usuario=self.request.user)
        return CartItem.objects.filter(id_carrito__id_cliente=cliente, id_carrito__estado="ACTIVO")

    def perform_create(self, serializer):
        """Agrega la prenda al carrito de la empresa dueña de esa prenda."""
        cliente = Cliente.objects.get(id_usuario=self.request.user)
        variante = serializer.validated_data["id_variante"]
        empresa = variante.id_producto.id_empresa
        if empresa is None or empresa.estado != "ACTIVA":
            raise ValidationError({"error": "Esta prenda no está disponible."})

        cart = CartService.obtener_carrito(cliente, empresa)
        cantidad_nueva = serializer.validated_data.get("cantidad", 1)
        existente = CartItem.objects.filter(
            id_carrito=cart, id_variante=variante, id_reserva_item__isnull=True
        ).first()
        if existente:
            existente.cantidad += cantidad_nueva
            existente.save()
            serializer.instance = existente
        else:
            serializer.save(id_carrito=cart)
        cart.save(update_fields=["fecha_actualizacion"])

    def perform_destroy(self, instance):
        """Quita la prenda del carrito (si venía de una reserva, repone su stock).

        MODIFICADO (Fase 2 - reservas con anticipo): una reserva pagada se
        retira completa; para no llevarla hay que cancelar la reserva (CU17),
        que devuelve lo pagado menos el 10%.
        """
        if instance.id_reserva_item_id:
            reserva = instance.id_reserva_item.id_reserva
            if reserva.monto_pagado:
                raise ValidationError({
                    "error": (
                        f"Esta prenda es de la Reserva #{reserva.id_reserva}, que ya está pagada. "
                        f"Para no llevarla, cancela la reserva desde Mis reservas."
                    )
                })
            from apps.reservations.services import ReservationStockService
            ReservationStockService.liberar_item(
                instance.id_reserva_item,
                usuario=self.request.user,
                motivo=(
                    f"Reserva #{instance.id_reserva_item.id_reserva_id}: "
                    f"el cliente quitó la prenda del carrito antes de pagar"
                ),
            )
        instance.delete()

class OrderViewSet(ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsCliente]

    def get_queryset(self):
        """Pedidos del cliente en todas las empresas donde compró."""
        cliente = Cliente.objects.get(id_usuario=self.request.user)
        return (
            Order.objects.filter(id_cliente=cliente)
            .select_related("id_empresa", "id_sucursal")
            .order_by("-fecha_creacion")
        )

class PosSaleViewSet(ReadOnlyModelViewSet):
    serializer_class = PosSaleSerializer
    permission_classes = [IsCajero]

    def get_queryset(self):
        """Ventas presenciales de la empresa del usuario."""
        queryset = PosSale.objects.all().order_by("-fecha_venta")
        return filtrar_queryset(queryset, self.request)

    @action(detail=False, methods=["post"])
    def registrar(self, request):
        """Registra una venta presencial en una sucursal de la empresa del cajero."""
        sucursal_id = request.data.get("id_sucursal")
        metodo_pago = request.data.get("metodo_pago")
        items = request.data.get("items", [])
        # NUEVO (CU08): cliente opcional, indicado por su correo.
        correo_cliente = (request.data.get("correo_cliente") or "").strip()

        if not sucursal_id:
            return Response({"error": "Debe indicar la sucursal."}, status=400)
        if metodo_pago not in ("EFECTIVO", "TARJETA", "QR"):
            return Response({"error": "Método de pago inválido."}, status=400)
        cliente = None
        if correo_cliente:
            cliente = Cliente.objects.filter(id_usuario__correo__iexact=correo_cliente).first()
            if cliente is None:
                return Response(
                    {"error": f"No existe un cliente con el correo {correo_cliente}."}, status=400
                )

        # SaaS: el cajero solo puede vender en sucursales de su empresa.
        try:
            sucursal = filtrar_queryset(Sucursal.objects.all(), request).get(pk=sucursal_id)
        except Sucursal.DoesNotExist:
            return Response({"error": "Sucursal no encontrada."}, status=404)

        # MODIFICADO (CU18): el cliente se guarda al crear la venta y, desde el
        # POS web, se aplica su descuento por fidelidad si lo tiene.
        aplicar_fidelidad = str(request.data.get("aplicar_fidelidad", "")).lower() in ("true", "1")
        try:
            with transaction.atomic():
                venta = PosSaleService.registrar_venta(
                    request.user, sucursal, items, metodo_pago,
                    cliente=cliente, aplicar_fidelidad=aplicar_fidelidad,
                )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        return Response(PosSaleSerializer(venta).data, status=201)

ROLES_GESTION = ["SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL"]

class DeliveryViewSet(ReadOnlyModelViewSet):
    serializer_class = DeliveryEntregaSerializer

    def get_permissions(self):
        """Gestión para encargados; consulta y avance de entregas para repartidores."""
        if self.action in ("preparar", "asignar", "repartidores"):
            return [IsEncargadoSucursal()]
        return [IsRepartidor()]

    def _es_gestor(self):
        """True si el usuario gestiona entregas (no es solo repartidor), por su rol o por un grupo."""
        usuario = self.request.user
        return usuario.roles.filter(nombre__in=ROLES_GESTION).exists() or tiene_alguno(
            usuario, "VER_ENTREGAS", "GESTIONAR_ENTREGAS"
        )

    def get_queryset(self):
        """Entregas de la empresa del usuario (el repartidor solo ve las suyas)."""
        qs = (
            Delivery.objects
            .select_related("id_orden__id_cliente__id_usuario", "id_orden__id_sucursal", "id_repartidor")
            .filter(id_orden__estado__in=["PAGADA", "ENVIADA", "ENTREGADA"])
            .order_by("-fecha_creacion")
        )
        qs = filtrar_queryset(qs, self.request, campo="id_orden__id_empresa")
        if not self._es_gestor():
            qs = qs.filter(id_repartidor=self.request.user)
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado)
        return qs

    def _repartidores_disponibles(self):
        """Repartidores activos de la empresa del usuario."""
        usuarios = Usuario.objects.filter(estado="ACTIVO", roles__nombre="REPARTIDOR")
        return filtrar_queryset(usuarios, self.request)

    def _auditar(self, request, accion, delivery, texto):
        """Registra en bitácora un cambio de estado de la entrega."""
        log_audit(
            usuario=request.user,
            accion=accion,
            tabla_afectada="delivery",
            registro_id=delivery.id_delivery,
            descripcion=(
                f"{request.user.nombres} {request.user.apellidos} {texto} "
                f"(Delivery #{delivery.id_delivery} - Orden #{delivery.id_orden_id})"
            ),
        )

    @action(detail=False, methods=["get"])
    def repartidores(self, request):
        """Lista los repartidores que se pueden asignar (solo de la propia empresa)."""
        usuarios = self._repartidores_disponibles().order_by("nombres")
        return Response([
            {"id_usuario": u.id_usuario, "nombre": f"{u.nombres} {u.apellidos}"}
            for u in usuarios
        ])

    @action(detail=True, methods=["post"])
    def preparar(self, request, pk=None):
        """Pasa la entrega a EN_PREPARACION."""
        delivery = self.get_object()
        with transaction.atomic():
            d = Delivery.objects.select_for_update().get(pk=delivery.pk)
            if d.estado != "PENDIENTE":
                return Response({"error": "Solo se puede preparar una entrega pendiente."}, status=400)
            d.estado = "EN_PREPARACION"
            d.fecha_preparacion = timezone.now()
            d.save()
        self._auditar(request, "ENTREGA_PREPARADA", d, "empezó a preparar el pedido")
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def asignar(self, request, pk=None):
        """Asigna un repartidor de la misma empresa que el pedido."""
        delivery = self.get_object()
        id_repartidor = request.data.get("id_repartidor")
        if not id_repartidor:
            return Response({"error": "Debe indicar el repartidor."}, status=400)
        try:
            repartidor = self._repartidores_disponibles().filter(
                pk=id_repartidor, id_empresa_id=delivery.id_orden.id_empresa_id
            ).first()
        except (TypeError, ValueError):
            repartidor = None
        if not repartidor:
            return Response({"error": "El usuario indicado no es un repartidor activo."}, status=400)
        with transaction.atomic():
            d = Delivery.objects.select_for_update().get(pk=delivery.pk)
            if d.estado not in ("PENDIENTE", "EN_PREPARACION"):
                return Response(
                    {"error": "Solo se puede asignar repartidor antes de que salga el pedido."},
                    status=400,
                )
            d.id_repartidor = repartidor
            d.save()
        self._auditar(request, "ENTREGA_ASIGNADA", d, f"asignó a {repartidor} el pedido")
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="en-camino")
    def en_camino(self, request, pk=None):
        """Marca la entrega EN_CAMINO y la orden como ENVIADA."""
        delivery = self.get_object()
        with transaction.atomic():
            d = Delivery.objects.select_for_update().get(pk=delivery.pk)
            if d.estado != "EN_PREPARACION":
                return Response({"error": "El pedido debe estar en preparación."}, status=400)
            if d.id_repartidor_id is None:
                return Response({"error": "Primero debe asignarse un repartidor."}, status=400)
            d.estado = "EN_CAMINO"
            d.fecha_en_camino = timezone.now()
            d.save()
            Order.objects.filter(pk=d.id_orden_id).update(estado="ENVIADA")
        self._auditar(request, "ENTREGA_EN_CAMINO", d, "marcó en camino el pedido")
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def entregar(self, request, pk=None):
        """Marca la entrega ENTREGADO y la orden como ENTREGADA."""
        delivery = self.get_object()
        with transaction.atomic():
            d = Delivery.objects.select_for_update().get(pk=delivery.pk)
            if d.estado != "EN_CAMINO":
                return Response({"error": "El pedido debe estar en camino."}, status=400)
            d.estado = "ENTREGADO"
            d.fecha_entrega = timezone.now()
            d.save()
            Order.objects.filter(pk=d.id_orden_id).update(estado="ENTREGADA")
        self._auditar(request, "ENTREGA_COMPLETADA", d, "marcó entregado el pedido")
        return Response(self.get_serializer(self.get_object()).data)

# NUEVO (SaaS - paso 6): sincronización de operaciones hechas sin conexión.
# MODIFICADO (Fase 2 - CU08): historial con filtros, conflictos y resolución.
ROLES_GESTION_SYNC = ("SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL")


class SyncOperacionViewSet(ReadOnlyModelViewSet):
    """Operaciones sin conexión de la empresa del usuario.

    GET  /api/sales/sync/                 -> historial (paginado). Filtros:
         ?estado=SINCRONIZADA|EN_CONFLICTO|RECHAZADA
         ?pendientes=1        (solo conflictos sin resolver)
         ?tipo_conflicto=PRECIO|STOCK|PRECIO_Y_STOCK
         ?sucursal=<id>  ?desde=AAAA-MM-DD  ?hasta=AAAA-MM-DD
         El SUPER_ADMIN puede filtrar por empresa con ?empresa=<slug>.
         El cajero solo ve sus propias operaciones.
    GET  /api/sales/sync/resumen/         -> cantidades por estado y conflictos pendientes
    POST /api/sales/sync/ventas-pos/      -> sincroniza un lote de ventas POS
        Body: {"operaciones": [{
            "uuid": "<uuid generado en el dispositivo>",
            "fecha_operacion": "2026-10-27T15:30:00-04:00",
            "id_sucursal": <int>,
            "metodo_pago": "EFECTIVO" | "TARJETA" | "QR",
            "correo_cliente": "<opcional>",
            "items": [{"id_variante": <int>, "cantidad": <int>, "precio_unitario": "<cobrado>"}]
        }]}
        Respuesta: un resultado por operación con estado SINCRONIZADA,
        EN_CONFLICTO, DUPLICADA o RECHAZADA (ver apps/sales/sync.py).
    POST /api/sales/sync/<id>/resolver/   -> resuelve un conflicto
        Body: {"accion": "CONFIRMAR" | "DEVOLVER", "nota": "<opcional>"}
        Solo SUPER_ADMIN, ADMIN_EMPRESA y ENCARGADO_SUCURSAL (ver apps/sales/conflictos.py).
    Disponible en los 3 planes (modo offline).
    """

    serializer_class = SyncOperacionSerializer

    def get_permissions(self):
        """Resolver: encargado o superior; el resto, cualquier personal de caja."""
        funcion_offline = requiere_funcion("modo_offline")()
        if self.action == "resolver":
            return [IsEncargadoSucursal(), funcion_offline]
        return [IsCajero(), funcion_offline]

    def _es_gestor(self):
        """True si el usuario gestiona conflictos (no es solo cajero)."""
        return self.request.user.roles.filter(nombre__in=ROLES_GESTION_SYNC).exists()

    def _base(self):
        """Operaciones visibles para el usuario (su empresa; el cajero, solo las suyas)."""
        queryset = SyncOperacion.objects.select_related(
            "id_usuario",
            "revisada_por",
            "id_venta__id_sucursal",
            "id_venta__id_usuario",
            "id_venta__id_cliente__id_usuario",
            "id_venta__nota_devolucion__id_usuario",
        ).filter(tipo="VENTA_POS")
        queryset = filtrar_queryset(queryset, self.request)
        if not self._es_gestor():
            queryset = queryset.filter(id_usuario=self.request.user)
        return queryset

    def get_queryset(self):
        """Historial filtrado, de la operación más reciente a la más antigua."""
        queryset = self._base().prefetch_related("id_venta__items__id_variante")
        params = self.request.query_params
        estado = params.get("estado")
        if estado:
            queryset = queryset.filter(estado=estado)
        if params.get("pendientes") in ("1", "true"):
            queryset = queryset.filter(estado="EN_CONFLICTO", fecha_revision__isnull=True)
        tipo_conflicto = params.get("tipo_conflicto")
        if tipo_conflicto:
            queryset = queryset.filter(tipo_conflicto=tipo_conflicto)
        sucursal = params.get("sucursal")
        if sucursal and str(sucursal).isdigit():
            queryset = queryset.filter(
                Q(id_venta__id_sucursal_id=int(sucursal)) | Q(datos__id_sucursal=int(sucursal))
            )
        desde = parse_date(params.get("desde") or "")
        if desde:
            queryset = queryset.filter(fecha_recepcion__date__gte=desde)
        hasta = parse_date(params.get("hasta") or "")
        if hasta:
            queryset = queryset.filter(fecha_recepcion__date__lte=hasta)
        return queryset.order_by("-fecha_recepcion")

    @action(detail=False, methods=["get"])
    def resumen(self, request):
        """Cantidad de operaciones por estado y conflictos pendientes de resolver."""
        base = self._base()
        return Response({
            "SINCRONIZADA": base.filter(estado="SINCRONIZADA").count(),
            "EN_CONFLICTO": base.filter(estado="EN_CONFLICTO").count(),
            "RECHAZADA": base.filter(estado="RECHAZADA").count(),
            "pendientes": base.filter(estado="EN_CONFLICTO", fecha_revision__isnull=True).count(),
        })

    @action(detail=True, methods=["post"])
    def resolver(self, request, pk=None):
        """Confirma la venta en conflicto o devuelve el efectivo (con nota)."""
        operacion = self.get_object()
        accion = (request.data.get("accion") or "").strip().upper()
        nota = request.data.get("nota")
        try:
            ConflictoService.resolver(operacion.pk, request.user, accion, nota)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return Response(self.get_serializer(self.get_queryset().get(pk=operacion.pk)).data)

    @action(detail=False, methods=["post"], url_path="ventas-pos")
    def ventas_pos(self, request):
        """Sincroniza las ventas POS que el dispositivo guardó sin conexión."""
        operaciones = request.data.get("operaciones") if isinstance(request.data, dict) else None
        if not isinstance(operaciones, list) or not operaciones:
            return Response({"error": "Envía la lista de operaciones."}, status=400)
        if len(operaciones) > MAX_OPERACIONES_POR_LOTE:
            return Response(
                {"error": f"Máximo {MAX_OPERACIONES_POR_LOTE} operaciones por envío."},
                status=400,
            )

        sucursales = filtrar_queryset(Sucursal.objects.select_related("id_empresa"), request)
        resultados = SyncService.sincronizar_ventas_pos(request.user, sucursales, operaciones)
        resumen = Counter(resultado["estado"] for resultado in resultados)
        return Response({
            "resultados": resultados,
            "resumen": {
                "SINCRONIZADA": resumen.get("SINCRONIZADA", 0),
                "EN_CONFLICTO": resumen.get("EN_CONFLICTO", 0),
                "DUPLICADA": resumen.get("DUPLICADA", 0),
                "RECHAZADA": resumen.get("RECHAZADA", 0),
            },
        })


# NUEVO (Fase 2 - CU05 / CU06): cambio de prenda por talla o color.
ROLES_TIENDA_CAMBIOS = {"SUPER_ADMIN", "ADMIN_EMPRESA", "ENCARGADO_SUCURSAL", "CAJERO"}
# NUEVO (arreglo RF02): privilegios de grupo que cuentan como personal de tienda.
PRIVILEGIOS_TIENDA_CAMBIOS = ("GESTIONAR_CAMBIOS",)
PRIVILEGIOS_TIENDA_DEVOLUCIONES = ("VER_DEVOLUCIONES", "GESTIONAR_DEVOLUCIONES")


def _leer_mes(texto):
    """(año, mes) de un texto AAAA-MM; por defecto el mes actual."""
    hoy = timezone.localdate()
    try:
        anio, mes = (int(parte) for parte in str(texto).split("-"))
        if 1 <= mes <= 12 and 2000 <= anio <= 2100:
            return anio, mes
    except (TypeError, ValueError):
        pass
    return hoy.year, hoy.month


class CambioPrendaViewSet(ReadOnlyModelViewSet):
    """Cambios de prenda por talla o color (CU05) y consulta del mes (CU06).

    GET  /api/sales/cambios/                     -> lista. Filtros: ?estado= ?modalidad=
         ?motivo= ?sucursal=<id> ?mes=AAAA-MM ?pendientes=1 (solicitados sin aprobar).
         Personal: su empresa (SUPER_ADMIN: todas o ?empresa=<slug>).
         Repartidor: solo los asignados a él. Cliente: solo los suyos.
    GET  /api/sales/cambios/resumen-mes/?mes=AAAA-MM -> totales del mes (CU06).
    GET  /api/sales/cambios/buscar-compra/?tipo=VENTA|PEDIDO&numero=<n> (personal)
    GET  /api/sales/cambios/opciones/?id_venta_item=<id> | ?id_orden_item=<id>
    POST /api/sales/cambios/solicitar/           (cliente, pedido con delivery)
         {"id_orden_item", "motivo": "ERROR_TIENDA"|"NO_LE_QUEDA", "id_variante", "cantidad", "observacion"}
    POST /api/sales/cambios/registrar-tienda/    (personal de la tienda)
         {"id_venta_item"|"id_orden_item", "motivo", "id_variante", "cantidad",
          "condiciones_ok": true, "observacion"}
    POST /api/sales/cambios/<id>/aprobar/        (encargado) {"id_repartidor", "fecha_programada"}
    POST /api/sales/cambios/<id>/rechazar/       (encargado) {"motivo"}
    POST /api/sales/cambios/<id>/en-camino/      (repartidor asignado o encargado)
    POST /api/sales/cambios/<id>/completar/      (repartidor asignado o encargado) {"condiciones_ok": true}
    """

    serializer_class = CambioPrendaSerializer

    def get_permissions(self):
        """Permiso según la acción."""
        if self.action == "solicitar":
            return [IsCliente()]
        if self.action in ("registrar_tienda", "buscar_compra", "resumen_mes"):
            return [IsCajero()]
        if self.action in ("aprobar", "rechazar"):
            return [IsEncargadoSucursal()]
        if self.action in ("en_camino", "completar"):
            return [IsRepartidor()]
        return [IsAuthenticated()]

    def _roles(self):
        """Roles del usuario de la petición (se calculan una vez)."""
        if not hasattr(self, "_roles_cache"):
            self._roles_cache = set(self.request.user.roles.values_list("nombre", flat=True))
        return self._roles_cache

    def _es_tienda(self, roles):
        """True si es personal de tienda por su rol o por un grupo (arreglo RF02)."""
        return bool(roles & ROLES_TIENDA_CAMBIOS) or tiene_alguno(
            self.request.user, *PRIVILEGIOS_TIENDA_CAMBIOS
        )

    def _cliente(self):
        """Ficha de cliente del usuario (o None)."""
        return Cliente.objects.filter(id_usuario=self.request.user).first()

    def _base(self):
        """Cambios visibles según el rol."""
        queryset = CambioPrenda.objects.select_related(
            "id_sucursal",
            "id_cliente__id_usuario",
            "id_venta_item",
            "id_orden_item__id_orden__delivery",
            "id_variante_devuelta__id_producto",
            "id_variante_devuelta__id_talla",
            "id_variante_devuelta__id_color",
            "id_variante_entregada__id_producto",
            "id_variante_entregada__id_talla",
            "id_variante_entregada__id_color",
            "id_repartidor",
            "solicitado_por",
            "aprobado_por",
            "completado_por",
        )
        roles = self._roles()
        if self._es_tienda(roles):
            return filtrar_queryset(queryset, self.request)
        if "REPARTIDOR" in roles:
            return filtrar_queryset(queryset, self.request).filter(id_repartidor=self.request.user)
        if "CLIENTE" in roles:
            cliente = self._cliente()
            return queryset.filter(id_cliente=cliente) if cliente else queryset.none()
        return queryset.none()

    def get_queryset(self):
        """Lista filtrada, del cambio más reciente al más antiguo."""
        queryset = self._base()
        params = self.request.query_params
        for campo in ("estado", "modalidad", "motivo"):
            valor = params.get(campo)
            if valor:
                queryset = queryset.filter(**{campo: valor})
        sucursal = params.get("sucursal")
        if sucursal and str(sucursal).isdigit():
            queryset = queryset.filter(id_sucursal_id=int(sucursal))
        if params.get("mes"):
            anio, mes = _leer_mes(params.get("mes"))
            queryset = queryset.filter(fecha_solicitud__year=anio, fecha_solicitud__month=mes)
        if params.get("pendientes") in ("1", "true"):
            queryset = queryset.filter(estado="SOLICITADO")
        return queryset.order_by("-fecha_solicitud")

    def _responder(self, cambio, status=200):
        """Devuelve el cambio actualizado."""
        cambio = self._base().get(pk=cambio.pk)
        return Response(self.get_serializer(cambio).data, status=status)

    def _empresa_del_personal(self):
        """Empresa del personal (None para el SUPER_ADMIN)."""
        alcance = alcance_de(self.request)
        return None if alcance.super_admin else self.request.user.id_empresa_id

    @action(detail=False, methods=["get"], url_path="resumen-mes")
    def resumen_mes(self, request):
        """CU06: cambios del mes por estado, motivo, modalidad, sucursal y prenda."""
        anio, mes = _leer_mes(request.query_params.get("mes"))
        cambios = self._base().filter(fecha_solicitud__year=anio, fecha_solicitud__month=mes)
        sucursal = request.query_params.get("sucursal")
        if sucursal and str(sucursal).isdigit():
            cambios = cambios.filter(id_sucursal_id=int(sucursal))

        def contar(campo):
            """Cantidad de cambios agrupados por un campo."""
            return {
                fila[campo]: fila["total"]
                for fila in cambios.values(campo).annotate(total=Count("id_cambio"))
            }

        prendas = (
            cambios.exclude(estado="RECHAZADO")
            .values(
                "id_variante_devuelta__id_producto__nombre",
                "id_variante_devuelta__id_talla__nombre",
                "id_variante_devuelta__id_color__nombre",
            )
            .annotate(total=Count("id_cambio"))
            .order_by("-total")[:5]
        )
        por_sucursal = (
            cambios.values("id_sucursal__nombre").annotate(total=Count("id_cambio")).order_by("-total")
        )
        estados = contar("estado")
        return Response({
            "mes": f"{anio:04d}-{mes:02d}",
            "total": cambios.count(),
            "completados": estados.get("COMPLETADO", 0),
            "en_proceso": sum(estados.get(e, 0) for e in ("SOLICITADO", "PROGRAMADO", "EN_CAMINO")),
            "rechazados": estados.get("RECHAZADO", 0),
            "por_estado": estados,
            "por_motivo": contar("motivo"),
            "por_modalidad": contar("modalidad"),
            "por_sucursal": [
                {"sucursal": fila["id_sucursal__nombre"], "total": fila["total"]} for fila in por_sucursal
            ],
            "prendas_mas_cambiadas": [
                {
                    "prenda": (
                        f"{fila['id_variante_devuelta__id_producto__nombre']} - "
                        f"{fila['id_variante_devuelta__id_talla__nombre']} - "
                        f"{fila['id_variante_devuelta__id_color__nombre']}"
                    ),
                    "total": fila["total"],
                }
                for fila in prendas
            ],
        })

    @action(detail=False, methods=["get"], url_path="buscar-compra")
    def buscar_compra(self, request):
        """Prendas de una venta POS o de un pedido de la empresa, con su elegibilidad."""
        tipo = (request.query_params.get("tipo") or "").upper()
        numero = request.query_params.get("numero")
        if tipo not in ("VENTA", "PEDIDO") or not str(numero or "").isdigit():
            return Response({"error": "Indica el tipo (venta o pedido) y su número."}, status=400)
        if tipo == "VENTA":
            compra = filtrar_queryset(
                PosSale.objects.select_related("id_sucursal", "id_cliente__id_usuario"), request
            ).filter(pk=int(numero)).first()
            if compra is None:
                return Response({"error": f"No existe la venta #{numero} en tu empresa."}, status=404)
            items = compra.items.select_related(
                "id_venta__id_sucursal", "id_variante__id_producto",
                "id_variante__id_talla", "id_variante__id_color",
            )
            origenes = [OrigenCambio(venta_item=item) for item in items]
            fecha, cliente, entrega = compra.fecha_venta, compra.id_cliente, "Venta en tienda"
        else:
            compra = filtrar_queryset(
                Order.objects.select_related("id_sucursal", "id_cliente__id_usuario"), request
            ).filter(pk=int(numero)).first()
            if compra is None:
                return Response({"error": f"No existe el pedido #{numero} en tu empresa."}, status=404)
            items = OrderItem.objects.filter(id_orden=compra).select_related(
                "id_orden__id_sucursal", "id_variante__id_producto",
                "id_variante__id_talla", "id_variante__id_color",
            )
            origenes = [OrigenCambio(orden_item=item) for item in items]
            fecha, cliente = compra.fecha_creacion, compra.id_cliente
            entrega = compra.get_tipo_entrega_display()
        return Response({
            "tipo": tipo,
            "numero": int(numero),
            "etiqueta": f"{'Venta' if tipo == 'VENTA' else 'Pedido'} #{numero}",
            "sucursal": compra.id_sucursal.nombre if compra.id_sucursal_id else None,
            "fecha": fecha,
            "entrega": entrega,
            "cliente": (
                {"nombre": f"{cliente.id_usuario.nombres} {cliente.id_usuario.apellidos}",
                 "correo": cliente.id_usuario.correo}
                if cliente else None
            ),
            "items": [
                {
                    "id_venta_item": origen.venta_item.pk if origen.venta_item else None,
                    "id_orden_item": origen.orden_item.pk if origen.orden_item else None,
                    "prenda": str(origen.variante),
                    "cantidad": origen.cantidad,
                    "precio": str(origen.variante.precio),
                    "vence": origen.vence,
                    "motivo_no_elegible": motivo_no_elegible(origen, "TIENDA"),
                }
                for origen in origenes
            ],
        })

    @action(detail=False, methods=["get"])
    def opciones(self, request):
        """Tallas/colores disponibles para cambiar una prenda y si se puede cambiar."""
        try:
            origen = cargar_origen(
                id_venta_item=request.query_params.get("id_venta_item"),
                id_orden_item=request.query_params.get("id_orden_item"),
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=404)
        roles = self._roles()
        if self._es_tienda(roles):
            empresa_id = self._empresa_del_personal()
            if empresa_id is not None and origen.empresa_id != empresa_id:
                return Response({"error": "La prenda no existe."}, status=404)
            modalidad = "TIENDA"
        elif "CLIENTE" in roles:
            cliente = self._cliente()
            if cliente is None or origen.cliente is None or origen.cliente.pk != cliente.pk:
                return Response({"error": "La prenda no existe."}, status=404)
            modalidad = "DELIVERY"
        else:
            return Response({"error": "No tienes permiso."}, status=403)
        return Response({
            "prenda": str(origen.variante),
            "id_variante": origen.variante.id_variante,
            "talla": origen.variante.id_talla.nombre,
            "color": origen.variante.id_color.nombre,
            "precio": str(origen.variante.precio),
            "cantidad": origen.cantidad,
            "origen": origen.etiqueta,
            "sucursal": origen.sucursal.nombre if origen.sucursal else None,
            "vence": origen.vence,
            "modalidad": modalidad,
            "motivo_no_elegible": motivo_no_elegible(origen, modalidad),
            "alternativas": alternativas(origen),
        })

    @action(detail=False, methods=["post"])
    def solicitar(self, request):
        """El cliente solicita el cambio de una prenda de su pedido con delivery."""
        cliente = self._cliente()
        if cliente is None:
            return Response({"error": "Tu usuario no tiene ficha de cliente."}, status=400)
        datos = request.data
        try:
            cambio = CambioService.solicitar(
                request.user,
                cliente,
                datos.get("id_orden_item"),
                datos.get("motivo"),
                datos.get("id_variante"),
                datos.get("cantidad", 1),
                datos.get("observacion"),
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(cambio, status=201)

    @action(detail=False, methods=["post"], url_path="registrar-tienda")
    def registrar_tienda(self, request):
        """El personal registra y completa un cambio en la tienda."""
        datos = request.data
        try:
            cambio = CambioService.registrar_en_tienda(
                request.user,
                self._empresa_del_personal(),
                datos.get("motivo"),
                datos.get("id_variante"),
                datos.get("cantidad", 1),
                id_venta_item=datos.get("id_venta_item"),
                id_orden_item=datos.get("id_orden_item"),
                condiciones_ok=datos.get("condiciones_ok") is True,
                observacion=datos.get("observacion"),
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(cambio, status=201)

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        """El encargado asigna repartidor y fecha de visita (dentro de 48 h)."""
        cambio = self.get_object()
        texto_fecha = request.data.get("fecha_programada")
        fecha = parse_datetime(str(texto_fecha)) if texto_fecha else None
        try:
            cambio = CambioService.aprobar(cambio.pk, request.user, request.data.get("id_repartidor"), fecha)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(cambio)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        """El encargado rechaza el cambio indicando el motivo."""
        cambio = self.get_object()
        try:
            cambio = CambioService.rechazar(cambio.pk, request.user, request.data.get("motivo"))
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(cambio)

    @action(detail=True, methods=["post"], url_path="en-camino")
    def en_camino(self, request, pk=None):
        """El repartidor sale a hacer el cambio."""
        cambio = self.get_object()
        try:
            cambio = CambioService.en_camino(cambio.pk, request.user)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(cambio)

    @action(detail=True, methods=["post"])
    def completar(self, request, pk=None):
        """El repartidor recogió la prenda devuelta y entregó la correcta."""
        cambio = self.get_object()
        try:
            cambio = CambioService.completar(
                cambio.pk, request.user, request.data.get("condiciones_ok") is True
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(cambio)


# NUEVO (devoluciones)
# MODIFICADO (Fase 2 - CU12): devolución con reembolso, recojo a domicilio y
# nota de devolución. Reemplaza la devolución automática anterior.
class DevolucionViewSet(ReadOnlyModelViewSet):
    """Devoluciones de prendas con reembolso (CU12).

    GET  /api/sales/devoluciones/                 -> lista. Filtros: ?estado= ?modalidad=
         ?sucursal=<id> ?mes=AAAA-MM ?pendientes=1 (solicitadas sin aprobar).
         Personal: su empresa (SUPER_ADMIN: todas o ?empresa=<slug>).
         Repartidor: solo los recojos asignados. Cliente: solo las suyas.
    GET  /api/sales/devoluciones/buscar-compra/?tipo=VENTA|PEDIDO&numero=<n>
         Personal: compras de su empresa. Cliente: solo sus pedidos.
    POST /api/sales/devoluciones/calcular/        -> montos sin guardar
         {"tipo", "numero", "items": [{"id_item", "cantidad", "motivo"}]}
    POST /api/sales/devoluciones/solicitar/       (cliente, pedido con delivery)
         {"id_orden", "items": [{"id_item", "cantidad", "motivo"}], "observacion"}
    POST /api/sales/devoluciones/registrar-tienda/ (personal de la tienda)
         {"tipo", "numero", "items": [...], "condiciones_ok": true, "observacion"}
    POST /api/sales/devoluciones/<id>/aprobar/    (encargado) {"id_repartidor", "fecha_programada"}
    POST /api/sales/devoluciones/<id>/rechazar/   (encargado) {"motivo"}
    POST /api/sales/devoluciones/<id>/en-camino/  (repartidor asignado o encargado)
    POST /api/sales/devoluciones/<id>/completar/  (repartidor asignado o encargado) {"condiciones_ok": true}
    Motivos: PRODUCTO_DANADO, ERROR_TIENDA (100% + envío), NO_LA_QUIERO (90%).
    """

    serializer_class = DevolucionSerializer

    def get_permissions(self):
        """Permiso según la acción."""
        if self.action == "solicitar":
            return [IsCliente()]
        if self.action == "registrar_tienda":
            return [IsCajero()]
        if self.action in ("aprobar", "rechazar"):
            return [IsEncargadoSucursal()]
        if self.action in ("en_camino", "completar"):
            return [IsRepartidor()]
        return [IsAuthenticated()]

    def _roles(self):
        """Roles del usuario de la petición (se calculan una vez)."""
        if not hasattr(self, "_roles_cache"):
            self._roles_cache = set(self.request.user.roles.values_list("nombre", flat=True))
        return self._roles_cache

    def _es_tienda(self, roles):
        """True si es personal de tienda por su rol o por un grupo (arreglo RF02)."""
        return bool(roles & ROLES_TIENDA_CAMBIOS) or tiene_alguno(
            self.request.user, *PRIVILEGIOS_TIENDA_DEVOLUCIONES
        )

    def _cliente(self):
        """Ficha de cliente del usuario (o None)."""
        return Cliente.objects.filter(id_usuario=self.request.user).first()

    def _empresa_del_personal(self):
        """Empresa del personal (None para el SUPER_ADMIN)."""
        alcance = alcance_de(self.request)
        return None if alcance.super_admin else self.request.user.id_empresa_id

    def _base(self):
        """Devoluciones visibles según el rol."""
        queryset = Devolucion.objects.select_related(
            "id_sucursal",
            "id_orden__id_sucursal",
            "id_orden__delivery",
            "id_cliente__id_usuario",
            "id_repartidor",
            "solicitado_por",
            "aprobado_por",
            "completado_por",
        ).prefetch_related(
            "items__id_orden_item__id_variante__id_producto",
            "items__id_orden_item__id_variante__id_talla",
            "items__id_orden_item__id_variante__id_color",
            "items__id_venta_item__id_variante__id_producto",
            "items__id_venta_item__id_variante__id_talla",
            "items__id_venta_item__id_variante__id_color",
        )
        roles = self._roles()
        if self._es_tienda(roles):
            return filtrar_queryset(queryset, self.request)
        if "REPARTIDOR" in roles:
            return filtrar_queryset(queryset, self.request).filter(id_repartidor=self.request.user)
        if "CLIENTE" in roles:
            cliente = self._cliente()
            return queryset.filter(id_cliente=cliente) if cliente else queryset.none()
        return queryset.none()

    def get_queryset(self):
        """Lista filtrada, de la devolución más reciente a la más antigua."""
        queryset = self._base()
        params = self.request.query_params
        for campo in ("estado", "modalidad"):
            valor = params.get(campo)
            if valor:
                queryset = queryset.filter(**{campo: valor})
        sucursal = params.get("sucursal")
        if sucursal and str(sucursal).isdigit():
            queryset = queryset.filter(
                Q(id_sucursal_id=int(sucursal))
                | Q(id_sucursal__isnull=True, id_orden__id_sucursal_id=int(sucursal))
            )
        if params.get("mes"):
            anio, mes = _leer_mes(params.get("mes"))
            queryset = queryset.filter(fecha_creacion__year=anio, fecha_creacion__month=mes)
        if params.get("pendientes") in ("1", "true"):
            queryset = queryset.filter(estado="SOLICITADA")
        return queryset.order_by("-fecha_creacion")

    def _responder(self, devolucion, status=200):
        """Devuelve la devolución actualizada."""
        devolucion = self._base().get(pk=devolucion.pk)
        return Response(self.get_serializer(devolucion).data, status=status)

    def _cargar_compra(self, tipo, numero):
        """Compra visible para el usuario: el personal, de su empresa; el cliente, sus pedidos."""
        roles = self._roles()
        if self._es_tienda(roles):
            return cargar_compra(tipo, numero, empresa_id=self._empresa_del_personal()), "TIENDA"
        if "CLIENTE" in roles:
            cliente = self._cliente()
            if cliente is None:
                raise ValueError("Tu usuario no tiene ficha de cliente.")
            return cargar_compra(tipo, numero, cliente=cliente), "DELIVERY"
        raise PermissionError("No tienes permiso.")

    @action(detail=False, methods=["get"], url_path="buscar-compra")
    def buscar_compra(self, request):
        """Prendas de la compra con lo que se puede devolver de cada una."""
        try:
            compra, modalidad = self._cargar_compra(
                request.query_params.get("tipo"), request.query_params.get("numero")
            )
        except PermissionError as e:
            return Response({"error": str(e)}, status=403)
        except ValueError as e:
            return Response({"error": str(e)}, status=404)
        cliente = compra.cliente
        problema_compra = compra.problema_compra(modalidad)
        return Response({
            "tipo": compra.tipo,
            "numero": compra.numero,
            "etiqueta": compra.etiqueta,
            "sucursal": compra.sucursal.nombre if compra.sucursal else None,
            "fecha": compra.fecha_base,
            "vence": compra.vence,
            "entrega": (
                "Venta en tienda" if compra.tipo == "VENTA" else compra.orden.get_tipo_entrega_display()
            ),
            "costo_envio": compra.orden.costo_envio if compra.tipo == "PEDIDO" else None,
            "envio_ya_devuelto": compra.envio_ya_devuelto(),
            "metodo_reembolso": metodo_de_reembolso(compra),
            "modalidad": modalidad,
            "motivo_no_elegible": problema_compra,
            "cliente": (
                {"nombre": f"{cliente.id_usuario.nombres} {cliente.id_usuario.apellidos}",
                 "correo": cliente.id_usuario.correo}
                if cliente else None
            ),
            "porcentaje_retencion": PORCENTAJE_RETENCION,
            "items": [
                {
                    "id_item": linea.pk,
                    "prenda": str(linea.id_variante),
                    "cantidad": linea.cantidad,
                    "disponible": compra.disponible(linea),
                    "precio_unitario": linea.precio_unitario,
                    "motivo_no_elegible": problema_compra or compra.problema_linea(linea),
                }
                for linea in compra.lineas
            ],
        })

    @action(detail=False, methods=["post"])
    def calcular(self, request):
        """Montos de la devolución antes de confirmarla (no guarda nada)."""
        datos = request.data
        try:
            compra, modalidad = self._cargar_compra(datos.get("tipo"), datos.get("numero"))
            problema = compra.problema_compra(modalidad)
            if problema:
                raise ValueError(problema)
            montos = calcular_devolucion(compra, leer_items(compra, datos.get("items")))
        except PermissionError as e:
            return Response({"error": str(e)}, status=403)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        for fila in montos["items"]:
            fila.pop("linea")
        return Response(montos)

    @action(detail=False, methods=["post"])
    def solicitar(self, request):
        """El cliente solicita la devolución de prendas de su pedido con delivery."""
        cliente = self._cliente()
        if cliente is None:
            return Response({"error": "Tu usuario no tiene ficha de cliente."}, status=400)
        datos = request.data
        try:
            devolucion = DevolucionService.solicitar(
                request.user, cliente, datos.get("id_orden"), datos.get("items"),
                datos.get("observacion"),
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(devolucion, status=201)

    @action(detail=False, methods=["post"], url_path="registrar-tienda")
    def registrar_tienda(self, request):
        """El personal registra y completa una devolución en la tienda."""
        datos = request.data
        try:
            devolucion = DevolucionService.registrar_en_tienda(
                request.user,
                self._empresa_del_personal(),
                datos.get("tipo"),
                datos.get("numero"),
                datos.get("items"),
                condiciones_ok=datos.get("condiciones_ok") is True,
                observacion=datos.get("observacion"),
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(devolucion, status=201)

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        """El encargado asigna repartidor y fecha de recojo (dentro de 48 h)."""
        devolucion = self.get_object()
        texto_fecha = request.data.get("fecha_programada")
        fecha = parse_datetime(str(texto_fecha)) if texto_fecha else None
        try:
            devolucion = DevolucionService.aprobar(
                devolucion.pk, request.user, request.data.get("id_repartidor"), fecha
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(devolucion)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        """El encargado rechaza la devolución indicando el motivo."""
        devolucion = self.get_object()
        try:
            devolucion = DevolucionService.rechazar(devolucion.pk, request.user, request.data.get("motivo"))
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(devolucion)

    @action(detail=True, methods=["post"], url_path="en-camino")
    def en_camino(self, request, pk=None):
        """El repartidor sale a recoger la prenda."""
        devolucion = self.get_object()
        try:
            devolucion = DevolucionService.en_camino(devolucion.pk, request.user)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(devolucion)

    @action(detail=True, methods=["post"])
    def completar(self, request, pk=None):
        """El repartidor recogió y revisó la prenda: se repone el stock y se reembolsa."""
        devolucion = self.get_object()
        try:
            devolucion = DevolucionService.completar(
                devolucion.pk, request.user, request.data.get("condiciones_ok") is True
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return self._responder(devolucion)