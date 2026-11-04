// web/src/app/modules/assistant-admin/assistant-admin.module.ts
//
// NUEVO (CU20): módulo del asistente de gestión, cargado solo por la ruta
// protegida /assistant-admin (ver app-routing.module.ts).
// MODIFICADO (Fase 3 - CU13): se agregan los reportes convencionales sin IA
// (/assistant-admin/reportes) y el componente de gráficos con Chart.js.
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AssistantAdminRoutingModule } from './assistant-admin-routing.module';
import { AssistantAdminHomeComponent } from './pages/assistant-admin-home/assistant-admin-home.component';
import { ReportesHomeComponent } from './pages/reportes-home/reportes-home.component';
import { GraficoReporteComponent } from './components/grafico-reporte/grafico-reporte.component';

@NgModule({
  declarations: [AssistantAdminHomeComponent, ReportesHomeComponent, GraficoReporteComponent],
  imports: [CommonModule, FormsModule, AssistantAdminRoutingModule]
})
export class AssistantAdminModule {}