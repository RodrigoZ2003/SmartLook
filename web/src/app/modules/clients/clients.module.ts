// web/src/app/modules/clients/clients.module.ts
//
// Archivo NUEVO. Incluye FormsModule por el buscador con [(ngModel)].
// MODIFICADO (Fase 3 - CU18): pantalla Clientes > Fidelidad.

import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ClientsRoutingModule } from './clients-routing.module';
import { ClientListComponent } from './pages/client-list/client-list.component';
import { FidelidadHomeComponent } from './pages/fidelidad-home/fidelidad-home.component';

@NgModule({
  declarations: [
    ClientListComponent,
    FidelidadHomeComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    ClientsRoutingModule
  ]
})
export class ClientsModule { }