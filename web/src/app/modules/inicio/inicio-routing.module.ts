// web/src/app/modules/inicio/inicio-routing.module.ts
//
// NUEVO (Fase 3): páginas públicas (sin menú lateral):
//   /              catálogo público
//   /producto/:id  detalle público de una prenda
// Cualquier otra ruta no coincide aquí y sigue con las rutas del panel.
import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { CatalogoPublicoComponent } from './pages/catalogo-publico/catalogo-publico.component';
import { DetallePublicoComponent } from './pages/detalle-publico/detalle-publico.component';

const routes: Routes = [
  { path: '', pathMatch: 'full', component: CatalogoPublicoComponent },
  { path: 'producto/:id', component: DetallePublicoComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class InicioRoutingModule { }