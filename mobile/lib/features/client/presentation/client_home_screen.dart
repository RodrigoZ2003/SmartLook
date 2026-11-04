// mobile/lib/features/client/presentation/client_home_screen.dart
//
// MODIFICADO (CU18/CU19): globo de chat del asistente virtual, visible solo
// en la pestaña Catálogo (índice 0).
// MODIFICADO (perfil): la pestaña Perfil muestra la pantalla real; se
// recarga al abrirla para que el historial incluya las compras nuevas.
// MODIFICADO (Fase 2 - CU16): pestaña "Avisos" con la campana y el contador
// de notificaciones sin leer (se consulta cada minuto si hay red). Tocar un
// aviso lleva a Reservas o Pedidos.
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/notificaciones/notificaciones_service.dart';
import '../../ai_assistant/presentation/chat_bubble_fab.dart';
import '../../catalog/presentation/product_list_screen.dart';
import '../../notificaciones/presentation/notificaciones_screen.dart';
import '../../reservations/presentation/reservation_status_screen.dart';
import '../../orders/presentation/orders_screen.dart';
import '../../../shared/theme/app_colors.dart';
import 'profile_screen.dart';

class ClientHomeScreen extends StatefulWidget {
  const ClientHomeScreen({super.key});

  @override
  State<ClientHomeScreen> createState() => _ClientHomeScreenState();
}

class _ClientHomeScreenState extends State<ClientHomeScreen> {
  static const int _indiceReservas = 1;
  static const int _indicePedidos = 2;
  static const int _indiceAvisos = 3;
  static const int _indicePerfil = 4;

  int _indiceActual = 0;
  final GlobalKey<ProfileScreenState> _perfilKey = GlobalKey<ProfileScreenState>();
  final GlobalKey<NotificacionesScreenState> _avisosKey = GlobalKey<NotificacionesScreenState>();
  late final NotificacionesService _notificaciones;
  late final List<Widget> _pantallas;

  @override
  void initState() {
    super.initState();
    _notificaciones = NotificacionesService(apiClient: context.read<ApiClient>());
    _notificaciones.iniciar();
    _pantallas = [
      const ProductListScreen(),
      const ReservationStatusScreen(),
      const OrdersScreen(),
      NotificacionesScreen(
        key: _avisosKey,
        service: _notificaciones,
        comoPantalla: false,
        onAbrir: _abrirEnlace,
      ),
      ProfileScreen(
        key: _perfilKey,
        onVerPedidos: () => _irA(_indicePedidos),
      ),
    ];
  }

  @override
  void dispose() {
    _notificaciones.dispose();
    super.dispose();
  }

  /// El enlace del aviso es una ruta de la web: se abre la pestaña equivalente.
  void _abrirEnlace(String enlace) {
    if (enlace.startsWith('/reservations')) {
      _irA(_indiceReservas);
    } else if (enlace.startsWith('/orders') || enlace.startsWith('/deliveries')) {
      _irA(_indicePedidos);
    }
  }

  void _irA(int index) {
    setState(() => _indiceActual = index);
    if (index == _indicePerfil) {
      _perfilKey.currentState?.recargar();
    }
    if (index == _indiceAvisos) {
      _avisosKey.currentState?.recargar();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _indiceActual,
        children: _pantallas,
      ),
      floatingActionButton: _indiceActual == 0 ? const ChatBubbleFab() : null,
      bottomNavigationBar: BottomNavigationBar(
        type: BottomNavigationBarType.fixed,
        currentIndex: _indiceActual,
        selectedItemColor: AppColors.primary,
        unselectedItemColor: Colors.grey,
        onTap: _irA,
        items: [
          const BottomNavigationBarItem(
            icon: Icon(Icons.checkroom_outlined),
            label: 'Catálogo',
          ),
          const BottomNavigationBarItem(
            icon: Icon(Icons.event_available_outlined),
            label: 'Reservas',
          ),
          const BottomNavigationBarItem(
            icon: Icon(Icons.receipt_long_outlined),
            label: 'Pedidos',
          ),
          BottomNavigationBarItem(
            icon: CampanaNotificaciones(service: _notificaciones),
            label: 'Avisos',
          ),
          const BottomNavigationBarItem(
            icon: Icon(Icons.person_outline),
            label: 'Perfil',
          ),
        ],
      ),
    );
  }
}