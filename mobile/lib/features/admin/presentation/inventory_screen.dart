// mobile/lib/features/admin/presentation/inventory_screen.dart
//
// Archivo NUEVO. Dos pestañas: Stock (solo lectura) y Movimientos (solo
// lectura + botón para registrar uno nuevo vía formulario).
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo
// se muestran con el permiso GESTIONAR de la pantalla (_puedeGestionar).

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../data/inventory_service.dart';

class InventoryScreen extends StatefulWidget {
  const InventoryScreen({super.key});

  @override
  State<InventoryScreen> createState() => _InventoryScreenState();
}

class _InventoryScreenState extends State<InventoryScreen> with SingleTickerProviderStateMixin {
  late final InventoryService _service;
  late final TabController _tabController;

  List<dynamic> _stock = [];
  List<dynamic> _movimientos = [];
  List<dynamic> _sucursales = [];
  List<dynamic> _variantes = [];
  bool _cargando = true;
  final _formatoFecha = DateFormat('dd/MM/yyyy HH:mm');

  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  late final bool _puedeGestionar;

  @override
  void initState() {
    super.initState();
    _puedeGestionar =
        context.read<AuthService>().currentUser?.puedeGestionar('inventario') ?? false;
    _tabController = TabController(length: 2, vsync: this);
    _service = InventoryService(apiClient: context.read<ApiClient>());
    _cargarTodo();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _cargarTodo() async {
    setState(() => _cargando = true);
    try {
      final stock = await _service.getStock();
      final movimientos = await _service.getMovimientos();
      final sucursales = await _service.getSucursales();
      final variantes = await _service.getVariantes();
      setState(() {
        _stock = stock;
        _movimientos = movimientos;
        _sucursales = sucursales;
        _variantes = variantes;
        _cargando = false;
      });
    } catch (_) {
      setState(() => _cargando = false);
    }
  }

  String _etiquetaVariante(dynamic v) {
    final talla = v['talla']?['nombre'] ?? '';
    final color = v['color']?['nombre'] ?? '';
    return '${v['codigo_producto']} · $talla · $color';
  }

  Future<void> _abrirFormularioMovimiento() async {
    int? sucursalSeleccionada = _sucursales.isNotEmpty ? _sucursales[0]['id_sucursal'] : null;
    int? varianteSeleccionada = _variantes.isNotEmpty ? _variantes[0]['id_variante'] : null;
    String tipoSeleccionado = 'ENTRADA';
    final cantidadCtrl = TextEditingController();
    final motivoCtrl = TextEditingController();
    final formKey = GlobalKey<FormState>();
    String? errorMsg;
    bool guardando = false;

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            return Padding(
              padding: EdgeInsets.only(
                left: 16,
                right: 16,
                top: 16,
                bottom: MediaQuery.of(context).viewInsets.bottom + 16,
              ),
              child: SingleChildScrollView(
                child: Form(
                  key: formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Registrar movimiento',
                          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 16),
                      DropdownButtonFormField<int>(
                        value: sucursalSeleccionada,
                        decoration: const InputDecoration(labelText: 'Sucursal'),
                        items: _sucursales.map<DropdownMenuItem<int>>((s) {
                          return DropdownMenuItem(
                            value: s['id_sucursal'] as int,
                            child: Text(s['nombre']),
                          );
                        }).toList(),
                        onChanged: (v) => setModalState(() => sucursalSeleccionada = v),
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: varianteSeleccionada,
                        decoration: const InputDecoration(labelText: 'Variante de producto'),
                        items: _variantes.map<DropdownMenuItem<int>>((v) {
                          return DropdownMenuItem(
                            value: v['id_variante'] as int,
                            child: Text(_etiquetaVariante(v), overflow: TextOverflow.ellipsis),
                          );
                        }).toList(),
                        onChanged: (v) => setModalState(() => varianteSeleccionada = v),
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<String>(
                        value: tipoSeleccionado,
                        decoration: const InputDecoration(labelText: 'Tipo de movimiento'),
                        items: const [
                          DropdownMenuItem(value: 'ENTRADA', child: Text('ENTRADA')),
                          DropdownMenuItem(value: 'SALIDA', child: Text('SALIDA')),
                          DropdownMenuItem(value: 'AJUSTE', child: Text('AJUSTE')),
                        ],
                        onChanged: (v) => setModalState(() => tipoSeleccionado = v ?? 'ENTRADA'),
                      ),
                      TextFormField(
                        controller: cantidadCtrl,
                        decoration: const InputDecoration(labelText: 'Cantidad'),
                        keyboardType: TextInputType.number,
                        validator: (v) {
                          if (v == null || int.tryParse(v) == null) return 'Cantidad inválida';
                          return null;
                        },
                      ),
                      TextFormField(
                        controller: motivoCtrl,
                        decoration: const InputDecoration(labelText: 'Motivo (opcional)'),
                      ),
                      if (errorMsg != null) ...[
                        const SizedBox(height: 8),
                        Text(errorMsg!, style: const TextStyle(color: Colors.red)),
                      ],
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton(
                          onPressed: guardando
                              ? null
                              : () async {
                                  if (!formKey.currentState!.validate()) return;
                                  if (sucursalSeleccionada == null || varianteSeleccionada == null) {
                                    setModalState(() => errorMsg = 'Seleccione sucursal y variante.');
                                    return;
                                  }

                                  setModalState(() {
                                    guardando = true;
                                    errorMsg = null;
                                  });

                                  try {
                                    await _service.registrarMovimiento(
                                      idSucursal: sucursalSeleccionada!,
                                      idVariante: varianteSeleccionada!,
                                      tipoMovimiento: tipoSeleccionado,
                                      cantidad: int.parse(cantidadCtrl.text),
                                      motivo: motivoCtrl.text.trim().isEmpty ? null : motivoCtrl.text.trim(),
                                    );
                                    if (context.mounted) Navigator.pop(context);
                                    _cargarTodo();
                                  } catch (e) {
                                    setModalState(() {
                                      guardando = false;
                                      errorMsg = 'No se pudo registrar el movimiento.';
                                    });
                                  }
                                },
                          child: Text(guardando ? 'Guardando...' : 'Registrar'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Inventario'),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: 'Stock'),
            Tab(text: 'Movimientos'),
          ],
        ),
      ),
      floatingActionButton: !_puedeGestionar
          ? null
          : FloatingActionButton(
        onPressed: _abrirFormularioMovimiento,
        child: const Icon(Icons.add),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : TabBarView(
              controller: _tabController,
              children: [
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: _stock.isEmpty
                      ? ListView(children: const [
                          Padding(
                            padding: EdgeInsets.all(32),
                            child: Center(child: Text('No hay stock registrado.')),
                          )
                        ])
                      : ListView.separated(
                          itemCount: _stock.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, index) {
                            final item = _stock[index];
                            return ListTile(
                              title: Text('${item['variante']}'),
                              subtitle: Text('${item['sucursal']}'),
                              trailing: Text(
                                '${item['cantidad']}',
                                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                              ),
                            );
                          },
                        ),
                ),
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: _movimientos.isEmpty
                      ? ListView(children: const [
                          Padding(
                            padding: EdgeInsets.all(32),
                            child: Center(child: Text('No hay movimientos registrados.')),
                          )
                        ])
                      : ListView.separated(
                          itemCount: _movimientos.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, index) {
                            final mov = _movimientos[index];
                            String fecha = '';
                            try {
                              fecha = _formatoFecha.format(
                                DateTime.parse(mov['fecha_movimiento']).toLocal(),
                              );
                            } catch (_) {}

                            return ListTile(
                              title: Text('${mov['tipo_movimiento']} · ${mov['cantidad']}'),
                              subtitle: Text(
                                '${mov['variante']} · ${mov['sucursal']}\n'
                                '${mov['usuario'] ?? 'Sistema'} · $fecha',
                              ),
                              isThreeLine: true,
                            );
                          },
                        ),
                ),
              ],
            ),
    );
  }
}