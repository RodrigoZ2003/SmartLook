// mobile/lib/features/admin/presentation/product_management_screen.dart
//
// Archivo NUEVO. Reutiliza AttributeService (Paso A) para llenar los
// selectores de categoría/marca/temporada/colección.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo
// se muestran con el permiso GESTIONAR de la pantalla (_puedeGestionar).

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/product_admin_service.dart';
import '../data/attribute_service.dart';
import 'product_variants_screen.dart';

class ProductManagementScreen extends StatefulWidget {
  const ProductManagementScreen({super.key});

  @override
  State<ProductManagementScreen> createState() => _ProductManagementScreenState();
}

class _ProductManagementScreenState extends State<ProductManagementScreen> {
  late final ProductAdminService _service;
  late final AttributeService _attributeService;

  List<dynamic> _productos = [];
  List<dynamic> _categorias = [];
  List<dynamic> _marcas = [];
  List<dynamic> _temporadas = [];
  List<dynamic> _colecciones = [];
  bool _cargando = true;

  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  late final bool _puedeGestionar;

  @override
  void initState() {
    super.initState();
    _puedeGestionar =
        context.read<AuthService>().currentUser?.puedeGestionar('productos') ?? false;
    final apiClient = context.read<ApiClient>();
    _service = ProductAdminService(apiClient: apiClient);
    _attributeService = AttributeService(apiClient: apiClient);
    _cargarTodo();
  }

  Future<void> _cargarTodo() async {
    setState(() => _cargando = true);
    try {
      final productos = await _service.getProductos();
      final categorias = await _attributeService.getCategorias();
      final marcas = await _attributeService.getMarcas();
      final temporadas = await _attributeService.getTemporadas();
      final colecciones = await _attributeService.getColecciones();
      setState(() {
        _productos = productos;
        _categorias = categorias;
        _marcas = marcas;
        _temporadas = temporadas;
        _colecciones = colecciones;
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

  Future<void> _formularioProducto({Map<String, dynamic>? producto}) async {
    final esEdicion = producto != null;
    final nombreCtrl = TextEditingController(text: producto?['nombre'] ?? '');
    final tipoCtrl = TextEditingController(text: producto?['tipo_prenda'] ?? '');
    final descCtrl = TextEditingController(text: producto?['descripcion'] ?? '');
    final imagenCtrl = TextEditingController(text: producto?['imagen_producto'] ?? '');

    int? categoriaSel;
    if (esEdicion) {
      final cat = producto['categoria'];
      categoriaSel = cat != null ? cat['id_categoria'] as int? : null;
    } else {
      categoriaSel = _categorias.isNotEmpty ? _categorias[0]['id_categoria'] as int? : null;
    }

    int? marcaSel;
    if (esEdicion) {
      final m = producto['marca'];
      marcaSel = m != null ? m['id_marca'] as int? : null;
    }

    int? temporadaSel;
    if (esEdicion) {
      final t = producto['temporada'];
      temporadaSel = t != null ? t['id_temporada'] as int? : null;
    }

    int? coleccionSel;
    if (esEdicion) {
      final c = producto['coleccion'];
      coleccionSel = c != null ? c['id_coleccion'] as int? : null;
    }

    String estadoSel = producto?['estado'] ?? 'ACTIVO';
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
                      Text(esEdicion ? 'Editar producto' : 'Nuevo producto',
                          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: nombreCtrl,
                        decoration: const InputDecoration(labelText: 'Nombre'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: tipoCtrl,
                        decoration: const InputDecoration(labelText: 'Tipo de prenda'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: categoriaSel,
                        decoration: const InputDecoration(labelText: 'Categoría'),
                        items: _categorias.map<DropdownMenuItem<int>>((c) {
                          return DropdownMenuItem(value: c['id_categoria'] as int, child: Text(c['nombre']));
                        }).toList(),
                        onChanged: (v) => setModalState(() => categoriaSel = v),
                        validator: (v) => v == null ? 'Seleccione categoría' : null,
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: marcaSel,
                        decoration: const InputDecoration(labelText: 'Marca (opcional)'),
                        items: [
                          const DropdownMenuItem<int>(value: null, child: Text('Sin marca')),
                          ..._marcas.map<DropdownMenuItem<int>>((m) {
                            return DropdownMenuItem(value: m['id_marca'] as int, child: Text(m['nombre']));
                          }),
                        ],
                        onChanged: (v) => setModalState(() => marcaSel = v),
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: temporadaSel,
                        decoration: const InputDecoration(labelText: 'Temporada (opcional)'),
                        items: [
                          const DropdownMenuItem<int>(value: null, child: Text('Sin temporada')),
                          ..._temporadas.map<DropdownMenuItem<int>>((t) {
                            return DropdownMenuItem(value: t['id_temporada'] as int, child: Text(t['nombre']));
                          }),
                        ],
                        onChanged: (v) => setModalState(() => temporadaSel = v),
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: coleccionSel,
                        decoration: const InputDecoration(labelText: 'Colección (opcional)'),
                        items: [
                          const DropdownMenuItem<int>(value: null, child: Text('Sin colección')),
                          ..._colecciones.map<DropdownMenuItem<int>>((c) {
                            return DropdownMenuItem(value: c['id_coleccion'] as int, child: Text(c['nombre']));
                          }),
                        ],
                        onChanged: (v) => setModalState(() => coleccionSel = v),
                      ),
                      TextFormField(
                        controller: descCtrl,
                        decoration: const InputDecoration(labelText: 'Descripción (opcional)'),
                        maxLines: 3,
                      ),
                      TextFormField(
                        controller: imagenCtrl,
                        decoration: const InputDecoration(labelText: 'URL de imagen (opcional)'),
                      ),
                      if (esEdicion) ...[
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          value: estadoSel,
                          decoration: const InputDecoration(labelText: 'Estado'),
                          items: const [
                            DropdownMenuItem(value: 'ACTIVO', child: Text('ACTIVO')),
                            DropdownMenuItem(value: 'INACTIVO', child: Text('INACTIVO')),
                          ],
                          onChanged: (v) => setModalState(() => estadoSel = v ?? 'ACTIVO'),
                        ),
                      ],
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

                                  final datos = <String, dynamic>{
                                    'nombre': nombreCtrl.text.trim(),
                                    'tipo_prenda': tipoCtrl.text.trim(),
                                    'id_categoria': categoriaSel,
                                    'id_marca': marcaSel,
                                    'id_temporada': temporadaSel,
                                    'id_coleccion': coleccionSel,
                                    'descripcion': descCtrl.text.trim(),
                                    'imagen_producto': imagenCtrl.text.trim(),
                                  };
                                  if (esEdicion) datos['estado'] = estadoSel;

                                  try {
                                    if (esEdicion) {
                                      await _service.actualizarProducto(producto['id_producto'], datos);
                                    } else {
                                      await _service.crearProducto(datos);
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

  Future<void> _eliminarProducto(Map<String, dynamic> producto) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar producto'),
        content: Text('¿Eliminar el producto "${producto['nombre']}"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar == true) {
      try {
        await _service.eliminarProducto(producto['id_producto']);
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
      appBar: AppBar(title: const Text('Productos')),
      floatingActionButton: !_puedeGestionar
          ? null
          : FloatingActionButton(
        onPressed: () => _formularioProducto(),
        child: const Icon(Icons.add),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _cargarTodo,
              child: _productos.isEmpty
                  ? ListView(children: const [
                      Padding(
                        padding: EdgeInsets.all(32),
                        child: Center(child: Text('No hay productos registrados.')),
                      )
                    ])
                  : ListView.separated(
                      itemCount: _productos.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final p = _productos[index];
                        final variantesCount = (p['variantes'] as List?)?.length ?? 0;
                        return ListTile(
                          title: Text(p['nombre'] ?? ''),
                          subtitle: Text(
                            '${p['categoria']?['nombre'] ?? 'N/A'} · ${p['marca']?['nombre'] ?? 'Sin marca'}\n'
                            '$variantesCount variante(s)',
                          ),
                          isThreeLine: true,
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                icon: const Icon(Icons.list_alt_outlined, size: 20),
                                tooltip: 'Variantes',
                                onPressed: () async {
                                  await Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                      builder: (context) => ProductVariantsScreen(producto: p),
                                    ),
                                  );
                                  _cargarTodo();
                                },
                              ),
                              if (_puedeGestionar) IconButton(
                                icon: const Icon(Icons.edit_outlined, size: 20),
                                onPressed: () => _formularioProducto(producto: p),
                              ),
                              if (_puedeGestionar) IconButton(
                                icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger),
                                onPressed: () => _eliminarProducto(p),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
            ),
    );
  }
}