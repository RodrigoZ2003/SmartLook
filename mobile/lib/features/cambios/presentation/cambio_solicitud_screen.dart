// mobile/lib/features/cambios/presentation/cambio_solicitud_screen.dart
//
// NUEVO (Fase 2 - CU05): el cliente pide el cambio de talla o color de una
// prenda de su pedido con delivery (dentro de los 7 días desde la entrega).
// - "No me quedó": elige otra talla/color al mismo precio con stock.
// - "Me llegó otra": indica qué talla/color le llegó por error; recibe la que pidió.
// Al confirmar vuelve el cambio creado (con su nota y mensaje).

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/network/api_client.dart';
import '../../../shared/theme/app_colors.dart';
import '../data/cambios_service.dart';

class CambioSolicitudScreen extends StatefulWidget {
  final int idOrdenItem;
  final String prenda;

  const CambioSolicitudScreen({super.key, required this.idOrdenItem, required this.prenda});

  @override
  State<CambioSolicitudScreen> createState() => _CambioSolicitudScreenState();
}

class _CambioSolicitudScreenState extends State<CambioSolicitudScreen> {
  late final CambiosService _service;
  final TextEditingController _observacionCtrl = TextEditingController();

  Map<String, dynamic>? _opciones;
  bool _cargando = true;
  String? _errorCarga;

  String _motivo = 'NO_LE_QUEDA';
  int? _idVariante;
  int _cantidad = 1;
  bool _enviando = false;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _service = CambiosService(apiClient: context.read<ApiClient>());
    _cargar();
  }

  @override
  void dispose() {
    _observacionCtrl.dispose();
    super.dispose();
  }

  Future<void> _cargar() async {
    try {
      final opciones = await _service.opciones(idOrdenItem: widget.idOrdenItem);
      if (!mounted) return;
      setState(() {
        _opciones = opciones;
        _cargando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _cargando = false;
        _errorCarga = CambiosService.textoError(e, 'No se pudieron cargar las tallas y colores.');
      });
    }
  }

  int get _cantidadMaxima => (_opciones?['cantidad'] ?? 1) as int;

  /// "No me quedó": solo al mismo precio y con stock. "Me llegó otra": cualquiera.
  List<Map<String, dynamic>> get _alternativas {
    final lista = ((_opciones?['alternativas'] ?? []) as List<dynamic>)
        .map((a) => Map<String, dynamic>.from(a as Map))
        .toList();
    if (_motivo == 'ERROR_TIENDA') return lista;
    return lista.where((a) => a['mismo_precio'] == true && ((a['stock'] ?? 0) as int) > 0).toList();
  }

  Future<void> _enviar() async {
    if (_idVariante == null) {
      setState(() => _error = _motivo == 'ERROR_TIENDA'
          ? 'Elige la talla o el color que te llegó.'
          : 'Elige la nueva talla o color.');
      return;
    }
    setState(() {
      _enviando = true;
      _error = '';
    });
    try {
      final cambio = await _service.solicitar(
        idOrdenItem: widget.idOrdenItem,
        motivo: _motivo,
        idVariante: _idVariante!,
        cantidad: _cantidad,
        observacion: _observacionCtrl.text.trim(),
      );
      if (!mounted) return;
      Navigator.pop(context, cambio);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _error = CambiosService.textoError(e, 'No se pudo solicitar el cambio.');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Cambiar talla o color')),
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
              : _formulario(),
    );
  }

  Widget _formulario() {
    final o = _opciones!;
    final noElegible = o['motivo_no_elegible'];
    final vence = DateTime.tryParse('${o['vence'] ?? ''}')?.toLocal();
    final alternativas = _alternativas;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(widget.prenda, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        Text('${o['origen'] ?? ''} · Bs ${o['precio']}',
            style: const TextStyle(fontSize: 13, color: AppColors.grey)),
        if (vence != null)
          Text('Puedes pedir el cambio hasta el ${DateFormat('dd/MM/yyyy HH:mm').format(vence)}.',
              style: const TextStyle(fontSize: 13, color: AppColors.grey)),
        const SizedBox(height: 12),
        if (noElegible != null)
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: AppColors.dangerBg, borderRadius: BorderRadius.circular(8)),
            child: Text('$noElegible', style: const TextStyle(color: AppColors.danger)),
          )
        else ...[
          RadioListTile<String>(
            contentPadding: EdgeInsets.zero,
            value: 'NO_LE_QUEDA',
            groupValue: _motivo,
            title: const Text('No me quedó: quiero otra talla o color (mismo precio)'),
            onChanged: (v) => setState(() {
              _motivo = v ?? _motivo;
              _idVariante = null;
            }),
          ),
          RadioListTile<String>(
            contentPadding: EdgeInsets.zero,
            value: 'ERROR_TIENDA',
            groupValue: _motivo,
            title: const Text('Me llegó otra talla o color por error'),
            onChanged: (v) => setState(() {
              _motivo = v ?? _motivo;
              _idVariante = null;
            }),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<int>(
            key: ValueKey('variantes-$_motivo'),
            value: alternativas.any((a) => a['id_variante'] == _idVariante) ? _idVariante : null,
            isExpanded: true,
            decoration: InputDecoration(
              labelText: _motivo == 'ERROR_TIENDA' ? '¿Qué talla/color te llegó?' : '¿Por cuál la cambias?',
              border: const OutlineInputBorder(),
            ),
            items: alternativas
                .map((a) => DropdownMenuItem<int>(
                      value: a['id_variante'] as int,
                      child: Text('Talla ${a['talla']} · ${a['color']} · Bs ${a['precio']}'),
                    ))
                .toList(),
            onChanged: (v) => setState(() => _idVariante = v),
          ),
          if (_motivo == 'NO_LE_QUEDA' && alternativas.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'No hay otra talla o color al mismo precio con stock en ${o['sucursal'] ?? 'la sucursal'}.',
                style: const TextStyle(fontSize: 12, color: AppColors.danger),
              ),
            ),
          if (_motivo == 'ERROR_TIENDA')
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Devuelves la que te llegó por error y recibes ${widget.prenda}.',
                style: const TextStyle(fontSize: 12, color: AppColors.grey),
              ),
            ),
          if (_cantidadMaxima > 1) ...[
            const SizedBox(height: 8),
            Row(
              children: [
                const Text('Cantidad'),
                IconButton(
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: _cantidad <= 1 ? null : () => setState(() => _cantidad--),
                ),
                Text('$_cantidad'),
                IconButton(
                  icon: const Icon(Icons.add_circle_outline),
                  onPressed: _cantidad >= _cantidadMaxima ? null : () => setState(() => _cantidad++),
                ),
              ],
            ),
          ],
          const SizedBox(height: 8),
          TextField(
            controller: _observacionCtrl,
            decoration: const InputDecoration(
              labelText: 'Observación (opcional)',
              border: OutlineInputBorder(),
            ),
          ),
          if (_error.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(_error, style: const TextStyle(color: AppColors.danger)),
          ],
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: _enviando ? null : _enviar,
            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 50)),
            child: Text(_enviando ? 'Enviando...' : 'Solicitar cambio'),
          ),
        ],
      ],
    );
  }
}