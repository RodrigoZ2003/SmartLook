// web/src/app/modules/deliveries/pages/deliveries-page/deliveries-page.component.ts
//
// MODIFICADO (Fase 2 - CU05): pestaña "Cambios de prenda". El repartidor ve
// los cambios que le asignaron (dirección, qué recoger y qué entregar, fecha
// de la visita y límite de 48 h), marca "Salir a hacer el cambio" y
// "Completar cambio" confirmando que la prenda devuelta está sin uso y con
// etiqueta. El encargado/administrador ve los de toda la empresa.
// MODIFICADO (Fase 2 - CU12): pestaña "Devoluciones". El repartidor ve los
// recojos asignados (dirección, prendas, monto a reembolsar, fecha y límite
// de 48 h), marca "Salir a recoger" y "Completar devolución" después de
// revisar la prenda; ahí se repone el stock y se reembolsa al cliente.
import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subject, timer } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { ApiService } from '../../../../core/services/api.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { CambiosService } from '../../../../core/services/cambios.service';
import { DevolucionesService } from '../../../../core/services/devoluciones.service';

const ROLES_GESTION = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];

@Component({
  selector: 'app-deliveries-page',
  template: `
    <div class="deliveries-container">
      <h2>{{ esGestor ? 'Entregas' : 'Mis entregas' }}</h2>
      <p class="hint">Esta pantalla se actualiza sola cada 10 segundos.</p>

      <div class="tabs">
        <button type="button" [class.active]="vista === 'ENTREGAS'" (click)="cambiarVista('ENTREGAS')">Pedidos</button>
        <button type="button" [class.active]="vista === 'CAMBIOS'" (click)="cambiarVista('CAMBIOS')">
          Cambios de prenda
          <span class="tab-count" *ngIf="cambiosPorHacer > 0">{{ cambiosPorHacer }}</span>
        </button>
        <button type="button" [class.active]="vista === 'DEVOLUCIONES'" (click)="cambiarVista('DEVOLUCIONES')">
          Devoluciones
          <span class="tab-count" *ngIf="recojosPorHacer > 0">{{ recojosPorHacer }}</span>
        </button>
      </div>

      <ng-container *ngIf="vista === 'ENTREGAS'">
      <div class="filters">
        <button type="button" *ngFor="let f of filtros"
                [class.active]="filtro === f.valor" (click)="cambiarFiltro(f.valor)">
          {{ f.texto }}
        </button>
      </div>

      <p class="msg-ok" *ngIf="mensaje">{{ mensaje }}</p>
      <p class="msg-error" *ngIf="error">{{ error }}</p>
      <div *ngIf="cargando">Cargando entregas...</div>

      <div class="empty" *ngIf="!cargando && entregas.length === 0">
        <p>No hay entregas en esta lista.</p>
      </div>

      <div class="delivery-card" *ngFor="let d of entregas; trackBy: porId">
        <div class="card-head">
          <div>
            <strong>Entrega #{{ d.id_delivery }}</strong>
            <span class="muted">Orden #{{ d.orden }} · {{ d.sucursal }}</span>
          </div>
          <span class="badge" [ngClass]="'estado-' + d.estado.toLowerCase()">{{ texto(d.estado) }}</span>
        </div>

        <div class="card-body">
          <p><strong>Cliente:</strong> {{ d.cliente }}
            <span *ngIf="d.telefono_cliente"> · Tel. {{ d.telefono_cliente }}</span></p>
          <p><strong>Dirección:</strong> {{ d.direccion }}
            <span *ngIf="d.referencia">({{ d.referencia }})</span></p>
          <p class="muted">
            {{ d.prendas }} prenda(s) · {{ d.distancia_km }} km · Pagado Bs {{ d.total_orden }}
          </p>
          <p><strong>Repartidor:</strong> {{ d.repartidor || 'Sin asignar' }}</p>
          <a class="map-link" target="_blank" rel="noopener"
             [href]="enlaceMapa(d)">Cómo llegar</a>
        </div>

        <div class="card-actions">
          <ng-container *ngIf="esGestor && (d.estado === 'PENDIENTE' || d.estado === 'EN_PREPARACION')">
            <select [(ngModel)]="seleccion[d.id_delivery]">
              <option [ngValue]="null">-- Repartidor --</option>
              <option *ngFor="let r of repartidores" [ngValue]="r.id_usuario">{{ r.nombre }}</option>
            </select>
            <button type="button" class="btn-sec" [disabled]="procesando === d.id_delivery"
                    (click)="asignar(d)">Asignar</button>
          </ng-container>

          <button type="button" class="btn-main"
                  *ngIf="esGestor && d.estado === 'PENDIENTE'"
                  [disabled]="procesando === d.id_delivery"
                  (click)="ejecutar(d, 'preparar')">Preparar pedido</button>

          <button type="button" class="btn-main"
                  *ngIf="d.estado === 'EN_PREPARACION'"
                  [disabled]="procesando === d.id_delivery || !d.id_repartidor"
                  (click)="ejecutar(d, 'en-camino')">Salir a entregar</button>

          <button type="button" class="btn-main"
                  *ngIf="d.estado === 'EN_CAMINO'"
                  [disabled]="procesando === d.id_delivery"
                  (click)="ejecutar(d, 'entregar')">Marcar entregado</button>
        </div>
      </div>
      </ng-container>

      <!-- NUEVO (CU05): cambios de prenda con delivery -->
      <ng-container *ngIf="vista === 'CAMBIOS'">
        <div class="filters">
          <button type="button" *ngFor="let f of filtrosCambio"
                  [class.active]="filtroCambio === f.valor" (click)="filtroCambio = f.valor">
            {{ f.texto }}
          </button>
        </div>
        <p class="msg-ok" *ngIf="mensaje">{{ mensaje }}</p>
        <p class="msg-error" *ngIf="error">{{ error }}</p>
        <div class="empty" *ngIf="cambiosVisibles.length === 0">
          <p>No hay cambios en esta lista.</p>
        </div>
        <div class="delivery-card" *ngFor="let c of cambiosVisibles; trackBy: porCambio" [class.atrasado]="c.atrasado">
          <div class="card-head">
            <div>
              <strong>Cambio {{ c.numero_nota }}</strong>
              <span class="muted">{{ c.origen?.etiqueta }} · {{ c.sucursal }}</span>
            </div>
            <span class="badge" [ngClass]="'estado-' + c.estado.toLowerCase()">{{ c.estado_display }}</span>
          </div>
          <div class="card-body">
            <p><strong>Cliente:</strong> {{ c.cliente?.nombre }}
              <span *ngIf="c.cliente?.telefono"> · Tel. {{ c.cliente.telefono }}</span></p>
            <p *ngIf="c.entrega"><strong>Dirección:</strong> {{ c.entrega.direccion }}
              <span *ngIf="c.entrega.referencia">({{ c.entrega.referencia }})</span></p>
            <p class="recoger"><strong>Recoger:</strong> {{ c.prenda_devuelta }} ({{ c.cantidad }} u.)</p>
            <p class="entregar"><strong>Entregar:</strong> {{ c.prenda_entregada }}</p>
            <p><strong>Visita:</strong> {{ c.fecha_programada | date:'dd/MM/yyyy HH:mm' }}
              · límite {{ c.fecha_limite | date:'dd/MM/yyyy HH:mm' }}
              <span class="tag-atrasado" *ngIf="c.atrasado">Atrasado</span></p>
            <p *ngIf="esGestor"><strong>Repartidor:</strong> {{ c.repartidor || 'Sin asignar' }}</p>
            <p *ngIf="c.observacion" class="muted-text">Comentario: {{ c.observacion }}</p>
            <a class="map-link" target="_blank" rel="noopener" *ngIf="c.entrega"
               [href]="enlaceMapa(c.entrega)">Cómo llegar</a>
          </div>
          <div class="card-actions">
            <button type="button" class="btn-main" *ngIf="c.estado === 'PROGRAMADO'"
                    [disabled]="procesandoCambio === c.id_cambio" (click)="salirACambio(c)">
              Salir a hacer el cambio
            </button>
            <ng-container *ngIf="c.estado === 'EN_CAMINO'">
              <label class="check">
                <input type="checkbox" [(ngModel)]="condiciones[c.id_cambio]">
                La prenda devuelta está sin uso y con etiqueta
              </label>
              <button type="button" class="btn-main"
                      [disabled]="procesandoCambio === c.id_cambio || !condiciones[c.id_cambio]"
                      (click)="completarCambio(c)">Completar cambio</button>
            </ng-container>
            <span class="muted-text" *ngIf="c.estado === 'SOLICITADO'">
              Pendiente de aprobación en Punto de Venta &gt; Cambios de prenda.
            </span>
          </div>
        </div>
      </ng-container>

      <!-- NUEVO (CU12): recojo de devoluciones -->
      <ng-container *ngIf="vista === 'DEVOLUCIONES'">
        <div class="filters">
          <button type="button" *ngFor="let f of filtrosRecojo"
                  [class.active]="filtroRecojo === f.valor" (click)="filtroRecojo = f.valor">
            {{ f.texto }}
          </button>
        </div>
        <p class="msg-ok" *ngIf="mensaje">{{ mensaje }}</p>
        <p class="msg-error" *ngIf="error">{{ error }}</p>
        <div class="empty" *ngIf="recojosVisibles.length === 0">
          <p>No hay devoluciones en esta lista.</p>
        </div>
        <div class="delivery-card" *ngFor="let d of recojosVisibles; trackBy: porDevolucion" [class.atrasado]="d.atrasado">
          <div class="card-head">
            <div>
              <strong>Devolución {{ d.numero_nota }}</strong>
              <span class="muted">{{ d.origen?.etiqueta }} · {{ d.sucursal }}</span>
            </div>
            <span class="badge" [ngClass]="'estado-' + d.estado.toLowerCase()">{{ d.estado_display }}</span>
          </div>
          <div class="card-body">
            <p><strong>Cliente:</strong> {{ d.cliente }}
              <span *ngIf="d.cliente_contacto?.telefono"> · Tel. {{ d.cliente_contacto.telefono }}</span></p>
            <p *ngIf="d.entrega"><strong>Dirección:</strong> {{ d.entrega.direccion }}
              <span *ngIf="d.entrega.referencia">({{ d.entrega.referencia }})</span></p>
            <p class="recoger" *ngFor="let i of d.items">
              <strong>Recoger:</strong> {{ i.cantidad }} x {{ i.variante }} ({{ i.motivo_display }})
            </p>
            <p><strong>Se le devuelve:</strong> Bs {{ d.monto_reembolso }} ({{ d.metodo_reembolso_display }})</p>
            <p *ngIf="d.fecha_programada"><strong>Recojo:</strong> {{ d.fecha_programada | date:'dd/MM/yyyy HH:mm' }}
              · límite {{ d.fecha_limite | date:'dd/MM/yyyy HH:mm' }}
              <span class="tag-atrasado" *ngIf="d.atrasado">Atrasado</span></p>
            <p *ngIf="esGestor"><strong>Repartidor:</strong> {{ d.repartidor || 'Sin asignar' }}</p>
            <p *ngIf="d.observacion" class="muted-text">Comentario: {{ d.observacion }}</p>
            <a class="map-link" target="_blank" rel="noopener" *ngIf="d.entrega"
               [href]="enlaceMapa(d.entrega)">Cómo llegar</a>
          </div>
          <div class="card-actions">
            <button type="button" class="btn-main" *ngIf="d.estado === 'PROGRAMADA'"
                    [disabled]="procesandoRecojo === d.id_devolucion" (click)="salirARecoger(d)">
              Salir a recoger
            </button>
            <ng-container *ngIf="d.estado === 'EN_CAMINO'">
              <label class="check">
                <input type="checkbox" [(ngModel)]="revisadas[d.id_devolucion]">
                Revisé la prenda: sin uso y con etiqueta (si está dañada, el defecto no es por mal uso)
              </label>
              <button type="button" class="btn-main"
                      [disabled]="procesandoRecojo === d.id_devolucion || !revisadas[d.id_devolucion]"
                      (click)="completarRecojo(d)">Completar devolución</button>
            </ng-container>
            <span class="muted-text" *ngIf="d.estado === 'SOLICITADA'">
              Pendiente de aprobación en Punto de Venta &gt; Devoluciones.
            </span>
          </div>
        </div>
      </ng-container>
    </div>
  `,
  styles: [`
    .deliveries-container { padding: 2rem; max-width: 900px; margin: 0 auto; }
    h2 { color: #1a1a2e; margin-bottom: 0.25rem; }
    .hint { color: #999; font-size: 0.85rem; margin: 0 0 1rem; }
    .filters { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
    .filters button {
      padding: 0.4rem 0.9rem; border: 1px solid #d0d7e2; background: white;
      border-radius: 999px; cursor: pointer; font-size: 0.85rem; color: #1a1a2e;
    }
    .filters button.active { background: #0f3460; border-color: #0f3460; color: white; }
    .msg-ok { color: #1b7f4b; }
    .msg-error { color: #f44336; }
    .empty { text-align: center; padding: 3rem; color: #999; }
    .delivery-card {
      background: white; border-radius: 8px; padding: 1rem 1.25rem;
      margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }
    .card-head { display: flex; justify-content: space-between; align-items: center; }
    .muted { margin-left: 0.5rem; color: #999; font-size: 0.85rem; }
    .card-body p { margin: 0.35rem 0; color: #1a1a2e; font-size: 0.95rem; }
    .card-body .muted { margin-left: 0; }
    .map-link { font-size: 0.9rem; color: #0f3460; font-weight: 600; }
    .badge {
      padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.8rem;
      font-weight: 600; background: #eef3fb; color: #0f3460;
    }
    .badge.estado-en_preparacion { background: #fff4e0; color: #b26a00; }
    .badge.estado-en_camino { background: #e3f2fd; color: #1565c0; }
    .badge.estado-entregado { background: #e8f8f0; color: #1b7f4b; }
    .card-actions {
      display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center;
      margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid #eee;
    }
    .card-actions:empty { display: none; }
    .card-actions select {
      padding: 0.45rem; border: 1px solid #d0d7e2; border-radius: 6px; min-width: 180px;
    }
    .btn-main, .btn-sec {
      padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer;
    }
    .btn-main { background: #0f3460; color: white; border: 1px solid #0f3460; }
    .btn-sec { background: white; color: #0f3460; border: 1px solid #0f3460; }
    button:disabled { opacity: 0.5; cursor: default; }
    .tabs { display: flex; gap: 0.25rem; border-bottom: 2px solid #e0e0e0; margin-bottom: 1rem; }
    .tabs button {
      padding: 0.6rem 1rem; border: none; background: none; cursor: pointer;
      font-weight: 600; color: #777; border-bottom: 3px solid transparent; margin-bottom: -2px;
    }
    .tabs button.active { color: #0f3460; border-bottom-color: #0f3460; }
    .tab-count {
      margin-left: 0.35rem; padding: 0.05rem 0.5rem; border-radius: 999px;
      background: #0f3460; color: white; font-size: 0.75rem;
    }
    .delivery-card.atrasado { border-left: 4px solid #c0392b; }
    .badge.estado-programado { background: #e3f2fd; color: #0d47a1; }
    .badge.estado-completado { background: #e8f8f0; color: #1b7f4b; }
    .badge.estado-rechazado { background: #fdecea; color: #c62828; }
    .badge.estado-solicitado { background: #fff8e1; color: #8a6d00; }
    .badge.estado-solicitada { background: #fff8e1; color: #8a6d00; }
    .badge.estado-programada { background: #e3f2fd; color: #0d47a1; }
    .badge.estado-completada { background: #e8f8f0; color: #1b7f4b; }
    .badge.estado-rechazada { background: #fdecea; color: #c62828; }
    .recoger { color: #c0392b !important; }
    .entregar { color: #1b7f4b !important; font-weight: 600; }
    .tag-atrasado {
      margin-left: 0.4rem; padding: 0.05rem 0.5rem; border-radius: 999px;
      background: #fdecea; color: #c0392b; font-size: 0.75rem; font-weight: 700;
    }
    .muted-text { color: #888; font-size: 0.85rem; }
    .check { display: flex; align-items: center; gap: 0.4rem; font-size: 0.9rem; cursor: pointer; }
  `]
})
export class DeliveriesPageComponent implements OnInit, OnDestroy {
  entregas: any[] = [];
  repartidores: any[] = [];
  seleccion: { [idDelivery: number]: number | null } = {};
  cargando = true;
  error: string | null = null;
  mensaje: string | null = null;
  procesando: number | null = null;
  esGestor = false;
  filtro = '';
  // NUEVO (CU05): cambios de prenda con delivery.
  vista: 'ENTREGAS' | 'CAMBIOS' | 'DEVOLUCIONES' = 'ENTREGAS';
  cambios: any[] = [];
  filtroCambio = 'POR_HACER';
  procesandoCambio: number | null = null;
  condiciones: { [idCambio: number]: boolean } = {};
  filtrosCambio = [
    { valor: 'POR_HACER', texto: 'Por hacer' },
    { valor: 'COMPLETADO', texto: 'Completados' },
    { valor: '', texto: 'Todos' }
  ];

  // NUEVO (CU12): recojo de devoluciones.
  recojos: any[] = [];
  filtroRecojo = 'POR_HACER';
  procesandoRecojo: number | null = null;
  revisadas: { [idDevolucion: number]: boolean } = {};
  filtrosRecojo = [
    { valor: 'POR_HACER', texto: 'Por recoger' },
    { valor: 'COMPLETADA', texto: 'Completadas' },
    { valor: '', texto: 'Todas' }
  ];

  filtros = [
    { valor: '', texto: 'Todas' },
    { valor: 'PENDIENTE', texto: 'Pendientes' },
    { valor: 'EN_PREPARACION', texto: 'En preparación' },
    { valor: 'EN_CAMINO', texto: 'En camino' },
    { valor: 'ENTREGADO', texto: 'Entregadas' }
  ];

  private destroy$ = new Subject<void>();

  constructor(
    private api: ApiService,
    private auth: AuthService,
    private cambiosService: CambiosService,
    private devolucionesService: DevolucionesService
  ) {}

  ngOnInit(): void {
    this.esGestor = this.auth.obtenerRoles().some((r) => ROLES_GESTION.includes(r));
    if (this.esGestor) {
      this.api.get<any>('/sales/entregas/repartidores/').subscribe({
        next: (lista) => (this.repartidores = lista),
        error: () => (this.repartidores = [])
      });
    }
    // Consulta al abrir y luego cada 10 segundos.
    timer(0, 10000).pipe(takeUntil(this.destroy$)).subscribe(() => {
      this.cargar();
      this.cargarCambios();
      this.cargarRecojos();
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  porId(_: number, d: any): number {
    return d.id_delivery;
  }

  cambiarFiltro(valor: string): void {
    this.filtro = valor;
    this.cargando = true;
    this.cargar();
  }

  cargar(): void {
    const params: any = { page_size: 100 };
    if (this.filtro) {
      params.estado = this.filtro;
    }
    this.api.get<any>('/sales/entregas/', params).subscribe({
      next: (data) => {
        this.cargando = false;
        this.entregas = data.results || data;
        // Deja preseleccionado el repartidor ya asignado, sin pisar lo que el usuario esté eligiendo.
        for (const d of this.entregas) {
          if (d.id_repartidor && this.seleccion[d.id_delivery] == null) {
            this.seleccion[d.id_delivery] = d.id_repartidor;
          }
        }
      },
      error: () => {
        this.cargando = false;
        this.error = 'No se pudieron cargar las entregas. Reintentando...';
      }
    });
  }

  ejecutar(d: any, accion: string, body: any = {}): void {
    this.procesando = d.id_delivery;
    this.mensaje = null;
    this.error = null;
    this.api.post<any>(`/sales/entregas/${d.id_delivery}/${accion}/`, body).subscribe({
      next: () => {
        this.procesando = null;
        this.mensaje = `Entrega #${d.id_delivery} actualizada.`;
        this.cargar();
      },
      error: (err) => {
        this.procesando = null;
        this.error = err?.error?.error || err?.error?.detail || 'No se pudo completar la acción.';
      }
    });
  }

  asignar(d: any): void {
    const id = this.seleccion[d.id_delivery];
    if (!id) {
      this.error = 'Elige un repartidor antes de asignar.';
      return;
    }
    this.ejecutar(d, 'asignar', { id_repartidor: id });
  }

  texto(estado: string): string {
    const t: { [k: string]: string } = {
      PENDIENTE: 'Pendiente',
      EN_PREPARACION: 'En preparación',
      EN_CAMINO: 'En camino',
      ENTREGADO: 'Entregado'
    };
    return t[estado] || estado;
  }

  // Enlace a Google Maps con la ruta hasta el punto de entrega (no requiere clave).
  enlaceMapa(d: any): string {
    return `https://www.google.com/maps/dir/?api=1&destination=${d.latitud},${d.longitud}`;
  }

  // ---------------------------------------------------------------- CU05 cambios de prenda
  cambiarVista(vista: 'ENTREGAS' | 'CAMBIOS' | 'DEVOLUCIONES'): void {
    this.vista = vista;
    this.mensaje = null;
    this.error = null;
  }

  porCambio(_: number, c: any): number {
    return c.id_cambio;
  }

  // Cambios con delivery visibles para el usuario (el repartidor, solo los suyos).
  cargarCambios(): void {
    this.cambiosService.listar({ modalidad: 'DELIVERY', page_size: 100 }).subscribe({
      next: (data: any) => this.cambios = data?.results || data || [],
      error: () => this.cambios = []
    });
  }

  get cambiosPorHacer(): number {
    return this.cambios.filter((c) => c.estado === 'PROGRAMADO' || c.estado === 'EN_CAMINO').length;
  }

  get cambiosVisibles(): any[] {
    if (this.filtroCambio === 'POR_HACER') {
      return this.cambios.filter((c) => c.estado === 'PROGRAMADO' || c.estado === 'EN_CAMINO');
    }
    if (this.filtroCambio) {
      return this.cambios.filter((c) => c.estado === this.filtroCambio);
    }
    return this.cambios;
  }

  salirACambio(c: any): void {
    this.procesandoCambio = c.id_cambio;
    this.mensaje = null;
    this.error = null;
    this.cambiosService.enCamino(c.id_cambio).subscribe({
      next: () => {
        this.procesandoCambio = null;
        this.mensaje = `Cambio ${c.numero_nota} en camino.`;
        this.cargarCambios();
      },
      error: (err) => {
        this.procesandoCambio = null;
        this.error = err?.error?.error || err?.error?.detail || 'No se pudo actualizar el cambio.';
      }
    });
  }

  completarCambio(c: any): void {
    this.procesandoCambio = c.id_cambio;
    this.mensaje = null;
    this.error = null;
    this.cambiosService.completar(c.id_cambio, !!this.condiciones[c.id_cambio]).subscribe({
      next: () => {
        this.procesandoCambio = null;
        this.mensaje = `Cambio ${c.numero_nota} completado. Se generó la nota de devolución.`;
        this.cargarCambios();
      },
      error: (err) => {
        this.procesandoCambio = null;
        this.error = err?.error?.error || err?.error?.detail || 'No se pudo completar el cambio.';
      }
    });
  }

  // ---------------------------------------------------------------- CU12 recojo de devoluciones
  porDevolucion(_: number, d: any): number {
    return d.id_devolucion;
  }

  // Devoluciones con recojo visibles para el usuario (el repartidor, solo las suyas).
  cargarRecojos(): void {
    this.devolucionesService.listar({ modalidad: 'DELIVERY', page_size: 100 }).subscribe({
      next: (data: any) => this.recojos = data?.results || data || [],
      error: () => this.recojos = []
    });
  }

  get recojosPorHacer(): number {
    return this.recojos.filter((d) => d.estado === 'PROGRAMADA' || d.estado === 'EN_CAMINO').length;
  }

  get recojosVisibles(): any[] {
    if (this.filtroRecojo === 'POR_HACER') {
      return this.recojos.filter((d) => d.estado === 'PROGRAMADA' || d.estado === 'EN_CAMINO');
    }
    if (this.filtroRecojo) {
      return this.recojos.filter((d) => d.estado === this.filtroRecojo);
    }
    return this.recojos;
  }

  salirARecoger(d: any): void {
    this.procesandoRecojo = d.id_devolucion;
    this.mensaje = null;
    this.error = null;
    this.devolucionesService.enCamino(d.id_devolucion).subscribe({
      next: () => {
        this.procesandoRecojo = null;
        this.mensaje = `Devolución ${d.numero_nota} en camino.`;
        this.cargarRecojos();
      },
      error: (err) => {
        this.procesandoRecojo = null;
        this.error = err?.error?.error || err?.error?.detail || 'No se pudo actualizar la devolución.';
      }
    });
  }

  completarRecojo(d: any): void {
    this.procesandoRecojo = d.id_devolucion;
    this.mensaje = null;
    this.error = null;
    this.devolucionesService.completar(d.id_devolucion, !!this.revisadas[d.id_devolucion]).subscribe({
      next: (actualizada) => {
        this.procesandoRecojo = null;
        this.mensaje = `Devolución ${d.numero_nota} completada: se devolvió Bs ${actualizada.monto_reembolso} al cliente.`;
        this.cargarRecojos();
      },
      error: (err) => {
        this.procesandoRecojo = null;
        this.error = err?.error?.error || err?.error?.detail || 'No se pudo completar la devolución.';
      }
    });
  }
}