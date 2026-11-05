// web/src/app/modules/inventory/pages/traspasos-home/traspasos-home.component.ts
//
// NUEVO (Fase 3 - CU07): traspasos de prendas entre sucursales.
//   - Pestañas por estado (solicitados, en tránsito, recibidos, rechazados o
//     cancelados, todos) y detalle con su historial.
//   - Nueva solicitud: origen, destino (el encargado solo hacia su sucursal),
//     prendas con su stock disponible en origen (no se pide más de lo que hay).
//   - Acciones según el rol y el estado (las decide el backend): aprobar,
//     rechazar con motivo, recibir y cancelar.
//   - Sugerencias de la Analítica (SUPER_ADMIN y ADMIN_EMPRESA): "Crear
//     solicitud" abre el formulario ya cargado.
import { Component, OnInit } from '@angular/core';
import {
  AccionTraspaso,
  EstadoTraspaso,
  OpcionesTraspaso,
  StockPrenda,
  SucursalOpcion,
  SugerenciaTraspaso,
  Traspaso,
  TraspasosService
} from '../../services/traspasos.service';

type Pestana = 'SOLICITADO' | 'EN_TRANSITO' | 'RECIBIDO' | 'CERRADOS' | 'TODOS';

interface LineaFormulario {
  id_variante: number;
  prenda: string;
  stock: number;
  cantidad: number;
}

@Component({
  selector: 'app-traspasos-home',
  templateUrl: './traspasos-home.component.html',
  styleUrls: ['./traspasos-home.component.scss']
})
export class TraspasosHomeComponent implements OnInit {
  opciones: OpcionesTraspaso | null = null;
  traspasos: Traspaso[] = [];
  cargando = false;
  error: string | null = null;
  mensaje: string | null = null;
  pestana: Pestana = 'SOLICITADO';

  readonly pestanas: { clave: Pestana; texto: string }[] = [
    { clave: 'SOLICITADO', texto: 'Solicitados' },
    { clave: 'EN_TRANSITO', texto: 'En tránsito' },
    { clave: 'RECIBIDO', texto: 'Recibidos' },
    { clave: 'CERRADOS', texto: 'Rechazados y cancelados' },
    { clave: 'TODOS', texto: 'Todos' }
  ];

  // Detalle
  seleccionado: Traspaso | null = null;
  procesando: AccionTraspaso | null = null;
  motivoRechazo = '';
  mostrarRechazo = false;

  // Formulario de solicitud
  formularioAbierto = false;
  empresaForm: number | null = null;
  origenForm: number | null = null;
  destinoForm: number | null = null;
  observacionForm = '';
  desdeSugerencia = false;
  stockOrigen: StockPrenda[] = [];
  cargandoStock = false;
  varianteElegida: number | null = null;
  cantidadElegida = 1;
  lineas: LineaFormulario[] = [];
  enviando = false;
  errorForm: string | null = null;

  // Sugerencias de la Analítica
  sugerencias: SugerenciaTraspaso[] = [];
  empresaSugerencias: number | null = null;
  cargandoSugerencias = false;
  sugerenciasDisponibles = false;

  constructor(private traspasosService: TraspasosService) {}

  ngOnInit(): void {
    this.traspasosService.opciones().subscribe({
      next: (opciones) => {
        this.opciones = opciones;
        const empresas = this.empresas;
        this.empresaSugerencias = empresas.length ? empresas[0].id : null;
        this.cargarSugerencias();
      },
      error: (err) => this.error = err?.error?.detail || 'No se pudieron cargar las sucursales.'
    });
    this.cargar();
  }

  // ---------------------------------------------------------------- listas
  get empresas(): { id: number; nombre: string }[] {
    const vistas = new Map<number, string>();
    (this.opciones?.sucursales ?? []).forEach(s => vistas.set(s.id_empresa, s.empresa));
    return Array.from(vistas.entries()).map(([id, nombre]) => ({ id, nombre }));
  }

  get traspasosPestana(): Traspaso[] {
    if (this.pestana === 'TODOS') {
      return this.traspasos;
    }
    if (this.pestana === 'CERRADOS') {
      return this.traspasos.filter(t => t.estado === 'RECHAZADO' || t.estado === 'CANCELADO');
    }
    return this.traspasos.filter(t => t.estado === this.pestana);
  }

  contar(clave: Pestana): number {
    if (clave === 'TODOS') {
      return this.traspasos.length;
    }
    if (clave === 'CERRADOS') {
      return this.traspasos.filter(t => t.estado === 'RECHAZADO' || t.estado === 'CANCELADO').length;
    }
    return this.traspasos.filter(t => t.estado === clave).length;
  }

  claseEstado(estado: EstadoTraspaso): string {
    return `estado estado--${estado.toLowerCase()}`;
  }

  cargar(): void {
    this.cargando = true;
    this.traspasosService.listar().subscribe({
      next: (lista) => {
        this.traspasos = lista;
        this.cargando = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || 'No se pudieron cargar los traspasos.';
        this.cargando = false;
      }
    });
  }

  // ---------------------------------------------------------------- detalle
  ver(traspaso: Traspaso): void {
    this.mostrarRechazo = false;
    this.motivoRechazo = '';
    this.traspasosService.detalle(traspaso.id).subscribe({
      next: (detalle) => this.seleccionado = detalle,
      error: (err) => this.error = err?.error?.detail || 'No se pudo abrir el traspaso.'
    });
  }

  cerrarDetalle(): void {
    this.seleccionado = null;
    this.mostrarRechazo = false;
  }

  ejecutar(accion: AccionTraspaso): void {
    if (!this.seleccionado || this.procesando) {
      return;
    }
    if (accion === 'rechazar' && !this.motivoRechazo.trim()) {
      this.error = 'Escribe el motivo del rechazo.';
      return;
    }
    this.procesando = accion;
    this.error = null;
    const textos: Record<AccionTraspaso, string> = {
      aprobar: 'aprobado: el stock salió de la sucursal de origen',
      rechazar: 'rechazado',
      recibir: 'recibido: el stock ya está en la sucursal de destino',
      cancelar: 'cancelado'
    };
    this.traspasosService.ejecutar(this.seleccionado.id, accion, this.motivoRechazo.trim()).subscribe({
      next: (traspaso) => {
        this.seleccionado = traspaso;
        this.mensaje = `Traspaso #${traspaso.id} ${textos[accion]}.`;
        this.procesando = null;
        this.mostrarRechazo = false;
        this.motivoRechazo = '';
        this.cargar();
        this.cargarSugerencias();
      },
      error: (err) => {
        this.error = err?.error?.detail || 'No se pudo completar la acción.';
        this.procesando = null;
      }
    });
  }

  // ---------------------------------------------------------------- formulario
  get sucursalesEmpresa(): SucursalOpcion[] {
    const todas = this.opciones?.sucursales ?? [];
    return this.empresaForm ? todas.filter(s => s.id_empresa === this.empresaForm) : todas;
  }

  get origenesPosibles(): SucursalOpcion[] {
    return this.sucursalesEmpresa.filter(s => s.id !== this.destinoForm);
  }

  get destinosPosibles(): SucursalOpcion[] {
    return this.sucursalesEmpresa.filter(s => s.id !== this.origenForm);
  }

  get prendasDisponibles(): StockPrenda[] {
    const usadas = new Set(this.lineas.map(l => l.id_variante));
    return this.stockOrigen.filter(p => !usadas.has(p.id_variante));
  }

  get stockElegido(): number {
    return this.stockOrigen.find(p => p.id_variante === this.varianteElegida)?.stock ?? 0;
  }

  get totalUnidades(): number {
    return this.lineas.reduce((suma, l) => suma + (l.cantidad || 0), 0);
  }

  abrirFormulario(): void {
    this.formularioAbierto = true;
    this.errorForm = null;
    this.desdeSugerencia = false;
    this.lineas = [];
    this.observacionForm = '';
    this.origenForm = null;
    this.stockOrigen = [];
    const fijo = this.opciones?.destino_fijo ?? null;
    this.destinoForm = fijo;
    const empresas = this.empresas;
    this.empresaForm = empresas.length === 1 ? empresas[0].id : null;
    if (fijo) {
      this.empresaForm = this.opciones?.sucursales.find(s => s.id === fijo)?.id_empresa ?? this.empresaForm;
    }
  }

  cerrarFormulario(): void {
    this.formularioAbierto = false;
  }

  cambiarEmpresaForm(): void {
    this.origenForm = null;
    this.destinoForm = this.opciones?.destino_fijo ?? null;
    this.stockOrigen = [];
    this.lineas = [];
  }

  cambiarOrigen(): void {
    this.lineas = [];
    this.varianteElegida = null;
    this.cargarStockOrigen();
  }

  private cargarStockOrigen(alTerminar?: () => void): void {
    this.stockOrigen = [];
    if (!this.origenForm) {
      return;
    }
    this.cargandoStock = true;
    this.traspasosService.stock(this.origenForm).subscribe({
      next: (stock) => {
        this.stockOrigen = stock;
        this.cargandoStock = false;
        alTerminar?.();
      },
      error: () => {
        this.errorForm = 'No se pudo cargar el stock de la sucursal de origen.';
        this.cargandoStock = false;
      }
    });
  }

  agregarLinea(): void {
    const prenda = this.stockOrigen.find(p => p.id_variante === this.varianteElegida);
    if (!prenda) {
      return;
    }
    const cantidad = Math.floor(Number(this.cantidadElegida) || 0);
    if (cantidad < 1 || cantidad > prenda.stock) {
      this.errorForm = `La cantidad debe estar entre 1 y ${prenda.stock} (stock en origen).`;
      return;
    }
    this.errorForm = null;
    this.lineas.push({
      id_variante: prenda.id_variante,
      prenda: `${prenda.prenda} - ${prenda.talla} - ${prenda.color}`,
      stock: prenda.stock,
      cantidad
    });
    this.varianteElegida = null;
    this.cantidadElegida = 1;
  }

  quitarLinea(indice: number): void {
    this.lineas.splice(indice, 1);
  }

  lineaInvalida(linea: LineaFormulario): boolean {
    return !linea.cantidad || linea.cantidad < 1 || linea.cantidad > linea.stock;
  }

  enviar(): void {
    if (!this.origenForm || !this.destinoForm) {
      this.errorForm = 'Elige la sucursal de origen y la de destino.';
      return;
    }
    if (!this.lineas.length) {
      this.errorForm = 'Agrega al menos una prenda.';
      return;
    }
    if (this.lineas.some(l => this.lineaInvalida(l))) {
      this.errorForm = 'Revisa las cantidades: no pueden superar el stock del origen.';
      return;
    }
    this.enviando = true;
    this.errorForm = null;
    this.traspasosService.crear({
      id_sucursal_origen: this.origenForm,
      id_sucursal_destino: this.destinoForm,
      observacion: this.observacionForm,
      desde_sugerencia: this.desdeSugerencia,
      lineas: this.lineas.map(l => ({ id_variante: l.id_variante, cantidad: Math.floor(l.cantidad) }))
    }).subscribe({
      next: (traspaso) => {
        this.enviando = false;
        this.formularioAbierto = false;
        this.mensaje = `Traspaso #${traspaso.id} solicitado. Queda pendiente de aprobación.`;
        this.pestana = 'SOLICITADO';
        this.cargar();
        this.cargarSugerencias();
      },
      error: (err) => {
        this.errorForm = err?.error?.detail || 'No se pudo registrar el traspaso.';
        this.enviando = false;
      }
    });
  }

  // ---------------------------------------------------------------- sugerencias
  cargarSugerencias(): void {
    if (!this.opciones?.puede_aprobar) {
      return;
    }
    if (this.opciones.super_admin && !this.empresaSugerencias) {
      return;
    }
    this.cargandoSugerencias = true;
    this.traspasosService.sugerencias(this.opciones.super_admin ? this.empresaSugerencias : null).subscribe({
      next: (r) => {
        this.sugerencias = r.sugerencias;
        this.sugerenciasDisponibles = true;
        this.cargandoSugerencias = false;
      },
      error: () => {
        // Plan sin IA o sin modelos: la sección simplemente no se muestra.
        this.sugerencias = [];
        this.sugerenciasDisponibles = false;
        this.cargandoSugerencias = false;
      }
    });
  }

  usarSugerencia(s: SugerenciaTraspaso): void {
    this.abrirFormulario();
    this.desdeSugerencia = true;
    this.empresaForm = this.opciones?.sucursales.find(x => x.id === s.id_sucursal_origen)?.id_empresa ?? null;
    this.origenForm = s.id_sucursal_origen;
    this.destinoForm = s.id_sucursal_destino;
    this.observacionForm = `Sugerido por la Analítica: demanda prevista de ${s.demanda_prevista} y stock de ${s.stock_destino} en destino.`;
    // Reparte la cantidad sugerida entre las tallas y colores con más stock en origen.
    this.cargarStockOrigen(() => {
      let falta = s.cantidad_sugerida;
      for (const v of s.variantes) {
        const prenda = this.stockOrigen.find(p => p.id_variante === v.id_variante);
        if (!prenda || falta <= 0) {
          continue;
        }
        const cantidad = Math.min(falta, prenda.stock);
        this.lineas.push({
          id_variante: prenda.id_variante,
          prenda: `${prenda.prenda} - ${prenda.talla} - ${prenda.color}`,
          stock: prenda.stock,
          cantidad
        });
        falta -= cantidad;
      }
    });
  }
}