// web/src/app/modules/assistant-admin/assistant-admin-routing.module.ts
//
// MODIFICADO (Fase 3 - CU13): ruta 'reportes' (reportes convencionales sin
// IA, disponibles en los tres planes).
import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AssistantAdminHomeComponent } from './pages/assistant-admin-home/assistant-admin-home.component';
import { ReportesHomeComponent } from './pages/reportes-home/reportes-home.component';

const routes: Routes = [
  {
    path: '',
    component: AssistantAdminHomeComponent
  },
  {
    path: 'reportes',
    component: ReportesHomeComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AssistantAdminRoutingModule {}