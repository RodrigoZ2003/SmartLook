// web/src/app/modules/orders/pages/mis-pedidos/mis-pedidos.component.ts
//
// NUEVO (Fase 3 - CU18): página "Mis pedidos" = tarjeta del descuento por
// fidelidad + la lista de pedidos de siempre (OrdersPageComponent, sin cambios).
import { Component } from '@angular/core';

@Component({
  selector: 'app-mis-pedidos',
  template: `
    <app-progreso-fidelidad></app-progreso-fidelidad>
    <app-orders-page></app-orders-page>
  `
})
export class MisPedidosComponent {}