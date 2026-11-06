# backend/apps/users_auth/migrations/0015_grupos_privilegios.py
# NUEVO (arreglo RF02 - usuarios, roles y permisos).
#
# Qué hace en la base de datos:
#   1. INSERTA en "permisos" los permisos nuevos que todavía no existan
#      (busca por nombre). Los 11 que ya existían no se modifican.
#   2. En "rol_permiso" reemplaza SOLO las filas de ENCARGADO_SUCURSAL,
#      CAJERO y REPARTIDOR por los permisos de la tabla acordada (las que
#      había estaban mal y nunca se usaron). Desde ahí se cambian en la
#      pantalla "Permisos por rol".
#   - Ajusta los contadores de ids de esas dos tablas al id más alto que ya
#     existe, para que las filas nuevas no choquen con las anteriores.
#   - NO toca roles, usuarios, usuario_rol, empresas ni ninguna otra tabla, ni
#     las filas de rol_permiso de SUPER_ADMIN, ADMIN_EMPRESA y CLIENTE.
from django.db import migrations

PERMISOS_NUEVOS = (
    ("VER_DASHBOARD", "Ver el dashboard"),
    ("VER_USUARIOS", "Ver usuarios y roles"),
    ("VER_PRODUCTOS", "Ver productos"),
    ("VER_ATRIBUTOS", "Ver atributos de producto"),
    ("GESTIONAR_ATRIBUTOS", "Administrar atributos de producto"),
    ("VER_INVENTARIO", "Ver existencias"),
    ("VER_TRASPASOS", "Ver traspasos entre sucursales"),
    ("GESTIONAR_TRASPASOS", "Crear y atender traspasos"),
    ("VER_SUCURSALES", "Ver sucursales"),
    ("VER_PROVEEDORES", "Ver proveedores"),
    ("VER_RESERVAS", "Ver reservas de la empresa"),
    ("GESTIONAR_RESERVAS", "Atender reservas de clientes"),
    ("GESTIONAR_CAMBIOS", "Registrar cambios de prenda"),
    ("VER_DEVOLUCIONES", "Ver devoluciones"),
    ("GESTIONAR_DEVOLUCIONES", "Atender devoluciones"),
    ("VER_ENTREGAS", "Ver entregas"),
    ("GESTIONAR_ENTREGAS", "Atender entregas (delivery)"),
    ("VER_REPORTES", "Ver reportes"),
    ("USAR_ASISTENTE", "Usar el asistente de gestión con IA"),
    ("VER_ANALITICA", "Ver la analítica con Machine Learning"),
    ("VER_CLIENTES", "Ver clientes y su perfil"),
    ("VER_FIDELIDAD", "Ver el descuento por fidelidad"),
)

# Copia fija de common/privilegios.POR_DEFECTO.
POR_DEFECTO = {
    "ENCARGADO_SUCURSAL": (
        "VER_DASHBOARD", "CONSULTAR_CATALOGO", "VER_RESERVAS", "GESTIONAR_RESERVAS",
        "REGISTRAR_VENTAS", "GESTIONAR_CAMBIOS", "VER_DEVOLUCIONES", "GESTIONAR_DEVOLUCIONES",
        "VER_ENTREGAS", "GESTIONAR_ENTREGAS", "VER_REPORTES", "USAR_ASISTENTE",
        "VER_INVENTARIO", "GESTIONAR_INVENTARIO", "VER_TRASPASOS", "GESTIONAR_TRASPASOS",
        "VER_SUCURSALES", "VER_PRODUCTOS",
    ),
    "CAJERO": (
        "VER_DASHBOARD", "CONSULTAR_CATALOGO", "VER_RESERVAS", "REGISTRAR_VENTAS",
        "GESTIONAR_CAMBIOS", "VER_DEVOLUCIONES", "GESTIONAR_DEVOLUCIONES",
    ),
    "REPARTIDOR": ("VER_ENTREGAS", "GESTIONAR_ENTREGAS"),
}


def ajustar_contador(schema_editor, tabla, columna):
    """Pone el contador de ids de la tabla en el id más alto existente."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"SELECT setval(pg_get_serial_sequence('{tabla}', '{columna}'), "
            f"COALESCE((SELECT MAX({columna}) FROM {tabla}), 1))"
        )


def aplicar(apps, schema_editor):
    """Inserta los permisos nuevos y carga los permisos por defecto de los 3 roles."""
    Permiso = apps.get_model("users_auth", "Permiso")
    Rol = apps.get_model("users_auth", "Rol")
    RolPermiso = apps.get_model("users_auth", "RolPermiso")

    ajustar_contador(schema_editor, "permisos", "id_permiso")
    for nombre, descripcion in PERMISOS_NUEVOS:
        if not Permiso.objects.filter(nombre=nombre).exists():
            Permiso.objects.create(nombre=nombre, descripcion=descripcion, estado=True)

    ajustar_contador(schema_editor, "rol_permiso", "id")
    for nombre_rol, nombres in POR_DEFECTO.items():
        rol = Rol.objects.filter(nombre=nombre_rol).first()
        if rol is None:
            continue
        RolPermiso.objects.filter(id_rol=rol).delete()
        RolPermiso.objects.bulk_create([
            RolPermiso(id_rol=rol, id_permiso=permiso)
            for permiso in Permiso.objects.filter(nombre__in=nombres)
        ])


class Migration(migrations.Migration):

    dependencies = [
        ("users_auth", "0014_alter_notificacion_tipo"),
    ]

    operations = [
        migrations.RunPython(aplicar, migrations.RunPython.noop),
    ]