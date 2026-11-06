# backend/apps/users_auth/views.py
# MODIFICADO (Fase 2 - reservas con anticipo): al iniciar sesión se procesan
# los vencimientos de reservas (ver _vencer_reservas_al_ingresar).
# MODIFICADO (arreglo RF02 - usuarios, roles y permisos): el login devuelve los
# permisos del rol del usuario; en "Permisos por rol" solo se guardan los de
# ENCARGADO_SUCURSAL, CAJERO y REPARTIDOR (SUPER_ADMIN y ADMIN_EMPRESA hacen
# todo); y quien gestiona usuarios por un permiso de su rol (sin ser
# administrador) no puede asignar ni tocar administradores.
import logging

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from drf_spectacular.utils import extend_schema

from common.permissions import IsAdminEmpresa, IsSuperAdmin
from common.privilegios import ASIGNABLES, ROLES_CONFIGURABLES
from common.tenancy import alcance_de, empresa_para_crear, filtrar_queryset
from .suscripciones import SuscripcionService
from .models import Usuario, Cliente, Rol, Permiso, RolPermiso, Bitacora
from .serializers import (
    UsuarioSerializer,
    UsuarioCreateSerializer,
    UsuarioUpdateSerializer,
    RegistroClienteSerializer,
    LoginSerializer,
    RolSerializer,
    PermisoSerializer,
    BitacoraSerializer,
)
from .services import AuthService
from .serializers_grupos import datos_sesion
from common.utils import log_audit, get_client_ip

logger = logging.getLogger(__name__)


def _vencer_reservas_al_ingresar(usuario):
    """NUEVO (Fase 2 - reservas con anticipo): al iniciar sesión se vencen las
    reservas cuyo plazo pasó (Render gratis no tiene tareas programadas).

    El cliente procesa las suyas; el personal, las de su empresa; el
    SUPER_ADMIN, todas. Un error aquí nunca impide iniciar sesión.
    """
    from apps.reservations.pagos import ReservaPagoService

    try:
        roles = set(usuario.roles.values_list("nombre", flat=True))
        if "CLIENTE" in roles:
            cliente = Cliente.objects.filter(id_usuario=usuario).first()
            if cliente is not None:
                ReservaPagoService.procesar_vencimientos(cliente=cliente)
        elif "SUPER_ADMIN" in roles:
            ReservaPagoService.procesar_vencimientos()
        elif usuario.id_empresa_id:
            ReservaPagoService.procesar_vencimientos(empresa_id=usuario.id_empresa_id)
    except Exception:
        logger.exception("No se pudieron procesar los vencimientos de reservas al ingresar.")

class RegistroClienteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=RegistroClienteSerializer,
        responses={
            201: dict
        }
    )
    def post(self, request):
        """Registro público de un cliente (global, sin empresa)."""
        serializer = RegistroClienteSerializer(data=request.data)

        if serializer.is_valid():
            usuario = serializer.save()

            log_audit(
                None,
                "REGISTRO_CLIENTE",
                "clientes",
                usuario.id_usuario,
                f"Registro público de nuevo cliente: {usuario.correo}",
                datos_nuevo={
                    "nombres": usuario.nombres,
                    "apellidos": usuario.apellidos,
                    "correo": usuario.correo,
                    "telefono": usuario.telefono,
                },
                direccion_ip=get_client_ip(request),
            )

            return Response(
                {
                    "message": "Cliente registrado exitosamente.",
                    "usuario_id": usuario.id_usuario
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: UsuarioSerializer
        }
    )
    def post(self, request):
        """Valida credenciales y devuelve los tokens JWT con los datos del usuario."""
        serializer = LoginSerializer(data=request.data)

        if serializer.is_valid():

            usuario = AuthService.autenticar_usuario(
                serializer.validated_data["correo"],
                serializer.validated_data["password"],
            )

            if usuario:

                tokens = AuthService.generar_tokens(usuario)
                _vencer_reservas_al_ingresar(usuario)

                log_audit(
                    usuario,
                    "LOGIN",
                    "usuarios",
                    usuario.id_usuario,
                    "Inicio de sesión",
                    direccion_ip=get_client_ip(request),
                )

                return Response(
                    {
                        "tokens": tokens,
                        "usuario": datos_sesion(usuario),
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    "error": "Credenciales inválidas."
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

# NUEVO (SaaS - paso 4): roles que el personal de una empresa puede asignar.
# SUPER_ADMIN solo lo asigna otro SUPER_ADMIN y CLIENTE no se asigna desde
# administración (los clientes se registran solos y son globales).
ROLES_DE_EMPRESA = {"ADMIN_EMPRESA", "ENCARGADO_SUCURSAL", "CAJERO", "REPARTIDOR"}

# NUEVO (arreglo RF02): roles que puede asignar quien gestiona usuarios por un
# permiso de su rol (GESTIONAR_USUARIOS) sin ser SUPER_ADMIN ni ADMIN_EMPRESA.
ROLES_ASIGNABLES_POR_GRUPO = {"ENCARGADO_SUCURSAL", "CAJERO", "REPARTIDOR"}
ROLES_ADMINISTRADORES = {"SUPER_ADMIN", "ADMIN_EMPRESA"}

class UsuarioViewSet(ModelViewSet):
    """Gestión de usuarios acotada a la empresa del administrador.

    - ADMIN_EMPRESA: solo ve, crea, edita y elimina usuarios de su empresa;
      no puede asignar SUPER_ADMIN ni CLIENTE ni mover usuarios a otra empresa.
    - SUPER_ADMIN: ve todo (opcional ?empresa=<slug>) y al crear indica la
      empresa con "id_empresa" (o ninguna, para otro SUPER_ADMIN).
    - ?rol=CLIENTE: clientes que compraron o reservaron en la empresa (solo lectura).
    """

    permission_classes = [IsAdminEmpresa]

    def get_queryset(self):
        """Usuarios de la empresa del administrador (o clientes con actividad en ella)."""
        queryset = Usuario.objects.select_related("id_empresa", "id_sucursal").prefetch_related(
            "roles"
        ).order_by("id_usuario")
        alcance = alcance_de(self.request)
        if not alcance.super_admin and alcance.empresa_id is None:
            return queryset.none()

        # Filtro opcional por rol, ej: /usuarios/?rol=CLIENTE
        # Usado por la pantalla de "Clientes" para listar solo usuarios
        # con rol CLIENTE (de solo lectura ahí, no se crean desde acá).
        rol = self.request.query_params.get("rol")
        if rol == "CLIENTE" and self.action == "list":
            clientes = queryset.filter(roles__nombre="CLIENTE")
            if alcance.super_admin and not alcance.slug_filtro:
                return clientes
            if alcance.super_admin:
                campo, valor = "id_empresa__slug", alcance.slug_filtro
            else:
                campo, valor = "id_empresa", alcance.empresa_id
            return clientes.filter(
                Q(**{f"cliente__order__{campo}": valor})
                | Q(**{f"cliente__fittingreservation__{campo}": valor})
            ).distinct()

        queryset = filtrar_queryset(queryset, self.request)
        if rol:
            queryset = queryset.filter(roles__nombre=rol)
        return queryset

    def get_serializer_class(self):
        """Serializer según la acción (crear, editar o listar)."""
        if self.action == "create":
            return UsuarioCreateSerializer

        if self.action in [
            "update",
            "partial_update"
        ]:
            return UsuarioUpdateSerializer

        return UsuarioSerializer

    def _es_administrador(self):
        """True si quien hace la petición es SUPER_ADMIN o ADMIN_EMPRESA (no solo por un permiso)."""
        return self.request.user.roles.filter(nombre__in=ROLES_ADMINISTRADORES).exists()

    def _validar_rol(self, rol):
        """Impide que el personal de una empresa asigne roles superiores o de cliente."""
        if rol is None:
            return
        alcance = alcance_de(self.request)
        if not alcance.super_admin and rol.nombre not in ROLES_DE_EMPRESA:
            raise PermissionDenied(f"No puedes asignar el rol {rol.nombre}.")
        if not self._es_administrador() and rol.nombre not in ROLES_ASIGNABLES_POR_GRUPO:
            raise PermissionDenied(
                f"Solo el administrador de la empresa puede asignar el rol {rol.nombre}."
            )

    def _validar_objetivo(self, usuario):
        """Quien gestiona usuarios por un permiso no puede editar ni eliminar administradores."""
        if self._es_administrador():
            return
        if usuario.roles.filter(nombre__in=ROLES_ADMINISTRADORES).exists():
            raise PermissionDenied("Solo el administrador de la empresa puede modificar a un administrador.")

    @staticmethod
    def _validar_sucursal(sucursal, empresa_id):
        """La sucursal asignada debe pertenecer a la empresa del usuario."""
        if sucursal is not None and sucursal.id_empresa_id != empresa_id:
            raise ValidationError({"id_sucursal": "La sucursal pertenece a otra empresa."})

    def _empresa_nueva(self, rol):
        """Empresa del usuario que se crea (None solo para un nuevo SUPER_ADMIN)."""
        alcance = alcance_de(self.request)
        if alcance.super_admin and rol is not None and rol.nombre == "SUPER_ADMIN":
            return None
        return empresa_para_crear(self.request)

    def create(self, request, *args, **kwargs):
        """Crea el usuario y responde con sus datos completos (empresa, sucursal y roles)."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rol = serializer.validated_data.get("rol")
        self._validar_rol(rol)
        empresa = self._empresa_nueva(rol)
        if empresa is not None:
            # Paso 5: el plan de la empresa limita cuántos usuarios del personal tiene.
            SuscripcionService.verificar_limite_personal(empresa)
        self._validar_sucursal(
            serializer.validated_data.get("id_sucursal"),
            empresa.id_empresa if empresa else None,
        )
        usuario = serializer.save(id_empresa=empresa)
        log_audit(
            request.user,
            "USUARIO_CREADO",
            "usuarios",
            usuario.id_usuario,
            f"Se creó el usuario {usuario.correo} con rol {rol.nombre}",
            direccion_ip=get_client_ip(request),
        )
        return Response(UsuarioSerializer(usuario).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        """Edita el usuario sin permitir roles superiores ni sucursales de otra empresa."""
        self._validar_objetivo(serializer.instance)
        self._validar_rol(serializer.validated_data.get("rol"))
        if "id_sucursal" in serializer.validated_data:
            self._validar_sucursal(
                serializer.validated_data["id_sucursal"], serializer.instance.id_empresa_id
            )
        serializer.save()

    def perform_destroy(self, instance):
        """Elimina un usuario de la empresa (nadie puede eliminarse a sí mismo)."""
        if instance.id_usuario == self.request.user.id_usuario:
            raise ValidationError({"error": "No puedes eliminar tu propio usuario."})
        self._validar_objetivo(instance)
        instance.delete()

class RolViewSet(ReadOnlyModelViewSet):
    serializer_class = RolSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Roles disponibles; el personal de una empresa no ve SUPER_ADMIN."""
        queryset = Rol.objects.all().order_by("id_rol")
        if not alcance_de(self.request).super_admin:
            queryset = queryset.exclude(nombre="SUPER_ADMIN")
        return queryset

    def get_permissions(self):
        """Ver permisos de un rol: administradores. Cambiarlos: solo SUPER_ADMIN.

        SaaS: los roles son globales (compartidos por todas las empresas), así
        que cambiar sus permisos afectaría a todas; por eso solo lo hace el
        operador de la plataforma.
        """
        if self.action == "permisos_asignados":
            if self.request.method == "PUT":
                return [IsSuperAdmin()]
            return [IsAdminEmpresa()]
        return super().get_permissions()

    @action(detail=True, methods=["get", "put"], url_path="permisos")
    def permisos_asignados(self, request, pk=None):
        """Consulta (GET) o reemplaza (PUT) los permisos asignados a un rol."""
        rol = self.get_object()

        if request.method == "GET":
            ids_asignados = list(
                RolPermiso.objects
                .filter(id_rol=rol)
                .values_list("id_permiso", flat=True)
            )
            return Response({"permisos": ids_asignados})

        # NUEVO (arreglo RF02): solo se configuran los roles del personal de
        # tienda y solo con los permisos de las pantallas.
        if rol.nombre not in ROLES_CONFIGURABLES:
            raise ValidationError(
                {"error": f"El rol {rol.nombre} no se configura aquí: tiene sus accesos fijos."}
            )

        ids_nuevos = request.data.get("permisos", [])

        with transaction.atomic():
            RolPermiso.objects.filter(id_rol=rol).delete()

            permisos_validos = Permiso.objects.filter(
                id_permiso__in=ids_nuevos, nombre__in=ASIGNABLES
            )

            RolPermiso.objects.bulk_create([
                RolPermiso(id_rol=rol, id_permiso=permiso)
                for permiso in permisos_validos
            ])

        log_audit(
            request.user,
            "ACTUALIZAR_PERMISOS_ROL",
            "rol_permiso",
            rol.id_rol,
            f"Permisos actualizados para el rol {rol.nombre}",
            datos_nuevo={"permisos": list(ids_nuevos)},
            direccion_ip=get_client_ip(request),
        )

        return Response({
            "permisos": list(
                permisos_validos.values_list("id_permiso", flat=True)
            )
        })

class PermisoViewSet(ReadOnlyModelViewSet):
    # MODIFICADO (arreglo RF02): solo los permisos de las pantallas (no los
    # del cliente), en el orden en que se crearon y sin paginar.
    queryset = Permiso.objects.filter(nombre__in=ASIGNABLES).order_by("id_permiso")
    serializer_class = PermisoSerializer
    permission_classes = [IsAdminEmpresa]
    pagination_class = None

class BitacoraViewSet(ReadOnlyModelViewSet):
    serializer_class = BitacoraSerializer
    permission_classes = [IsAdminEmpresa]

    def get_queryset(self):
        """Bitácora de la empresa del administrador (el SUPER_ADMIN ve toda)."""
        queryset = Bitacora.objects.select_related("id_usuario").order_by("-fecha_evento")
        return filtrar_queryset(queryset, self.request)