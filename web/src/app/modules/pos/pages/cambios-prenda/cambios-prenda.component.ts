// web/src/app/modules/pos/pages/cambios-prenda/cambios-prenda.component.ts
//
// NUEVO (Fase 2 - CU05 / CU06): cambio de prenda por talla o color.
// Tres pestañas:
//   - Registrar en tienda: busca la venta o el pedido, elige la prenda, el
//     motivo y la nueva talla/color; se completa en el momento (nota NC-...).
//   - Seguimiento: solicitudes de los clientes (delivery). El encargado o el
//     administrador asigna repartidor y fecha de visita (máximo 48 h) o la
//     rechaza; se ve el avance hasta "Completado".
//   - Consulta del mes (CU06): totales por estado, motivo, modalidad,
//     sucursal y prendas más cambiadas, con la lista de cambios del mes.
// El cajero registra en tienda y consulta; aprobar y rechazar es del
// encargado, el administrador o el SUPER_ADMIN.
import { Component, OnInit } from '@angular/core';
import { AuthService } from '../../../../core/auth/auth.service';
import { CambiosService, MotivoCambio } from '../../../../core/services/cambios.service';

type Pestana = 'TIENDA' | 'SEGUIMIENTO' | 'MES';

const ROLES_GESTION = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];
const PLAZO_VISITA_HORAS = 48;

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
  selector: 'app-cambios-prenda',
  templateUrl: './cambios-prenda.component.html',
  styleUrls: ['./cambios-prenda.component.scss']
})
export class CambiosPrendaComponent implements OnInit {
  pestana: Pestana = 'SEGUIMIENTO';
  esGestor = false;
  mensaje: string | null = null;
  error: string | null = null;

  // ---- Registrar en tienda
  tipoCompra: 'VENTA' | 'PEDIDO' = 'VENTA';
  numeroCompra: number | null = null;
  buscandoCompra = false;
  compra: any = null;
  itemSel: any = null;
  opciones: any = null;
  cargandoOpciones = false;
  form = {
    motivo: 'NO_LE_QUEDA' as MotivoCambio,
    id_variante: null as number | null,
    cantidad: 1,
    condiciones_ok: false,
    observacion: ''
  };
  registrando = false;

  // ---- Seguimiento
  filtroEstado = 'SOLICITADO';
  filtroModalidad = '';
  cambios: any[] = [];
  cargando = false;
  repartidores: any[] = [];
  accion: { id: number; tipo: 'APROBAR' | 'RECHAZAR' } | null = null;
  aprobacion = { id_repartidor: null as number | null, fecha: '' };
  motivoRechazo = '';
  procesando = false;

  // ---- Consulta del mes (CU06)
  mes = mesActual();
  resumen: any = null;
  cambiosMes: any[] = [];
  cargandoMes = false;

  // ---- Nota de devolución
  nota: any = null;

  readonly estados = [
    { valor: 'SOLICITADO', texto: 'Por aprobar' },
    { valor: 'PROGRAMADO', texto: 'Programados' },
    { valor: 'EN_CAMINO', texto: 'En camino' },
    { valor: 'COMPLETADO', texto: 'Completados' },
    { valor: 'RECHAZADO', texto: 'Rechazados' },
    { valor: '', texto: 'Todos' }
  ];

  constructor(private cambiosService: CambiosService, private authService: AuthService) {
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
  buscarCompra(): void {
    if (!this.numeroCompra || this.numeroCompra < 1) {
      this.error = 'Escribe el número de la venta o del pedido.';
      return;
    }
    this.buscandoCompra = true;
    this.error = null;
    this.mensaje = null;
    this.itemSel = null;
    this.opciones = null;
    this.cambiosService.buscarCompra(this.tipoCompra, this.numeroCompra).subscribe({
      next: (compra) => {
        this.compra = compra;
        this.buscandoCompra = false;
      },
      error: (err) => {
        this.compra = null;
        this.buscandoCompra = false;
        this.error = this.textoError(err, 'No se encontró la compra.');
      }
    });
  }

  elegirItem(item: any): void {
    if (item.motivo_no_elegible) {
      return;
    }
    this.itemSel = item;
    this.opciones = null;
    this.error = null;
    this.form = { motivo: 'NO_LE_QUEDA', id_variante: null, cantidad: 1, condiciones_ok: false, observacion: '' };
    this.cargandoOpciones = true;
    this.cambiosService.opciones({ id_venta_item: item.id_venta_item, id_orden_item: item.id_orden_item }).subscribe({
      next: (opciones) => {
        this.opciones = opciones;
        this.cargandoOpciones = false;
      },
      error: (err) => {
        this.cargandoOpciones = false;
        this.error = this.textoError(err, 'No se pudieron cargar las tallas disponibles.');
      }
    });
  }

  cancelarItem(): void {
    this.itemSel = null;
    this.opciones = null;
  }

  cambiarMotivo(): void {
    this.form.id_variante = null;
  }

  // ERROR_TIENDA: cualquier otra talla/color (la que le llegó por error).
  // NO_LE_QUEDA: misma prenda, mismo precio y con stock en la sucursal.
  get alternativasValidas(): any[] {
    const lista: any[] = this.opciones?.alternativas || [];
    if (this.form.motivo === 'ERROR_TIENDA') {
      return lista;
    }
    return lista.filter(a => a.mismo_precio && a.stock > 0);
  }

  registrar(): void {
    if (!this.itemSel || !this.form.id_variante) {
      this.error = this.form.motivo === 'ERROR_TIENDA'
        ? 'Elige la talla o el color que se entregó por error.'
        : 'Elige la nueva talla o color.';
      return;
    }
    if (!this.form.condiciones_ok) {
      this.error = 'Confirma que la prenda devuelta está sin uso y con etiqueta.';
      return;
    }
    this.registrando = true;
    this.error = null;
    this.cambiosService.registrarTienda({
      id_venta_item: this.itemSel.id_venta_item,
      id_orden_item: this.itemSel.id_orden_item,
      motivo: this.form.motivo,
      id_variante: this.form.id_variante,
      cantidad: this.form.cantidad,
      condiciones_ok: true,
      observacion: this.form.observacion.trim() || undefined
    }).subscribe({
      next: (cambio) => {
        this.registrando = false;
        this.itemSel = null;
        this.opciones = null;
        this.mensaje = `Cambio ${cambio.numero_nota} registrado: el cliente devolvió ${cambio.prenda_devuelta} y recibió ${cambio.prenda_entregada}.`;
        this.nota = cambio;
        this.buscarCompra();
      },
      error: (err) => {
        this.registrando = false;
        this.error = this.textoError(err, 'No se pudo registrar el cambio.');
      }
    });
  }

  // ---------------------------------------------------------------- seguimiento
  cargarSeguimiento(): void {
    this.cargando = true;
    this.cambiosService.listar({
      estado: this.filtroEstado,
      modalidad: this.filtroModalidad,
      page_size: 50
    }).subscribe({
      next: (data: any) => {
        this.cambios = data?.results || data || [];
        this.cargando = false;
      },
      error: (err) => {
        this.cambios = [];
        this.cargando = false;
        this.error = this.textoError(err, 'No se pudieron cargar los cambios.');
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
    return fechaLocal(new Date(Date.now() + PLAZO_VISITA_HORAS * 3600 * 1000));
  }

  abrirAccion(cambio: any, tipo: 'APROBAR' | 'RECHAZAR'): void {
    this.accion = { id: cambio.id_cambio, tipo };
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

  aprobar(cambio: any): void {
    if (!this.aprobacion.id_repartidor || !this.aprobacion.fecha) {
      this.error = 'Elige el repartidor y la fecha de la visita.';
      return;
    }
    this.procesando = true;
    this.error = null;
    const fecha = new Date(this.aprobacion.fecha).toISOString();
    this.cambiosService.aprobar(cambio.id_cambio, this.aprobacion.id_repartidor, fecha).subscribe({
      next: (actualizado) => {
        this.procesando = false;
        this.accion = null;
        this.mensaje = `Cambio ${actualizado.numero_nota} programado con ${actualizado.repartidor}.`;
        this.cargarSeguimiento();
      },
      error: (err) => {
        this.procesando = false;
        this.error = this.textoError(err, 'No se pudo aprobar el cambio.');
      }
    });
  }

  rechazar(cambio: any): void {
    if (!this.motivoRechazo.trim()) {
      this.error = 'Escribe el motivo del rechazo.';
      return;
    }
    this.procesando = true;
    this.error = null;
    this.cambiosService.rechazar(cambio.id_cambio, this.motivoRechazo.trim()).subscribe({
      next: (actualizado) => {
        this.procesando = false;
        this.accion = null;
        this.mensaje = `Cambio ${actualizado.numero_nota} rechazado.`;
        this.cargarSeguimiento();
      },
      error: (err) => {
        this.procesando = false;
        this.error = this.textoError(err, 'No se pudo rechazar el cambio.');
      }
    });
  }

  // ---------------------------------------------------------------- consulta del mes (CU06)
  cargarMes(): void {
    if (!this.mes) {
      this.mes = mesActual();
    }
    this.cargandoMes = true;
    this.cambiosService.resumenMes(this.mes).subscribe({
      next: (resumen) => this.resumen = resumen,
      error: (err) => {
        this.resumen = null;
        this.error = this.textoError(err, 'No se pudo cargar el resumen del mes.');
      }
    });
    this.cambiosService.listar({ mes: this.mes, page_size: 100 }).subscribe({
      next: (data: any) => {
        this.cambiosMes = data?.results || data || [];
        this.cargandoMes = false;
      },
      error: () => {
        this.cambiosMes = [];
        this.cargandoMes = false;
      }
    });
  }

  cantidad(objeto: any, clave: string): number {
    return objeto?.[clave] || 0;
  }

  // ---------------------------------------------------------------- nota de devolución
  verNota(cambio: any): void {
    this.nota = cambio;
  }

  cerrarNota(): void {
    this.nota = null;
  }

  claseEstado(cambio: any): string {
    return 'estado--' + String(cambio.estado || '').toLowerCase();
  }
}