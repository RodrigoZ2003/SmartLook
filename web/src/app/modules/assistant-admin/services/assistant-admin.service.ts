// web/src/app/modules/assistant-admin/services/assistant-admin.service.ts
//
// NUEVO (CU20): consume el asistente de gestión para el personal.
//   POST /api/innovation/asistente/                                  { mensaje }
//   GET  /api/innovation/asistente/reportes/
//   GET  /api/innovation/asistente/reportes/:id/
//   GET  /api/innovation/asistente/reportes/:id/exportar/?formato=..  (blob)
// MODIFICADO (Fase 3 - CU13):
//   - El resultado trae "grafico" (Chart.js) y la respuesta del asistente
//     trae "exportar" (descarga pedida en el chat) y "aclaracion".
//   - Reportes convencionales sin IA (los tres planes):
//     GET  /api/innovation/reportes/opciones/
//     POST /api/innovation/reportes/generar/   { consulta, filtros }
//   - guardarArchivo(): descarga el blob con el nombre real del archivo.
// El token JWT lo agrega el JwtInterceptor global. El backend expone el
// nombre real del archivo en la cabecera Content-Disposition.
import { HttpClient, HttpResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';

export type FormatoReporte = 'pdf' | 'xlsx' | 'html';

export interface KpiResultado {
  etiqueta: string;
  valor: number | string;
  tipo: 'numero' | 'dinero' | 'texto';
}

export interface ColumnaResultado {
  nombre: string;
  tipo: 'numero' | 'dinero' | 'texto';
}

// NUEVO (CU13): datos del gráfico calculados por el backend.
export interface SerieGrafico {
  nombre: string;
  datos: number[];
}

export interface GraficoResultado {
  tipo: 'bar' | 'barh' | 'line' | 'doughnut';
  titulo: string;
  etiquetas: string[];
  series: SerieGrafico[];
  formato: 'numero' | 'dinero';
}

export interface ResultadoConsulta {
  titulo: string;
  subtitulo: string;
  kpis: KpiResultado[];
  columnas: ColumnaResultado[];
  filas: (string | number | null)[][];
  notas: string[];
  grafico?: GraficoResultado | null;
}

export interface ReporteGenerado {
  id_reporte: number;
  consulta: string;
  resultado: ResultadoConsulta;
}

// NUEVO (CU13): descarga pedida en el chat ("descárgamelo en PDF").
export interface ExportacionPedida {
  id_reporte: number;
  formato: FormatoReporte;
  titulo: string;
}

export interface RespuestaAsistenteAdmin {
  respuesta: string;
  resultados: ReporteGenerado[];
  exportar: ExportacionPedida | null;
  aclaracion: string | null;
  proveedor: string;
  modelo: string | null;
}

export interface ReporteResumen {
  id_reporte: number;
  fecha: string;
  pregunta: string;
  titulo: string;
  consulta: string;
}

export interface ReporteDetalle {
  id_reporte: number;
  fecha: string;
  pregunta: string;
  consulta: string;
  respuesta: string;
  resultado: ResultadoConsulta;
}

// NUEVO (CU13): reportes convencionales (sin IA).
export interface TipoReporte {
  clave: string;
  nombre: string;
  filtros: string[];
}

export interface OpcionConEmpresa {
  nombre: string;
  empresa: string | null;
}

export interface OpcionesReporte {
  tipos: TipoReporte[];
  empresas: string[];
  sucursales: OpcionConEmpresa[];
  categorias: OpcionConEmpresa[];
  productos: OpcionConEmpresa[];
  sucursal_fija: string | null;
  super_admin: boolean;
}

export interface FiltrosReporte {
  periodo?: string;
  desde?: string;
  hasta?: string;
  empresa?: string;
  sucursal?: string;
  categoria?: string;
  producto?: string;
  texto?: string;
  agrupar_por?: string;
  canal?: string;
  meses?: number | null;
  limite?: number | null;
  estado?: string;
  tipo?: string;
  situacion?: string;
  talla?: string;
  color?: string;
  solo_bajo_stock?: boolean;
}

export interface ReporteConvencional {
  id_reporte: number;
  consulta: string;
  filtros: FiltrosReporte;
  resultado: ResultadoConsulta;
}

// Alias mínimo para no importar HttpResponse<Blob> en cada componente.
export type HttpEventBlobResponse = HttpResponse<Blob>;

@Injectable({
  providedIn: 'root'
})
export class AssistantAdminService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  preguntar(mensaje: string): Observable<RespuestaAsistenteAdmin> {
    return this.http.post<RespuestaAsistenteAdmin>(`${this.apiUrl}/innovation/asistente/`, { mensaje });
  }

  listarReportes(): Observable<ReporteResumen[]> {
    return this.http.get<ReporteResumen[]>(`${this.apiUrl}/innovation/asistente/reportes/`);
  }

  obtenerReporte(idReporte: number): Observable<ReporteDetalle> {
    return this.http.get<ReporteDetalle>(`${this.apiUrl}/innovation/asistente/reportes/${idReporte}/`);
  }

  // Devuelve el archivo (blob) junto con la respuesta completa, para leer el
  // nombre real desde Content-Disposition.
  descargarReporte(idReporte: number, formato: FormatoReporte): Observable<HttpEventBlobResponse> {
    return this.http.get(
      `${this.apiUrl}/innovation/asistente/reportes/${idReporte}/exportar/?formato=${formato}`,
      { observe: 'response', responseType: 'blob' }
    );
  }

  // NUEVO (CU13): tipos de reporte y opciones de los filtros (sin IA).
  opcionesReporte(): Observable<OpcionesReporte> {
    return this.http.get<OpcionesReporte>(`${this.apiUrl}/innovation/reportes/opciones/`);
  }

  // NUEVO (CU13): genera un reporte convencional con el tipo y los filtros elegidos.
  generarReporte(consulta: string, filtros: FiltrosReporte): Observable<ReporteConvencional> {
    return this.http.post<ReporteConvencional>(`${this.apiUrl}/innovation/reportes/generar/`, {
      consulta,
      filtros
    });
  }

  // NUEVO (CU13): guarda en el equipo el archivo descargado, con su nombre real.
  guardarArchivo(respuesta: HttpEventBlobResponse, formato: FormatoReporte): void {
    const contenido = respuesta.body;
    if (!contenido) {
      return;
    }
    const disposicion = respuesta.headers.get('Content-Disposition');
    const coincidencia = disposicion?.match(/filename="?([^"]+)"?/);
    const nombre = coincidencia?.[1] ?? `reporte.${formato}`;
    const url = URL.createObjectURL(contenido);
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = nombre;
    enlace.click();
    URL.revokeObjectURL(url);
  }
}