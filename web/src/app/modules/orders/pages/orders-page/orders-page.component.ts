// web/src/app/modules/orders/pages/orders-page/orders-page.component.ts
//
// NUEVO (devoluciones): botón "Solicitar devolución" en pedidos con
// delivery ya entregados, con modal para elegir prendas + motivo. Se
// completa sola (sin aprobación de un encargado) y muestra el mensaje
// de disculpa que devuelve el backend según el motivo.
// MODIFICADO (devoluciones): el badge ahora distingue "Devuelto" (todas
// las prendas del pedido se devolvieron) y "Entregado (con devolución
// parcial)" (solo algunas), usando los campos devuelto/tiene_devolucion
// que ahora manda OrderSerializer. El botón de devolución se oculta si
// el pedido ya se devolvió por completo.
// MODIFICADO (SaaS): cada pedido muestra la tienda (empresa) donde se hizo,
// usando el campo empresa_nombre que manda OrderSerializer.
// MODIFICADO (Fase 2 - CU05): en pedidos con delivery entregados, botón
// "Solicitar cambio de talla o color" (7 días desde la entrega). El cliente
// elige la prenda, el motivo (le llegó otra talla/color o no le quedó) y la
// talla/color; cada prenda muestra el estado de su cambio y cuándo pasará
// el repartidor.
// MODIFICADO (Fase 2 - CU12): la devolución ahora reembolsa el dinero. El
// cliente elige prendas, cantidad y motivo (dañada / le llegó otra prenda:
// 100% y el envío; ya no la quiere: 90%, la empresa retiene el 10%), ve
// cuánto se le devolverá antes de confirmar y luego el estado del recojo y
// la nota de devolución. Los motivos de talla/color pasaron al cambio (CU05).
import { Component, OnDestroy, OnInit } from '@angular/core';
import { of, Subject, timer } from 'rxjs';
import { catchError, switchMap, takeUntil } from 'rxjs/operators';
import { ApiService } from '../../../../core/services/api.service';
import { CambiosService, MotivoCambio } from '../../../../core/services/cambios.service';
import {
  DevolucionesService, ItemDevolucion, MOTIVOS_DEVOLUCION, MotivoDevolucion
} from '../../../../core/services/devoluciones.service';
const PASOS_DELIVERY = [
  { clave: 'PENDIENTE', texto: 'Pedido recibido' },
  { clave: 'EN_PREPARACION', texto: 'En preparación' },
  { clave: 'EN_CAMINO', texto: 'En camino' },
  { clave: 'ENTREGADO', texto: 'Entregado' }
];
@Component({
  selector: 'app-orders-page',
  template: `
    <div class="orders-container">
      <h2>Mis pedidos</h2>
      <p class="hint">Esta pantalla se actualiza sola cada 10 segundos.</p>
      <div *ngIf="cargando">Cargando pedidos...</div>
      <p class="error" *ngIf="error">{{ error }}</p>
      <div class="empty" *ngIf="!cargando && !error && pedidos.length === 0">
        <p>Todavía no tienes pedidos.</p>
        <a routerLink="/catalog" class="btn btn-accent">Ir al catálogo</a>
      </div>
      <div class="order-card" *ngFor="let o of pedidos">
        <div class="order-head">
          <div>
            <strong>Pedido #{{ o.id_orden }}</strong>
            <span class="order-date">{{ o.fecha_creacion | date:'dd/MM/yyyy HH:mm' }}</span>
          </div>
          <span class="badge" [ngClass]="claseEstado(o)">{{ textoEstado(o) }}</span>
        </div>
        <p class="order-store" *ngIf="o.empresa_nombre">Tienda: {{ o.empresa_nombre }}</p>
        <ul class="order-items">
          <li *ngFor="let i of o.items">
            <div class="item-row">
              <span>{{ i.cantidad }} x {{ i.variante }}</span>
              <span>Bs {{ i.subtotal }}</span>
            </div>
            <div class="item-cambio" *ngIf="i.cambio" [ngClass]="'cambio-' + i.cambio.estado.toLowerCase()">
              <strong>Cambio {{ i.cambio.numero_nota }} · {{ i.cambio.estado_display }}</strong>
              <span>{{ i.cambio.mensaje_cliente }}</span>
            </div>
          </li>
        </ul>
        <div class="order-total">
          <span *ngIf="o.tipo_entrega === 'DELIVERY'">Envío: Bs {{ o.costo_envio }}</span>
          <strong>Total: Bs {{ o.total }}</strong>
        </div>
        <div class="order-delivery" *ngIf="o.tipo_entrega === 'DELIVERY' && o.delivery">
          <p>
            Entrega en: {{ o.delivery.direccion }}
            <span *ngIf="o.delivery.referencia">({{ o.delivery.referencia }})</span>
          </p>
          <p *ngIf="o.delivery.repartidor">Repartidor: {{ o.delivery.repartidor }}</p>
          <ol class="timeline">
            <li *ngFor="let p of pasos; let idx = index"
                [class.done]="idx <= indicePaso(o)"
                [class.current]="idx === indicePaso(o)">
              <span class="dot"></span>{{ p.texto }}
            </li>
          </ol>
        </div>
        <p class="order-pickup" *ngIf="o.tipo_entrega !== 'DELIVERY'">
          Retiro en sucursal: {{ o.sucursal }}
        </p>
        <!-- NUEVO (CU12): devoluciones del pedido con su reembolso -->
        <div class="order-devolucion" *ngFor="let d of o.devoluciones" [ngClass]="'devolucion-' + d.estado.toLowerCase()">
          <strong>Devolución {{ d.numero_nota }} · {{ d.estado_display }}</strong>
          <span>{{ d.mensaje_cliente }}</span>
          <span class="detalle" *ngIf="!d.es_anterior && d.estado !== 'RECHAZADA'">{{ d.resumen_reembolso }}</span>
        </div>
        <p class="order-cambio-plazo" *ngIf="puedeCambiar(o) || puedeDevolver(o)">
          Puedes pedir un cambio de talla o color o una devolución hasta el
          {{ (o.devolucion_vence || o.cambio_vence) | date:'dd/MM/yyyy HH:mm' }}.
        </p>
        <div class="order-actions" *ngIf="puedeDevolver(o) || puedeCambiar(o)">
          <button class="btn btn-link" *ngIf="puedeCambiar(o)" (click)="abrirCambio(o)">Solicitar cambio de talla o color</button>
          <button class="btn btn-link" *ngIf="puedeDevolver(o)" (click)="abrirDevolucion(o)">Solicitar devolución</button>
        </div>
      </div>
    </div>
    <!-- NUEVO (CU05): solicitud de cambio de talla o color -->
    <div class="modal-overlay" *ngIf="pedidoCambio" (click)="cerrarCambio()">
      <div class="modal" (click)="$event.stopPropagation()">
        <h3>Cambio de talla o color · Pedido #{{ pedidoCambio.id_orden }}</h3>
        <div class="mensajes-exito" *ngIf="cambioCreado">
          <p>Solicitud {{ cambioCreado.numero_nota }} enviada.</p>
          <p>{{ cambioCreado.mensaje_cliente }}</p>
          <button class="btn btn-primary" (click)="cerrarCambio()">Cerrar</button>
        </div>
        <div *ngIf="!cambioCreado">
          <p class="error" *ngIf="errorCambio">{{ errorCambio }}</p>
          <div class="form-group">
            <label>Prenda</label>
            <select [ngModel]="itemCambio" (ngModelChange)="itemCambio = $event; elegirItemCambio()">
              <option [ngValue]="null">-- Elige la prenda --</option>
              <option *ngFor="let i of itemsCambiables(pedidoCambio)" [ngValue]="i">{{ i.variante }}</option>
            </select>
          </div>
          <p class="cargando" *ngIf="cargandoOpciones">Cargando tallas y colores...</p>
          <ng-container *ngIf="opcionesCambio">
            <div class="radio-group">
              <label class="checkbox-row">
                <input type="radio" name="motivoCambio" value="ERROR_TIENDA" [(ngModel)]="motivoCambio"
                       (ngModelChange)="varianteCambio = null">
                Me llegó otra talla o color
              </label>
              <label class="checkbox-row">
                <input type="radio" name="motivoCambio" value="NO_LE_QUEDA" [(ngModel)]="motivoCambio"
                       (ngModelChange)="varianteCambio = null">
                No me quedó, quiero otra talla o color
              </label>
            </div>
            <div class="form-group">
              <label>{{ motivoCambio === 'ERROR_TIENDA' ? '¿Qué talla y color te llegó?' : '¿Por cuál la quieres cambiar?' }}</label>
              <select [(ngModel)]="varianteCambio">
                <option [ngValue]="null">-- Elige --</option>
                <option *ngFor="let a of alternativasCambio()" [ngValue]="a.id_variante">
                  Talla {{ a.talla }} · {{ a.color }}
                </option>
              </select>
              <small class="ayuda" *ngIf="motivoCambio === 'NO_LE_QUEDA' && alternativasCambio().length === 0">
                No hay otra talla o color disponible al mismo precio en la tienda.
              </small>
              <small class="ayuda" *ngIf="motivoCambio === 'ERROR_TIENDA'">
                El repartidor recogerá la prenda que te llegó y te entregará {{ opcionesCambio.prenda }}.
              </small>
            </div>
            <div class="form-group">
              <label>Comentario (opcional)</label>
              <input type="text" [(ngModel)]="observacionCambio" placeholder="Ej.: me queda ajustada">
            </div>
            <p class="ayuda">La prenda debe estar sin uso y con etiqueta. El repartidor pasará en un máximo de 48 horas.</p>
          </ng-container>
          <div class="modal-actions">
            <button class="btn" (click)="cerrarCambio()">Cancelar</button>
            <button class="btn btn-primary" [disabled]="enviandoCambio || !varianteCambio" (click)="enviarCambio()">
              {{ enviandoCambio ? 'Enviando...' : 'Solicitar cambio' }}
            </button>
          </div>
        </div>
      </div>
    </div>
    <!-- MODIFICADO (CU12): devolución con reembolso -->
    <div class="modal-overlay" *ngIf="pedidoDevolucion" (click)="cerrarDevolucion()">
      <div class="modal" (click)="$event.stopPropagation()">
        <h3>Devolver prendas del Pedido #{{ pedidoDevolucion.id_orden }}</h3>
        <div class="mensajes-exito" *ngIf="devolucionCreada">
          <p>Solicitud {{ devolucionCreada.numero_nota }} enviada.</p>
          <p>{{ devolucionCreada.mensaje_cliente }}</p>
          <p class="detalle-reembolso">{{ devolucionCreada.resumen_reembolso }}</p>
          <button class="btn btn-primary" (click)="cerrarDevolucion()">Cerrar</button>
        </div>
        <div *ngIf="!devolucionCreada">
          <p class="error" *ngIf="errorDevolucion">{{ errorDevolucion }}</p>
          <p class="cargando" *ngIf="!compraDevolucion && !errorDevolucion">Cargando prendas...</p>
          <ng-container *ngIf="compraDevolucion">
            <div class="devolucion-item" *ngFor="let item of compraDevolucion.items">
              <label class="checkbox-row" *ngIf="!item.motivo_no_elegible">
                <input type="checkbox" [(ngModel)]="seleccion[item.id_item].incluir" (ngModelChange)="recalcularDevolucion()">
                {{ item.prenda }} (puedes devolver {{ item.disponible }})
              </label>
              <p class="no-elegible" *ngIf="item.motivo_no_elegible">{{ item.prenda }}: {{ item.motivo_no_elegible }}</p>
              <div class="devolucion-fields" *ngIf="!item.motivo_no_elegible && seleccion[item.id_item].incluir">
                <div class="form-group" *ngIf="item.disponible > 1">
                  <label>Cantidad</label>
                  <input type="number" min="1" [max]="item.disponible" [(ngModel)]="seleccion[item.id_item].cantidad"
                         (ngModelChange)="recalcularDevolucion()">
                </div>
                <div class="form-group">
                  <label>Motivo</label>
                  <select [(ngModel)]="seleccion[item.id_item].motivo" (ngModelChange)="recalcularDevolucion()">
                    <option *ngFor="let m of motivos" [value]="m.valor">{{ m.texto }}</option>
                  </select>
                </div>
              </div>
            </div>
            <div class="resumen-montos" *ngIf="montosDevolucion">
              <div class="fila"><span>Prendas</span><span>Bs {{ montosDevolucion.monto_prendas }}</span></div>
              <div class="fila retencion" *ngIf="positivo(montosDevolucion.monto_retenido)">
                <span>La tienda se queda con el 10%</span><span>- Bs {{ montosDevolucion.monto_retenido }}</span>
              </div>
              <div class="fila" *ngIf="positivo(montosDevolucion.monto_envio)">
                <span>Te devolvemos el envío</span><span>+ Bs {{ montosDevolucion.monto_envio }}</span>
              </div>
              <div class="fila total"><span>Te devolveremos</span><span>Bs {{ montosDevolucion.monto_reembolso }}</span></div>
              <small class="ayuda" *ngIf="montosDevolucion.metodo_reembolso === 'STRIPE'">
                Se reembolsa a tu tarjeta cuando el repartidor recoja la prenda.
              </small>
            </div>
            <div class="form-group">
              <label>Comentario (opcional)</label>
              <input type="text" [(ngModel)]="observacionDevolucion" placeholder="Ej.: tiene una costura abierta">
            </div>
            <p class="ayuda">Si llegó dañada o te llegó otra prenda, te devolvemos el 100%. Si ya no la quieres,
              te devolvemos el 90%. La prenda debe estar sin uso y con etiqueta; el repartidor pasará a
              recogerla en un máximo de 48 horas.</p>
          </ng-container>
          <div class="modal-actions">
            <button class="btn" (click)="cerrarDevolucion()">Cancelar</button>
            <button class="btn btn-primary" [disabled]="enviandoDevolucion || !montosDevolucion" (click)="enviarDevolucion()">
              {{ enviandoDevolucion ? 'Enviando...' : 'Solicitar devolución' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .orders-container { padding: 2rem; max-width: 800px; margin: 0 auto; }
    h2 { color: #1a1a2e; margin-bottom: 0.25rem; }
    .hint { color: #999; font-size: 0.85rem; margin: 0 0 1.5rem; }
    .error { color: #f44336; }
    .empty { text-align: center; padding: 3rem; color: #999; }
    .empty .btn { margin-top: 1rem; display: inline-block; }
    .order-card {
      background: white; border-radius: 8px; padding: 1rem 1.25rem;
      margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }
    .order-head { display: flex; justify-content: space-between; align-items: center; }
    .order-date { margin-left: 0.75rem; font-size: 0.85rem; color: #999; }
    .order-store { margin: 0.35rem 0 0; font-size: 0.9rem; font-weight: 600; color: #0f3460; }
    .badge {
      padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.8rem;
      font-weight: 600; background: #eef3fb; color: #0f3460;
    }
    .badge.estado-entregado, .badge.estado-entregada { background: #e8f8f0; color: #1b7f4b; }
    .badge.estado-cancelada { background: #fdecea; color: #c62828; }
    .badge.estado-devuelto { background: #f3e8fd; color: #6a1b9a; }
    .badge.estado-devolucion-parcial { background: #fff3e0; color: #e65100; }
    .order-items { list-style: none; padding: 0; margin: 0.75rem 0; }
    .order-items li { padding: 0.25rem 0; color: #1a1a2e; font-size: 0.95rem; }
    .item-row { display: flex; justify-content: space-between; }
    .item-cambio {
      display: flex; flex-direction: column; gap: 0.15rem; margin: 0.35rem 0 0.25rem;
      padding: 0.45rem 0.6rem; border-radius: 6px; font-size: 0.82rem;
      background: #eef3fb; color: #0f3460;
    }
    .item-cambio.cambio-completado { background: #e8f8f0; color: #1b7f4b; }
    .item-cambio.cambio-rechazado { background: #fdecea; color: #c62828; }
    .item-cambio.cambio-solicitado { background: #fff8e1; color: #8a6d00; }
    .order-cambio-plazo { margin: 0.75rem 0 0; font-size: 0.85rem; color: #0f3460; }
    .radio-group { display: flex; flex-direction: column; gap: 0.4rem; margin: 0.75rem 0; }
    .ayuda { display: block; font-size: 0.8rem; color: #777; margin-top: 0.3rem; }
    .cargando { color: #777; font-size: 0.85rem; }
    .order-actions .btn-link + .btn-link { margin-left: 1rem; }
    .order-total {
      display: flex; justify-content: space-between; align-items: center;
      border-top: 1px solid #eee; padding-top: 0.5rem; color: #1a1a2e;
    }
    .order-delivery { margin-top: 0.75rem; font-size: 0.9rem; color: #444; }
    .order-delivery p { margin: 0.25rem 0; }
    .order-pickup { margin: 0.75rem 0 0; font-size: 0.9rem; color: #444; }
    .order-devolucion {
      display: flex; flex-direction: column; gap: 0.15rem; margin: 0.75rem 0 0;
      padding: 0.5rem 0.7rem; border-radius: 6px; font-size: 0.82rem;
      background: #f3e8fd; color: #6a1b9a;
    }
    .order-devolucion .detalle { color: #444; }
    .order-devolucion.devolucion-completada { background: #e8f8f0; color: #1b7f4b; }
    .order-devolucion.devolucion-rechazada { background: #fdecea; color: #c62828; }
    .no-elegible { color: #999; font-size: 0.85rem; margin: 0; }
    .resumen-montos { border: 1px solid #eee; border-radius: 8px; padding: 0.6rem 0.8rem; margin: 0.75rem 0; }
    .resumen-montos .fila { display: flex; justify-content: space-between; font-size: 0.9rem; padding: 0.15rem 0; }
    .resumen-montos .retencion { color: #c62828; }
    .resumen-montos .total { border-top: 1px solid #eee; margin-top: 0.25rem; padding-top: 0.4rem; font-weight: 700; color: #1b7f4b; }
    .detalle-reembolso { color: #444 !important; font-size: 0.85rem; }
    .timeline { display: flex; list-style: none; padding: 0; margin: 1rem 0 0; }
    .timeline li {
      flex: 1; text-align: center; font-size: 0.8rem; color: #aaa; position: relative;
    }
    .timeline li::before {
      content: ''; position: absolute; top: 6px; left: -50%;
      width: 100%; height: 2px; background: #ddd;
    }
    .timeline li:first-child::before { display: none; }
    .timeline li.done { color: #0f3460; }
    .timeline li.done::before { background: #0f3460; }
    .timeline li.current { font-weight: 700; }
    .timeline .dot {
      display: block; width: 14px; height: 14px; border-radius: 50%;
      background: #ddd; margin: 0 auto 6px; position: relative; z-index: 1;
    }
    .timeline li.done .dot { background: #0f3460; }
    .order-actions { margin-top: 0.75rem; text-align: right; }
    .btn-link {
      background: none; border: none; color: #0f3460; font-weight: 600;
      text-decoration: underline; cursor: pointer; padding: 0;
    }
    .modal-overlay {
      position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5);
      display: flex; align-items: center; justify-content: center; z-index: 1000;
    }
    .modal {
      background: white; border-radius: 10px; padding: 1.5rem;
      width: 90%; max-width: 480px; max-height: 85vh; overflow-y: auto;
    }
    .modal h3 { margin-top: 0; color: #1a1a2e; }
    .devolucion-item { border-top: 1px solid #eee; padding: 0.75rem 0; }
    .checkbox-row { display: flex; align-items: center; gap: 0.5rem; cursor: pointer; }
    .devolucion-fields { margin-top: 0.5rem; padding-left: 1.5rem; display: flex; gap: 1rem; }
    .form-group { flex: 1; }
    .form-group label { display: block; font-size: 0.8rem; color: #666; margin-bottom: 0.25rem; }
    .form-group input, .form-group select {
      width: 100%; padding: 0.4rem; border-radius: 6px; border: 1px solid #ddd;
    }
    .modal-actions {
      display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.5rem;
    }
    .btn { padding: 0.5rem 1rem; border-radius: 6px; border: 1px solid #ddd; background: white; cursor: pointer; }
    .btn-primary { background: #0f3460; color: white; border-color: #0f3460; }
    .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
    .mensajes-exito p { color: #1b7f4b; margin: 0.5rem 0; }
  `]
})
export class OrdersPageComponent implements OnInit, OnDestroy {
  pedidos: any[] = [];
  cargando = true;
  error: string | null = null;
  pasos = PASOS_DELIVERY;
  // MODIFICADO (CU12): devolución con reembolso.
  motivos = MOTIVOS_DEVOLUCION;
  pedidoDevolucion: any = null;
  compraDevolucion: any = null;
  seleccion: { [idItem: number]: { incluir: boolean; cantidad: number; motivo: MotivoDevolucion } } = {};
  montosDevolucion: any = null;
  observacionDevolucion = '';
  enviandoDevolucion = false;
  errorDevolucion: string | null = null;
  devolucionCreada: any = null;
  // NUEVO (CU05): solicitud de cambio de talla o color.
  pedidoCambio: any = null;
  itemCambio: any = null;
  opcionesCambio: any = null;
  cargandoOpciones = false;
  motivoCambio: MotivoCambio = 'ERROR_TIENDA';
  varianteCambio: number | null = null;
  observacionCambio = '';
  enviandoCambio = false;
  errorCambio: string | null = null;
  cambioCreado: any = null;
  private destroy$ = new Subject<void>();
  constructor(
    private api: ApiService,
    private cambiosService: CambiosService,
    private devolucionesService: DevolucionesService
  ) {}
  ngOnInit(): void {
    timer(0, 10000).pipe(
      switchMap(() =>
        this.api.get<any>('/sales/ordenes/').pipe(catchError(() => of(null)))
      ),
      takeUntil(this.destroy$)
    ).subscribe((data) => {
      this.cargando = false;
      if (data === null) {
        this.error = 'No se pudieron cargar tus pedidos. Reintentando...';
        return;
      }
      this.error = null;
      const lista: any[] = data.results || data;
      this.pedidos = lista.filter((o) => o.estado !== 'PENDIENTE');
    });
  }
  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
  indicePaso(o: any): number {
    const estado = o.delivery?.estado;
    const i = this.pasos.findIndex((p) => p.clave === estado);
    return i < 0 ? 0 : i;
  }
  // NUEVO (CU12): true si alguna devolución del pedido sigue en curso.
  devolucionEnCurso(o: any): boolean {
    return (o.devoluciones || []).some((d: any) => ['SOLICITADA', 'PROGRAMADA', 'EN_CAMINO'].includes(d.estado));
  }
  textoEstado(o: any): string {
    if (o.estado === 'CANCELADA') {
      return 'Cancelado';
    }
    if (this.devolucionEnCurso(o)) {
      return 'Devolución en curso';
    }
    if (o.devuelto) {
      return 'Devuelto';
    }
    if (o.tiene_devolucion) {
      return 'Entregado (devolución parcial)';
    }
    if (o.tipo_entrega === 'DELIVERY' && o.delivery) {
      return this.pasos[this.indicePaso(o)].texto;
    }
    return o.estado === 'ENTREGADA' ? 'Entregado' : 'Pagado';
  }
  claseEstado(o: any): string {
    if (this.devolucionEnCurso(o)) {
      return 'estado-devolucion-parcial';
    }
    if (o.devuelto) {
      return 'estado-devuelto';
    }
    if (o.tiene_devolucion) {
      return 'estado-devolucion-parcial';
    }
    if (o.tipo_entrega === 'DELIVERY' && o.delivery) {
      return 'estado-' + o.delivery.estado.toLowerCase();
    }
    return 'estado-' + String(o.estado).toLowerCase();
  }
  // MODIFICADO (CU12): plazo de 7 días y prendas por devolver (lo indica el backend).
  puedeDevolver(o: any): boolean {
    return o.tipo_entrega === 'DELIVERY' && !!o.puede_solicitar_devolucion;
  }
  positivo(valor: any): boolean {
    return Number(valor || 0) > 0;
  }
  abrirDevolucion(o: any): void {
    this.pedidoDevolucion = o;
    this.compraDevolucion = null;
    this.seleccion = {};
    this.montosDevolucion = null;
    this.observacionDevolucion = '';
    this.errorDevolucion = null;
    this.devolucionCreada = null;
    this.devolucionesService.buscarCompra('PEDIDO', o.id_orden).subscribe({
      next: (compra) => {
        if (compra.motivo_no_elegible) {
          this.errorDevolucion = compra.motivo_no_elegible;
          return;
        }
        for (const item of compra.items || []) {
          this.seleccion[item.id_item] = { incluir: false, cantidad: 1, motivo: 'NO_LA_QUIERO' };
        }
        this.compraDevolucion = compra;
      },
      error: (err) => {
        this.errorDevolucion = err.error?.error || 'No se pudieron cargar las prendas del pedido.';
      }
    });
  }
  cerrarDevolucion(): void {
    this.pedidoDevolucion = null;
  }
  private itemsDevolucion(): ItemDevolucion[] {
    const items: ItemDevolucion[] = [];
    for (const item of this.compraDevolucion?.items || []) {
      const sel = this.seleccion[item.id_item];
      if (sel && sel.incluir && !item.motivo_no_elegible) {
        items.push({ id_item: item.id_item, cantidad: Number(sel.cantidad) || 1, motivo: sel.motivo });
      }
    }
    return items;
  }
  // Muestra cuánto se devolverá cada vez que cambia la selección.
  recalcularDevolucion(): void {
    const items = this.itemsDevolucion();
    this.montosDevolucion = null;
    this.errorDevolucion = null;
    if (!this.pedidoDevolucion || items.length === 0) {
      return;
    }
    this.devolucionesService.calcular('PEDIDO', this.pedidoDevolucion.id_orden, items).subscribe({
      next: (montos) => this.montosDevolucion = montos,
      error: (err) => this.errorDevolucion = err.error?.error || 'No se pudo calcular la devolución.'
    });
  }
  enviarDevolucion(): void {
    const items = this.itemsDevolucion();
    if (!this.pedidoDevolucion || items.length === 0) {
      this.errorDevolucion = 'Selecciona al menos una prenda a devolver.';
      return;
    }
    this.enviandoDevolucion = true;
    this.errorDevolucion = null;
    this.devolucionesService.solicitar(
      this.pedidoDevolucion.id_orden, items, this.observacionDevolucion.trim() || undefined
    ).subscribe({
      next: (devolucion) => {
        this.enviandoDevolucion = false;
        this.devolucionCreada = devolucion;
      },
      error: (err) => {
        this.enviandoDevolucion = false;
        this.errorDevolucion = err.error?.error || 'No se pudo registrar la devolución.';
      }
    });
  }

  // ---------------------------------------------------------------- CU05 cambio de talla o color
  // Prendas del pedido que todavía no tienen un cambio (o cuyo cambio se rechazó).
  itemsCambiables(o: any): any[] {
    return (o.items || []).filter((i: any) => !i.cambio || i.cambio.estado === 'RECHAZADO');
  }

  puedeCambiar(o: any): boolean {
    return !!o.puede_solicitar_cambio && !o.devuelto && this.itemsCambiables(o).length > 0;
  }

  abrirCambio(o: any): void {
    this.pedidoCambio = o;
    this.itemCambio = null;
    this.opcionesCambio = null;
    this.motivoCambio = 'ERROR_TIENDA';
    this.varianteCambio = null;
    this.observacionCambio = '';
    this.errorCambio = null;
    this.cambioCreado = null;
  }

  cerrarCambio(): void {
    this.pedidoCambio = null;
  }

  elegirItemCambio(): void {
    this.opcionesCambio = null;
    this.varianteCambio = null;
    this.errorCambio = null;
    if (!this.itemCambio) {
      return;
    }
    this.cargandoOpciones = true;
    this.cambiosService.opciones({ id_orden_item: this.itemCambio.id_item }).subscribe({
      next: (opciones) => {
        this.cargandoOpciones = false;
        if (opciones.motivo_no_elegible) {
          this.errorCambio = opciones.motivo_no_elegible;
          return;
        }
        this.opcionesCambio = opciones;
      },
      error: (err) => {
        this.cargandoOpciones = false;
        this.errorCambio = err.error?.error || 'No se pudieron cargar las tallas disponibles.';
      }
    });
  }

  // Le llegó otra: cualquier otra talla/color. No le quedó: mismo precio y con stock.
  alternativasCambio(): any[] {
    const lista: any[] = this.opcionesCambio?.alternativas || [];
    if (this.motivoCambio === 'ERROR_TIENDA') {
      return lista;
    }
    return lista.filter((a: any) => a.mismo_precio && a.stock > 0);
  }

  enviarCambio(): void {
    if (!this.itemCambio || !this.varianteCambio) {
      this.errorCambio = 'Elige la prenda y la talla o color.';
      return;
    }
    this.enviandoCambio = true;
    this.errorCambio = null;
    this.cambiosService.solicitar({
      id_orden_item: this.itemCambio.id_item,
      motivo: this.motivoCambio,
      id_variante: this.varianteCambio,
      cantidad: 1,
      observacion: this.observacionCambio.trim() || undefined
    }).subscribe({
      next: (cambio) => {
        this.enviandoCambio = false;
        this.cambioCreado = cambio;
      },
      error: (err) => {
        this.enviandoCambio = false;
        this.errorCambio = err.error?.error || 'No se pudo solicitar el cambio.';
      }
    });
  }
}