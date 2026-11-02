// web/src/app/modules/pos/pages/sync-operaciones/sync-operaciones.component.ts
//
// NUEVO (Fase 2 - CU08): historial de las ventas POS hechas sin conexión
// (sincronizadas, en conflicto y rechazadas) con filtros, y resolución de los
// conflictos por el encargado, el administrador de la empresa o el SUPER_ADMIN:
//   - Confirmar: la venta queda válida (si faltó stock, se ajusta el inventario).
//   - Devolver efectivo: la venta se anula, se repone lo descontado y se
//     genera la nota de devolución.
// El cajero también puede entrar, pero el backend solo le muestra sus propias
// operaciones y no le permite resolverlas.
import { Component, OnInit } from '@angular/core';
import { AuthService } from '../../../../core/auth/auth.service';
import { AccionConflicto, PosSaleService } from '../../services/pos-sale.service';

interface Filtros {
  estado: string;
  pendientes: boolean;
  tipo_conflicto: string;
  sucursal: number | null;
  desde: string;
  hasta: string;
  empresa: string | null;
}

interface Resumen {
  SINCRONIZADA: number;
  EN_CONFLICTO: number;
  RECHAZADA: number;
  pendientes: number;
}

const FILTROS_INICIALES: Filtros = {
  estado: '',
  pendientes: false,
  tipo_conflicto: '',
  sucursal: null,
  desde: '',
  hasta: '',
  empresa: null
};

@Component({
  selector: 'app-sync-operaciones',
  templateUrl: './sync-operaciones.component.html',
  styleUrls: ['./sync-operaciones.component.scss']
})
export class SyncOperacionesComponent implements OnInit {
  filtros: Filtros = { ...FILTROS_INICIALES };
  operaciones: any[] = [];
  resumen: Resumen | null = null;
  total = 0;
  pagina = 1;
  hayAnterior = false;
  haySiguiente = false;
  cargando = false;
  error: string | null = null;
  mensaje: string | null = null;

  esSuperAdmin = false;
  empresas: any[] = [];
  sucursales: any[] = [];

  // Detalle abierto y resolución en curso.
  abierta: number | null = null;
  notas: { [idOperacion: number]: string } = {};
  confirmando: { id: number; accion: AccionConflicto } | null = null;
  resolviendo = false;

  constructor(private posSaleService: PosSaleService, private authService: AuthService) {
    this.esSuperAdmin = this.authService.obtenerRoles().includes('SUPER_ADMIN');
  }

  ngOnInit(): void {
    if (this.esSuperAdmin) {
      this.posSaleService.listarEmpresas().subscribe({
        next: (data: any) => this.empresas = data?.results || data || [],
        error: () => this.empresas = []
      });
    }
    this.cargarSucursales();
    this.buscar();
  }

  cargarSucursales(): void {
    this.posSaleService.listarSucursales(this.filtros.empresa).subscribe({
      next: (data: any) => this.sucursales = data?.results || data || [],
      error: () => this.sucursales = []
    });
  }

  cambiarEmpresa(): void {
    this.filtros.sucursal = null;
    this.cargarSucursales();
    this.buscar();
  }

  // Atajo desde las tarjetas del resumen.
  filtrarPorEstado(estado: string, pendientes = false): void {
    this.filtros.estado = estado;
    this.filtros.pendientes = pendientes;
    this.buscar();
  }

  limpiar(): void {
    this.filtros = { ...FILTROS_INICIALES };
    this.cargarSucursales();
    this.buscar();
  }

  buscar(pagina = 1): void {
    this.pagina = pagina;
    this.cargando = true;
    this.error = null;
    const f = this.filtros;
    this.posSaleService.listarOperaciones({
      estado: f.estado,
      pendientes: f.pendientes ? 1 : null,
      tipo_conflicto: f.tipo_conflicto,
      sucursal: f.sucursal,
      desde: f.desde,
      hasta: f.hasta,
      empresa: f.empresa,
      page: pagina
    }).subscribe({
      next: (data: any) => {
        this.operaciones = data?.results || data || [];
        this.total = data?.count ?? this.operaciones.length;
        this.hayAnterior = !!data?.previous;
        this.haySiguiente = !!data?.next;
        this.cargando = false;
      },
      error: (err) => {
        this.cargando = false;
        this.operaciones = [];
        this.error = err?.error?.detail || err?.error?.error || 'No se pudo cargar el historial.';
      }
    });
    this.posSaleService.resumenOperaciones(f.empresa).subscribe({
      next: (r: Resumen) => this.resumen = r,
      error: () => this.resumen = null
    });
  }

  alternar(op: any): void {
    this.abierta = this.abierta === op.id_operacion ? null : op.id_operacion;
    this.confirmando = null;
  }

  tieneConflictoDeStock(op: any): boolean {
    return (op.detalle_conflicto || []).some((c: any) => c.tipo === 'STOCK');
  }

  textoConfirmar(op: any): string {
    return this.tieneConflictoDeStock(op) ? 'Confirmar y ajustar stock' : 'Marcar como revisada';
  }

  pedirConfirmacion(op: any, accion: AccionConflicto): void {
    this.confirmando = { id: op.id_operacion, accion };
    this.mensaje = null;
  }

  cancelarConfirmacion(): void {
    this.confirmando = null;
  }

  resolver(op: any): void {
    if (!this.confirmando || this.confirmando.id !== op.id_operacion || this.resolviendo) {
      return;
    }
    const accion = this.confirmando.accion;
    const nota = (this.notas[op.id_operacion] || '').trim() || null;
    this.resolviendo = true;
    this.error = null;
    this.posSaleService.resolverOperacion(op.id_operacion, accion, nota).subscribe({
      next: (actualizada: any) => {
        this.resolviendo = false;
        this.confirmando = null;
        const indice = this.operaciones.findIndex(o => o.id_operacion === op.id_operacion);
        if (indice >= 0) {
          this.operaciones[indice] = actualizada;
        }
        this.mensaje = accion === 'DEVOLVER'
          ? `Venta #${actualizada.id_venta} anulada: se devolvió Bs ${actualizada.nota_devolucion?.monto_devuelto} y se generó la nota de devolución.`
          : `Venta #${actualizada.id_venta} confirmada.`;
        this.posSaleService.resumenOperaciones(this.filtros.empresa).subscribe({
          next: (r: Resumen) => this.resumen = r,
          error: () => undefined
        });
      },
      error: (err) => {
        this.resolviendo = false;
        this.error = err?.error?.error || err?.error?.detail || 'No se pudo resolver la operación.';
      }
    });
  }

  claseEstado(op: any): string {
    if (op.estado === 'EN_CONFLICTO' && op.resolucion) {
      return 'estado--resuelta';
    }
    return 'estado--' + (op.estado || '').toLowerCase();
  }

  textoEstado(op: any): string {
    if (op.estado === 'EN_CONFLICTO' && op.resolucion) {
      return `Conflicto resuelto · ${op.resolucion_display}`;
    }
    if (op.estado === 'EN_CONFLICTO') {
      return `En conflicto · ${op.tipo_conflicto_display}`;
    }
    return op.estado_display || op.estado;
  }

  totalPrendas(op: any): number {
    return (op.venta?.items || []).reduce((s: number, i: any) => s + (i.cantidad || 0), 0);
  }
}