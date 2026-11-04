// MODIFICADO: rango de precio más corto ("Bs 120.00 – 136.00"), igual que en el móvil.
import { Component, Input } from '@angular/core';
import { Router } from '@angular/router';
import { Product } from '../../../core/models/product.interface';

@Component({
  selector: 'app-product-card',
  templateUrl: './product-card.component.html',
  styleUrls: ['./product-card.component.scss']
})
export class ProductCardComponent {
  @Input() product!: Product;

  constructor(private router: Router) {}

  getPriceRange(): string {
    if (!this.product.variantes || this.product.variantes.length === 0) {
      return 'Sin precio';
    }
    const prices = this.product.variantes.map(v => Number(v.precio));
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    return min === max ? `Bs ${min.toFixed(2)}` : `Bs ${min.toFixed(2)} – ${max.toFixed(2)}`;
  }

  verDetalle(): void {
    this.router.navigate(['/catalog', this.product.id_producto]);
  }
}