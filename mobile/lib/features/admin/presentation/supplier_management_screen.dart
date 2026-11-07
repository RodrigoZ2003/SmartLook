// mobile/lib/features/admin/presentation/supplier_management_screen.dart
//
// Archivo NUEVO. CRUD completo (ProveedorViewSet es ModelViewSet,
// IsAdminEmpresa).
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo
// se muestran con el permiso GESTIONAR de la pantalla (_puedeGestionar).

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/store_service.dart';

class SupplierManagementScreen extends StatefulWidget {
  const SupplierManagementScreen({super.key});

  @override
  State<SupplierManagementScreen> createState() => _SupplierManagementScreenState();
}

class _SupplierManagementScreenState extends State<SupplierManagementScreen> {
  late final StoreService _service;
  List<dynamic> _proveedores = [];
  bool _cargando = true;

  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  late final bool _puedeGestionar;

  @override
  void initState() {
    super.initState();
    _puedeGestionar =
        context.read<AuthService>().currentUser?.puedeGestionar('proveedores') ?? false;
    _service = StoreService(apiClient: context.read<ApiClient>());
    _cargar();
  }

  Future<void> _cargar() async {
    setState(() => _cargando = true);
    try {
      final proveedores = await _service.getProveedores();
      setState(() {
        _proveedores = proveedores;
        _cargando = false;
      });
    } catch (_) {
      setState(() {
        _proveedores = [];
        _cargando = false;
      });
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

  Future<void> _mostrarFormulario({Map<String, dynamic>? proveedor}) async {
    final esEdicion = proveedor != null;

    final nombreEmpresaCtrl = TextEditingController(text: proveedor?['nombre_empresa'] ?? '');
    final nombreContactoCtrl = TextEditingController(text: proveedor?['nombre_contacto'] ?? '');
    final telefonoCtrl = TextEditingController(text: proveedor?['telefono'] ?? '');
    final correoCtrl = TextEditingController(text: proveedor?['correo'] ?? '');
    final direccionCtrl = TextEditingController(text: proveedor?['direccion'] ?? '');
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
                      Text(
                        esEdicion ? 'Editar proveedor' : 'Nuevo proveedor',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: nombreEmpresaCtrl,
                        decoration: const InputDecoration(labelText: 'Nombre de la empresa'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: nombreContactoCtrl,
                        decoration: const InputDecoration(labelText: 'Nombre de contacto'),
                      ),
                      TextFormField(
                        controller: telefonoCtrl,
                        decoration: const InputDecoration(labelText: 'Teléfono'),
                        keyboardType: TextInputType.phone,
                      ),
                      TextFormField(
                        controller: correoCtrl,
                        decoration: const InputDecoration(labelText: 'Correo'),
                        keyboardType: TextInputType.emailAddress,
                      ),
                      TextFormField(
                        controller: direccionCtrl,
                        decoration: const InputDecoration(labelText: 'Dirección'),
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

                                  setModalState(() {
                                    guardando = true;
                                    errorMsg = null;
                                  });

                                  final datos = {
                                    'nombre_empresa': nombreEmpresaCtrl.text.trim(),
                                    'nombre_contacto': nombreContactoCtrl.text.trim(),
                                    'telefono': telefonoCtrl.text.trim(),
                                    'correo': correoCtrl.text.trim(),
                                    'direccion': direccionCtrl.text.trim(),
                                  };

                                  try {
                                    if (esEdicion) {
                                      await _service.actualizarProveedor(
                                        proveedor['id_proveedor'],
                                        datos,
                                      );
                                    } else {
                                      await _service.crearProveedor(datos);
                                    }
                                    if (context.mounted) Navigator.pop(context);
                                    _cargar();
                                  } catch (e) {
                                    setModalState(() {
                                      guardando = false;
                                      errorMsg = _extraerError(e);
                                    });
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

  Future<void> _confirmarEliminar(Map<String, dynamic> proveedor) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar proveedor'),
        content: Text('¿Eliminar a ${proveedor['nombre_empresa']}?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );

    if (confirmar == true) {
      try {
        await _service.eliminarProveedor(proveedor['id_proveedor']);
        _cargar();
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(_extraerError(e))),
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Proveedores')),
      floatingActionButton: !_puedeGestionar
          ? null
          : FloatingActionButton(
        onPressed: () => _mostrarFormulario(),
        child: const Icon(Icons.add),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _cargar,
              child: _proveedores.isEmpty
                  ? ListView(children: const [
                      Padding(
                        padding: EdgeInsets.all(32),
                        child: Center(child: Text('No hay proveedores registrados.')),
                      )
                    ])
                  : ListView.separated(
                      itemCount: _proveedores.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final proveedor = _proveedores[index];
                        return ListTile(
                          title: Text(proveedor['nombre_empresa'] ?? ''),
                          subtitle: Text(
                            '${proveedor['nombre_contacto'] ?? ''}\n'
                            '${proveedor['telefono'] ?? 'N/A'} · ${proveedor['correo'] ?? ''}',
                          ),
                          isThreeLine: true,
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (_puedeGestionar) IconButton(
                                icon: const Icon(Icons.edit_outlined, size: 20),
                                onPressed: () => _mostrarFormulario(proveedor: proveedor),
                              ),
                              if (_puedeGestionar) IconButton(
                                icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger),
                                onPressed: () => _confirmarEliminar(proveedor),
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