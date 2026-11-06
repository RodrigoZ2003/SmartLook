// web/src/app/modules/inicio/pages/catalogo-publico/catalogo-publico.component.ts
//
// NUEVO (Fase 3): catálogo público de la raíz del sitio.
// - La barra (logo, buscador, Iniciar sesión, Registrarse) se ve al instante
//   porque es parte de la web estática.
// - Los productos vienen del backend. Si el backend está despertando, la
//   petición puede fallar o tardar: se sigue mostrando "Cargando catálogo..."
//   y se reintenta cada 5 s (hasta ~1 minuto) antes de mostrar un error.
// - La búsqueda llega como ?busqueda= (la pone la barra pública).
// - Se piden hasta 100 productos (máximo del backend) para no cortar en 20.
// - "Ver detalle" abre el detalle público (/producto/:id).
// - Si ya hay sesión iniciada, se va directo al panel que le corresponde
//   (igual que después del login).
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../../../core/auth/auth.service';
import { Product } from '../../../../core/models/product.interface';
import { CatalogService } from '../../../catalog/services/catalog.service';

const MAX_INTENTOS = 12;
const ESPERA_REINTENTO_MS = 5000;
const PRODUCTOS_POR_PAGINA = 100;

@Component({
  selector: 'app-catalogo-publico',
  templateUrl: './catalogo-publico.component.html',
  styleUrls: ['./catalogo-publico.component.scss']
})
export class CatalogoPublicoComponent implements OnInit, OnDestroy {
  productos: Product[] = [];
  texto = '';
  cargando = true;
  error = false;

  private intentos = 0;
  private reintento: ReturnType<typeof setTimeout> | null = null;
  private peticion?: Subscription;
  private parametros?: Subscription;

  constructor(
    private catalogService: CatalogService,
    private authService: AuthService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    if (this.authService.estaAutenticado()) {
      this.irAlPanel();
      return;
    }
    // Cada búsqueda (o "Ver todo") cambia ?busqueda= y vuelve a cargar.
    this.parametros = this.route.queryParamMap.subscribe(params => {
      this.texto = (params.get('busqueda') || '').trim();
      this.intentos = 0;
      this.cargar();
    });
  }

  ngOnDestroy(): void {
    this.parametros?.unsubscribe();
    this.cancelar();
  }

  /** Ruta del detalle público de una prenda. */
  rutaDetalle(producto: Product): string {
    return `/producto/${producto.id_producto}`;
  }

  /** Quita la búsqueda y vuelve a mostrar todo el catálogo. */
  verTodo(): void {
    this.router.navigate(['/']);
  }

  /** Vuelve a intentar después de un error. */
  reintentar(): void {
    this.intentos = 0;
    this.cargar();
  }

  /** Pide los productos; si falla, reintenta sin dejar de mostrar "Cargando catálogo...". */
  private cargar(): void {
    this.cancelar();
    this.cargando = true;
    this.error = false;
    const filtros: any = { page_size: PRODUCTOS_POR_PAGINA };
    if (this.texto) {
      filtros.busqueda = this.texto;
    }
    this.peticion = this.catalogService.getProducts(filtros).subscribe({
      next: (data: any) => {
        this.productos = data?.results || data || [];
        this.cargando = false;
        this.intentos = 0;
      },
      error: () => {
        this.intentos++;
        if (this.intentos < MAX_INTENTOS) {
          this.reintento = setTimeout(() => this.cargar(), ESPERA_REINTENTO_MS);
          return;
        }
        this.productos = [];
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

  /** Mismo destino que después del login: cliente al catálogo, personal al panel. */
  private irAlPanel(): void {
    if (this.authService.esCliente()) {
      this.router.navigate(['/catalog'], { replaceUrl: true });
      return;
    }
    const roles = this.authService.obtenerRoles();
    const esSoloRepartidor = roles.includes('REPARTIDOR') && !roles.some(
      r => ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL', 'CAJERO'].includes(r)
    );
    this.router.navigate([esSoloRepartidor ? '/deliveries' : '/dashboard'], { replaceUrl: true });
  }
}