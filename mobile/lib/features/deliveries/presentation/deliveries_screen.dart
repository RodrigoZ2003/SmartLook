// mobile/lib/features/deliveries/presentation/deliveries_screen.dart
//
// MODIFICADO (SaaS - A.2): cuando es la pantalla inicial del repartidor,
// muestra arriba su empresa (y sucursal) con EmpresaBanner.
// MODIFICADO (Fase 2 - CU05 / CU12, igual que la web): tres pestañas,
// Pedidos, Cambios de prenda y Devoluciones (recojos). El repartidor sale a
// hacer el cambio / recoger y lo completa confirmando que la prenda está
// sin uso y con etiqueta. Se actualiza cada 10 segundos.

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../../../shared/widgets/empresa_banner.dart';
import '../../../shared/widgets/gestion_dialogs.dart';
import '../../cambios/data/cambios_service.dart';
import '../../devoluciones/data/devoluciones_service.dart';

class DeliveriesScreen extends StatefulWidget {
  /// true cuando es la pantalla inicial del repartidor (sin botón de volver
  /// y con "Cerrar sesión").
  final bool esInicio;

  const DeliveriesScreen({super.key, this.esInicio = false});

  @override
  State<DeliveriesScreen> createState() => _DeliveriesScreenState();
}

class _DeliveriesScreenState extends State<DeliveriesScreen> {
  late final ApiClient _api;
  late final CambiosService _cambiosService;
  late final DevolucionesService _devolucionesService;
  late final bool _esGestor;
  final DateFormat _fmt = DateFormat('dd/MM/yyyy HH:mm');

  List<Map<String, dynamic>> _entregas = [];
  List<Map<String, dynamic>> _repartidores = [];
  final Map<int, int?> _seleccion = {};
  bool _cargando = true;
  int? _procesando;
  String _filtro = '';
  Timer? _timer;

  // NUEVO (CU05): cambios con delivery.
  List<Map<String, dynamic>> _cambios = [];
  String _filtroCambio = 'POR_HACER';
  final Map<int, bool> _condiciones = {};
  int? _procesandoCambio;

  // NUEVO (CU12): recojo de devoluciones.
  List<Map<String, dynamic>> _recojos = [];
  String _filtroRecojo = 'POR_HACER';
  final Map<int, bool> _revisadas = {};
  int? _procesandoRecojo;

  static const List<List<String>> _filtros = [
    ['', 'Todas'],
    ['PENDIENTE', 'Pendientes'],
    ['EN_PREPARACION', 'En preparación'],
    ['EN_CAMINO', 'En camino'],
    ['ENTREGADO', 'Entregadas'],
  ];
  static const List<List<String>> _filtrosCambio = [
    ['POR_HACER', 'Por hacer'],
    ['COMPLETADO', 'Completados'],
    ['', 'Todos'],
  ];
  static const List<List<String>> _filtrosRecojo = [
    ['POR_HACER', 'Por recoger'],
    ['COMPLETADA', 'Completadas'],
    ['', 'Todas'],
  ];

  @override
  void initState() {
    super.initState();
    _api = context.read<ApiClient>();
    _cambiosService = CambiosService(apiClient: _api);
    _devolucionesService = DevolucionesService(apiClient: _api);
    final usuario = context.read<AuthService>().currentUser;
    _esGestor = usuario != null &&
        (usuario.hasRole('SUPER_ADMIN') ||
            usuario.hasRole('ADMIN_EMPRESA') ||
            usuario.hasRole('ENCARGADO_SUCURSAL'));
    if (_esGestor) _cargarRepartidores();
    _cargarTodo();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _cargarTodo());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _cargarTodo() async {
    await Future.wait([_cargar(), _cargarCambios(), _cargarRecojos()]);
  }

  String _errorDe(Object e, String fallback) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map) {
        if (data['error'] != null) return data['error'].toString();
        if (data['detail'] != null) return data['detail'].toString();
      }
    } catch (_) {}
    return fallback;
  }

  void _avisar(String texto, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(texto),
        backgroundColor: error ? AppColors.danger : null,
      ),
    );
  }

  String _fecha(dynamic iso) {
    final dt = DateTime.tryParse('${iso ?? ''}')?.toLocal();
    return dt == null ? '' : _fmt.format(dt);
  }

  Future<void> _cargarRepartidores() async {
    try {
      final response = await _api.dio.get('/sales/entregas/repartidores/');
      final lista = (response.data as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      if (!mounted) return;
      setState(() => _repartidores = lista);
    } catch (_) {
      if (!mounted) return;
      setState(() => _repartidores = []);
    }
  }

  Future<void> _cargar() async {
    try {
      final response = await _api.dio.get(
        '/sales/entregas/',
        queryParameters: {
          'page_size': 100,
          if (_filtro.isNotEmpty) 'estado': _filtro,
        },
      );
      final data = response.data;
      final lista = (data is Map ? (data['results'] ?? []) : data) as List;
      if (!mounted) return;
      setState(() {
        _entregas = lista.map((e) => Map<String, dynamic>.from(e as Map)).toList();
        _cargando = false;
        // Deja preseleccionado el repartidor ya asignado, sin pisar lo que el usuario esté eligiendo.
        for (final d in _entregas) {
          final id = d['id_delivery'] as int;
          if (d['id_repartidor'] != null && _seleccion[id] == null) {
            _seleccion[id] = d['id_repartidor'] as int;
          }
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _cargando = false);
    }
  }

  void _cambiarFiltro(String valor) {
    setState(() {
      _filtro = valor;
      _cargando = true;
    });
    _cargar();
  }

  Future<void> _ejecutar(Map<String, dynamic> d, String accion, {Map<String, dynamic>? body}) async {
    final id = d['id_delivery'] as int;
    setState(() => _procesando = id);
    try {
      await _api.dio.post('/sales/entregas/$id/$accion/', data: body ?? {});
      if (!mounted) return;
      setState(() => _procesando = null);
      _avisar('Entrega #$id actualizada.');
      _cargar();
    } catch (e) {
      if (!mounted) return;
      setState(() => _procesando = null);
      _avisar(_errorDe(e, 'No se pudo completar la acción.'), error: true);
    }
  }

  void _asignar(Map<String, dynamic> d) {
    final elegido = _valorSeleccion(d);
    if (elegido == null) {
      _avisar('Elige un repartidor antes de asignar.', error: true);
      return;
    }
    _ejecutar(d, 'asignar', body: {'id_repartidor': elegido});
  }

  // Solo devuelve un valor que exista en la lista, para que el desplegable no falle.
  int? _valorSeleccion(Map<String, dynamic> d) {
    final v = _seleccion[d['id_delivery'] as int];
    return _repartidores.any((r) => r['id_usuario'] == v) ? v : null;
  }

  // Abre el mapa (Google Maps o el navegador) con la ruta hasta el punto.
  Future<void> _abrirMapa(dynamic latitud, dynamic longitud) async {
    final uri = Uri.parse(
      'https://www.google.com/maps/dir/?api=1&destination=$latitud,$longitud&travelmode=driving',
    );
    try {
      final abierto = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!abierto) _avisar('No se pudo abrir el mapa.', error: true);
    } catch (_) {
      _avisar('No se pudo abrir el mapa.', error: true);
    }
  }

  Future<void> _cerrarSesion() async {
    final nav = Navigator.of(context);
    await context.read<AuthService>().logout();
    nav.pushNamedAndRemoveUntil('/login', (_) => false);
  }

  String _textoEstado(String estado) {
    switch (estado) {
      case 'PENDIENTE':
        return 'Pendiente';
      case 'EN_PREPARACION':
        return 'En preparación';
      case 'EN_CAMINO':
        return 'En camino';
      case 'ENTREGADO':
        return 'Entregado';
      default:
        return estado;
    }
  }

  Color _colorEstado(String estado) {
    switch (estado) {
      case 'EN_PREPARACION':
        return const Color(0xFFB26A00);
      case 'EN_CAMINO':
        return const Color(0xFF1565C0);
      case 'ENTREGADO':
        return const Color(0xFF1B7F4B);
      default:
        return AppColors.primary;
    }
  }

  // ---------------------------------------------------------------- CU05 cambios
  Future<void> _cargarCambios() async {
    try {
      final lista = await _cambiosService.listar({'modalidad': 'DELIVERY', 'page_size': 100});
      if (mounted) setState(() => _cambios = lista);
    } catch (_) {
      if (mounted) setState(() => _cambios = []);
    }
  }

  int get _cambiosPorHacer =>
      _cambios.where((c) => c['estado'] == 'PROGRAMADO' || c['estado'] == 'EN_CAMINO').length;

  List<Map<String, dynamic>> get _cambiosVisibles {
    if (_filtroCambio == 'POR_HACER') {
      return _cambios.where((c) => c['estado'] == 'PROGRAMADO' || c['estado'] == 'EN_CAMINO').toList();
    }
    if (_filtroCambio.isNotEmpty) return _cambios.where((c) => c['estado'] == _filtroCambio).toList();
    return _cambios;
  }

  Future<void> _salirACambio(Map<String, dynamic> c) async {
    final id = c['id_cambio'] as int;
    setState(() => _procesandoCambio = id);
    try {
      await _cambiosService.enCamino(id);
      _avisar('Cambio ${c['numero_nota']} en camino.');
    } catch (e) {
      _avisar(_errorDe(e, 'No se pudo actualizar el cambio.'), error: true);
    }
    if (mounted) setState(() => _procesandoCambio = null);
    _cargarCambios();
  }

  Future<void> _completarCambio(Map<String, dynamic> c) async {
    final id = c['id_cambio'] as int;
    setState(() => _procesandoCambio = id);
    try {
      await _cambiosService.completar(id, _condiciones[id] == true);
      _avisar('Cambio ${c['numero_nota']} completado.');
    } catch (e) {
      _avisar(_errorDe(e, 'No se pudo completar el cambio.'), error: true);
    }
    if (mounted) setState(() => _procesandoCambio = null);
    _cargarCambios();
  }

  // ---------------------------------------------------------------- CU12 recojos
  Future<void> _cargarRecojos() async {
    try {
      final lista = await _devolucionesService.listar({'modalidad': 'DELIVERY', 'page_size': 100});
      if (mounted) setState(() => _recojos = lista);
    } catch (_) {
      if (mounted) setState(() => _recojos = []);
    }
  }

  int get _recojosPorHacer =>
      _recojos.where((d) => d['estado'] == 'PROGRAMADA' || d['estado'] == 'EN_CAMINO').length;

  List<Map<String, dynamic>> get _recojosVisibles {
    if (_filtroRecojo == 'POR_HACER') {
      return _recojos.where((d) => d['estado'] == 'PROGRAMADA' || d['estado'] == 'EN_CAMINO').toList();
    }
    if (_filtroRecojo.isNotEmpty) return _recojos.where((d) => d['estado'] == _filtroRecojo).toList();
    return _recojos;
  }

  Future<void> _salirARecoger(Map<String, dynamic> d) async {
    final id = d['id_devolucion'] as int;
    setState(() => _procesandoRecojo = id);
    try {
      await _devolucionesService.enCamino(id);
      _avisar('Devolución ${d['numero_nota']} en camino.');
    } catch (e) {
      _avisar(_errorDe(e, 'No se pudo actualizar la devolución.'), error: true);
    }
    if (mounted) setState(() => _procesandoRecojo = null);
    _cargarRecojos();
  }

  Future<void> _completarRecojo(Map<String, dynamic> d) async {
    final id = d['id_devolucion'] as int;
    setState(() => _procesandoRecojo = id);
    try {
      final actualizada = await _devolucionesService.completar(id, _revisadas[id] == true);
      _avisar('Devolución ${d['numero_nota']} completada: se devolvió Bs ${actualizada['monto_reembolso']} al cliente.');
    } catch (e) {
      _avisar(_errorDe(e, 'No se pudo completar la devolución.'), error: true);
    }
    if (mounted) setState(() => _procesandoRecojo = null);
    _cargarRecojos();
  }

  // ---------------------------------------------------------------- interfaz
  @override
  Widget build(BuildContext context) {
    final usuario = context.watch<AuthService>().currentUser;
    final mostrarEmpresa = widget.esInicio && usuario?.empresaNombre != null;
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: Text(_esGestor ? 'Entregas' : 'Mis entregas'),
          automaticallyImplyLeading: !widget.esInicio,
          actions: [
            if (widget.esInicio)
              IconButton(
                icon: const Icon(Icons.logout),
                tooltip: 'Cerrar sesión',
                onPressed: _cerrarSesion,
              ),
          ],
          bottom: TabBar(
            tabs: [
              const Tab(text: 'Pedidos'),
              Tab(child: _tabConContador('Cambios', _cambiosPorHacer)),
              Tab(child: _tabConContador('Devoluciones', _recojosPorHacer)),
            ],
          ),
        ),
        body: Column(
          children: [
            // NUEVO (SaaS - A.2): empresa del repartidor.
            if (mostrarEmpresa)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                child: const EmpresaBanner(),
              ),
            Expanded(
              child: TabBarView(
                children: [
                  _vistaPedidos(),
                  _vistaCambios(),
                  _vistaRecojos(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _tabConContador(String texto, int cantidad) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Flexible(child: Text(texto, overflow: TextOverflow.ellipsis)),
        if (cantidad > 0) ...[
          const SizedBox(width: 4),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(color: AppColors.danger, borderRadius: BorderRadius.circular(999)),
            child: Text('$cantidad', style: const TextStyle(color: Colors.white, fontSize: 11)),
          ),
        ],
      ],
    );
  }

  Widget _chips(List<List<String>> filtros, String actual, ValueChanged<String> onSel) {
    return SizedBox(
      height: 56,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        children: [
          for (final f in filtros)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(f[1]),
                selected: actual == f[0],
                onSelected: (_) => onSel(f[0]),
              ),
            ),
        ],
      ),
    );
  }

  Widget _vacio(String texto) => ListView(
        children: [
          const SizedBox(height: 100),
          Center(child: Text(texto, style: const TextStyle(color: AppColors.grey))),
        ],
      );

  // ---- Pedidos
  Widget _vistaPedidos() {
    return Column(
      children: [
        _chips(_filtros, _filtro, _cambiarFiltro),
        Expanded(
          child: _cargando
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _cargar,
                  child: _entregas.isEmpty
                      ? _vacio('No hay entregas en esta lista.')
                      : ListView.builder(
                          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                          itemCount: _entregas.length,
                          itemBuilder: (context, i) => _tarjeta(_entregas[i]),
                        ),
                ),
        ),
      ],
    );
  }

  Widget _tarjeta(Map<String, dynamic> d) {
    final estado = d['estado'] as String;
    final color = _colorEstado(estado);
    final referencia = (d['referencia'] ?? '').toString();
    final telefono = (d['telefono_cliente'] ?? '').toString();

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Entrega #${d['id_delivery']}',
                          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                      Text('Orden #${d['orden']} · ${d['sucursal']}',
                          style: const TextStyle(color: AppColors.grey, fontSize: 12)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    _textoEstado(estado),
                    style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text('Cliente: ${d['cliente']}${telefono.isNotEmpty ? ' · Tel. $telefono' : ''}'),
            const SizedBox(height: 2),
            Text('Dirección: ${d['direccion']}${referencia.isNotEmpty ? ' ($referencia)' : ''}'),
            const SizedBox(height: 2),
            Text(
              '${d['prendas']} prenda(s) · ${d['distancia_km']} km · Pagado Bs ${d['total_orden']}',
              style: const TextStyle(color: AppColors.grey, fontSize: 12),
            ),
            const SizedBox(height: 2),
            Text('Repartidor: ${d['repartidor'] ?? 'Sin asignar'}'),
            TextButton.icon(
              style: TextButton.styleFrom(
                padding: EdgeInsets.zero,
                alignment: Alignment.centerLeft,
              ),
              onPressed: () => _abrirMapa(d['latitud'], d['longitud']),
              icon: const Icon(Icons.directions, size: 20),
              label: const Text('Cómo llegar'),
            ),
            _acciones(d),
          ],
        ),
      ),
    );
  }

  Widget _acciones(Map<String, dynamic> d) {
    final id = d['id_delivery'] as int;
    final estado = d['estado'] as String;
    final ocupado = _procesando == id;
    final widgets = <Widget>[];

    if (_esGestor && (estado == 'PENDIENTE' || estado == 'EN_PREPARACION')) {
      widgets.add(SizedBox(
        width: 180,
        child: DropdownButton<int>(
          isExpanded: true,
          isDense: true,
          value: _valorSeleccion(d),
          hint: const Text('Repartidor'),
          items: _repartidores
              .map((r) => DropdownMenuItem<int>(
                    value: r['id_usuario'] as int,
                    child: Text('${r['nombre']}', overflow: TextOverflow.ellipsis),
                  ))
              .toList(),
          onChanged: (v) => setState(() => _seleccion[id] = v),
        ),
      ));
      widgets.add(OutlinedButton(
        onPressed: ocupado ? null : () => _asignar(d),
        child: const Text('Asignar'),
      ));
    }

    if (_esGestor && estado == 'PENDIENTE') {
      widgets.add(ElevatedButton(
        onPressed: ocupado ? null : () => _ejecutar(d, 'preparar'),
        child: const Text('Preparar pedido'),
      ));
    }

    if (estado == 'EN_PREPARACION') {
      widgets.add(ElevatedButton(
        onPressed: (ocupado || d['id_repartidor'] == null)
            ? null
            : () => _ejecutar(d, 'en-camino'),
        child: const Text('Salir a entregar'),
      ));
    }

    if (estado == 'EN_CAMINO') {
      widgets.add(ElevatedButton(
        onPressed: ocupado ? null : () => _ejecutar(d, 'entregar'),
        child: const Text('Marcar entregado'),
      ));
    }

    if (widgets.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: widgets,
      ),
    );
  }

  // ---- Cambios (CU05)
  Widget _vistaCambios() {
    final lista = _cambiosVisibles;
    return Column(
      children: [
        _chips(_filtrosCambio, _filtroCambio, (v) => setState(() => _filtroCambio = v)),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _cargarCambios,
            child: lista.isEmpty
                ? _vacio('No hay cambios en esta lista.')
                : ListView(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                    children: [for (final c in lista) _tarjetaCambio(c)],
                  ),
          ),
        ),
      ],
    );
  }

  Widget _tarjetaCambio(Map<String, dynamic> c) {
    final id = c['id_cambio'] as int;
    final estado = '${c['estado']}';
    final (fondo, color) = coloresEstadoGestion(estado);
    final cliente = c['cliente'] as Map?;
    final entrega = c['entrega'] as Map?;
    final origen = c['origen'] as Map?;
    final ocupado = _procesandoCambio == id;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: c['atrasado'] == true ? AppColors.danger : AppColors.greyLight),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Cambio ${c['numero_nota']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text('${origen?['etiqueta'] ?? ''} · ${c['sucursal'] ?? ''}',
                          style: const TextStyle(fontSize: 12, color: AppColors.grey)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                  child: Text('${c['estado_display'] ?? estado}',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color)),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text('Cliente: ${cliente?['nombre'] ?? ''}'
                '${cliente?['telefono'] != null ? ' · Tel. ${cliente!['telefono']}' : ''}'),
            if (entrega != null)
              Text('Dirección: ${entrega['direccion']}'
                  '${entrega['referencia'] != null && '${entrega['referencia']}'.isNotEmpty ? ' (${entrega['referencia']})' : ''}'),
            Text('Recoger: ${c['prenda_devuelta']} (${c['cantidad']} u.)',
                style: const TextStyle(fontWeight: FontWeight.w600, color: Color(0xFFC0392B))),
            Text('Entregar: ${c['prenda_entregada']}',
                style: const TextStyle(fontWeight: FontWeight.w600, color: Color(0xFF1B7F4B))),
            if (c['fecha_programada'] != null)
              Text('Visita: ${_fecha(c['fecha_programada'])} · límite ${_fecha(c['fecha_limite'])}'
                  '${c['atrasado'] == true ? ' · ATRASADO' : ''}'),
            if (_esGestor) Text('Repartidor: ${c['repartidor'] ?? 'Sin asignar'}'),
            if (c['observacion'] != null)
              Text('Comentario: ${c['observacion']}', style: const TextStyle(color: AppColors.grey)),
            if (entrega != null)
              TextButton.icon(
                style: TextButton.styleFrom(padding: EdgeInsets.zero, alignment: Alignment.centerLeft),
                onPressed: () => _abrirMapa(entrega['latitud'], entrega['longitud']),
                icon: const Icon(Icons.directions, size: 20),
                label: const Text('Cómo llegar'),
              ),
            if (estado == 'PROGRAMADO')
              ElevatedButton(
                onPressed: ocupado ? null : () => _salirACambio(c),
                child: const Text('Salir a hacer el cambio'),
              ),
            if (estado == 'EN_CAMINO') ...[
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _condiciones[id] == true,
                title: const Text('La prenda devuelta está sin uso y con etiqueta'),
                onChanged: (v) => setState(() => _condiciones[id] = v ?? false),
              ),
              ElevatedButton(
                onPressed: (ocupado || _condiciones[id] != true) ? null : () => _completarCambio(c),
                child: const Text('Completar cambio'),
              ),
            ],
            if (estado == 'SOLICITADO')
              const Text('Pendiente de aprobación en Cambios de prenda.',
                  style: TextStyle(fontSize: 12, color: AppColors.grey)),
          ],
        ),
      ),
    );
  }

  // ---- Devoluciones (CU12)
  Widget _vistaRecojos() {
    final lista = _recojosVisibles;
    return Column(
      children: [
        _chips(_filtrosRecojo, _filtroRecojo, (v) => setState(() => _filtroRecojo = v)),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _cargarRecojos,
            child: lista.isEmpty
                ? _vacio('No hay devoluciones en esta lista.')
                : ListView(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                    children: [for (final d in lista) _tarjetaRecojo(d)],
                  ),
          ),
        ),
      ],
    );
  }

  Widget _tarjetaRecojo(Map<String, dynamic> d) {
    final id = d['id_devolucion'] as int;
    final estado = '${d['estado']}';
    final (fondo, color) = coloresEstadoGestion(estado);
    final contacto = d['cliente_contacto'] as Map?;
    final entrega = d['entrega'] as Map?;
    final origen = d['origen'] as Map?;
    final items = (d['items'] ?? []) as List;
    final ocupado = _procesandoRecojo == id;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: d['atrasado'] == true ? AppColors.danger : AppColors.greyLight),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Devolución ${d['numero_nota']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text('${origen?['etiqueta'] ?? ''} · ${d['sucursal'] ?? ''}',
                          style: const TextStyle(fontSize: 12, color: AppColors.grey)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
                  child: Text('${d['estado_display'] ?? estado}',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color)),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text('Cliente: ${d['cliente'] ?? ''}'
                '${contacto?['telefono'] != null ? ' · Tel. ${contacto!['telefono']}' : ''}'),
            if (entrega != null)
              Text('Dirección: ${entrega['direccion']}'
                  '${entrega['referencia'] != null && '${entrega['referencia']}'.isNotEmpty ? ' (${entrega['referencia']})' : ''}'),
            for (final i in items)
              Text('Recoger: ${i['cantidad']} x ${i['variante']} (${i['motivo_display']})',
                  style: const TextStyle(fontWeight: FontWeight.w600, color: Color(0xFFC0392B))),
            Text('Se le devuelve: Bs ${d['monto_reembolso']} (${d['metodo_reembolso_display'] ?? ''})'),
            if (d['fecha_programada'] != null)
              Text('Recojo: ${_fecha(d['fecha_programada'])} · límite ${_fecha(d['fecha_limite'])}'
                  '${d['atrasado'] == true ? ' · ATRASADO' : ''}'),
            if (_esGestor) Text('Repartidor: ${d['repartidor'] ?? 'Sin asignar'}'),
            if (d['observacion'] != null)
              Text('Comentario: ${d['observacion']}', style: const TextStyle(color: AppColors.grey)),
            if (entrega != null)
              TextButton.icon(
                style: TextButton.styleFrom(padding: EdgeInsets.zero, alignment: Alignment.centerLeft),
                onPressed: () => _abrirMapa(entrega['latitud'], entrega['longitud']),
                icon: const Icon(Icons.directions, size: 20),
                label: const Text('Cómo llegar'),
              ),
            if (estado == 'PROGRAMADA')
              ElevatedButton(
                onPressed: ocupado ? null : () => _salirARecoger(d),
                child: const Text('Salir a recoger'),
              ),
            if (estado == 'EN_CAMINO') ...[
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _revisadas[id] == true,
                title: const Text('Revisé la prenda: sin uso y con etiqueta (si está dañada, el defecto no es por mal uso)'),
                onChanged: (v) => setState(() => _revisadas[id] = v ?? false),
              ),
              ElevatedButton(
                onPressed: (ocupado || _revisadas[id] != true) ? null : () => _completarRecojo(d),
                child: const Text('Completar devolución'),
              ),
            ],
            if (estado == 'SOLICITADA')
              const Text('Pendiente de aprobación en Devoluciones.',
                  style: TextStyle(fontSize: 12, color: AppColors.grey)),
          ],
        ),
      ),
    );
  }
}