// web/src/app/modules/clients/services/clientes-empresa.service.ts
//
// NUEVO (Fase 3 - CU04): perfil de clientes por empresa.
//   GET /api/analytics/clientes/        clientes con su resumen
//   GET /api/analytics/clientes/:id/    perfil del cliente
// SUPER_ADMIN ve todos los clientes; ADMIN_EMPRESA solo los de su empresa.
import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';

export type SegmentoCliente = 'VIP' | 'LEAL' | 'OCASIONAL' | 'RIESGO';

export interface SegmentoResumen {
  empresa: string;
  segmento: SegmentoCliente;
  nombre: string;
}

export interface ClienteResumen {
  id: number;
  nombre: string;
  correo: string;
  telefono: string | null;
  estado: string;
  empresas: string[];
  compras: number;
  total_gastado: number;
  ultima_compra: string | null;
  segmentos: SegmentoResumen[];
}

export interface Preferencia {
  nombre: string;
  unidades: number;
}

export interface SegmentoDetalle extends SegmentoResumen {
  recencia_dias: number;
  frecuencia: number;
  monto: number;
  fecha: string;
}

export interface EventoCliente {
  tipo: 'PEDIDO' | 'VENTA' | 'RESERVA' | 'DEVOLUCION' | 'CAMBIO';
  tipo_display: string;
  numero: number;
  fecha: string | null;
  empresa: string;
  sucursal: string;
  estado: string;
  monto: number | null;
  detalle: string;
}

export interface PerfilCliente {
  super_admin: boolean;
  cliente: {
    id: number;
    nombre: string;
    correo: string;
    telefono: string | null;
    estado: string;
    fecha_registro: string;
  };
  resumen: {
    compras: number;
    pedidos_web: number;
    ventas_tienda: number;
    total_gastado: number;
    ticket_promedio: number;
    primera_compra: string | null;
    ultima_compra: string | null;
    sucursal_favorita: string | null;
    reservas: number;
    devoluciones: number;
    monto_reembolsado: number;
    cambios: number;
  };
  preferencias: {
    unidades: number;
    prendas: Preferencia[];
    categorias: Preferencia[];
    tallas: Preferencia[];
    colores: Preferencia[];
  };
  segmentos: SegmentoDetalle[];
  por_empresa: { empresa: string; compras: number; total: number }[];
  historial: EventoCliente[];
}

@Injectable({
  providedIn: 'root'
})
export class ClientesEmpresaService {
  private apiUrl = `${environment.apiUrl}/analytics/clientes`;

  constructor(private http: HttpClient) {}

  listar(): Observable<{ super_admin: boolean; clientes: ClienteResumen[] }> {
    return this.http.get<{ super_admin: boolean; clientes: ClienteResumen[] }>(`${this.apiUrl}/`);
  }

  perfil(id: number): Observable<PerfilCliente> {
    return this.http.get<PerfilCliente>(`${this.apiUrl}/${id}/`);
  }
}