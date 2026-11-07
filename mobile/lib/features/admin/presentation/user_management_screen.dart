// mobile/lib/features/admin/presentation/user_management_screen.dart
//
// Archivo NUEVO. Lista + formulario (bottom sheet) para crear/editar
// usuarios administrativos. El rol CLIENTE queda excluido del selector,
// igual que en la web (los clientes se registran solos, CU01).
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo
// se muestran con el permiso GESTIONAR de la pantalla (_puedeGestionar).

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/user_admin_service.dart';

class UserManagementScreen extends StatefulWidget {
  const UserManagementScreen({super.key});

  @override
  State<UserManagementScreen> createState() => _UserManagementScreenState();
}

class _UserManagementScreenState extends State<UserManagementScreen> {
  late final UserAdminService _service;
  List<dynamic> _usuarios = [];
  List<dynamic> _roles = [];
  bool _cargando = true;

  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  late final bool _puedeGestionar;

  @override
  void initState() {
    super.initState();
    _puedeGestionar =
        context.read<AuthService>().currentUser?.puedeGestionar('usuarios') ?? false;
    _service = UserAdminService(apiClient: context.read<ApiClient>());
    _cargarDatos();
  }

  Future<void> _cargarDatos() async {
    setState(() => _cargando = true);

    try {
      final roles = await _service.getRoles();
      final usuarios = await _service.getUsuarios();

      setState(() {
        // El rol CLIENTE no se gestiona desde este panel.
        _roles = roles.where((r) => r['nombre'] != 'CLIENTE').toList();
        _usuarios = usuarios.where(
          (u) => !(u['roles'] as List).any((r) => r['nombre'] == 'CLIENTE'),
        ).toList();
        _cargando = false;
      });
    } catch (_) {
      setState(() {
        _usuarios = [];
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

  Future<void> _mostrarFormulario({Map<String, dynamic>? usuario}) async {
    final esEdicion = usuario != null;

    final nombresCtrl = TextEditingController(text: usuario?['nombres'] ?? '');
    final apellidosCtrl = TextEditingController(text: usuario?['apellidos'] ?? '');
    final correoCtrl = TextEditingController(text: usuario?['correo'] ?? '');
    final telefonoCtrl = TextEditingController(text: usuario?['telefono'] ?? '');
    final passwordCtrl = TextEditingController();

    int? rolSeleccionado = esEdicion
        ? (usuario['roles'] as List).isNotEmpty
            ? usuario['roles'][0]['id_rol']
            : null
        : (_roles.isNotEmpty ? _roles[0]['id_rol'] : null);

    String estadoSeleccionado = usuario?['estado'] ?? 'ACTIVO';
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
                        esEdicion ? 'Editar usuario' : 'Nuevo usuario',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: nombresCtrl,
                        decoration: const InputDecoration(labelText: 'Nombres'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: apellidosCtrl,
                        decoration: const InputDecoration(labelText: 'Apellidos'),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Obligatorio' : null,
                      ),
                      TextFormField(
                        controller: correoCtrl,
                        decoration: const InputDecoration(labelText: 'Correo electrónico'),
                        keyboardType: TextInputType.emailAddress,
                        validator: (v) => (v == null || !v.contains('@')) ? 'Correo inválido' : null,
                      ),
                      TextFormField(
                        controller: telefonoCtrl,
                        decoration: const InputDecoration(labelText: 'Teléfono (opcional)'),
                        keyboardType: TextInputType.phone,
                      ),
                      TextFormField(
                        controller: passwordCtrl,
                        decoration: InputDecoration(
                          labelText: esEdicion ? 'Nueva contraseña (opcional)' : 'Contraseña',
                        ),
                        obscureText: true,
                        validator: (v) {
                          if (!esEdicion && (v == null || v.length < 8)) {
                            return 'Mínimo 8 caracteres';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: rolSeleccionado,
                        decoration: const InputDecoration(labelText: 'Rol'),
                        items: _roles.map<DropdownMenuItem<int>>((rol) {
                          return DropdownMenuItem(
                            value: rol['id_rol'] as int,
                            child: Text(rol['nombre']),
                          );
                        }).toList(),
                        onChanged: (v) => setModalState(() => rolSeleccionado = v),
                        validator: (v) => v == null ? 'Seleccione un rol' : null,
                      ),
                      if (esEdicion) ...[
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          value: estadoSeleccionado,
                          decoration: const InputDecoration(labelText: 'Estado'),
                          items: const [
                            DropdownMenuItem(value: 'ACTIVO', child: Text('ACTIVO')),
                            DropdownMenuItem(value: 'INACTIVO', child: Text('INACTIVO')),
                            DropdownMenuItem(value: 'BLOQUEADO', child: Text('BLOQUEADO')),
                          ],
                          onChanged: (v) => setModalState(() => estadoSeleccionado = v ?? 'ACTIVO'),
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

                                  setModalState(() {
                                    guardando = true;
                                    errorMsg = null;
                                  });

                                  final datos = <String, dynamic>{
                                    'nombres': nombresCtrl.text.trim(),
                                    'apellidos': apellidosCtrl.text.trim(),
                                    'correo': correoCtrl.text.trim(),
                                    'telefono': telefonoCtrl.text.trim(),
                                    'rol': rolSeleccionado,
                                  };

                                  if (esEdicion) {
                                    datos['estado'] = estadoSeleccionado;
                                    if (passwordCtrl.text.isNotEmpty) {
                                      datos['password'] = passwordCtrl.text;
                                    }
                                  } else {
                                    datos['password'] = passwordCtrl.text;
                                  }

                                  try {
                                    if (esEdicion) {
                                      await _service.actualizarUsuario(
                                        usuario['id_usuario'],
                                        datos,
                                      );
                                    } else {
                                      await _service.crearUsuario(datos);
                                    }
                                    if (context.mounted) Navigator.pop(context);
                                    _cargarDatos();
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

  Future<void> _confirmarEliminar(Map<String, dynamic> usuario) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar usuario'),
        content: Text('¿Eliminar a ${usuario['nombres']} ${usuario['apellidos']}?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Eliminar')),
        ],
      ),
    );

    if (confirmar == true) {
      try {
        await _service.eliminarUsuario(usuario['id_usuario']);
        _cargarDatos();
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
      appBar: AppBar(title: const Text('Usuarios y Roles')),
      floatingActionButton: !_puedeGestionar
          ? null
          : FloatingActionButton(
        onPressed: () => _mostrarFormulario(),
        child: const Icon(Icons.add),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _cargarDatos,
              child: _usuarios.isEmpty
                  ? ListView(
                      children: const [
                        Padding(
                          padding: EdgeInsets.all(32),
                          child: Center(child: Text('No hay usuarios administrativos.')),
                        ),
                      ],
                    )
                  : ListView.separated(
                      itemCount: _usuarios.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final usuario = _usuarios[index];
                        final rolNombre = (usuario['roles'] as List).isNotEmpty
                            ? usuario['roles'][0]['nombre']
                            : 'Sin rol';

                        return ListTile(
                          title: Text('${usuario['nombres']} ${usuario['apellidos']}'),
                          subtitle: Text('${usuario['correo']} · $rolNombre'),
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (_puedeGestionar) IconButton(
                                icon: const Icon(Icons.edit_outlined, size: 20),
                                onPressed: () => _mostrarFormulario(usuario: usuario),
                              ),
                              if (_puedeGestionar) IconButton(
                                icon: Icon(Icons.delete_outline, size: 20, color: AppColors.danger),
                                onPressed: () => _confirmarEliminar(usuario),
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