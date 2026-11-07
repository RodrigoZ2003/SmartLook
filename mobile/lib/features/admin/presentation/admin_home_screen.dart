// mobile/lib/features/admin/presentation/admin_home_screen.dart
//
// MODIFICADO (SaaS - A.2): bajo el nombre y rol se muestran la empresa,
// la sucursal y el plan con su vencimiento (EmpresaBanner).
// MODIFICADO (SaaS): tarjeta "Empresas" (SUPER_ADMIN: lista de empresas con
// sus sucursales; ADMIN_EMPRESA: detalle de la suya) y se enlaza
// "Usuarios y Roles", que mostraba "próximamente".
// MODIFICADO (Fase 2 - CU05 / CU12): tarjetas "Cambios de prenda" y
// "Devoluciones" (seguimiento, registrar en tienda y consulta del mes) para
// SUPER_ADMIN, ADMIN_EMPRESA, ENCARGADO_SUCURSAL y CAJERO.
// MODIFICADO (Fase 2 - CU16): campana de notificaciones con contador, solo
// para SUPER_ADMIN y ADMIN_EMPRESA (el resto del personal no recibe avisos).
// MODIFICADO (arreglo RF02): las tarjetas se muestran según los permisos del
// rol (User.puedeVer; SUPER_ADMIN y ADMIN_EMPRESA ven todo) y se quita la
// tarjeta "Permisos" (los permisos se configuran desde la web).

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/notificaciones/notificaciones_service.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../../../shared/widgets/empresa_banner.dart';
import '../../pos/presentation/pos_cart_screen.dart';
import '../../deliveries/presentation/deliveries_screen.dart';
import '../../catalog/presentation/product_list_screen.dart';
import '../../cambios/presentation/cambios_tienda_screen.dart';
import '../../devoluciones/presentation/devoluciones_tienda_screen.dart';
import '../../notificaciones/presentation/notificaciones_screen.dart';
import 'user_management_screen.dart';
import 'bitacora_list_screen.dart';
import 'client_list_screen.dart';
import 'inventory_screen.dart';
import 'branch_management_screen.dart';
import 'supplier_management_screen.dart';
import 'dashboard_home_screen.dart';
import 'attribute_management_screen.dart';
import 'product_management_screen.dart';
import 'reservation_management_screen.dart';
import 'empresa_list_screen.dart';
import 'empresa_detail_screen.dart';

class AdminHomeScreen extends StatefulWidget {
  const AdminHomeScreen({super.key});

  @override
  State<AdminHomeScreen> createState() => _AdminHomeScreenState();
}

class _AdminHomeScreenState extends State<AdminHomeScreen> {
  NotificacionesService? _notificaciones;

  @override
  void initState() {
    super.initState();
    final authService = context.read<AuthService>();
    final usuario = authService.currentUser;
    // NUEVO (arreglo RF02): trae los permisos actuales del rol.
    authService.refrescarPrivilegios();
    final recibeAvisos =
        (usuario?.hasRole('SUPER_ADMIN') ?? false) || (usuario?.hasRole('ADMIN_EMPRESA') ?? false);
    if (recibeAvisos) {
      _notificaciones = NotificacionesService(apiClient: context.read<ApiClient>())..iniciar();
    }
  }

  @override
  void dispose() {
    _notificaciones?.dispose();
    super.dispose();
  }

  void _abrir(Widget pantalla) {
    Navigator.push(context, MaterialPageRoute(builder: (context) => pantalla));
  }

  /// El enlace del aviso es una ruta de la web: se abre la pantalla equivalente.
  void _abrirEnlace(String enlace) {
    if (enlace.startsWith('/reservations')) {
      _abrir(const ReservationManagementScreen());
    } else if (enlace.startsWith('/deliveries')) {
      _abrir(const DeliveriesScreen());
    } else if (enlace.startsWith('/pos')) {
      _abrir(const PosCartScreen());
    } else if (enlace.startsWith('/orders') || enlace.startsWith('/devoluciones')) {
      _abrir(const DevolucionesTiendaScreen());
    }
  }

  Future<void> _abrirNotificaciones() async {
    final service = _notificaciones;
    if (service == null) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => NotificacionesScreen(service: service, onAbrir: _abrirEnlace),
      ),
    );
    service.actualizarContador();
  }

  @override
  Widget build(BuildContext context) {
    final authService = context.watch<AuthService>();
    final usuario = authService.currentUser;
    final esSuperAdmin = usuario?.hasRole('SUPER_ADMIN') ?? false;
    final esAdminEmpresa = usuario?.hasRole('ADMIN_EMPRESA') ?? false;
    // NUEVO (arreglo RF02): cada tarjeta solo si el rol tiene el permiso.
    bool ver(String pantalla) => usuario?.puedeVer(pantalla) ?? false;

    final secciones = <_SeccionAdmin>[
      if (ver('dashboard')) _SeccionAdmin('Dashboard', Icons.dashboard_outlined, 'dashboard'),
      if (esSuperAdmin || (esAdminEmpresa && usuario?.idEmpresa != null))
        _SeccionAdmin(esSuperAdmin ? 'Empresas' : 'Mi empresa', Icons.business_outlined, 'empresas'),
      if (ver('catalogo')) _SeccionAdmin('Catálogo', Icons.shopping_bag_outlined, 'catalogo'),
      if (ver('pos')) _SeccionAdmin('Punto de Venta', Icons.point_of_sale_outlined, 'pos'),
      if (ver('cambios')) _SeccionAdmin('Cambios de prenda', Icons.swap_horiz, 'cambios'),
      if (ver('devoluciones'))
        _SeccionAdmin('Devoluciones', Icons.assignment_return_outlined, 'devoluciones'),
      if (ver('usuarios')) _SeccionAdmin('Usuarios y Roles', Icons.people_outline, 'usuarios'),
      if (ver('productos')) _SeccionAdmin('Productos', Icons.checkroom_outlined, 'productos'),
      if (ver('atributos'))
        _SeccionAdmin('Atributos de Producto', Icons.straighten_outlined, 'atributos'),
      if (ver('inventario')) _SeccionAdmin('Inventario', Icons.inventory_2_outlined, 'inventario'),
      if (ver('reservas')) _SeccionAdmin('Reservas', Icons.event_available_outlined, 'reservas'),
      if (ver('sucursales')) _SeccionAdmin('Sucursales', Icons.storefront_outlined, 'sucursales'),
      if (ver('proveedores'))
        _SeccionAdmin('Proveedores', Icons.local_shipping_outlined, 'proveedores'),
      if (ver('clientes')) _SeccionAdmin('Clientes', Icons.person_outline, 'clientes'),
      if (ver('bitacora')) _SeccionAdmin('Bitácora', Icons.receipt_long_outlined, 'bitacora'),
      if (ver('entregas')) _SeccionAdmin('Entregas', Icons.delivery_dining, 'entregas'),
    ];

    final nombreRol = usuario != null && usuario.roles.isNotEmpty
        ? usuario.roles.first.nombre
        : '';

    return Scaffold(
      backgroundColor: AppColors.panelBg,
      appBar: AppBar(
        backgroundColor: AppColors.bgDeep,
        elevation: 0,
        title: Text(
          'SmartLook',
          style: GoogleFonts.fraunces(
            fontSize: 18,
            fontWeight: FontWeight.w500,
            color: AppColors.panelBg,
          ),
        ),
        iconTheme: const IconThemeData(color: AppColors.panelBg),
        actions: [
          if (_notificaciones != null)
            IconButton(
              tooltip: 'Notificaciones',
              icon: CampanaNotificaciones(service: _notificaciones!, color: AppColors.panelBg),
              onPressed: _abrirNotificaciones,
            ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Cerrar sesión',
            onPressed: () async {
              _notificaciones?.dispose();
              _notificaciones = null;
              await authService.logout();
              if (context.mounted) {
                Navigator.pushReplacementNamed(context, '/login');
              }
            },
          ),
        ],
      ),
      body: Column(
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppColors.white,
              border: Border(
                bottom: BorderSide(color: AppColors.line),
                top: const BorderSide(color: AppColors.primary, width: 3),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  usuario != null ? '${usuario.nombreCompleto} · $nombreRol' : nombreRol,
                  style: GoogleFonts.inter(
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                    color: AppColors.textDark,
                  ),
                ),
                if (usuario?.empresaNombre != null) ...[
                  const SizedBox(height: 8),
                  const EmpresaBanner(),
                ],
              ],
            ),
          ),
          Expanded(
            child: GridView.builder(
              padding: const EdgeInsets.all(16),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 1.1,
              ),
              itemCount: secciones.length,
              itemBuilder: (context, index) {
                final seccion = secciones[index];
                return _TarjetaSeccion(
                  seccion: seccion,
                  onTap: () {
                    switch (seccion.clave) {
                      case 'dashboard':
                        _abrir(const DashboardHomeScreen());
                        break;
                      case 'empresas':
                        if (esSuperAdmin) {
                          _abrir(const EmpresaListScreen());
                        } else if (usuario?.idEmpresa != null) {
                          _abrir(EmpresaDetailScreen(idEmpresa: usuario!.idEmpresa!));
                        }
                        break;
                      case 'catalogo':
                        _abrir(const ProductListScreen());
                        break;
                      case 'pos':
                        _abrir(const PosCartScreen());
                        break;
                      case 'cambios':
                        _abrir(const CambiosTiendaScreen());
                        break;
                      case 'devoluciones':
                        _abrir(const DevolucionesTiendaScreen());
                        break;
                      case 'usuarios':
                        _abrir(const UserManagementScreen());
                        break;
                      case 'productos':
                        _abrir(const ProductManagementScreen());
                        break;
                      case 'atributos':
                        _abrir(const AttributeManagementScreen());
                        break;
                      case 'bitacora':
                        _abrir(const BitacoraListScreen());
                        break;
                      case 'clientes':
                        _abrir(const ClientListScreen());
                        break;
                      case 'inventario':
                        _abrir(const InventoryScreen());
                        break;
                      case 'reservas':
                        _abrir(const ReservationManagementScreen());
                        break;
                      case 'sucursales':
                        _abrir(const BranchManagementScreen());
                        break;
                      case 'entregas':
                        _abrir(const DeliveriesScreen());
                        break;
                      case 'proveedores':
                        _abrir(const SupplierManagementScreen());
                        break;
                      default:
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text('${seccion.titulo}: próximamente'),
                          ),
                        );
                    }
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _SeccionAdmin {
  final String titulo;
  final IconData icono;
  final String? clave;

  _SeccionAdmin(this.titulo, this.icono, this.clave);
}

class _TarjetaSeccion extends StatelessWidget {
  final _SeccionAdmin seccion;
  final VoidCallback onTap;

  const _TarjetaSeccion({required this.seccion, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.white,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: AppColors.line),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.04),
                blurRadius: 6,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Column(
            children: [
              Container(
                height: 3,
                decoration: const BoxDecoration(
                  color: AppColors.primary,
                  borderRadius: BorderRadius.vertical(top: Radius.circular(6)),
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(seccion.icono, size: 30, color: AppColors.primary),
                      const SizedBox(height: 12),
                      Text(
                        seccion.titulo,
                        textAlign: TextAlign.center,
                        style: GoogleFonts.inter(
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                          color: AppColors.textDark,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}