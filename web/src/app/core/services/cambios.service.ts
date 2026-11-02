// web/src/app/core/services/cambios.service.ts
//
// NUEVO (Fase 2 - CU05 / CU06): cambio de prenda por talla o color.
// Lo usan el personal (Punto de Venta > Cambios de prenda), el cliente
// (Mis pedidos) y el repartidor (Entregas > Cambios).
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export type MotivoCambio = 'ERROR_TIENDA' | 'NO_LE_QUEDA';

@Injectable({
  providedIn: 'root'
})
export class CambiosService {
  constructor(private api: ApiService) {}

  // Lista de cambios visibles para el usuario (filtros: estado, modalidad, motivo, sucursal, mes, pendientes).
  listar(filtros: { [clave: string]: any } = {}): Observable<any> {
    return this.api.get('/sales/cambios/', filtros);
  }

  // CU06: totales de los cambios del mes (AAAA-MM).
  resumenMes(mes: string, sucursal: number | null = null): Observable<any> {
    return this.api.get('/sales/cambios/resumen-mes/', { mes, sucursal });
  }

  // Prendas de una venta POS o de un pedido de la empresa (personal).
  buscarCompra(tipo: 'VENTA' | 'PEDIDO', numero: number): Observable<any> {
    return this.api.get('/sales/cambios/buscar-compra/', { tipo, numero });
  }

  // Tallas/colores disponibles para cambiar una prenda.
  opciones(item: { id_venta_item?: number | null; id_orden_item?: number | null }): Observable<any> {
    return this.api.get('/sales/cambios/opciones/', item);
  }

  // El cliente solicita el cambio de una prenda de su pedido con delivery.
  solicitar(datos: {
    id_orden_item: number; motivo: MotivoCambio; id_variante: number; cantidad: number; observacion?: string;
  }): Observable<any> {
    return this.api.post('/sales/cambios/solicitar/', datos);
  }

  // El personal registra y completa un cambio en la tienda.
  registrarTienda(datos: {
    id_venta_item?: number | null; id_orden_item?: number | null; motivo: MotivoCambio;
    id_variante: number; cantidad: number; condiciones_ok: boolean; observacion?: string;
  }): Observable<any> {
    return this.api.post('/sales/cambios/registrar-tienda/', datos);
  }

  aprobar(idCambio: number, idRepartidor: number, fechaProgramada: string): Observable<any> {
    return this.api.post(`/sales/cambios/${idCambio}/aprobar/`, {
      id_repartidor: idRepartidor,
      fecha_programada: fechaProgramada
    });
  }

  rechazar(idCambio: number, motivo: string): Observable<any> {
    return this.api.post(`/sales/cambios/${idCambio}/rechazar/`, { motivo });
  }

  enCamino(idCambio: number): Observable<any> {
    return this.api.post(`/sales/cambios/${idCambio}/en-camino/`, {});
  }

  completar(idCambio: number, condicionesOk: boolean): Observable<any> {
    return this.api.post(`/sales/cambios/${idCambio}/completar/`, { condiciones_ok: condicionesOk });
  }

  // Repartidores activos de la empresa (para asignar la visita).
  repartidores(): Observable<any> {
    return this.api.get('/sales/entregas/repartidores/');
  }
}