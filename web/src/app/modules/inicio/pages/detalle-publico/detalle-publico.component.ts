// web/src/app/modules/inicio/pages/detalle-publico/detalle-publico.component.ts
//
// NUEVO (Fase 3): detalle público de una prenda (/producto/:id), sin menú
// lateral. Muestra lo mismo que el detalle del cliente (datos, variantes con
// talla, color y precio, y disponibilidad por sucursal); en lugar de
// "Agregar al carrito" hay un botón que lleva al login.
// Si el backend está despertando se sigue mostrando "Cargando..." y se
// reintenta cada 5 s (hasta ~1 minuto). Si ya hay sesión iniciada, se abre el
// detalle de siempre (/catalog/:id).
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../../../core/auth/auth.service';
import { Product } from '../../../../core/models/product.interface';
import { StockItem } from '../../../../core/models/inventory.interface';
import { CatalogService } from '../../../catalog/services/catalog.service';
import { InventoryService } from '../../../inventory/services/inventory.service';

const MAX_INTENTOS = 12;
const ESPERA_REINTENTO_MS = 5000;

@Component({
  selector: 'app-detalle-publico',
  templateUrl: './detalle-publico.component.html',
  styleUrls: ['./detalle-publico.component.scss']
})
export class DetallePublicoComponent implements OnInit, OnDestroy {
  producto: Product | null = null;
  varianteElegida: any = null;
  stockPorSucursal: StockItem[] = [];
  cargando = true;
  cargandoStock = false;
  error = false;

  private idProducto = 0;
  private intentos = 0;
  private reintento: ReturnType<typeof setTimeout> | null = null;
  private peticion?: Subscription;
  private peticionStock?: Subscription;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private authService: AuthService,
    private catalogService: CatalogService,
    private inventoryService: InventoryService
  ) {}

  ngOnInit(): void {
    this.idProducto = Number(this.route.snapshot.paramMap.get('id'));
    if (this.authService.estaAutenticado()) {
      this.router.navigate(['/catalog', this.idProducto], { replaceUrl: true });
      return;
    }
    this.cargar();
  }

  ngOnDestroy(): void {
    this.cancelar();
    this.peticionStock?.unsubscribe();
  }

  /** Vuelve a intentar después de un error. */
  reintentar(): void {
    this.intentos = 0;
    this.cargar();
  }

  /** Elige una talla/color y consulta su disponibilidad por sucursal. */
  elegirVariante(variante: any): void {
    this.varianteElegida = variante;
    this.peticionStock?.unsubscribe();
    this.cargandoStock = true;
    this.stockPorSucursal = [];
    this.peticionStock = this.inventoryService.getStockItems(variante.id_variante).subscribe({
      next: (data: any) => {
        this.stockPorSucursal = data?.results || data || [];
        this.cargandoStock = false;
      },
      error: () => {
        this.stockPorSucursal = [];
        this.cargandoStock = false;
      }
    });
  }

  /** Pide la prenda; si falla, reintenta sin dejar de mostrar "Cargando...". */
  private cargar(): void {
    this.cancelar();
    this.cargando = true;
    this.error = false;
    this.peticion = this.catalogService.getProduct(this.idProducto).subscribe({
      next: (data: any) => {
        this.producto = data;
        this.cargando = false;
        this.intentos = 0;
        if (data?.variantes?.length) {
          this.elegirVariante(data.variantes[0]);
        }
      },
      error: (err) => {
        this.intentos++;
        // 404: la prenda no existe o no está activa; no tiene sentido reintentar.
        if (err?.status !== 404 && this.intentos < MAX_INTENTOS) {
          this.reintento = setTimeout(() => this.cargar(), ESPERA_REINTENTO_MS);
          return;
        }
        this.producto = null;
        this.cargando = false;
        this.error = true;
      }
    });
  }

  /** Cancela la petición y el reintento pendientes. */
  private cancelar(): void {
    this.peticion?.unsubscribe();
    if (this.reintento) {
      clearTimeout(this.reintento);
      this.reintento = null;
    }
  }
}