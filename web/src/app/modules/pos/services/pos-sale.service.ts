// web/src/app/modules/pos/services/pos-sale.service.ts
//
// MODIFICADO (Fase 2 - CU08): cliente opcional en la venta en línea e
// historial / resolución de las operaciones hechas sin conexión.
// MODIFICADO (Fase 2 - reservas con anticipo): las prendas de una reserva
// confirmada se cobran con "id_reserva_item" (solo el saldo) y se listan las
// reservas confirmadas de la sucursal para retirarlas en caja.
// MODIFICADO (Fase 3 - CU18): aplicar_fidelidad=true pide aplicar el descuento
// por fidelidad del cliente (solo el POS web en línea lo envía).

import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';

export type AccionConflicto = 'CONFIRMAR' | 'DEVOLVER';

// Línea de la venta: prenda normal (id_variante) o prenda de una reserva (id_reserva_item).
export interface ItemPayload {
  id_variante?: number;
  id_reserva_item?: number;
  cantidad: number;
}

@Injectable({
  providedIn: 'root'
})
export class PosSaleService {
  constructor(private apiService: ApiService) {}

  registrarVenta(
    idSucursal: number,
    metodoPago: string,
    items: ItemPayload[],
    correoCliente: string | null = null,
    aplicarFidelidad = false
  ): Observable<any> {
    return this.apiService.post('/sales/ventas-pos/registrar/', {
      id_sucursal: idSucursal,
      metodo_pago: metodoPago,
      items,
      correo_cliente: correoCliente || undefined,
      aplicar_fidelidad: aplicarFidelidad || undefined,
    });
  }

  // NUEVO (Fase 2): reservas pagadas (confirmadas) de la sucursal, listas para retirar.
  // Al listar, el backend también vence las reservas cuyo plazo pasó.
  reservasPorRetirar(idSucursal: number): Observable<any> {
    return this.apiService.get('/reservations/reservas/', {
      estado: 'CONFIRMADA', sucursal: idSucursal, page_size: 100
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