// web/src/app/modules/orders/components/progreso-fidelidad/progreso-fidelidad.component.ts
//
// NUEVO (Fase 3 - CU18): tarjeta "Tu descuento por fidelidad" del cliente
// (arriba de Mis pedidos). Muestra, por tienda, cuántas compras lleva en el
// mes, si ya tiene el descuento, si ya lo usó y cuánto le falta.
import { Component, OnInit } from '@angular/core';
import { FidelidadService, ProgresoFidelidad } from '../../../../core/services/fidelidad.service';

@Component({
  selector: 'app-progreso-fidelidad',
  template: `
    <section class="fidelidad" *ngIf="datos && (datos.regla.activa || datos.empresas.length > 0)">
      <h3>Tu descuento por fidelidad</h3>
      <p class="regla" *ngIf="datos.regla.activa">
        Compra {{ datos.regla.compras_requeridas }} veces en una misma tienda este mes y tu siguiente compra
        sin reservas tendrá {{ datos.regla.porcentaje }}% de descuento en las prendas. Se reinicia cada mes.
      </p>
      <p class="regla" *ngIf="!datos.regla.activa">El descuento por fidelidad no está activo en este momento.</p>
      <div class="tienda" *ngFor="let e of datos.empresas" [class.tienda--lista]="e.disponible">
        <div class="tienda-cabecera">
          <strong>{{ e.empresa }}</strong>
          <span>{{ e.compras }} de {{ e.requeridas }} compras</span>
        </div>
        <div class="barra"><div class="relleno" [style.width.%]="avance(e.compras, e.requeridas)"></div></div>
        <p class="mensaje" *ngIf="e.estado === 'DISPONIBLE'">
          ¡Tienes {{ e.porcentaje }}% de descuento en tu próxima compra sin reservas! Válido hasta el {{ datos.vence | date:'dd/MM/yyyy' }}.
        </p>
        <p class="mensaje" *ngIf="e.estado === 'USADO'">
          Usaste tu descuento este mes en {{ e.uso }} (−Bs {{ e.monto_descuento | number:'1.2-2' }}).
        </p>
        <p class="mensaje" *ngIf="e.estado === 'EN_PROGRESO' && datos.regla.activa">
          Te {{ e.faltan === 1 ? 'falta 1 compra' : 'faltan ' + e.faltan + ' compras' }} para ganar el descuento.
        </p>
      </div>
    </section>
  `,
  styles: [`
    .fidelidad {
      max-width: 800px; margin: 0 auto; padding: 2rem 2rem 0; box-sizing: border-box;
    }
    h3 { margin: 0 0 0.35rem; color: #1a1a2e; font-size: 1.1rem; }
    .regla { margin: 0 0 0.75rem; color: #6b6459; font-size: 0.88rem; }
    .tienda {
      background: white; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 0.6rem;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06); border-left: 4px solid #e2e5ec;
    }
    .tienda--lista { border-left-color: #16a085; }
    .tienda-cabecera { display: flex; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; color: #1a1a2e; }
    .tienda-cabecera span { color: #0f3460; font-size: 0.88rem; font-weight: 600; }
    .barra { height: 8px; border-radius: 999px; background: #eef0f4; overflow: hidden; margin: 0.5rem 0 0.35rem; }
    .relleno { height: 100%; border-radius: 999px; background: #16a085; }
    .mensaje { margin: 0; font-size: 0.85rem; color: #1a1a2e; }
    .tienda--lista .mensaje { color: #1e6b3a; font-weight: 600; }
    @media (max-width: 600px) {
      .fidelidad { padding: 1rem 1rem 0; }
    }
  `]
})
export class ProgresoFidelidadComponent implements OnInit {
  datos: ProgresoFidelidad | null = null;

  constructor(private fidelidad: FidelidadService) {}

  ngOnInit(): void {
    this.fidelidad.miProgreso().subscribe({
      next: (datos) => this.datos = datos,
      error: () => this.datos = null
    });
  }

  avance(compras: number, requeridas: number): number {
    return Math.min(100, Math.round((compras / Math.max(requeridas, 1)) * 100));
  }
}