// web/src/app/modules/assistant-admin/services/analitica.service.ts
//
// NUEVO (Fase 3 - CU09): consume la API de Analítica con Machine Learning.
//   GET  /api/analytics/dashboard/?empresa=<id>
//   POST /api/analytics/reentrenar/   { empresa: <id> | 'todas' }
//   GET  /api/analytics/exportar/?empresa=<id>&reporte=..&formato=..  (blob)
// Solo SUPER_ADMIN y ADMIN_EMPRESA con plan que incluya IA. Para el
// ADMIN_EMPRESA el backend ignora "empresa" y usa la suya.
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { FormatoReporte, HttpEventBlobResponse } from './assistant-admin.service';

export type ReporteAnalitica = 'demanda' | 'segmentos' | 'modelos';
export type Segmento = 'VIP' | 'LEAL' | 'OCASIONAL' | 'RIESGO';

export interface ImportanciaVariable {
  variable: string;
  importancia: number;
}

export interface PuntoPrueba {
  semana: string;
  real: number;
  predicho: number;
}

export interface VentanaDemanda {
  id: number;
  ventana_meses: number;
  vigente: boolean;
  fecha: string;
  desde: string | null;
  hasta: string | null;
  filas_entrenamiento: number;
  filas_prueba: number;
  mae: number | null;
  rmse: number | null;
  r2: number | null;
  mae_linea_base: number | null;
  aviso: string | null;
  importancias: ImportanciaVariable[];
  serie_prueba: PuntoPrueba[];
}

export interface FilaPrediccion {
  sucursal: string;
  prenda: string;
  unidades: number[];
  total: number;
}

export interface ResumenSegmento {
  segmento: Segmento;
  nombre: string;
  descripcion: string;
  clientes: number;
  recencia_media: number;
  frecuencia_media: number;
  monto_medio: number;
}

export interface ClienteSegmento {
  cliente: string;
  correo: string;
  segmento: Segmento;
  nombre_segmento: string;
  recencia_dias: number;
  frecuencia: number;
  monto: number;
}

export interface Segmentacion {
  id: number;
  fecha: string;
  vigente: boolean;
  desde: string | null;
  hasta: string | null;
  clientes_total: number;
  k: number | null;
  silhouette: Record<string, number>;
  inercia: Record<string, number>;
  silhouette_k: number | null;
  resumen: ResumenSegmento[];
  aviso: string | null;
  clientes: ClienteSegmento[];
}

export interface EmpresaAnalitica {
  id: number;
  nombre: string;
}

export interface DashboardAnalitica {
  empresa: EmpresaAnalitica;
  empresas: EmpresaAnalitica[];
  super_admin: boolean;
  demanda: {
    ventanas: VentanaDemanda[];
    vigente: VentanaDemanda | null;
    predicciones: { semanas: string[]; filas: FilaPrediccion[] };
  };
  segmentacion: Segmentacion | null;
}

export interface ResultadoReentreno {
  empresa: string;
  corrida: string;
  predicciones: number;
}

@Injectable({
  providedIn: 'root'
})
export class AnaliticaService {
  private apiUrl = `${environment.apiUrl}/analytics`;

  constructor(private http: HttpClient) {}

  dashboard(empresa?: number | null): Observable<DashboardAnalitica> {
    let params = new HttpParams();
    if (empresa) {
      params = params.set('empresa', String(empresa));
    }
    return this.http.get<DashboardAnalitica>(`${this.apiUrl}/dashboard/`, { params });
  }

  reentrenar(empresa: number | 'todas' | null): Observable<{ resultados: ResultadoReentreno[] }> {
    return this.http.post<{ resultados: ResultadoReentreno[] }>(`${this.apiUrl}/reentrenar/`, { empresa });
  }

  exportar(empresa: number | null, reporte: ReporteAnalitica, formato: FormatoReporte): Observable<HttpEventBlobResponse> {
    let params = new HttpParams().set('reporte', reporte).set('formato', formato);
    if (empresa) {
      params = params.set('empresa', String(empresa));
    }
    return this.http.get(`${this.apiUrl}/exportar/`, { params, observe: 'response', responseType: 'blob' });
  }
}