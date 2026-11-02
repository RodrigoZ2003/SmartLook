// web/src/app/core/services/devoluciones.service.ts
//
// NUEVO (Fase 2 - CU12): devolución de prendas con reembolso y nota de
// devolución. Lo usan el personal (Punto de Venta > Devoluciones), el
// cliente (Mis pedidos) y el repartidor (Entregas > Devoluciones).
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export type MotivoDevolucion = 'PRODUCTO_DANADO' | 'ERROR_TIENDA' | 'NO_LA_QUIERO';
export type TipoCompra = 'VENTA' | 'PEDIDO';

export interface ItemDevolucion {
  id_item: number;
  cantidad: number;
  motivo: MotivoDevolucion;
}

// Textos de los motivos (los mismos del backend).
export const MOTIVOS_DEVOLUCION: { valor: MotivoDevolucion; texto: string; ayuda: string }[] = [
  { valor: 'PRODUCTO_DANADO', texto: 'Llegó dañada o con defecto', ayuda: 'Se devuelve el 100%.' },
  { valor: 'ERROR_TIENDA', texto: 'Le llegó otra prenda', ayuda: 'Se devuelve el 100%.' },
  { valor: 'NO_LA_QUIERO', texto: 'Ya no la quiere / no le gustó', ayuda: 'Se devuelve el 90%: la empresa retiene el 10%.' }
];

@Injectable({
  providedIn: 'root'
})
export class DevolucionesService {
  constructor(private api: ApiService) {}

  // Devoluciones visibles para el usuario (filtros: estado, modalidad, sucursal, mes, pendientes).
  listar(filtros: { [clave: string]: any } = {}): Observable<any> {
    return this.api.get('/sales/devoluciones/', filtros);
  }

  // Prendas de una venta POS o de un pedido con lo que se puede devolver de cada una.
  buscarCompra(tipo: TipoCompra, numero: number): Observable<any> {
    return this.api.get('/sales/devoluciones/buscar-compra/', { tipo, numero });
  }

  // Montos de la devolución sin guardarla (lo pagado, lo retenido y lo que se devuelve).
  calcular(tipo: TipoCompra, numero: number, items: ItemDevolucion[]): Observable<any> {
    return this.api.post('/sales/devoluciones/calcular/', { tipo, numero, items });
  }

  // El cliente solicita la devolución de su pedido con delivery (con recojo).
  solicitar(idOrden: number, items: ItemDevolucion[], observacion?: string): Observable<any> {
    return this.api.post('/sales/devoluciones/solicitar/', { id_orden: idOrden, items, observacion });
  }

  // El personal registra y completa la devolución en la tienda.
  registrarTienda(datos: {
    tipo: TipoCompra; numero: number; items: ItemDevolucion[]; condiciones_ok: boolean; observacion?: string;
  }): Observable<any> {
    return this.api.post('/sales/devoluciones/registrar-tienda/', datos);
  }

  aprobar(idDevolucion: number, idRepartidor: number, fechaProgramada: string): Observable<any> {
    return this.api.post(`/sales/devoluciones/${idDevolucion}/aprobar/`, {
      id_repartidor: idRepartidor,
      fecha_programada: fechaProgramada
    });
  }

  rechazar(idDevolucion: number, motivo: string): Observable<any> {
    return this.api.post(`/sales/devoluciones/${idDevolucion}/rechazar/`, { motivo });
  }

  enCamino(idDevolucion: number): Observable<any> {
    return this.api.post(`/sales/devoluciones/${idDevolucion}/en-camino/`, {});
  }

  completar(idDevolucion: number, condicionesOk: boolean): Observable<any> {
    return this.api.post(`/sales/devoluciones/${idDevolucion}/completar/`, { condiciones_ok: condicionesOk });
  }
}