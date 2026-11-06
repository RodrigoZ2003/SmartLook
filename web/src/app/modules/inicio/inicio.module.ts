// web/src/app/modules/inicio/inicio.module.ts
//
// NUEVO (Fase 3): páginas públicas de la raíz del sitio: catálogo con
// buscador y detalle de prenda, con los botones "Iniciar sesión" y
// "Registrarse", sin el menú lateral. No cambia el catálogo del cliente
// (CatalogModule).
import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

import { InicioRoutingModule } from './inicio-routing.module';
import { BarraPublicaComponent } from './components/barra-publica/barra-publica.component';
import { CatalogoPublicoComponent } from './pages/catalogo-publico/catalogo-publico.component';
import { DetallePublicoComponent } from './pages/detalle-publico/detalle-publico.component';
import { SharedModule } from '../../shared/shared.module';

@NgModule({
  declarations: [
    BarraPublicaComponent,
    CatalogoPublicoComponent,
    DetallePublicoComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    SharedModule,
    InicioRoutingModule
  ]
})
export class InicioModule { }