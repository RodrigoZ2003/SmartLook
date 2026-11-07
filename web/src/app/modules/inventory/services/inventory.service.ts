// web/src/app/modules/inventory/services/inventory.service.ts
//
// MODIFICADO (corrección listas incompletas): la API devuelve las listas por
// páginas (20 por defecto, 100 como máximo) y antes solo se leía la primera.
// Por eso, al pasar de 50 variantes, las prendas nuevas no aparecían en el
// selector de Inventario. Ahora las listas de sucursales, variantes, stock y
// movimientos se leen completas (todas las páginas).

import { Injectable } from '@angular/core';
import { EMPTY, Observable } from 'rxjs';
import { expand, map, reduce } from 'rxjs/operators';
import { ApiService } from '../../../core/services/api.service';
import { InventoryMovement } from '../../../core/models/inventory.interface';

@Injectable({
  providedIn: 'root'
})
export class InventoryService {
  constructor(private apiService: ApiService) {}

  /**
   * NUEVO: pide todas las páginas de una lista y las devuelve juntas en un
   * solo arreglo. Si la respuesta no viene paginada, la devuelve tal cual.
   */
  private todasLasPaginas(endpoint: string, params: any = {}): Observable<any[]> {
    const pedir = (pagina: number) =>
      this.apiService.get<any>(endpoint, { ...params, page_size: 100, page: pagina });

    return pedir(1).pipe(
      expand((respuesta, indice) => (respuesta?.next ? pedir(indice + 2) : EMPTY)),
      map(respuesta => (respuesta?.results ?? respuesta ?? []) as any[]),
      reduce((todas, pagina) => todas.concat(pagina), [] as any[])
    );
  }

  getStockItems(varianteId?: number): Observable<any> {
    const params: any = {};
    if (varianteId) {
      params.variante = varianteId;
    }
    return this.todasLasPaginas('/inventory/stock/', params);
  }

  getMovements(): Observable<any> {
    return this.todasLasPaginas('/inventory/movimientos/');
  }

  registerMovement(data: any): Observable<InventoryMovement> {
    return this.apiService.post('/inventory/movimientos/registrar/', data);
  }

  getSucursales(): Observable<any> {
    return this.todasLasPaginas('/catalog/sucursales/');
  }

  getVariantes(busqueda?: string): Observable<any> {
    const params: any = {};
    if (busqueda) {
      params.busqueda = busqueda;
    }
    return this.todasLasPaginas('/catalog/variantes/', params);
  }
}