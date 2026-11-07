// mobile/lib/features/admin/presentation/product_variants_screen.dart
//
// Archivo NUEVO. Se abre desde ProductManagementScreen al tocar
// "Variantes" en un producto. Usa producto['variantes'] (ya viene
// anidado desde el backend) como punto de partida, y recarga la lista
// completa de productos tras cada cambio para refrescarlo.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo
// se muestran con el permiso GESTIONAR de la pantalla (_puedeGestionar).

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/product_admin_service.dart';
import '../data/attribute_service.dart';

class ProductVariantsScreen extends StatefulWidget {
  final Map<String, dynamic> producto;

  const ProductVariantsScreen({super.key, required this.producto});

  @override
  State<ProductVariantsScreen> createState() => _ProductVariantsScreenState();
}

class _ProductVariantsScreenState extends State<ProductVariantsScreen> {
  late final ProductAdminService _service;
  late final AttributeService _attributeService;

  late Map<String, dynamic> _producto;
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
        context.read<AuthService>().currentUser?.puedeGestionar('productos') ?? false;
    _producto = widget.producto;
    final apiClient = context.read<ApiClient>();
    _service = ProductAdminService(apiClient: apiClient);
    _attributeService = AttributeService(apiClient: apiClient);
    _cargarAtributos();
  }

  Future<void> _cargarAtributos() async {
    setState(() => _cargando = true);
    try {
      final tallas = await _attributeService.getTallas();
      final colores = await _attributeService.getColores();
      setState(() {
        _tallas = tallas;
        _colores = colores;
        _cargando = false;
      });
    } catch (_) {
      setState(() => _cargando = false);
    }
  }

  Future<void> _recargarProducto() async {
    try {
      final productos = await _service.getProductos();
      final actualizado = productos.firstWhere(
        (p) => p['id_producto'] == _producto['id_producto'],
        orElse: () => _producto,
      );
      setState(() => _producto = actualizado);
    } catch (_) {}
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

  Future<void> _formularioVariante({Map<String, dynamic>? variante}) async {
    final esEdicion = variante != null;
    final codigoCtrl = TextEditingController(text: variante?['codigo_producto'] ?? '');
    final precioCtrl = TextEditingController(text: variante?['precio']?.toString() ?? '');
    final cantidadCtrl = TextEditingController(text: variante?['cantidad']?.toString() ?? '0');

    int? tallaSel;
    if (esEdicion) {
      final t = variante['talla'];
      tallaSel = t != null ? t['id_talla'] as int? : null;
    } else {
      tallaSel = _tallas.isNotEmpty ? _tallas[0]['id_talla'] as int? : null;
    }

    int? colorSel;
    if (esEdicion) {
      final c = variante['color'];
      colorSel = c != null ? c['id_color'] as int? : null;
    } else {
      colorSel = _colores.isNotEmpty ? _colores[0]['id_color'] as int? : null;
    }

    String estadoSel = variante?['estado'] ?? 'DISPONIBLE';
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
                      Text(esEdicion ? 'Editar variante' : 'Nueva variante',
                          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 16),
                      DropdownButtonFormField<int>(
                        value: tallaSel,
                        decoration: const InputDecoration(labelText: 'Talla'),
                        items: _tallas.map<DropdownMenuItem<int>>((t) {
                          return DropdownMenuItem(value: t['id_talla'] as int, child: Text(t['nombre']));
                        }).toList(),
                        onChanged: (v) => setModalState(() => tallaSel = v),
                        validator: (v) => v == null ? 'Seleccione talla' : null,
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: colorSel,
                        decoration: const InputDecoration(labelText: 'Color'),
                        items: _colores.map<DropdownMenuItem<int>>((c) {
                          return DropdownMenuItem(value: c['id_color'] as int, child: Text(c['nombre']));
                        }).toList(),
                        onChanged: (v) => setModalState(() => colorSel = v),
                        validator: (v) => v == null ? 'Seleccione color' : null,
                      ),
                      TextFormField(
                        controller: codigoCtrl,
                        decoration: const InputDecoration(labelText: 'Código (SKU)'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: precioCtrl,
                        decoration: const InputDecoration(labelText: 'Precio (Bs)'),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        validator: (v) => (v == null || double.tryParse(v) == null) ? 'Precio inválido' : null,
                      ),
                      TextFormField(
                        controller: cantidadCtrl,
                        decoration: const InputDecoration(labelText: 'Cantidad inicial'),
                        keyboardType: TextInputType.number,
                        validator: (v) => (v == null || int.tryParse(v) == null) ? 'Cantidad inválida' : null,
                      ),
                      if (esEdicion) ...[
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          value: estadoSel,
                          decoration: const InputDecoration(labelText: 'Estado'),
                          items: const [
                            DropdownMenuItem(value: 'DISPONIBLE', child: Text('DISPONIBLE')),
                            DropdownMenuItem(value: 'AGOTADO', child: Text('AGOTADO')),
                            DropdownMenuItem(value: 'INACTIVO', child: Text('INACTIVO')),
                          ],
                          onChanged: (v) => setModalState(() => estadoSel = v ?? 'DISPONIBLE'),
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
                                    'id_producto': _producto['id_producto'],
                                    'id_talla': tallaSel,
                                    'id_color': colorSel,
                                    'codigo_producto': codigoCtrl.text.trim(),
                                    'precio': precioCtrl.text.trim(),
                                    'cantidad': int.parse(cantidadCtrl.text.trim()),
                                  };
                                  if (esEdicion) datos['estado'] = estadoSel;

                                  try {
                                    if (esEdicion) {
                                      await _service.actualizarVariante(variante['id_variante'], datos);
                                    } else {
                                      await _service.crearVariante(datos);
                                    }
                                    if (context.mounted) Navigator.pop(context);
                                    await _recargarProducto();
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

  Future<void> _eliminarVariante(Map<String, dynamic> variante) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar variante'),
        content: Text('¿Eliminar la variante "${variante['codigo_producto']}"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmar == true) {
      try {
        await _service.eliminarVariante(variante['id_variante']);
        await _recargarProducto();
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_extraerError(e))));
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final variantes = (_producto['variantes'] as List?) ?? [];

    return Scaffold(
      appBar: AppBar(title: Text('Variantes: ${_producto['nombre'] ?? ''}')),
      floatingActionButton: !_puedeGestionar
          ? null
          : FloatingActionButton(
        onPressed: () => _formularioVariante(),
        child: const Icon(Icons.add),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : variantes.isEmpty
              ? const Center(child: Text('Este producto todavía no tiene variantes.'))
              : ListView.separated(
                  itemCount: variantes.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final v = variantes[index];
                    return ListTile(
                      title: Text('${v['codigo_producto']} · ${v['talla']?['nombre'] ?? ''} · ${v['color']?['nombre'] ?? ''}'),
                      subtitle: Text('Bs ${v['precio']} · Stock: ${v['cantidad']} · ${v['estado']}'),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (_puedeGestionar) IconButton(
                            icon: const Icon(Icons.edit_outlined, size: 20),
                            onPressed: () => _formularioVariante(variante: v),
                          ),
                          if (_puedeGestionar) IconButton(
                            icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger),
                            onPressed: () => _eliminarVariante(v),
                          ),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}