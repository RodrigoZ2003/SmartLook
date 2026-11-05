// web/src/app/modules/inventory/inventory-routing.module.ts
//
// MODIFICADO (Fase 3 - CU07): ruta 'traspasos' (traspasos entre sucursales).
import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { StockListComponent } from './pages/stock-list/stock-list.component';
import { MovementHistoryComponent } from './pages/movement-history/movement-history.component';
import { TraspasosHomeComponent } from './pages/traspasos-home/traspasos-home.component';

const routes: Routes = [
  { path: 'stock', component: StockListComponent },
  { path: 'movimientos', component: MovementHistoryComponent },
  { path: 'traspasos', component: TraspasosHomeComponent },
  { path: '', redirectTo: 'stock', pathMatch: 'full' }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class InventoryRoutingModule { }