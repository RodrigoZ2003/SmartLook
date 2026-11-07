// mobile/lib/features/admin/presentation/attribute_management_screen.dart
//
// Reemplaza la versión anterior (2 pestañas: Tallas/Colores). Ahora
// tiene 6: Categorías, Marcas, Temporadas, Colecciones, Tallas, Colores.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo
// se muestran con el permiso GESTIONAR de la pantalla (_puedeGestionar).

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/attribute_service.dart';

class AttributeManagementScreen extends StatefulWidget {
  const AttributeManagementScreen({super.key});

  @override
  State<AttributeManagementScreen> createState() => _AttributeManagementScreenState();
}

class _AttributeManagementScreenState extends State<AttributeManagementScreen>
    with SingleTickerProviderStateMixin {
  late final AttributeService _service;
  late final TabController _tabController;

  List<dynamic> _categorias = [];
  List<dynamic> _marcas = [];
  List<dynamic> _temporadas = [];
  List<dynamic> _colecciones = [];
  List<dynamic> _tallas = [];
  List<dynamic> _colores = [];
  bool _cargando = true;

  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  late final bool _puedeGestionar;

  @override
  void initState() {
    super.initState();
    _puedeGestionar =
        context.read<AuthService>().currentUser?.puedeGestionar('atributos') ?? false;
    _tabController = TabController(length: 6, vsync: this);
    _service = AttributeService(apiClient: context.read<ApiClient>());
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
      final categorias = await _service.getCategorias();
      final marcas = await _service.getMarcas();
      final temporadas = await _service.getTemporadas();
      final colecciones = await _service.getColecciones();
      final tallas = await _service.getTallas();
      final colores = await _service.getColores();
      setState(() {
        _categorias = categorias;
        _marcas = marcas;
        _temporadas = temporadas;
        _colecciones = colecciones;
        _tallas = tallas;
        _colores = colores;
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

  // ---- Formulario genérico: nombre + descripción (Categoría / Marca) ----

  Future<void> _formularioSimple({
    required String titulo,
    Map<String, dynamic>? item,
    required String idKey,
    required Future<void> Function(Map<String, dynamic>) crear,
    required Future<void> Function(int, Map<String, dynamic>) actualizar,
  }) async {
    final esEdicion = item != null;
    final nombreCtrl = TextEditingController(text: item?['nombre'] ?? '');
    final descCtrl = TextEditingController(text: item?['descripcion'] ?? '');
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
                    Text(esEdicion ? 'Editar $titulo' : 'Nueva $titulo',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: nombreCtrl,
                      decoration: const InputDecoration(labelText: 'Nombre'),
                      validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                    ),
                    TextFormField(
                      controller: descCtrl,
                      decoration: const InputDecoration(labelText: 'Descripción (opcional)'),
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
                                  'nombre': nombreCtrl.text.trim(),
                                  'descripcion': descCtrl.text.trim(),
                                };

                                try {
                                  if (esEdicion) {
                                    await actualizar(item[idKey], datos);
                                  } else {
                                    await crear(datos);
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

  Future<void> _confirmarEliminar(String titulo, String nombre, Future<void> Function() eliminar) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Eliminar $titulo'),
        content: Text('¿Eliminar "$nombre"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar == true) {
      try {
        await eliminar();
        _cargarTodo();
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_extraerError(e))));
        }
      }
    }
  }

  // ---- Formulario Temporada ----

  Future<void> _formularioTemporada({Map<String, dynamic>? temporada}) async {
    final esEdicion = temporada != null;
    final nombreCtrl = TextEditingController(text: temporada?['nombre'] ?? '');
    final descCtrl = TextEditingController(text: temporada?['descripcion'] ?? '');
    final inicioCtrl = TextEditingController(text: temporada?['fecha_inicio'] ?? '');
    final finCtrl = TextEditingController(text: temporada?['fecha_fin'] ?? '');
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
                      Text(esEdicion ? 'Editar temporada' : 'Nueva temporada',
                          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: nombreCtrl,
                        decoration: const InputDecoration(labelText: 'Nombre'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: inicioCtrl,
                        decoration: const InputDecoration(labelText: 'Fecha inicio (AAAA-MM-DD)'),
                      ),
                      TextFormField(
                        controller: finCtrl,
                        decoration: const InputDecoration(labelText: 'Fecha fin (AAAA-MM-DD)'),
                      ),
                      TextFormField(
                        controller: descCtrl,
                        decoration: const InputDecoration(labelText: 'Descripción (opcional)'),
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
                                    'nombre': nombreCtrl.text.trim(),
                                    'descripcion': descCtrl.text.trim(),
                                    'fecha_inicio': inicioCtrl.text.trim().isEmpty ? null : inicioCtrl.text.trim(),
                                    'fecha_fin': finCtrl.text.trim().isEmpty ? null : finCtrl.text.trim(),
                                  };

                                  try {
                                    if (esEdicion) {
                                      await _service.actualizarTemporada(temporada['id_temporada'], datos);
                                    } else {
                                      await _service.crearTemporada(datos);
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

  // ---- Formulario Colección ----

  Future<void> _formularioColeccion({Map<String, dynamic>? coleccion}) async {
    final esEdicion = coleccion != null;
    final nombreCtrl = TextEditingController(text: coleccion?['nombre'] ?? '');
    final descCtrl = TextEditingController(text: coleccion?['descripcion'] ?? '');
    final anioCtrl = TextEditingController(text: coleccion?['anio']?.toString() ?? '');
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
                    Text(esEdicion ? 'Editar colección' : 'Nueva colección',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: nombreCtrl,
                      decoration: const InputDecoration(labelText: 'Nombre'),
                      validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                    ),
                    TextFormField(
                      controller: anioCtrl,
                      decoration: const InputDecoration(labelText: 'Año'),
                      keyboardType: TextInputType.number,
                    ),
                    TextFormField(
                      controller: descCtrl,
                      decoration: const InputDecoration(labelText: 'Descripción (opcional)'),
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
                                  'nombre': nombreCtrl.text.trim(),
                                  'descripcion': descCtrl.text.trim(),
                                  'anio': anioCtrl.text.trim().isEmpty ? null : int.tryParse(anioCtrl.text.trim()),
                                };

                                try {
                                  if (esEdicion) {
                                    await _service.actualizarColeccion(coleccion['id_coleccion'], datos);
                                  } else {
                                    await _service.crearColeccion(datos);
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

  // ---- Formulario Talla ----

  Future<void> _formularioTalla({Map<String, dynamic>? talla}) async {
    await _formularioSimple(
      titulo: 'talla',
      item: talla,
      idKey: 'id_talla',
      crear: _service.crearTalla,
      actualizar: _service.actualizarTalla,
    );
  }

  // ---- Formulario Color (tiene código hex, no descripción) ----

  Future<void> _formularioColor({Map<String, dynamic>? color}) async {
    final esEdicion = color != null;
    final nombreCtrl = TextEditingController(text: color?['nombre'] ?? '');
    final hexCtrl = TextEditingController(text: color?['codigo_hex'] ?? '#000000');
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
                    Text(esEdicion ? 'Editar color' : 'Nuevo color',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: nombreCtrl,
                      decoration: const InputDecoration(labelText: 'Nombre'),
                      validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                    ),
                    TextFormField(
                      controller: hexCtrl,
                      decoration: const InputDecoration(labelText: 'Código Hex'),
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
                                  'nombre': nombreCtrl.text.trim(),
                                  'codigo_hex': hexCtrl.text.trim(),
                                };

                                try {
                                  if (esEdicion) {
                                    await _service.actualizarColor(color['id_color'], datos);
                                  } else {
                                    await _service.crearColor(datos);
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

  Color _colorDesdeHex(String? hex) {
    if (hex == null || hex.isEmpty) return Colors.grey;
    try {
      return Color(int.parse('FF${hex.replaceAll('#', '')}', radix: 16));
    } catch (_) {
      return Colors.grey;
    }
  }

  Widget _listaGenerica(List<dynamic> items, String idKey, Future<void> Function({Map<String, dynamic>? item}) editar, Future<void> Function(Map<String, dynamic>) eliminar) {
    return RefreshIndicator(
      onRefresh: _cargarTodo,
      child: ListView.separated(
        itemCount: items.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final item = items[index];
          return ListTile(
            title: Text(item['nombre'] ?? ''),
            subtitle: Text(item['descripcion'] ?? ''),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (_puedeGestionar) IconButton(
                  icon: const Icon(Icons.edit_outlined, size: 20),
                  onPressed: () => editar(item: item),
                ),
                if (_puedeGestionar) IconButton(
                  icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger),
                  onPressed: () => eliminar(item),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Atributos de Producto'),
        bottom: TabBar(
          controller: _tabController,
          isScrollable: true,
          tabs: const [
            Tab(text: 'Categorías'),
            Tab(text: 'Marcas'),
            Tab(text: 'Temporadas'),
            Tab(text: 'Colecciones'),
            Tab(text: 'Tallas'),
            Tab(text: 'Colores'),
          ],
        ),
      ),
      floatingActionButton: !_puedeGestionar
          ? null
          : FloatingActionButton(
        onPressed: () {
          switch (_tabController.index) {
            case 0:
              _formularioSimple(
                titulo: 'categoría', idKey: 'id_categoria',
                crear: _service.crearCategoria, actualizar: _service.actualizarCategoria,
              );
              break;
            case 1:
              _formularioSimple(
                titulo: 'marca', idKey: 'id_marca',
                crear: _service.crearMarca, actualizar: _service.actualizarMarca,
              );
              break;
            case 2:
              _formularioTemporada();
              break;
            case 3:
              _formularioColeccion();
              break;
            case 4:
              _formularioTalla();
              break;
            case 5:
              _formularioColor();
              break;
          }
        },
        child: const Icon(Icons.add),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : TabBarView(
              controller: _tabController,
              children: [
                _listaGenerica(_categorias, 'id_categoria',
                    ({item}) => _formularioSimple(titulo: 'categoría', item: item, idKey: 'id_categoria', crear: _service.crearCategoria, actualizar: _service.actualizarCategoria),
                    (c) => _confirmarEliminar('categoría', c['nombre'], () => _service.eliminarCategoria(c['id_categoria']))),
                _listaGenerica(_marcas, 'id_marca',
                    ({item}) => _formularioSimple(titulo: 'marca', item: item, idKey: 'id_marca', crear: _service.crearMarca, actualizar: _service.actualizarMarca),
                    (m) => _confirmarEliminar('marca', m['nombre'], () => _service.eliminarMarca(m['id_marca']))),
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: ListView.separated(
                    itemCount: _temporadas.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final t = _temporadas[index];
                      return ListTile(
                        title: Text(t['nombre'] ?? ''),
                        subtitle: Text('${t['fecha_inicio'] ?? 'N/A'} - ${t['fecha_fin'] ?? 'N/A'}'),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (_puedeGestionar) IconButton(icon: const Icon(Icons.edit_outlined, size: 20), onPressed: () => _formularioTemporada(temporada: t)),
                            if (_puedeGestionar) IconButton(icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger), onPressed: () => _confirmarEliminar('temporada', t['nombre'], () => _service.eliminarTemporada(t['id_temporada']))),
                          ],
                        ),
                      );
                    },
                  ),
                ),
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: ListView.separated(
                    itemCount: _colecciones.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final c = _colecciones[index];
                      return ListTile(
                        title: Text(c['nombre'] ?? ''),
                        subtitle: Text('${c['anio'] ?? 'N/A'}'),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (_puedeGestionar) IconButton(icon: const Icon(Icons.edit_outlined, size: 20), onPressed: () => _formularioColeccion(coleccion: c)),
                            if (_puedeGestionar) IconButton(icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger), onPressed: () => _confirmarEliminar('colección', c['nombre'], () => _service.eliminarColeccion(c['id_coleccion']))),
                          ],
                        ),
                      );
                    },
                  ),
                ),
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: ListView.separated(
                    itemCount: _tallas.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final t = _tallas[index];
                      return ListTile(
                        title: Text(t['nombre'] ?? ''),
                        subtitle: Text(t['descripcion'] ?? ''),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (_puedeGestionar) IconButton(icon: const Icon(Icons.edit_outlined, size: 20), onPressed: () => _formularioTalla(talla: t)),
                            if (_puedeGestionar) IconButton(icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger), onPressed: () => _confirmarEliminar('talla', t['nombre'], () => _service.eliminarTalla(t['id_talla']))),
                          ],
                        ),
                      );
                    },
                  ),
                ),
                RefreshIndicator(
                  onRefresh: _cargarTodo,
                  child: ListView.separated(
                    itemCount: _colores.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final c = _colores[index];
                      return ListTile(
                        leading: CircleAvatar(backgroundColor: _colorDesdeHex(c['codigo_hex'])),
                        title: Text(c['nombre'] ?? ''),
                        subtitle: Text(c['codigo_hex'] ?? ''),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (_puedeGestionar) IconButton(icon: const Icon(Icons.edit_outlined, size: 20), onPressed: () => _formularioColor(color: c)),
                            if (_puedeGestionar) IconButton(icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger), onPressed: () => _confirmarEliminar('color', c['nombre'], () => _service.eliminarColor(c['id_color']))),
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