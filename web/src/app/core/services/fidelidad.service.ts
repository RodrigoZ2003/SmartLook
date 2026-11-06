// web/src/app/core/services/fidelidad.service.ts
//
// NUEVO (Fase 3 - CU18): descuento por fidelidad.
//   GET /fidelidad/regla/          regla vigente (SUPER_ADMIN y ADMIN_EMPRESA)
//   PUT /fidelidad/regla/          cambia la regla (solo SUPER_ADMIN)
//   GET /fidelidad/monitoreo/      clientes del mes con su progreso (?mes=AAAA-MM&id_cliente=)
//   GET /fidelidad/mi-progreso/    progreso del cliente por empresa (?id_empresa=)
//   GET /fidelidad/pos/            si el cliente del POS tiene el descuento (?correo=&id_sucursal=)
// Lo usan: Clientes > Fidelidad, el perfil del cliente, el carrito, Mis pedidos y el POS web.
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export type EstadoFidelidad = 'EN_PROGRESO' | 'DISPONIBLE' | 'USADO' | 'VENCIDO';

export interface ReglaFidelidad {
  compras_requeridas: number;
  porcentaje: number;
  activa: boolean;
  fecha_actualizacion: string;
  actualizado_por: string | null;
  ganaron_ahora?: number;
}

export interface FilaFidelidad {
  compras: number;
  requeridas: number;
  faltan: number;
  estado: EstadoFidelidad;
  estado_display: string;
  fecha_alcanzado: string | null;
  fecha_uso: string | null;
  porcentaje_usado: number | null;
  monto_descuento: number;
  uso: string | null;
  id_empresa: number;
  empresa: string;
  id_cliente?: number;
  cliente?: string;
  correo?: string;
  disponible?: boolean;
  porcentaje?: number;
}

export interface MonitoreoFidelidad {
  mes: string;
  vence: string;
  super_admin: boolean;
  regla: ReglaFidelidad;
  resumen: {
    clientes: number;
    ganaron: number;
    por_usar: number;
    usados: number;
    vencidos: number;
    costo_descuentos: number;
  };
  clientes: FilaFidelidad[];
}

export interface ProgresoFidelidad {
  mes: string;
  vence: string;
  regla: ReglaFidelidad;
  empresas: FilaFidelidad[];
}

export interface FidelidadPos {
  cliente: string;
  correo: string;
  empresa: string;
  activa: boolean;
  compras: number;
  requeridas: number;
  faltan: number;
  porcentaje: number;
  disponible: boolean;
  usado: boolean;
  vence: string;
}

@Injectable({
  providedIn: 'root'
})
export class FidelidadService {
  constructor(private api: ApiService) {}

  regla(): Observable<ReglaFidelidad> {
    return this.api.get<ReglaFidelidad>('/fidelidad/regla/');
  }

  guardarRegla(datos: { compras_requeridas: number; porcentaje: number; activa: boolean }): Observable<ReglaFidelidad> {
    return this.api.put<ReglaFidelidad>('/fidelidad/regla/', datos);
  }

  monitoreo(mes: string | null = null, idCliente: number | null = null): Observable<MonitoreoFidelidad> {
    return this.api.get<MonitoreoFidelidad>('/fidelidad/monitoreo/', { mes, id_cliente: idCliente });
  }

  miProgreso(idEmpresa: number | null = null): Observable<ProgresoFidelidad> {
    return this.api.get<ProgresoFidelidad>('/fidelidad/mi-progreso/', { id_empresa: idEmpresa });
  }

  consultarPos(correo: string, idSucursal: number): Observable<FidelidadPos> {
    return this.api.get<FidelidadPos>('/fidelidad/pos/', { correo, id_sucursal: idSucursal });
  }
}