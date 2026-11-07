// mobile/lib/features/admin/presentation/branch_management_screen.dart
//
// Reemplaza branch_list_screen.dart (que era solo lectura). Ahora es
// CRUD completo, con dos pestañas: Sucursales / Ciudades.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo
// se muestran con el permiso GESTIONAR de la pantalla (_puedeGestionar).

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/store_service.dart';

class BranchManagementScreen extends StatefulWidget {
  const BranchManagementScreen({super.key});

  @override
  State<BranchManagementScreen> createState() => _BranchManagementScreenState();
}

class _BranchManagementScreenState extends State<BranchManagementScreen>
    with SingleTickerProviderStateMixin {
  late final StoreService _service;
  late final TabController _tabController;

  List<dynamic> _sucursales = [];
  List<dynamic> _ciudades = [];
  List<dynamic> _paises = [];
  bool _cargando = true;

  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  late final bool _puedeGestionar;

  @override
  void initState() {
    super.initState();
    _puedeGestionar =
        context.read<AuthService>().currentUser?.puedeGestionar('sucursales') ?? false;
    _tabController = TabController(length: 2, vsync: this);
    _service = StoreService(apiClient: context.read<ApiClient>());
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
      final sucursales = await _service.getSucursales();
      final ciudades = await _service.getCiudades();
      final paises = await _service.getPaises();
      setState(() {
        _sucursales = sucursales;
        _ciudades = ciudades;
        _paises = paises;
        _cargando = false;
      });
    } catch (_) {
      setState(() => _cargando = false);
    }
  }

  String _extraerError(dynamic error) {
    try {
      final data = error.response?.data;
      if (data is Map) {
        final primeraClave = data.keys.first;
        final valor = data[primeraClave];
        return valor is List ? valor.first.toString() : valor.toString();
      }
    } catch (_) {}
    return 'Ocurrió un error inesperado.';
  }

  // ---- Formulario Sucursal ----

  Future<void> _formularioSucursal({Map<String, dynamic>? sucursal}) async {
    final esEdicion = sucursal != null;
    final nombreCtrl = TextEditingController(text: sucursal?['nombre'] ?? '');
    final direccionCtrl = TextEditingController(text: sucursal?['direccion'] ?? '');
    final telefonoCtrl = TextEditingController(text: sucursal?['telefono'] ?? '');
    int? ciudadSeleccionada;
    if (esEdicion) {
      final ciudadActual = sucursal['ciudad'];
      ciudadSeleccionada = ciudadActual != null ? ciudadActual['id_ciudad'] as int? : null;
    } else {
      ciudadSeleccionada = _ciudades.isNotEmpty ? _ciudades[0]['id_ciudad'] as int? : null;
    }
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
                left: 16, right: 16, top: 16,
                bottom: MediaQuery.of(context).viewInsets.bottom + 16,
              ),
              child: SingleChildScrollView(
                child: Form(
                  key: formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(esEdicion ? 'Editar sucursal' : 'Nueva sucursal',
                          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 16),
                      DropdownButtonFormField<int>(
                        value: ciudadSeleccionada,
                        decoration: const InputDecoration(labelText: 'Ciudad'),
                        items: _ciudades.map<DropdownMenuItem<int>>((c) {
                          return DropdownMenuItem(
                            value: c['id_ciudad'] as int,
                            child: Text('${c['nombre']} - ${c['pais']?['nombre'] ?? ''}'),
                          );
                        }).toList(),
                        onChanged: (v) => setModalState(() => ciudadSeleccionada = v),
                        validator: (v) => v == null ? 'Seleccione una ciudad' : null,
                      ),
                      TextFormField(
                        controller: nombreCtrl,
                        decoration: const InputDecoration(labelText: 'Nombre'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: direccionCtrl,
                        decoration: const InputDecoration(labelText: 'Dirección'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: telefonoCtrl,
                        decoration: const InputDecoration(labelText: 'Teléfono (opcional)'),
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
                                  setModalState(() { guardando = true; errorMsg = null; });

                                  final datos = {
                                    'id_ciudad': ciudadSeleccionada,
                                    'nombre': nombreCtrl.text.trim(),
                                    'direccion': direccionCtrl.text.trim(),
                                    'telefono': telefonoCtrl.text.trim(),
                                  };

                                  try {
                                    if (esEdicion) {
                                      await _service.actualizarSucursal(sucursal['id_sucursal'], datos);
                                    } else {
                                      await _service.crearSucursal(datos);
                                    }
                                    if (context.mounted) Navigator.pop(context);
                                    _cargarTodo();
                                  } catch (e) {
                                    setModalState(() { guardando = false; errorMsg = _extraerError(e); });
                                  }
                                },
                          child: Text(guardando ? 'Guardando...' : 'Guardar'),
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

  Future<void> _eliminarSucursal(Map<String, dynamic> sucursal) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar sucursal'),
        content: Text('¿Eliminar la sucursal "${sucursal['nombre']}"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar == true) {
      try {
        await _service.eliminarSucursal(sucursal['id_sucursal']);
        _cargarTodo();
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_extraerError(e))));
        }
      }
    }
  }

  // ---- Formulario Ciudad ----

  Future<void> _formularioCiudad({Map<String, dynamic>? ciudad}) async {
    final esEdicion = ciudad != null;
    final nombreCtrl = TextEditingController(text: ciudad?['nombre'] ?? '');
    int? paisSeleccionado;
    if (esEdicion) {
      final paisActual = ciudad['pais'];
      paisSeleccionado = paisActual != null ? paisActual['id_pais'] as int? : null;
    } else {
      paisSeleccionado = _paises.isNotEmpty ? _paises[0]['id_pais'] as int? : null;
    }
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
                left: 16, right: 16, top: 16,
                bottom: MediaQuery.of(context).viewInsets.bottom + 16,
              ),
              child: Form(
                key: formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(esEdicion ? 'Editar ciudad' : 'Nueva ciudad',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<int>(
                      value: paisSeleccionado,
                      decoration: const InputDecoration(labelText: 'País'),
                      items: _paises.map<DropdownMenuItem<int>>((p) {
                        return DropdownMenuItem(
                          value: p['id_pais'] as int,
                          child: Text(p['nombre']),
                        );
                      }).toList(),
                      onChanged: (v) => setModalState(() => paisSeleccionado = v),
                      validator: (v) => v == null ? 'Seleccione un país' : null,
                    ),
                    TextFormField(
                      controller: nombreCtrl,
                      decoration: const InputDecoration(labelText: 'Nombre'),
                      validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
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
                                setModalState(() { guardando = true; errorMsg = null; });

                                final datos = {
                                  'id_pais': paisSeleccionado,
                                  'nombre': nombreCtrl.text.trim(),
                                  'estado': true,
                                };

                                try {
                                  if (esEdicion) {
                                    await _service.actualizarCiudad(ciudad['id_ciudad'], datos);
                                  } else {
                                    await _service.crearCiudad(datos);
                                  }
                                  if (context.mounted) Navigator.pop(context);
                                  _cargarTodo();
                                } catch (e) {
                                  setModalState(() { guardando = false; errorMsg = _extraerError(e); });
                                }
                              },
                        child: Text(guardando ? 'Guardando...' : 'Guardar'),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Future<void> _eliminarCiudad(Map<String, dynamic> ciudad) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar ciudad'),
        content: Text('¿Eliminar la ciudad "${ciudad['nombre']}"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar == true) {
      try {
        await _service.eliminarCiudad(ciudad['id_ciudad']);
        _cargarTodo();
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_extraerError(e))));
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Sucursales y Ciudades'),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [Tab(text: 'Sucursales'), Tab(text: 'Ciudades')],
        ),
      ),
      floatingActionButton: !_puedeGestionar
          ? null
          : FloatingActionButton(
        onPressed: () {
          if (_tabController.index == 0) {
            _formularioSucursal();
          } else {
            _formularioCiudad();
          }
        },
        child: const Icon(Icons.add),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : TabBarView(
              controller: _tabController,
              children: [
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: ListView.separated(
                    itemCount: _sucursales.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final s = _sucursales[index];
                      return ListTile(
                        title: Text(s['nombre'] ?? ''),
                        subtitle: Text(
                          '${s['direccion'] ?? ''}\n'
                          '${s['ciudad']?['nombre'] ?? ''}, ${s['ciudad']?['pais']?['nombre'] ?? ''}',
                        ),
                        isThreeLine: true,
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (_puedeGestionar) IconButton(
                              icon: const Icon(Icons.edit_outlined, size: 20),
                              onPressed: () => _formularioSucursal(sucursal: s),
                            ),
                            if (_puedeGestionar) IconButton(
                              icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger),
                              onPressed: () => _eliminarSucursal(s),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: ListView.separated(
                    itemCount: _ciudades.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final c = _ciudades[index];
                      return ListTile(
                        title: Text(c['nombre'] ?? ''),
                        subtitle: Text(c['pais']?['nombre'] ?? ''),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (_puedeGestionar) IconButton(
                              icon: const Icon(Icons.edit_outlined, size: 20),
                              onPressed: () => _formularioCiudad(ciudad: c),
                            ),
                            if (_puedeGestionar) IconButton(
                              icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger),
                              onPressed: () => _eliminarCiudad(c),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
    );
  }
}