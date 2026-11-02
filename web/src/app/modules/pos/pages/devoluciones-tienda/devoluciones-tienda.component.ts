// web/src/app/modules/pos/pages/devoluciones-tienda/devoluciones-tienda.component.ts
//
// NUEVO (Fase 2 - CU12): devolución de prendas con reembolso y nota de
// devolución (ND-000001). Tres pestañas:
//   - Seguimiento: solicitudes de los clientes (recojo a domicilio). El
//     encargado o el administrador asigna repartidor y fecha de recojo
//     (máximo 48 h) o la rechaza; se ve el avance hasta "Completada".
//   - Registrar en tienda: busca la venta o el pedido, elige prendas,
//     cantidad y motivo; muestra cuánto se devuelve (100% o 90% si el
//     cliente ya no la quiere) y se completa en el momento.
//   - Historial del mes: devoluciones del mes con el total reembolsado.
// El cajero registra en tienda y consulta; aprobar y rechazar es del
// encargado, el administrador o el SUPER_ADMIN.
import { Component, OnInit } from '@angular/core';
import { AuthService } from '../../../../core/auth/auth.service';
import { CambiosService } from '../../../../core/services/cambios.service';
import {
  DevolucionesService, ItemDevolucion, MOTIVOS_DEVOLUCION, MotivoDevolucion, TipoCompra
} from '../../../../core/services/devoluciones.service';

type Pestana = 'SEGUIMIENTO' | 'TIENDA' | 'MES';

interface SeleccionItem {
  incluir: boolean;
  cantidad: number;
  motivo: MotivoDevolucion;
}

const ROLES_GESTION = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];
const PLAZO_RECOJO_HORAS = 48;

// Fecha local en el formato de <input type="datetime-local"> (AAAA-MM-DDTHH:mm).
function fechaLocal(fecha: Date): string {
  const d = (n: number) => String(n).padStart(2, '0');
  return `${fecha.getFullYear()}-${d(fecha.getMonth() + 1)}-${d(fecha.getDate())}T${d(fecha.getHours())}:${d(fecha.getMinutes())}`;
}

function mesActual(): string {
  const hoy = new Date();
  return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}`;
}

@Component({
  selector: 'app-devoluciones-tienda',
  templateUrl: './devoluciones-tienda.component.html',
  styleUrls: ['./devoluciones-tienda.component.scss']
})
export class DevolucionesTiendaComponent implements OnInit {
  pestana: Pestana = 'SEGUIMIENTO';
  esGestor = false;
  mensaje: string | null = null;
  error: string | null = null;
  readonly motivos = MOTIVOS_DEVOLUCION;

  // ---- Registrar en tienda
  tipoCompra: TipoCompra = 'VENTA';
  numeroCompra: number | null = null;
  buscandoCompra = false;
  compra: any = null;
  seleccion: { [idItem: number]: SeleccionItem } = {};
  montos: any = null;
  calculando = false;
  condicionesOk = false;
  observacion = '';
  registrando = false;

  // ---- Seguimiento
  filtroEstado = 'SOLICITADA';
  filtroModalidad = '';
  devoluciones: any[] = [];
  cargando = false;
  repartidores: any[] = [];
  accion: { id: number; tipo: 'APROBAR' | 'RECHAZAR' } | null = null;
  aprobacion = { id_repartidor: null as number | null, fecha: '' };
  motivoRechazo = '';
  procesando = false;

  // ---- Historial del mes
  mes = mesActual();
  devolucionesMes: any[] = [];
  cargandoMes = false;

  // ---- Nota de devolución
  nota: any = null;

  readonly estados = [
    { valor: 'SOLICITADA', texto: 'Por aprobar' },
    { valor: 'PROGRAMADA', texto: 'Recojo programado' },
    { valor: 'EN_CAMINO', texto: 'En camino' },
    { valor: 'COMPLETADA', texto: 'Completadas' },
    { valor: 'RECHAZADA', texto: 'Rechazadas' },
    { valor: '', texto: 'Todas' }
  ];

  constructor(
    private devolucionesService: DevolucionesService,
    private cambiosService: CambiosService,
    private authService: AuthService
  ) {
    this.esGestor = this.authService.obtenerRoles().some(rol => ROLES_GESTION.includes(rol));
  }

  ngOnInit(): void {
    if (this.esGestor) {
      this.cambiosService.repartidores().subscribe({
        next: (lista: any) => this.repartidores = lista || [],
        error: () => this.repartidores = []
      });
    }
    this.cargarSeguimiento();
  }

  cambiarPestana(pestana: Pestana): void {
    this.pestana = pestana;
    this.mensaje = null;
    this.error = null;
    if (pestana === 'SEGUIMIENTO') {
      this.cargarSeguimiento();
    } else if (pestana === 'MES') {
      this.cargarMes();
    }
  }

  private textoError(err: any, defecto: string): string {
    return err?.error?.error || err?.error?.detail || defecto;
  }

  // ---------------------------------------------------------------- registrar en tienda
  buscarCompra(limpiarMensaje = true): void {
    if (!this.numeroCompra || this.numeroCompra < 1) {
      this.error = 'Escribe el número de la venta o del pedido.';
      return;
    }
    this.buscandoCompra = true;
    this.error = null;
    if (limpiarMensaje) {
      this.mensaje = null;
    }
    this.montos = null;
    this.condicionesOk = false;
    this.observacion = '';
    this.devolucionesService.buscarCompra(this.tipoCompra, this.numeroCompra).subscribe({
      next: (compra) => {
        this.compra = compra;
        this.seleccion = {};
        for (const item of compra.items || []) {
          this.seleccion[item.id_item] = { incluir: false, cantidad: 1, motivo: 'NO_LA_QUIERO' };
        }
        this.buscandoCompra = false;
      },
      error: (err) => {
        this.compra = null;
        this.buscandoCompra = false;
        this.error = this.textoError(err, 'No se encontró la compra.');
      }
    });
  }

  private itemsElegidos(): ItemDevolucion[] {
    const elegidos: ItemDevolucion[] = [];
    for (const item of this.compra?.items || []) {
      const sel = this.seleccion[item.id_item];
      if (sel && sel.incluir && !item.motivo_no_elegible) {
        elegidos.push({ id_item: item.id_item, cantidad: Number(sel.cantidad) || 1, motivo: sel.motivo });
      }
    }
    return elegidos;
  }

  get hayElegidos(): boolean {
    return this.itemsElegidos().length > 0;
  }

  // Recalcula los montos cada vez que cambia la selección.
  recalcular(): void {
    const items = this.itemsElegidos();
    this.montos = null;
    if (!this.compra || items.length === 0) {
      return;
    }
    this.calculando = true;
    this.error = null;
    this.devolucionesService.calcular(this.compra.tipo, this.compra.numero, items).subscribe({
      next: (montos) => {
        this.montos = montos;
        this.calculando = false;
      },
      error: (err) => {
        this.calculando = false;
        this.error = this.textoError(err, 'No se pudo calcular la devolución.');
      }
    });
  }

  registrar(): void {
    const items = this.itemsElegidos();
    if (!this.compra || items.length === 0) {
      this.error = 'Elige al menos una prenda.';
      return;
    }
    if (!this.condicionesOk) {
      this.error = 'Confirma que revisaste la prenda.';
      return;
    }
    this.registrando = true;
    this.error = null;
    this.devolucionesService.registrarTienda({
      tipo: this.compra.tipo,
      numero: this.compra.numero,
      items,
      condiciones_ok: true,
      observacion: this.observacion.trim() || undefined
    }).subscribe({
      next: (devolucion) => {
        this.registrando = false;
        this.mensaje = `Devolución ${devolucion.numero_nota} registrada: se devuelve Bs ${devolucion.monto_reembolso} (${devolucion.metodo_reembolso_display}).`;
        this.nota = devolucion;
        this.buscarCompra(false);
      },
      error: (err) => {
        this.registrando = false;
        this.error = this.textoError(err, 'No se pudo registrar la devolución.');
      }
    });
  }

  // ---------------------------------------------------------------- seguimiento
  cargarSeguimiento(): void {
    this.cargando = true;
    this.devolucionesService.listar({
      estado: this.filtroEstado,
      modalidad: this.filtroModalidad,
      page_size: 50
    }).subscribe({
      next: (data: any) => {
        this.devoluciones = data?.results || data || [];
        this.cargando = false;
      },
      error: (err) => {
        this.devoluciones = [];
        this.cargando = false;
        this.error = this.textoError(err, 'No se pudieron cargar las devoluciones.');
      }
    });
  }

  filtrarEstado(estado: string): void {
    this.filtroEstado = estado;
    this.accion = null;
    this.cargarSeguimiento();
  }

  get fechaMinima(): string {
    return fechaLocal(new Date());
  }

  get fechaMaxima(): string {
    return fechaLocal(new Date(Date.now() + PLAZO_RECOJO_HORAS * 3600 * 1000));
  }

  abrirAccion(devolucion: any, tipo: 'APROBAR' | 'RECHAZAR'): void {
    this.accion = { id: devolucion.id_devolucion, tipo };
    this.error = null;
    this.mensaje = null;
    this.aprobacion = {
      id_repartidor: this.repartidores.length === 1 ? this.repartidores[0].id_usuario : null,
      fecha: fechaLocal(new Date(Date.now() + 2 * 3600 * 1000))
    };
    this.motivoRechazo = '';
  }

  cerrarAccion(): void {
    this.accion = null;
  }

  aprobar(devolucion: any): void {
    if (!this.aprobacion.id_repartidor || !this.aprobacion.fecha) {
      this.error = 'Elige el repartidor y la fecha del recojo.';
      return;
    }
    this.procesando = true;
    this.error = null;
    const fecha = new Date(this.aprobacion.fecha).toISOString();
    this.devolucionesService.aprobar(devolucion.id_devolucion, this.aprobacion.id_repartidor, fecha).subscribe({
      next: (actualizada) => {
        this.procesando = false;
        this.accion = null;
        this.mensaje = `Devolución ${actualizada.numero_nota}: recojo programado con ${actualizada.repartidor}.`;
        this.cargarSeguimiento();
      },
      error: (err) => {
        this.procesando = false;
        this.error = this.textoError(err, 'No se pudo aprobar la devolución.');
      }
    });
  }

  rechazar(devolucion: any): void {
    if (!this.motivoRechazo.trim()) {
      this.error = 'Escribe el motivo del rechazo.';
      return;
    }
    this.procesando = true;
    this.error = null;
    this.devolucionesService.rechazar(devolucion.id_devolucion, this.motivoRechazo.trim()).subscribe({
      next: (actualizada) => {
        this.procesando = false;
        this.accion = null;
        this.mensaje = `Devolución ${actualizada.numero_nota} rechazada.`;
        this.cargarSeguimiento();
      },
      error: (err) => {
        this.procesando = false;
        this.error = this.textoError(err, 'No se pudo rechazar la devolución.');
      }
    });
  }

  // ---------------------------------------------------------------- historial del mes
  cargarMes(): void {
    if (!this.mes) {
      this.mes = mesActual();
    }
    this.cargandoMes = true;
    this.devolucionesService.listar({ mes: this.mes, page_size: 100 }).subscribe({
      next: (data: any) => {
        this.devolucionesMes = data?.results || data || [];
        this.cargandoMes = false;
      },
      error: (err) => {
        this.devolucionesMes = [];
        this.cargandoMes = false;
        this.error = this.textoError(err, 'No se pudieron cargar las devoluciones del mes.');
      }
    });
  }

  private sumaCompletadas(campo: string): number {
    return this.devolucionesMes
      .filter(d => d.estado === 'COMPLETADA' && !d.es_anterior)
      .reduce((total, d) => total + Number(d[campo] || 0), 0);
  }

  get totalReembolsado(): number {
    return this.sumaCompletadas('monto_reembolso');
  }

  get totalRetenido(): number {
    return this.sumaCompletadas('monto_retenido');
  }

  get completadasMes(): number {
    return this.devolucionesMes.filter(d => d.estado === 'COMPLETADA').length;
  }

  get enProcesoMes(): number {
    return this.devolucionesMes.filter(d => ['SOLICITADA', 'PROGRAMADA', 'EN_CAMINO'].includes(d.estado)).length;
  }

  // ---------------------------------------------------------------- nota de devolución
  verNota(devolucion: any): void {
    this.nota = devolucion;
  }

  cerrarNota(): void {
    this.nota = null;
  }

  imprimirNota(): void {
    window.print();
  }

  // True si el monto (texto decimal del backend) es mayor que cero.
  positivo(valor: any): boolean {
    return Number(valor || 0) > 0;
  }

  claseEstado(devolucion: any): string {
    return 'estado--' + String(devolucion.estado || '').toLowerCase();
  }
}