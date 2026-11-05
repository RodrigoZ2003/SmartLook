// web/src/app/modules/assistant-admin/assistant-admin-routing.module.ts
//
// MODIFICADO (Fase 3 - CU13): ruta 'reportes' (reportes convencionales sin
// IA, disponibles en los tres planes).
// MODIFICADO (Fase 3 - CU09): ruta 'analitica' (Machine Learning; el backend
// solo la permite a SUPER_ADMIN y ADMIN_EMPRESA con plan que incluya IA).
import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AssistantAdminHomeComponent } from './pages/assistant-admin-home/assistant-admin-home.component';
import { ReportesHomeComponent } from './pages/reportes-home/reportes-home.component';
import { AnaliticaHomeComponent } from './pages/analitica-home/analitica-home.component';

const routes: Routes = [
  {
    path: '',
    component: AssistantAdminHomeComponent
  },
  {
    path: 'reportes',
    component: ReportesHomeComponent
  },
  {
    path: 'analitica',
    component: AnaliticaHomeComponent
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AssistantAdminRoutingModule {}