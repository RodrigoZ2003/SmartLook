// web/src/app/modules/inicio/components/barra-publica/barra-publica.component.ts
//
// NUEVO (Fase 3): barra de las páginas públicas (inicio y detalle de prenda):
// logo, buscador y botones "Iniciar sesión" y "Registrarse". Buscar siempre
// lleva al catálogo público con ?busqueda=, así funciona igual desde el
// detalle.
import { Component, Input, OnChanges } from '@angular/core';
import { FormControl } from '@angular/forms';
import { Router } from '@angular/router';

@Component({
  selector: 'app-barra-publica',
  templateUrl: './barra-publica.component.html',
  styleUrls: ['./barra-publica.component.scss']
})
export class BarraPublicaComponent implements OnChanges {
  /** Texto que se muestra en el buscador (la búsqueda actual del catálogo). */
  @Input() texto = '';

  busqueda = new FormControl('', { nonNullable: true });

  constructor(private router: Router) {}

  ngOnChanges(): void {
    this.busqueda.setValue(this.texto || '');
  }

  /** Abre el catálogo público con la búsqueda (sin texto, muestra todo). */
  buscar(): void {
    const texto = this.busqueda.value.trim();
    this.router.navigate(['/'], { queryParams: texto ? { busqueda: texto } : {} });
  }
}