// web/src/app/modules/inventory/inventory.module.ts
//
// MODIFICADO (Fase 3 - CU07): pantalla de traspasos entre sucursales
// (/inventory/traspasos). SharedModule aporta app-loading-spinner y los
// módulos de formularios (FormsModule para ngModel y ReactiveFormsModule).
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { SharedModule } from '../../shared/shared.module';
import { InventoryRoutingModule } from './inventory-routing.module';
import { StockListComponent } from './pages/stock-list/stock-list.component';
import { MovementHistoryComponent } from './pages/movement-history/movement-history.component';
import { TraspasosHomeComponent } from './pages/traspasos-home/traspasos-home.component';

@NgModule({
  declarations: [
    StockListComponent,
    MovementHistoryComponent,
    TraspasosHomeComponent
  ],
  imports: [
    CommonModule,
    SharedModule,
    InventoryRoutingModule
  ]
})
export class InventoryModule { }