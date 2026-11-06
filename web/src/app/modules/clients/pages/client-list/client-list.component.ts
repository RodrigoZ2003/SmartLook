// web/src/app/modules/clients/pages/client-list/client-list.component.ts
//
// MODIFICADO (Fase 3 - CU04): perfil de clientes por empresa.
//   - ADMIN_EMPRESA: solo los clientes que compraron o reservaron en su
//     empresa, y de cada uno solo lo que hizo en ella (aislamiento SaaS).
//   - SUPER_ADMIN: todos los clientes, con sus empresas y el detalle por empresa.
//   - Al elegir un cliente se abre su perfil: resumen de compras, preferencias
//     (prendas, categorías, tallas y colores), segmento de la Analítica (ML) e
//     historial (pedidos web, compras en tienda, reservas, devoluciones y cambios).
// Solo lectura: los clientes se registran solos.
// MODIFICADO (Fase 3 - CU18): el perfil muestra el progreso del descuento por
// fidelidad del mes (por empresa).
import { Component, OnInit } from '@angular/core';
import { FidelidadService, FilaFidelidad } from '../../../../core/services/fidelidad.service';
import {
  ClienteResumen,
  ClientesEmpresaService,
  PerfilCliente,
  SegmentoCliente
} from '../../services/clientes-empresa.service';

@Component({
  selector: 'app-client-list',
  templateUrl: './client-list.component.html',
  styleUrls: ['./client-list.component.scss']
})
export class ClientListComponent implements OnInit {
  clientes: ClienteResumen[] = [];
  superAdmin = false;
  loading = false;
  error: string | null = null;
  busqueda = '';

  perfil: PerfilCliente | null = null;
  cargandoPerfil = false;
  seleccionadoId: number | null = null;
  fidelidad: FilaFidelidad[] = [];

  constructor(
    private clientesService: ClientesEmpresaService,
    private fidelidadService: FidelidadService
  ) {}

  ngOnInit(): void {
    this.cargar();
  }

  cargar(): void {
    this.loading = true;
    this.error = null;
    this.clientesService.listar().subscribe({
      next: (r) => {
        this.clientes = r.clientes;
        this.superAdmin = r.super_admin;
        this.loading = false;
      },
      error: (err) => {
        this.clientes = [];
        this.error = err?.error?.detail || 'No se pudieron cargar los clientes.';
        this.loading = false;
      }
    });
  }

  get clientesFiltrados(): ClienteResumen[] {
    const termino = this.busqueda.trim().toLowerCase();
    if (!termino) {
      return this.clientes;
    }
    return this.clientes.filter(c =>
      c.nombre.toLowerCase().includes(termino) ||
      c.correo.toLowerCase().includes(termino) ||
      c.empresas.some(e => e.toLowerCase().includes(termino))
    );
  }

  get totalCompras(): number {
    return this.clientes.reduce((suma, c) => suma + c.compras, 0);
  }

  get totalGastado(): number {
    return this.clientes.reduce((suma, c) => suma + c.total_gastado, 0);
  }

  verPerfil(cliente: ClienteResumen): void {
    this.seleccionadoId = cliente.id;
    this.cargandoPerfil = true;
    this.perfil = null;
    this.fidelidad = [];
    this.fidelidadService.monitoreo(null, cliente.id).subscribe({
      next: (datos) => this.fidelidad = datos.clientes,
      error: () => this.fidelidad = []
    });
    this.clientesService.perfil(cliente.id).subscribe({
      next: (perfil) => {
        this.perfil = perfil;
        this.cargandoPerfil = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || 'No se pudo abrir el perfil del cliente.';
        this.cargandoPerfil = false;
        this.seleccionadoId = null;
      }
    });
  }

  cerrarPerfil(): void {
    this.perfil = null;
    this.fidelidad = [];
    this.seleccionadoId = null;
    this.cargandoPerfil = false;
  }

  claseSegmento(segmento: SegmentoCliente): string {
    return `seg seg-${segmento.toLowerCase()}`;
  }

  claseFidelidad(estado: string): string {
    return `fid fid--${estado.toLowerCase()}`;
  }

  claseEvento(tipo: string): string {
    return `evento evento--${tipo.toLowerCase()}`;
  }
}