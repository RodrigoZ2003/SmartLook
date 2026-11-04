// web/src/app/modules/assistant-admin/pages/reportes-home/reportes-home.component.ts
//
// NUEVO (Fase 3 - CU13): reportes convencionales SIN IA, en los tres planes
// (PLUS, PRO y ULTRA). El usuario elige el tipo de reporte y sus filtros; el
// backend ejecuta la misma consulta controlada que usa el asistente con IA,
// dentro de su empresa y sucursal. El resultado se muestra con indicadores,
// gráfico y tabla, y se descarga en PDF, Excel o HTML.
import { Component, OnInit } from '@angular/core';
import {
  AssistantAdminService,
  FiltrosReporte,
  FormatoReporte,
  OpcionConEmpresa,
  OpcionesReporte,
  ReporteConvencional,
  TipoReporte
} from '../../services/assistant-admin.service';

interface Opcion {
  valor: string;
  texto: string;
}

const PERIODOS: Opcion[] = [
  { valor: 'hoy', texto: 'Hoy' },
  { valor: 'ayer', texto: 'Ayer' },
  { valor: 'semana', texto: 'Esta semana' },
  { valor: 'semana_pasada', texto: 'Semana pasada' },
  { valor: 'mes', texto: 'Este mes' },
  { valor: 'mes_pasado', texto: 'Mes pasado' },
  { valor: 'anio', texto: 'Este año' },
  { valor: 'todo', texto: 'Todo el historial' }
];

const AGRUPACIONES: Opcion[] = [
  { valor: 'dia', texto: 'Día' },
  { valor: 'semana', texto: 'Semana' },
  { valor: 'mes', texto: 'Mes' },
  { valor: 'sucursal', texto: 'Sucursal' },
  { valor: 'categoria', texto: 'Categoría' },
  { valor: 'metodo', texto: 'Método de pago' },
  { valor: 'canal', texto: 'Canal' }
];

const CANALES: Opcion[] = [
  { valor: 'pos', texto: 'Punto de venta' },
  { valor: 'web', texto: 'Web / App' }
];

// Los estados se envían como texto: el backend los valida contra su catálogo.
const ESTADOS: Record<string, Opcion[]> = {
  consultar_reservas: [
    { valor: 'pendiente de pago', texto: 'Pendiente de pago' },
    { valor: 'confirmada', texto: 'Confirmada' },
    { valor: 'completada', texto: 'Completada' },
    { valor: 'cancelada', texto: 'Cancelada' },
    { valor: 'vencida', texto: 'Vencida' }
  ],
  consultar_entregas: [
    { valor: 'pendiente', texto: 'Pendiente' },
    { valor: 'en preparación', texto: 'En preparación' },
    { valor: 'en camino', texto: 'En camino' },
    { valor: 'entregado', texto: 'Entregado' }
  ]
};

const TIPOS_SOLICITUD: Opcion[] = [
  { valor: 'devoluciones', texto: 'Solo devoluciones' },
  { valor: 'cambios', texto: 'Solo cambios de prenda' }
];

const SITUACIONES: Opcion[] = [
  { valor: 'pendiente de revisión', texto: 'Pendiente de revisión' },
  { valor: 'confirmada', texto: 'Confirmada' },
  { valor: 'anulada', texto: 'Anulada (efectivo devuelto)' }
];

@Component({
  selector: 'app-reportes-home',
  templateUrl: './reportes-home.component.html',
  styleUrls: [
    '../assistant-admin-home/assistant-admin-home.component.scss',
    './reportes-home.component.scss'
  ]
})
export class ReportesHomeComponent implements OnInit {
  opciones: OpcionesReporte | null = null;
  cargandoOpciones = true;
  errorOpciones = '';

  tipoSeleccionado = '';
  filtros: FiltrosReporte = {};

  generando = false;
  error = '';
  reporte: ReporteConvencional | null = null;
  descargando: FormatoReporte | null = null;

  readonly periodos = PERIODOS;
  readonly canales = CANALES;
  readonly tiposSolicitud = TIPOS_SOLICITUD;
  readonly situaciones = SITUACIONES;

  constructor(private assistantAdminService: AssistantAdminService) {}

  ngOnInit(): void {
    this.assistantAdminService.opcionesReporte().subscribe({
      next: (opciones) => {
        this.opciones = opciones;
        this.cargandoOpciones = false;
        if (opciones.tipos.length > 0) {
          this.elegirTipo(opciones.tipos[0].clave);
        }
      },
      error: (err) => {
        this.errorOpciones = err?.error?.detail || 'No se pudieron cargar los tipos de reporte.';
        this.cargandoOpciones = false;
      }
    });
  }

  get tipo(): TipoReporte | undefined {
    return this.opciones?.tipos.find(t => t.clave === this.tipoSeleccionado);
  }

  get agrupaciones(): Opcion[] {
    if (this.opciones?.super_admin) {
      return [...AGRUPACIONES, { valor: 'empresa', texto: 'Empresa' }];
    }
    return AGRUPACIONES;
  }

  get estados(): Opcion[] {
    return ESTADOS[this.tipoSeleccionado] ?? [];
  }

  // Sucursales, categorías y prendas de la empresa elegida (SUPER_ADMIN) o todas.
  get sucursales(): string[] {
    return this.deEmpresa(this.opciones?.sucursales ?? []);
  }

  get categorias(): string[] {
    return this.deEmpresa(this.opciones?.categorias ?? []);
  }

  get productos(): string[] {
    return this.deEmpresa(this.opciones?.productos ?? []);
  }

  usa(filtro: string): boolean {
    return !!this.tipo?.filtros.includes(filtro);
  }

  elegirTipo(clave: string): void {
    this.tipoSeleccionado = clave;
    this.filtros = { empresa: this.filtros.empresa };
    if (this.opciones?.sucursal_fija) {
      this.filtros.sucursal = this.opciones.sucursal_fija;
    }
    this.error = '';
  }

  cambiarEmpresa(): void {
    // Al cambiar de empresa se limpian los filtros que dependen de ella.
    this.filtros.sucursal = undefined;
    this.filtros.categoria = undefined;
    this.filtros.producto = undefined;
    this.filtros.texto = undefined;
  }

  generar(): void {
    if (!this.tipoSeleccionado || this.generando) {
      return;
    }
    if (this.filtros.desde && this.filtros.hasta && this.filtros.desde > this.filtros.hasta) {
      this.error = 'La fecha "desde" no puede ser posterior a la fecha "hasta".';
      return;
    }
    this.generando = true;
    this.error = '';
    this.assistantAdminService.generarReporte(this.tipoSeleccionado, this.filtrosAEnviar()).subscribe({
      next: (reporte) => {
        this.reporte = reporte;
        this.generando = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || 'No se pudo generar el reporte. Intenta de nuevo.';
        this.generando = false;
      }
    });
  }

  descargar(formato: FormatoReporte): void {
    if (!this.reporte || this.descargando) {
      return;
    }
    this.descargando = formato;
    this.assistantAdminService.descargarReporte(this.reporte.id_reporte, formato).subscribe({
      next: (respuesta) => {
        this.assistantAdminService.guardarArchivo(respuesta, formato);
        this.descargando = null;
      },
      error: () => {
        this.error = 'No se pudo descargar el archivo. Intenta de nuevo.';
        this.descargando = null;
      }
    });
  }

  esNumerica(tipo: string): boolean {
    return tipo === 'numero' || tipo === 'dinero';
  }

  // Solo se envían los filtros que usa el tipo elegido y que tienen valor.
  private filtrosAEnviar(): FiltrosReporte {
    const enviar: Record<string, string | number | boolean> = {};
    Object.entries(this.filtros).forEach(([clave, valor]) => {
      if (this.usa(clave) && valor !== undefined && valor !== null && valor !== '' && valor !== false) {
        enviar[clave] = valor as string | number | boolean;
      }
    });
    return enviar as FiltrosReporte;
  }

  private deEmpresa(lista: OpcionConEmpresa[]): string[] {
    const empresa = this.filtros.empresa;
    const nombres = lista
      .filter(o => !empresa || o.empresa === empresa)
      .map(o => o.nombre);
    return Array.from(new Set(nombres));
  }
}