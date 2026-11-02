// web/src/app/modules/pos/pos.module.ts
//
// MODIFICADO (Fase 2 - CU08): se declara SyncOperacionesComponent.
// MODIFICADO (Fase 2 - CU05 / CU06): se declara CambiosPrendaComponent.
// MODIFICADO (Fase 2 - CU12): se declara DevolucionesTiendaComponent.
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { PosRoutingModule } from './pos-routing.module';
import { PosCartComponent } from './pages/pos-cart/pos-cart.component';
import { SyncOperacionesComponent } from './pages/sync-operaciones/sync-operaciones.component';
import { CambiosPrendaComponent } from './pages/cambios-prenda/cambios-prenda.component';
import { DevolucionesTiendaComponent } from './pages/devoluciones-tienda/devoluciones-tienda.component';

@NgModule({
  declarations: [
    PosCartComponent,
    SyncOperacionesComponent,
    CambiosPrendaComponent,
    DevolucionesTiendaComponent
  ],
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    PosRoutingModule
  ]
})
export class PosModule { }