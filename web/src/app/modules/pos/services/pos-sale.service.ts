// web/src/app/modules/pos/services/pos-sale.service.ts
//
// MODIFICADO (Fase 2 - CU08): cliente opcional en la venta en línea e
// historial / resolución de las operaciones hechas sin conexión.

import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';

export type AccionConflicto = 'CONFIRMAR' | 'DEVOLVER';

@Injectable({
  providedIn: 'root'
})
export class PosSaleService {
  constructor(private apiService: ApiService) {}

  registrarVenta(
    idSucursal: number,
    metodoPago: string,
    items: { id_variante: number; cantidad: number }[],
    correoCliente: string | null = null
  ): Observable<any> {
    return this.apiService.post('/sales/ventas-pos/registrar/', {
      id_sucursal: idSucursal,
      metodo_pago: metodoPago,
      items,
      correo_cliente: correoCliente || undefined,
    });
  }

  // Historial de operaciones sin conexión (paginado, con filtros).
  listarOperaciones(filtros: { [clave: string]: any }): Observable<any> {
    return this.apiService.get('/sales/sync/', filtros);
  }

  // Cantidades por estado y conflictos pendientes de resolver.
  resumenOperaciones(empresa: string | null = null): Observable<any> {
    return this.apiService.get('/sales/sync/resumen/', { empresa });
  }

  // Confirma la venta en conflicto o devuelve el efectivo (con nota).
  resolverOperacion(idOperacion: number, accion: AccionConflicto, nota: string | null): Observable<any> {
    return this.apiService.post(`/sales/sync/${idOperacion}/resolver/`, { accion, nota });
  }

  // Empresas (solo SUPER_ADMIN las necesita para filtrar).
  listarEmpresas(): Observable<any> {
    return this.apiService.get('/auth/empresas/', { page_size: 100 });
  }

  // Sucursales visibles para el usuario (el SUPER_ADMIN puede filtrar por empresa).
  listarSucursales(empresa: string | null = null): Observable<any> {
    return this.apiService.get('/catalog/sucursales/', { page_size: 100, empresa });
  }
}