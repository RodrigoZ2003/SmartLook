// web/src/app/modules/orders/orders.module.ts
// MODIFICADO (Fase 3 - CU18): la ruta muestra MisPedidosComponent, que agrega la
// tarjeta del descuento por fidelidad arriba de la lista de pedidos.
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { OrdersPageComponent } from './pages/orders-page/orders-page.component';
import { MisPedidosComponent } from './pages/mis-pedidos/mis-pedidos.component';
import { ProgresoFidelidadComponent } from './components/progreso-fidelidad/progreso-fidelidad.component';

@NgModule({
  declarations: [
    OrdersPageComponent,
    MisPedidosComponent,
    ProgresoFidelidadComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    RouterModule.forChild([
      { path: '', component: MisPedidosComponent }
    ])
  ]
})
export class OrdersModule { }