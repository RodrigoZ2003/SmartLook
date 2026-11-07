// web/src/app/modules/products/services/product.service.ts
//
// Archivo YA EXISTENTE. Se agrega CRUD de variantes (Paso C).
// getProductos/crearProducto/actualizarProducto/eliminarProducto
// quedan igual.
// MODIFICADO (corrección listas incompletas): getProductos() lee todas las
// páginas de la API (antes solo la primera, 20 productos).

import { Injectable } from '@angular/core';
import { EMPTY, Observable } from 'rxjs';
import { expand, map, reduce } from 'rxjs/operators';
import { ApiService } from '../../../core/services/api.service';

@Injectable({
  providedIn: 'root'
})
export class ProductService {
  constructor(private apiService: ApiService) {}

  getProductos(): Observable<any> {
    const pedir = (pagina: number) =>
      this.apiService.get<any>('/catalog/productos/', { page_size: 100, page: pagina });
    return pedir(1).pipe(
      expand((respuesta, indice) => (respuesta?.next ? pedir(indice + 2) : EMPTY)),
      map(respuesta => (respuesta?.results ?? respuesta ?? []) as any[]),
      reduce((todos, pagina) => todos.concat(pagina), [] as any[])
    );
  }

  crearProducto(data: any): Observable<any> {
    return this.apiService.post('/catalog/productos/', data);
  }

  actualizarProducto(id: number, data: any): Observable<any> {
    return this.apiService.patch(`/catalog/productos/${id}/`, data);
  }

  eliminarProducto(id: number): Observable<any> {
    return this.apiService.delete(`/catalog/productos/${id}/`);
  }

  crearVariante(data: any): Observable<any> {
    return this.apiService.post('/catalog/variantes/', data);
  }

  actualizarVariante(id: number, data: any): Observable<any> {
    return this.apiService.patch(`/catalog/variantes/${id}/`, data);
  }

  eliminarVariante(id: number): Observable<any> {
    return this.apiService.delete(`/catalog/variantes/${id}/`);
  }
}