// web/src/app/modules/clients/clients-routing.module.ts
//
// Archivo NUEVO.
// MODIFICADO (Fase 3 - CU18): ruta /clients/fidelidad.

import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { ClientListComponent } from './pages/client-list/client-list.component';
import { FidelidadHomeComponent } from './pages/fidelidad-home/fidelidad-home.component';

const routes: Routes = [
  { path: '', component: ClientListComponent },
  { path: 'fidelidad', component: FidelidadHomeComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class ClientsRoutingModule { }