// mobile/lib/shared/widgets/product_card.dart
//
// MODIFICADO (SaaS - A.1): muestra "Vendido por <empresa>" en el catálogo
// unificado.
// MODIFICADO: la foto se ve completa (contain sobre fondo blanco, sin
// recortar la prenda) y el precio va en una sola línea ("Bs 100.00 – 176.00")
// que se achica si no entra, para que el texto no le quite alto a la foto.
import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import '../../core/models/product_model.dart';
import '../theme/app_colors.dart';

class ProductCard extends StatelessWidget {
  final Product product;
  final VoidCallback? onTap;

  const ProductCard({
    super.key,
    required this.product,
    this.onTap,
  });

  String getPriceRange() {
    if (product.variantes.isEmpty) return 'Sin precio';
    final prices = product.variantes.map((v) => v.precio).toList();
    final min = prices.reduce((a, b) => a < b ? a : b);
    final max = prices.reduce((a, b) => a > b ? a : b);
    if (min == max) return 'Bs ${min.toStringAsFixed(2)}';
    return 'Bs ${min.toStringAsFixed(2)} – ${max.toStringAsFixed(2)}';
  }

  Widget _sinImagen(IconData icono) {
    return Container(
      color: AppColors.greyLight,
      child: Center(child: Icon(icono, size: 48, color: AppColors.grey)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final empresa = product.empresaNombre ?? '';
    final categoria = product.categoria?.nombre ?? '';
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // La imagen ocupa el espacio que sobra después del texto,
            // así nunca desborda sin importar el childAspectRatio del grid.
            Expanded(
              child: Container(
                width: double.infinity,
                color: Colors.white,
                padding: const EdgeInsets.all(6),
                child: product.imagenProducto != null
                    ? CachedNetworkImage(
                        imageUrl: product.imagenProducto!,
                        fit: BoxFit.contain,
                        placeholder: (context, url) => const Center(
                          child: SizedBox(
                            width: 24,
                            height: 24,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                        ),
                        errorWidget: (context, url, error) => _sinImagen(Icons.image_not_supported),
                      )
                    : _sinImagen(Icons.shopping_bag),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    product.marca?.nombre ?? 'SmartLook',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 10,
                      color: AppColors.grey,
                      letterSpacing: 1,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    product.nombre,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.dark,
                    ),
                  ),
                  if (categoria.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      categoria,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12, color: AppColors.grey),
                    ),
                  ],
                  // NUEVO (SaaS - A.1): tienda que vende la prenda.
                  if (empresa.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        const Icon(Icons.storefront, size: 12, color: AppColors.grey),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            empresa,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 11, color: AppColors.dark),
                          ),
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 6),
                  // Una sola línea: si el rango no entra, se achica en vez de saltar de línea.
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(
                      getPriceRange(),
                      maxLines: 1,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: AppColors.accent,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}