// mobile/lib/features/catalog/presentation/product_detail_screen.dart
//
// MODIFICADO (SaaS - A.1): "Vendido por <empresa>" y aviso del carrito de
// la tienda a la que se agregó la prenda.
// MODIFICADO (SaaS - 6.2): consultable sin conexión. El producto sale de la
// copia local y la disponibilidad por sucursal de la última consulta
// guardada, avisando que puede estar desactualizada.
// Del modelo solo se importan Product y ProductVariant: sus clases Color/Size
// chocan con las de Flutter.
// MODIFICADO (vestidor virtual): al abrir el vestidor se le pasa la talla de
// la variante elegida, para ajustar el tamaño de la prenda.
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../../core/models/product_model.dart' show Product, ProductVariant;
import '../../../core/network/api_client.dart';
import '../../../core/offline/cache_local.dart';
import '../../../core/offline/conexion.dart';
import '../../../core/services/auth_service.dart';
import '../../../shared/theme/app_colors.dart';
import '../../../shared/widgets/loading_overlay.dart';
import '../../cart_checkout/data/cart_service.dart';
import '../../reservations/data/reserva_offline_service.dart';
import '../../virtual_tryon/presentation/ar_tryon_screen.dart';

class ProductDetailScreen extends StatefulWidget {
  final int productId;

  const ProductDetailScreen({super.key, required this.productId});

  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  late final ReservaOfflineService _offline;
  Product? _product;
  ProductVariant? _selectedVariant;
  bool _isLoading = false;
  // NUEVO (6.2): el producto o la disponibilidad salen de la copia local.
  bool _usandoCopia = false;
  DateTime? _fechaStockCopia;

  // CU08 - Disponibilidad por Sucursal
  List<dynamic> _stockPorSucursal = [];
  bool _loadingStock = false;
  late final CartService _cartService;
  bool _addingToCart = false;
  String _cartMessage = '';
  bool _cartError = false;

  @override
  void initState() {
    super.initState();
    final apiClient = context.read<ApiClient>();
    _cartService = CartService(apiClient: apiClient);
    _offline = context.read<ReservaOfflineService>();
    _loadProduct();
  }

  int get _idUsuario => context.read<AuthService>().currentUser?.idUsuario ?? 0;

  Future<void> _loadProduct() async {
    setState(() {
      _isLoading = true;
    });
    Product? producto;
    var desdeCopia = false;
    try {
      final response = await context.read<ApiClient>().dio.get('/catalog/productos/${widget.productId}/');
      producto = Product.fromJson(response.data);
    } catch (e) {
      if (esErrorDeRed(e)) {
        _offline.marcarSinConexion();
        final locales = await _offline.productosLocales();
        for (final p in locales) {
          if (p['id_producto'] == widget.productId) producto = Product.fromJson(p);
        }
        desdeCopia = producto != null;
      }
    }
    if (!mounted) return;
    setState(() {
      _product = producto;
      _usandoCopia = desdeCopia;
      if (producto != null && producto.variantes.isNotEmpty) {
        _selectedVariant = producto.variantes.first;
      }
      _isLoading = false;
    });
    if (_selectedVariant != null) {
      _loadDisponibilidad(_selectedVariant!.idVariante);
    }
  }

  // CU08 - Disponibilidad por Sucursal (con copia local para consultarla sin conexión)
  Future<void> _loadDisponibilidad(int varianteId) async {
    setState(() {
      _loadingStock = true;
      _stockPorSucursal = [];
      _fechaStockCopia = null;
    });
    final clave = 'stock_variante_$varianteId';
    try {
      final response = await context.read<ApiClient>().dio.get(
        '/inventory/stock/',
        queryParameters: {'variante': varianteId},
      );
      final data = response.data;
      final results = (data['results'] ?? data) as List<dynamic>;
      CacheLocal.guardar(_idUsuario, clave, results);
      if (mounted) {
        setState(() {
          _stockPorSucursal = results;
          _loadingStock = false;
        });
      }
    } catch (e) {
      if (esErrorDeRed(e)) {
        final copia = await CacheLocal.leer(_idUsuario, clave);
        if (mounted && copia != null) {
          setState(() {
            _stockPorSucursal = copia.$1 as List<dynamic>;
            _fechaStockCopia = copia.$2;
          });
        }
      }
      if (mounted) {
        setState(() {
          _loadingStock = false;
        });
      }
    }
  }

  void _onVariantSelected(ProductVariant variant) {
    setState(() {
      _selectedVariant = variant;
    });
    _loadDisponibilidad(variant.idVariante);
  }

  Future<void> _agregarAlCarrito() async {
    setState(() {
      _addingToCart = true;
      _cartMessage = '';
      _cartError = false;
    });
    try {
      await _cartService.agregarItem(_selectedVariant!.idVariante);
      if (!mounted) return;
      final empresa = _product?.empresaNombre ?? '';
      setState(() {
        _addingToCart = false;
        _cartMessage = empresa.isNotEmpty
            ? 'Agregado al carrito de $empresa.'
            : 'Agregado al carrito.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _addingToCart = false;
        _cartError = true;
        _cartMessage = 'No se pudo agregar al carrito.';
      });
    }
  }

  Widget _aviso(String texto) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF3E0),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(texto, style: const TextStyle(fontSize: 12, color: Color(0xFF8A4B00))),
    );
  }

  @override
  Widget build(BuildContext context) {
    final fmt = DateFormat('dd/MM/yyyy HH:mm');
    final fechaCatalogo = _offline.fechaCatalogo;
    return Scaffold(
      appBar: AppBar(
        title: Text(_product?.nombre ?? 'Detalle de Producto'),
      ),
      body: LoadingOverlay(
        isLoading: _isLoading,
        child: _product == null
            ? const Center(child: Text('Producto no encontrado'))
            : SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Imagen: prioriza la de la variante activa, con fallback
                    // a la foto general del producto.
                    Container(
                      height: 350,
                      width: double.infinity,
                      color: AppColors.greyLight,
                      child: (_selectedVariant?.imagenVariante ?? _product!.imagenProducto) != null
                          ? CachedNetworkImage(
                              imageUrl: (_selectedVariant?.imagenVariante ?? _product!.imagenProducto)!,
                              fit: BoxFit.cover,
                              placeholder: (context, url) => const Center(
                                child: CircularProgressIndicator(),
                              ),
                              errorWidget: (context, url, error) => const Icon(
                                Icons.shopping_bag,
                                size: 64,
                                color: AppColors.grey,
                              ),
                            )
                          : const Icon(
                              Icons.shopping_bag,
                              size: 64,
                              color: AppColors.grey,
                            ),
                    ),
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if (_usandoCopia)
                            _aviso(
                              fechaCatalogo != null
                                  ? 'Sin conexión: estás viendo información guardada en este dispositivo el '
                                      '${fmt.format(fechaCatalogo.toLocal())}. '
                                      'Precios y disponibilidad pueden estar desactualizados.'
                                  : 'Sin conexión: puedes consultar lo que ya se descargó y registrar ventas o reservas; '
                                      'se enviarán al recuperar internet.',
                            ),
                          Text(
                            _product!.marca?.nombre ?? 'SmartLook',
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppColors.grey,
                              letterSpacing: 1.5,
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            _product!.nombre,
                            style: const TextStyle(
                              fontSize: 24,
                              fontWeight: FontWeight.bold,
                              color: AppColors.dark,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            _product!.categoria?.nombre ?? '',
                            style: const TextStyle(
                              fontSize: 14,
                              color: AppColors.grey,
                            ),
                          ),
                          // Tienda que vende la prenda.
                          if ((_product!.empresaNombre ?? '').isNotEmpty) ...[
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                const Icon(Icons.storefront, size: 16, color: AppColors.grey),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: Text(
                                    'Vendido por ${_product!.empresaNombre}',
                                    style: const TextStyle(
                                      fontSize: 14,
                                      fontWeight: FontWeight.w600,
                                      color: AppColors.dark,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                          const SizedBox(height: 16),
                          if (_product!.descripcion != null)
                            Text(
                              _product!.descripcion!,
                              style: const TextStyle(
                                fontSize: 14,
                                height: 1.5,
                              ),
                            ),
                          const SizedBox(height: 16),
                          Row(
                            children: [
                              _buildInfoChip(
                                Icons.checkroom,
                                _product!.tipoPrenda,
                              ),
                              const SizedBox(width: 8),
                              _buildInfoChip(
                                Icons.person,
                                _product!.genero,
                              ),
                            ],
                          ),
                          const SizedBox(height: 24),
                          // Variantes
                          if (_product!.variantes.isNotEmpty) ...[
                            const Text(
                              'Variantes Disponibles',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 12),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: _product!.variantes.map((variant) {
                                final isSelected = _selectedVariant?.idVariante == variant.idVariante;
                                return InkWell(
                                  onTap: () => _onVariantSelected(variant),
                                  child: Container(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 12,
                                      vertical: 8,
                                    ),
                                    decoration: BoxDecoration(
                                      color: isSelected ? AppColors.accent : AppColors.white,
                                      border: Border.all(
                                        color: isSelected ? AppColors.accent : AppColors.greyLight,
                                      ),
                                      borderRadius: BorderRadius.circular(8),
                                    ),
                                    child: Row(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Container(
                                          width: 16,
                                          height: 16,
                                          decoration: BoxDecoration(
                                            color: ui.Color(
                                              variant.color?.colorValue ?? 0xFF808080,
                                            ),
                                            shape: BoxShape.circle,
                                            border: Border.all(
                                              color: AppColors.grey,
                                            ),
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        Text(
                                          '${variant.talla?.nombre} - ${variant.color?.nombre}',
                                          style: TextStyle(
                                            color: isSelected ? AppColors.white : AppColors.dark,
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        Text(
                                          'Bs ${variant.precio.toStringAsFixed(2)}',
                                          style: TextStyle(
                                            fontWeight: FontWeight.w600,
                                            color: isSelected ? AppColors.white : AppColors.accent,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                );
                              }).toList(),
                            ),
                          ],
                          // CU17 - Botón del Vestidor Virtual
                          if (_selectedVariant != null) ...[
                            const SizedBox(height: 16),
                            OutlinedButton.icon(
                              onPressed: () {
                                Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                    builder: (context) => ArTryOnScreen(
                                      productoId: _product!.idProducto,
                                      overlayImageUrl: _selectedVariant!.imagenVariante ??
                                          _product!.imagenProducto,
                                      nombreProducto: _product!.nombre,
                                      // NUEVO (vestidor): la talla elegida ajusta el tamaño de la prenda.
                                      talla: _selectedVariant!.talla?.nombre,
                                    ),
                                  ),
                                );
                              },
                              icon: const Icon(Icons.camera_alt),
                              label: const Text('Probar en Vestidor Virtual (AR)'),
                            ),
                          ],
                          // CU08 - Disponibilidad por Sucursal
                          if (_selectedVariant != null) ...[
                            const SizedBox(height: 24),
                            const Text(
                              'Disponibilidad por Sucursal',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 12),
                            if (_fechaStockCopia != null)
                              _aviso(
                                'Sin conexión: estás viendo información guardada en este dispositivo el '
                                '${fmt.format(_fechaStockCopia!.toLocal())}. '
                                'Precios y disponibilidad pueden estar desactualizados.',
                              ),
                            if (_loadingStock)
                              const Center(child: CircularProgressIndicator())
                            else if (_stockPorSucursal.isEmpty)
                              const Text(
                                'No hay stock registrado en ninguna sucursal para esta variante.',
                                style: TextStyle(
                                  color: AppColors.grey,
                                  fontStyle: FontStyle.italic,
                                ),
                              )
                            else
                              Column(
                                children: _stockPorSucursal.map((stock) {
                                  final bool disponible = stock['disponible'] == true;
                                  return Padding(
                                    padding: const EdgeInsets.only(bottom: 8),
                                    child: Row(
                                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                      children: [
                                        Expanded(
                                          child: Column(
                                            crossAxisAlignment: CrossAxisAlignment.start,
                                            children: [
                                              Text(
                                                stock['sucursal_nombre']?.toString() ?? '',
                                                style: const TextStyle(fontWeight: FontWeight.w600),
                                              ),
                                              Text(
                                                stock['ciudad']?.toString() ?? '',
                                                style: const TextStyle(
                                                  fontSize: 12,
                                                  color: AppColors.grey,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                        Text(
                                          '${stock['cantidad']} und.',
                                          style: const TextStyle(fontWeight: FontWeight.w600),
                                        ),
                                        const SizedBox(width: 12),
                                        Container(
                                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                          decoration: BoxDecoration(
                                            color: disponible
                                                ? AppColors.success.withOpacity(0.15)
                                                : AppColors.danger.withOpacity(0.15),
                                            borderRadius: BorderRadius.circular(4),
                                          ),
                                          child: Text(
                                            disponible ? 'Disponible' : 'Agotado',
                                            style: TextStyle(
                                              color: disponible ? AppColors.success : AppColors.danger,
                                              fontWeight: FontWeight.w600,
                                              fontSize: 12,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  );
                                }).toList(),
                              ),
                          ],
                          const SizedBox(height: 24),
                          // Precio
                          if (_selectedVariant != null) ...[
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                const Text(
                                  'Precio:',
                                  style: TextStyle(
                                    fontSize: 16,
                                    color: AppColors.grey,
                                  ),
                                ),
                                Text(
                                  'Bs ${_selectedVariant!.precio.toStringAsFixed(2)}',
                                  style: const TextStyle(
                                    fontSize: 24,
                                    fontWeight: FontWeight.bold,
                                    color: AppColors.accent,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Text(
                              _selectedVariant!.cantidad > 0
                                  ? '${_selectedVariant!.cantidad} unidades disponibles'
                                  : 'Agotado',
                              style: TextStyle(
                                color: _selectedVariant!.cantidad > 0 ? AppColors.success : AppColors.danger,
                              ),
                            ),
                            const SizedBox(height: 16),
                            ElevatedButton(
                              onPressed: (_selectedVariant!.cantidad > 0 && !_addingToCart)
                                  ? _agregarAlCarrito
                                  : null,
                              style: ElevatedButton.styleFrom(
                                minimumSize: const ui.Size(double.infinity, 50),
                              ),
                              child: Text(_addingToCart ? 'Agregando...' : 'Agregar al Carrito'),
                            ),
                            if (_cartMessage.isNotEmpty) ...[
                              const SizedBox(height: 8),
                              Text(
                                _cartMessage,
                                style: TextStyle(
                                  color: _cartError ? AppColors.danger : AppColors.success,
                                ),
                              ),
                            ],
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }

  Widget _buildInfoChip(IconData icon, String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.greyLight,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: AppColors.grey),
          const SizedBox(width: 4),
          Text(
            text,
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.dark,
            ),
          ),
        ],
      ),
    );
  }
}