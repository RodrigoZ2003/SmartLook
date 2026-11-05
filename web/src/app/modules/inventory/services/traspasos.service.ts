// web/src/app/modules/inventory/services/traspasos.service.ts
//
// NUEVO (Fase 3 - CU07): traspasos de prendas entre sucursales.
//   GET  /api/inventory/traspasos/                 lista visible para el usuario
//   POST /api/inventory/traspasos/                 solicitar
//   GET  /api/inventory/traspasos/:id/             detalle
//   POST /api/inventory/traspasos/:id/aprobar|rechazar|recibir|cancelar/
//   GET  /api/inventory/traspasos/opciones/        sucursales y rol
//   GET  /api/inventory/traspasos/stock/?sucursal= prendas con stock
//   GET  /api/inventory/traspasos/sugerencias/     sugerencias de la Analítica
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';

export type EstadoTraspaso = 'SOLICITADO' | 'EN_TRANSITO' | 'RECIBIDO' | 'RECHAZADO' | 'CANCELADO';
export type AccionTraspaso = 'aprobar' | 'rechazar' | 'recibir' | 'cancelar';

export interface SucursalOpcion {
  id: number;
  nombre: string;
  id_empresa: number;
  empresa: string;
}

export interface OpcionesTraspaso {
  super_admin: boolean;
  puede_aprobar: boolean;
  encargado: boolean;
  destino_fijo: number | null;
  sucursales: SucursalOpcion[];
}

export interface StockPrenda {
  id_variante: number;
  id_producto: number;
  prenda: string;
  talla: string;
  color: string;
  codigo: string | null;
  stock: number;
}

export interface DetalleTraspaso {
  id_variante: number;
  prenda: string;
  talla: string;
  color: string;
  codigo: string | null;
  cantidad: number;
  stock_origen: number;
}

export interface Traspaso {
  id: number;
  estado: EstadoTraspaso;
  estado_display: string;
  empresa: { id: number; nombre: string };
  origen: { id: number; nombre: string };
  destino: { id: number; nombre: string };
  observacion: string | null;
  desde_sugerencia: boolean;
  motivo_rechazo: string | null;
  solicitado_por: string;
  fecha_solicitud: string | null;
  aprobado_por: string;
  fecha_aprobacion: string | null;
  rechazado_por: string;
  fecha_rechazo: string | null;
  recibido_por: string;
  fecha_recepcion: string | null;
  cancelado_por: string;
  fecha_cancelacion: string | null;
  acciones: Record<AccionTraspaso, boolean>;
  prendas: number;
  unidades: number;
  detalles?: DetalleTraspaso[];
}

export interface LineaTraspaso {
  id_variante: number;
  cantidad: number;
}

export interface NuevoTraspaso {
  id_sucursal_origen: number;
  id_sucursal_destino: number;
  observacion: string;
  desde_sugerencia: boolean;
  lineas: LineaTraspaso[];
}

export interface VarianteSugerida {
  id_variante: number;
  talla: string;
  color: string;
  stock_origen: number;
}

export interface SugerenciaTraspaso {
  id_producto: number;
  producto: string;
  id_sucursal_origen: number;
  sucursal_origen: string;
  id_sucursal_destino: number;
  sucursal_destino: string;
  demanda_prevista: number;
  stock_destino: number;
  stock_origen: number;
  cantidad_sugerida: number;
  variantes: VarianteSugerida[];
}

@Injectable({
  providedIn: 'root'
})
export class TraspasosService {
  private apiUrl = `${environment.apiUrl}/inventory/traspasos`;

  constructor(private http: HttpClient) {}

  listar(): Observable<Traspaso[]> {
    return this.http.get<Traspaso[]>(`${this.apiUrl}/`);
  }

  detalle(id: number): Observable<Traspaso> {
    return this.http.get<Traspaso>(`${this.apiUrl}/${id}/`);
  }

  crear(datos: NuevoTraspaso): Observable<Traspaso> {
    return this.http.post<Traspaso>(`${this.apiUrl}/`, datos);
  }

  ejecutar(id: number, accion: AccionTraspaso, motivo?: string): Observable<Traspaso> {
    return this.http.post<Traspaso>(`${this.apiUrl}/${id}/${accion}/`, motivo ? { motivo } : {});
  }

  opciones(): Observable<OpcionesTraspaso> {
    return this.http.get<OpcionesTraspaso>(`${this.apiUrl}/opciones/`);
  }

  stock(sucursal: number): Observable<StockPrenda[]> {
    return this.http.get<StockPrenda[]>(`${this.apiUrl}/stock/`, {
      params: new HttpParams().set('sucursal', String(sucursal))
    });
  }

  sugerencias(empresa: number | null): Observable<{ sugerencias: SugerenciaTraspaso[] }> {
    let params = new HttpParams();
    if (empresa) {
      params = params.set('empresa', String(empresa));
    }
    return this.http.get<{ sugerencias: SugerenciaTraspaso[] }>(`${this.apiUrl}/sugerencias/`, { params });
  }
}