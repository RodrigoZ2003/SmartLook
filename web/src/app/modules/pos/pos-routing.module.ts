// web/src/app/modules/pos/pos-routing.module.ts
//
// MODIFICADO (Fase 2 - CU08): ruta 'pos/operaciones' (historial y conflictos
// de las ventas sin conexión). El backend limita lo que ve cada rol: el cajero
// solo sus operaciones y sin poder resolverlas.
// MODIFICADO (Fase 2 - CU05 / CU06): ruta 'pos/cambios' (cambio de prenda
// por talla o color y consulta de cambios del mes).
// MODIFICADO (Fase 2 - CU12): ruta 'pos/devoluciones' (devolución con
// reembolso y nota de devolución).
import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { RoleGuard } from '../../core/auth/role.guard';
import { PosCartComponent } from './pages/pos-cart/pos-cart.component';
import { SyncOperacionesComponent } from './pages/sync-operaciones/sync-operaciones.component';
import { CambiosPrendaComponent } from './pages/cambios-prenda/cambios-prenda.component';
import { DevolucionesTiendaComponent } from './pages/devoluciones-tienda/devoluciones-tienda.component';

const routes: Routes = [
  { path: '', component: PosCartComponent },
  {
    path: 'operaciones',
    component: SyncOperacionesComponent,
    canActivate: [RoleGuard],
    data: { rolesExcluidos: ['CLIENTE'] }
  },
  {
    path: 'cambios',
    component: CambiosPrendaComponent,
    canActivate: [RoleGuard],
    data: { rolesExcluidos: ['CLIENTE'] }
  },
  {
    path: 'devoluciones',
    component: DevolucionesTiendaComponent,
    canActivate: [RoleGuard],
    data: { rolesExcluidos: ['CLIENTE'] }
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class PosRoutingModule { }