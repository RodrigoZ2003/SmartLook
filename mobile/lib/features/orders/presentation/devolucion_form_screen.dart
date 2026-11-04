// mobile/lib/features/orders/presentation/devolucion_form_screen.dart
//
// MODIFICADO (Fase 2 - CU12, igual que la web): el cliente pide la
// devolución de prendas de su pedido con delivery (con recojo).
// - Las prendas y lo que se puede devolver de cada una salen de
//   /sales/devoluciones/buscar-compra/.
// - Motivos: dañada o con defecto (100%), le llegó otra prenda (100%),
//   ya no la quiere (90%: se retiene el 10%).
// - Antes de confirmar se muestran los montos (/sales/devoluciones/calcular/).
// - Al confirmar (/sales/devoluciones/solicitar/) vuelve la devolución creada.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';

/// Motivos de devolución (los mismos textos del backend y la web).
const List<Map<String, String>> motivosDevolucion = [
  {'valor': 'PRODUCTO_DANADO', 'texto': 'Llegó dañada o con defecto', 'ayuda': 'Se devuelve el 100%.'},
  {'valor': 'ERROR_TIENDA', 'texto': 'Le llegó otra prenda', 'ayuda': 'Se devuelve el 100%.'},
  {
    'valor': 'NO_LA_QUIERO',
    'texto': 'Ya no la quiere / no le gustó',
    'ayuda': 'Se devuelve el 90%: la empresa retiene el 10%.'
  },
];

class DevolucionFormScreen extends StatefulWidget {
  final Map<String, dynamic> pedido;

  const DevolucionFormScreen({super.key, required this.pedido});

  @override
  State<DevolucionFormScreen> createState() => _DevolucionFormScreenState();
}

class _DevolucionFormScreenState extends State<DevolucionFormScreen> {
  late final ApiClient _api;
  final TextEditingController _observacionCtrl = TextEditingController();

  Map<String, dynamic>? _compra;
  List<Map<String, dynamic>> _filas = [];
  bool _cargando = true;
  String? _errorCarga;

  Map<String, dynamic>? _montos;
  bool _calculando = false;
  int _calculoId = 0;

  bool _enviando = false;
  String _error = '';

  int get _idOrden => widget.pedido['id_orden'] as int;

  @override
  void initState() {
    super.initState();
    _api = context.read<ApiClient>();
    _cargarCompra();
  }

  @override
  void dispose() {
    _observacionCtrl.dispose();
    super.dispose();
  }

  double _num(dynamic v) => double.tryParse('${v ?? ''}') ?? 0;

  String _bs(dynamic v) => _num(v).toStringAsFixed(2);

  String _mensajeError(Object e, String fallback) {
    try {
      final data = (e as dynamic).response?.data;
      if (data is Map && data['error'] != null) return data['error'].toString();
      if (data is Map && data['detail'] != null) return data['detail'].toString();
    } catch (_) {}
    return fallback;
  }

  Future<void> _cargarCompra() async {
    setState(() {
      _cargando = true;
      _errorCarga = null;
    });
    try {
      final response = await _api.dio.get(
        '/sales/devoluciones/buscar-compra/',
        queryParameters: {'tipo': 'PEDIDO', 'numero': _idOrden},
      );
      final compra = Map<String, dynamic>.from(response.data as Map);
      final items = (compra['items'] ?? []) as List<dynamic>;
      if (!mounted) return;
      setState(() {
        _compra = compra;
        _filas = items.map((i) {
          final m = Map<String, dynamic>.from(i as Map);
          return <String, dynamic>{
            'id_item': m['id_item'],
            'prenda': m['prenda'],
            'disponible': (m['disponible'] ?? 0) as int,
            'precio_unitario': m['precio_unitario'],
            'motivo_no_elegible': m['motivo_no_elegible'],
            'incluir': false,
            'cantidad': 1,
            'motivo': 'PRODUCTO_DANADO',
          };
        }).toList();
        _cargando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _cargando = false;
        _errorCarga = _mensajeError(e, 'No se pudo cargar el pedido.');
      });
    }
  }

  bool _elegible(Map<String, dynamic> fila) =>
      fila['motivo_no_elegible'] == null && (fila['disponible'] as int) > 0;

  List<Map<String, dynamic>> get _seleccionadas =>
      _filas.where((f) => f['incluir'] == true && _elegible(f)).toList();

  List<Map<String, dynamic>> get _itemsPayload => _seleccionadas
      .map((f) => {'id_item': f['id_item'], 'cantidad': f['cantidad'], 'motivo': f['motivo']})
      .toList();

  // Montos de la devolución sin guardarla (lo pagado, lo retenido y lo que se devuelve).
  Future<void> _calcular() async {
    final items = _itemsPayload;
    final id = ++_calculoId;
    if (items.isEmpty) {
      setState(() {
        _montos = null;
        _calculando = false;
      });
      return;
    }
    setState(() {
      _calculando = true;
      _error = '';
    });
    try {
      final response = await _api.dio.post(
        '/sales/devoluciones/calcular/',
        data: {'tipo': 'PEDIDO', 'numero': _idOrden, 'items': items},
      );
      if (!mounted || id != _calculoId) return;
      setState(() {
        _montos = Map<String, dynamic>.from(response.data as Map);
        _calculando = false;
      });
    } catch (e) {
      if (!mounted || id != _calculoId) return;
      setState(() {
        _montos = null;
        _calculando = false;
        _error = _mensajeError(e, 'No se pudo calcular el reembolso.');
      });
    }
  }

  void _cambiar(VoidCallback cambio) {
    setState(cambio);
    _calcular();
  }

  Future<void> _enviar() async {
    final items = _itemsPayload;
    if (items.isEmpty) {
      setState(() => _error = 'Selecciona al menos una prenda a devolver.');
      return;
    }
    setState(() {
      _enviando = true;
      _error = '';
    });
    try {
      final observacion = _observacionCtrl.text.trim();
      final response = await _api.dio.post(
        '/sales/devoluciones/solicitar/',
        data: {
          'id_orden': _idOrden,
          'items': items,
          if (observacion.isNotEmpty) 'observacion': observacion,
        },
      );
      if (!mounted) return;
      Navigator.pop(context, Map<String, dynamic>.from(response.data as Map));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _error = _mensajeError(e, 'No se pudo registrar la devolución. Intenta nuevamente.');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Devolver Pedido #$_idOrden')),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : _errorCarga != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(_errorCarga!, textAlign: TextAlign.center,
                        style: const TextStyle(color: AppColors.danger)),
                  ),
                )
              : _contenido(),
    );
  }

  Widget _contenido() {
    final compra = _compra!;
    final noElegible = compra['motivo_no_elegible'];
    final vence = DateTime.tryParse('${compra['vence'] ?? ''}')?.toLocal();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          '${compra['etiqueta'] ?? 'Pedido #$_idOrden'}'
          '${compra['sucursal'] != null ? ' · ${compra['sucursal']}' : ''}',
          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
        ),
        if (vence != null)
          Text('Puedes pedir la devolución hasta el ${DateFormat('dd/MM/yyyy HH:mm').format(vence)}.',
              style: const TextStyle(fontSize: 13, color: AppColors.grey)),
        const SizedBox(height: 12),
        if (noElegible != null)
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: AppColors.dangerBg, borderRadius: BorderRadius.circular(8)),
            child: Text('$noElegible', style: const TextStyle(color: AppColors.danger)),
          )
        else ...[
          for (final fila in _filas) _tarjetaFila(fila),
          const SizedBox(height: 8),
          TextField(
            controller: _observacionCtrl,
            maxLines: 2,
            decoration: const InputDecoration(
              labelText: 'Observación (opcional)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          if (_calculando)
            const Padding(
              padding: EdgeInsets.all(8),
              child: Text('Calculando el reembolso...', style: TextStyle(fontSize: 13)),
            ),
          if (_montos != null && !_calculando) _resumenMontos(_montos!),
          if (_error.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(_error, style: const TextStyle(color: AppColors.danger)),
          ],
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: (_enviando || _seleccionadas.isEmpty) ? null : _enviar,
            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
            child: Text(_enviando ? 'Enviando...' : 'Solicitar devolución'),
          ),
        ],
      ],
    );
  }

  Widget _tarjetaFila(Map<String, dynamic> fila) {
    final elegible = _elegible(fila);
    final disponible = fila['disponible'] as int;
    final incluir = fila['incluir'] == true;
    String ayuda = '';
    for (final m in motivosDevolucion) {
      if (m['valor'] == fila['motivo']) ayuda = m['ayuda']!;
    }
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: Text('${fila['prenda']}'),
              subtitle: Text(
                elegible
                    ? 'Bs ${_bs(fila['precio_unitario'])} c/u · puedes devolver $disponible'
                    : '${fila['motivo_no_elegible'] ?? 'Ya no se puede devolver.'}',
                style: TextStyle(color: elegible ? AppColors.grey : AppColors.danger, fontSize: 12),
              ),
              value: incluir && elegible,
              onChanged: elegible ? (v) => _cambiar(() => fila['incluir'] = v ?? false) : null,
            ),
            if (incluir && elegible) ...[
              Row(
                children: [
                  const Text('Cantidad'),
                  IconButton(
                    icon: const Icon(Icons.remove_circle_outline),
                    onPressed: (fila['cantidad'] as int) <= 1
                        ? null
                        : () => _cambiar(() => fila['cantidad'] = (fila['cantidad'] as int) - 1),
                  ),
                  Text('${fila['cantidad']}'),
                  IconButton(
                    icon: const Icon(Icons.add_circle_outline),
                    onPressed: (fila['cantidad'] as int) >= disponible
                        ? null
                        : () => _cambiar(() => fila['cantidad'] = (fila['cantidad'] as int) + 1),
                  ),
                ],
              ),
              DropdownButtonFormField<String>(
                value: fila['motivo'] as String,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Motivo', border: OutlineInputBorder()),
                items: motivosDevolucion
                    .map((m) => DropdownMenuItem(value: m['valor'], child: Text(m['texto']!)))
                    .toList(),
                onChanged: (v) => _cambiar(() => fila['motivo'] = v ?? fila['motivo']),
              ),
              const SizedBox(height: 4),
              Text(ayuda, style: const TextStyle(fontSize: 12, color: AppColors.grey)),
            ],
          ],
        ),
      ),
    );
  }

  Widget _resumenMontos(Map<String, dynamic> m) {
    Widget fila(String etiqueta, String valor, {bool resaltar = false, Color? color}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            children: [
              Expanded(child: Text(etiqueta, style: TextStyle(color: color))),
              Text(valor,
                  style: TextStyle(
                    fontWeight: resaltar ? FontWeight.bold : FontWeight.w600,
                    fontSize: resaltar ? 16 : 14,
                    color: color,
                  )),
            ],
          ),
        );
    final retenido = _num(m['monto_retenido']);
    final envio = _num(m['monto_envio']);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: AppColors.light, borderRadius: BorderRadius.circular(8)),
      child: Column(
        children: [
          fila('Prendas devueltas', 'Bs ${_bs(m['monto_prendas'])}'),
          if (retenido > 0)
            fila('Retenido (${_compra?['porcentaje_retencion'] ?? 10}%)', '- Bs ${_bs(retenido)}',
                color: AppColors.danger),
          if (envio > 0) fila('Envío devuelto', 'Bs ${_bs(envio)}'),
          const Divider(),
          fila(
            m['metodo_reembolso'] == 'STRIPE' ? 'Se devuelve a tu tarjeta' : 'Se devuelve',
            'Bs ${_bs(m['monto_reembolso'])}',
            resaltar: true,
            color: AppColors.success,
          ),
        ],
      ),
    );
  }
}