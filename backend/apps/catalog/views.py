# backend/apps/catalog/views.py
# MODIFICADO (arreglo RF02): _es_admin también acepta el privilegio GESTIONAR
# de la pantalla que da un grupo (ver lo inactivo para poder editarlo).
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.db.models import Q

from common.permissions import (
    IsAdminEmpresa,
    IsAdminEmpresaOrReadOnly,
    IsGlobalEditableSoloSuperAdmin,
)
from common.privilegios import modulo_de_request, privilegio_requerido, privilegios_de_request
from common.tenancy import EmpresaScopedMixin, empresa_para_crear, validar_relaciones
from apps.users_auth.suscripciones import SuscripcionService
from .models import (
    Pais,
    Ciudad,
    Sucursal,
    Categoria,
    Marca,
    Temporada,
    Coleccion,
    Producto,
    Talla,
    Color,
    ProductoVariante,
    Proveedor,
)
from .serializers import (
    PaisSerializer,
    CiudadSerializer,
    SucursalSerializer,
    CategoriaSerializer,
    MarcaSerializer,
    TemporadaSerializer,
    ColeccionSerializer,
    ProductoSerializer,
    TallaSerializer,
    ColorSerializer,
    ProductoVarianteSerializer,
    ProveedorSerializer,
)


def _es_admin(request):
    """True si el usuario es SUPER_ADMIN o ADMIN_EMPRESA (ve también lo inactivo).

    MODIFICADO (arreglo RF02): también quien tiene por un grupo el privilegio
    GESTIONAR de esa pantalla (por ejemplo GESTIONAR_PRODUCTOS), para que pueda
    ver y reactivar lo que está inactivo.
    """
    usuario = request.user
    if not usuario.is_authenticated:
        return False
    if usuario.roles.filter(nombre__in=["SUPER_ADMIN", "ADMIN_EMPRESA"]).exists():
        return True
    gestionar = privilegio_requerido(modulo_de_request(request), "POST")
    return bool(gestionar) and gestionar in privilegios_de_request(request)


# ----------------------------------------------------------------------
# Catálogos GLOBALES (compartidos por todas las empresas)
# ----------------------------------------------------------------------

class PaisViewSet(ReadOnlyModelViewSet):
    queryset = Pais.objects.filter(estado=True)
    serializer_class = PaisSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class CiudadViewSet(ModelViewSet):
    serializer_class = CiudadSerializer
    permission_classes = [IsGlobalEditableSoloSuperAdmin]

    def get_queryset(self):
        """Ciudades activas (los administradores ven también las inactivas)."""
        return Ciudad.objects.all() if _es_admin(self.request) else Ciudad.objects.filter(estado=True)


class TallaViewSet(ModelViewSet):
    serializer_class = TallaSerializer
    permission_classes = [IsGlobalEditableSoloSuperAdmin]

    def get_queryset(self):
        """Tallas activas (los administradores ven también las inactivas)."""
        return Talla.objects.all() if _es_admin(self.request) else Talla.objects.filter(estado=True)


class ColorViewSet(ModelViewSet):
    serializer_class = ColorSerializer
    permission_classes = [IsGlobalEditableSoloSuperAdmin]

    def get_queryset(self):
        """Colores activos (los administradores ven también los inactivos)."""
        return Color.objects.all() if _es_admin(self.request) else Color.objects.filter(estado=True)


# ----------------------------------------------------------------------
# Datos de cada EMPRESA (aislados por tenant)
# ----------------------------------------------------------------------

class SucursalViewSet(EmpresaScopedMixin, ModelViewSet):
    serializer_class = SucursalSerializer
    permission_classes = [IsAdminEmpresaOrReadOnly]
    lectura_publica = True

    def get_queryset(self):
        """Sucursales de la empresa del usuario (o de todas las empresas activas si es público)."""
        if _es_admin(self.request):
            queryset = Sucursal.objects.all()
        else:
            queryset = Sucursal.objects.filter(estado="ACTIVA")
        queryset = queryset.select_related("id_empresa", "id_ciudad").order_by("id_sucursal")
        return self.filtrar_por_empresa(queryset)

    def perform_create(self, serializer):
        """Crea la sucursal solo si el plan de la empresa lo permite (paso 5)."""
        empresa = empresa_para_crear(self.request)
        SuscripcionService.verificar_limite_sucursales(empresa)
        validar_relaciones(serializer.validated_data, empresa.id_empresa)
        serializer.save(id_empresa=empresa)


class _CatalogoBaseViewSet(EmpresaScopedMixin, ModelViewSet):
    """Base para categoría, marca, temporada y colección.

    En el catálogo público (unificado) varias empresas pueden tener una
    categoría con el mismo nombre; se devuelve una sola por nombre para
    que los filtros del cliente no muestren valores repetidos.
    """

    permission_classes = [IsAdminEmpresaOrReadOnly]
    lectura_publica = True
    modelo = None

    def get_queryset(self):
        """Registros de la empresa del usuario, o únicos por nombre en el catálogo público."""
        if _es_admin(self.request):
            queryset = self.modelo.objects.all()
        else:
            queryset = self.modelo.objects.filter(estado=True)
        queryset = self.filtrar_por_empresa(queryset)
        if self.es_vista_publica():
            queryset = queryset.order_by("nombre", "pk").distinct("nombre")
        return queryset


class CategoriaViewSet(_CatalogoBaseViewSet):
    serializer_class = CategoriaSerializer
    modelo = Categoria


class MarcaViewSet(_CatalogoBaseViewSet):
    serializer_class = MarcaSerializer
    modelo = Marca


class TemporadaViewSet(_CatalogoBaseViewSet):
    serializer_class = TemporadaSerializer
    modelo = Temporada


class ColeccionViewSet(_CatalogoBaseViewSet):
    serializer_class = ColeccionSerializer
    modelo = Coleccion


class ProductoViewSet(EmpresaScopedMixin, ModelViewSet):
    serializer_class = ProductoSerializer
    permission_classes = [IsAdminEmpresaOrReadOnly]
    lectura_publica = True

    def get_queryset(self):
        """Productos de la empresa del usuario, o de todas las empresas activas (catálogo unificado)."""
        if _es_admin(self.request):
            queryset = Producto.objects.all()
        else:
            queryset = Producto.objects.filter(estado="ACTIVO")
        queryset = self.filtrar_por_empresa(
            queryset.select_related("id_empresa")
            .prefetch_related("productovariante_set")
            .order_by("id_producto")
        )

        categoria = self.request.query_params.get("categoria")
        marca = self.request.query_params.get("marca")
        talla = self.request.query_params.get("talla")
        color = self.request.query_params.get("color")
        busqueda = self.request.query_params.get("busqueda")

        if categoria:
            queryset = queryset.filter(id_categoria__nombre=categoria)
        if marca:
            queryset = queryset.filter(id_marca__nombre=marca)
        if talla:
            queryset = queryset.filter(productovariante__id_talla__nombre=talla)
        if color:
            queryset = queryset.filter(productovariante__id_color__nombre=color)
        if busqueda:
            queryset = queryset.filter(nombre__icontains=busqueda)

        return queryset.distinct()

    def perform_create(self, serializer):
        """Crea el producto solo si el plan de la empresa lo permite (paso 5)."""
        empresa = empresa_para_crear(self.request)
        SuscripcionService.verificar_limite_productos(empresa)
        validar_relaciones(serializer.validated_data, empresa.id_empresa)
        serializer.save(id_empresa=empresa)


class ProductoVarianteViewSet(EmpresaScopedMixin, ModelViewSet):
    serializer_class = ProductoVarianteSerializer
    permission_classes = [IsAdminEmpresaOrReadOnly]
    lectura_publica = True
    # La variante no guarda empresa propia: la hereda de su producto.
    campo_empresa = "id_producto__id_empresa"
    asigna_empresa = False

    def get_queryset(self):
        """Variantes de productos de la empresa del usuario (o de empresas activas si es público)."""
        if _es_admin(self.request):
            queryset = ProductoVariante.objects.all()
        else:
            queryset = ProductoVariante.objects.filter(estado__in=["DISPONIBLE", "AGOTADO"])
        queryset = self.filtrar_por_empresa(queryset.order_by("id_variante"))

        busqueda = self.request.query_params.get("busqueda")
        if busqueda:
            queryset = queryset.filter(
                Q(codigo_producto__icontains=busqueda) | Q(id_producto__nombre__icontains=busqueda)
            )
        return queryset


class ProveedorViewSet(EmpresaScopedMixin, ModelViewSet):
    serializer_class = ProveedorSerializer
    permission_classes = [IsAdminEmpresa]

    def get_queryset(self):
        """Proveedores activos de la empresa del usuario (privado, no es catálogo público)."""
        return self.filtrar_por_empresa(
            Proveedor.objects.filter(estado="ACTIVO").order_by("id_proveedor")
        )