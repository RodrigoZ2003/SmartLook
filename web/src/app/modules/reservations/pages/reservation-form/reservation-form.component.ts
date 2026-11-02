// web/src/app/modules/reservations/pages/reservation-form/reservation-form.component.ts
//
// Archivo NUEVO (estaba vacío). Permite al cliente elegir sucursal,
// fecha/hora, e ir agregando varias prendas (producto+variante) antes
// de enviar la reserva - consume POST /reservations/reservas/, que ahora
// acepta "items" (varias variantes por reserva).
// MODIFICADO (SaaS - A.5): reserva sin conexión.
// - Sin internet (o si se corta al enviar), la reserva se guarda en el
//   dispositivo como "Registrada localmente" y se envía sola al volver la
//   conexión (ReservaOfflineService). Los productos y sucursales salen de la
//   copia guardada cuando no hay conexión.
// - Una reserva solo puede tener prendas de una misma tienda (empresa), y
//   solo se ofrecen las sucursales activas de esa tienda.
// - La fecha no puede ser anterior a hoy.
// MODIFICADO (Fase 2 - reservas con anticipo): la reserva se crea
// "Pendiente de pago" y a continuación se paga con Stripe (anticipo o
// total, ver PagoReservaComponent). Si el cliente paga después, tiene 3
// horas para hacerlo desde "Mis reservas".
import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { CatalogService } from '../../../catalog/services/catalog.service';
import { ReservationService } from '../../services/reservation.service';
import { ReservaOfflineService } from '../../services/reserva-offline.service';
import { ConexionService } from '../../../../core/services/conexion.service';

interface ReservationItem {
  id_variante: number;
  label: string;
  id_empresa: number | null;
  empresa_nombre: string | null;
}

@Component({
  selector: 'app-reservation-form',
  templateUrl: './reservation-form.component.html',
  styleUrls: ['./reservation-form.component.scss']
})
export class ReservationFormComponent implements OnInit, OnDestroy {
  products: any[] = [];
  sucursales: any[] = [];
  selectedProductId: number | null = null;
  selectedVarianteId: number | null = null;
  selectedSucursalId: number | null = null;
  fechaReserva: string = '';
  horaReserva: string = '';
  items: ReservationItem[] = [];
  loading = false;
  submitting = false;
  errorMessage = '';
  successMessage = '';
  // NUEVO (Fase 2): reserva recién creada que espera el pago.
  reservaPorPagar: any = null;
  reservaPagada: any = null;
  avisoPendientePago = false;
  // NUEVO (A.5)
  enLinea = true;
  guardadaSinConexion = false;
  private suscripciones = new Subscription();

  constructor(
    private catalogService: CatalogService,
    private reservationService: ReservationService,
    private reservaOffline: ReservaOfflineService,
    private conexion: ConexionService
  ) {}

  ngOnInit(): void {
    this.suscripciones.add(this.conexion.enLinea$.subscribe(enLinea => this.enLinea = enLinea));
    this.loading = true;
    this.catalogService.getProducts().subscribe({
      next: (data: any) => {
        this.products = data.results || data;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
      }
    });
    this.catalogService.getBranches().subscribe({
      next: (data: any) => {
        this.sucursales = data.results || data;
      },
      error: () => {}
    });
  }

  ngOnDestroy(): void {
    this.suscripciones.unsubscribe();
  }

  get selectedProduct(): any {
    return this.products.find(p => p.id_producto === Number(this.selectedProductId));
  }

  // Tienda de las prendas ya agregadas (todas deben ser de la misma).
  get empresaReserva(): { id: number | null; nombre: string | null } | null {
    if (this.items.length === 0) {
      return null;
    }
    return { id: this.items[0].id_empresa, nombre: this.items[0].empresa_nombre };
  }

  // Solo sucursales activas de la tienda de las prendas agregadas.
  get sucursalesDisponibles(): any[] {
    const empresa = this.empresaReserva;
    return this.sucursales.filter(s =>
      (!s.estado || s.estado === 'ACTIVA') &&
      (!empresa || empresa.id === null || s.id_empresa === empresa.id)
    );
  }

  // Fecha mínima del selector (hoy, en la hora local del dispositivo).
  get hoy(): string {
    const ahora = new Date();
    const mes = String(ahora.getMonth() + 1).padStart(2, '0');
    const dia = String(ahora.getDate()).padStart(2, '0');
    return `${ahora.getFullYear()}-${mes}-${dia}`;
  }

  addItem(): void {
    this.errorMessage = '';
    const producto = this.selectedProduct;
    if (!producto || !this.selectedVarianteId) {
      this.errorMessage = 'Selecciona un producto y una variante antes de agregar.';
      return;
    }
    const variante = (producto.variantes || []).find(
      (v: any) => v.id_variante === Number(this.selectedVarianteId)
    );
    if (!variante) {
      return;
    }
    const yaAgregada = this.items.some(i => i.id_variante === variante.id_variante);
    if (yaAgregada) {
      this.errorMessage = 'Esa prenda ya está en la reserva.';
      return;
    }
    const empresa = this.empresaReserva;
    const idEmpresa = producto.id_empresa ?? null;
    if (empresa && empresa.id !== null && idEmpresa !== null && empresa.id !== idEmpresa) {
      this.errorMessage = `Una reserva solo puede tener prendas de una misma tienda (${empresa.nombre}).`;
      return;
    }
    this.items.push({
      id_variante: variante.id_variante,
      label: `${producto.nombre} - ${variante.talla?.nombre} - ${variante.color?.nombre}`,
      id_empresa: idEmpresa,
      empresa_nombre: producto.empresa_nombre ?? null
    });
    this.selectedVarianteId = null;
    if (!this.sucursalesDisponibles.some(s => s.id_sucursal === this.selectedSucursalId)) {
      this.selectedSucursalId = null;
    }
  }

  removeItem(index: number): void {
    this.items.splice(index, 1);
  }

  submit(): void {
    this.errorMessage = '';
    this.successMessage = '';
    this.guardadaSinConexion = false;
    this.reservaPagada = null;
    this.avisoPendientePago = false;
    if (!this.selectedSucursalId) {
      this.errorMessage = 'Selecciona una sucursal.';
      return;
    }
    if (!this.fechaReserva || !this.horaReserva) {
      this.errorMessage = 'Selecciona fecha y hora.';
      return;
    }
    if (this.fechaReserva < this.hoy) {
      this.errorMessage = 'La fecha de la reserva no puede ser anterior a hoy.';
      return;
    }
    if (this.items.length === 0) {
      this.errorMessage = 'Agrega al menos una prenda a la reserva.';
      return;
    }
    if (!this.enLinea) {
      this.guardarSinConexion();
      return;
    }
    const payload = {
      id_sucursal: this.selectedSucursalId,
      fecha_reserva: this.fechaReserva,
      hora_reserva: this.horaReserva,
      items: this.items.map(i => ({ id_variante: i.id_variante }))
    };
    this.submitting = true;
    this.reservationService.crearReserva(payload).subscribe({
      next: (reserva: any) => {
        this.submitting = false;
        this.reservaPorPagar = reserva;
        this.limpiarFormulario();
      },
      error: (err) => {
        this.submitting = false;
        // Se cortó la conexión al enviar: la reserva se guarda en el dispositivo.
        if (this.conexion.esErrorDeRed(err)) {
          this.guardarSinConexion();
          return;
        }
        this.errorMessage = err?.error?.error || err?.error?.detail || 'No se pudo crear la reserva. Intenta nuevamente.';
      }
    });
  }

  private async guardarSinConexion(): Promise<void> {
    const sucursal = this.sucursales.find(s => s.id_sucursal === this.selectedSucursalId);
    this.submitting = true;
    try {
      await this.reservaOffline.guardar({
        id_sucursal: this.selectedSucursalId as number,
        sucursal: sucursal?.nombre || '',
        fecha_reserva: this.fechaReserva,
        hora_reserva: this.horaReserva,
        items: this.items.map(i => ({ id_variante: i.id_variante, label: i.label }))
      });
      this.guardadaSinConexion = true;
      this.successMessage = 'Sin conexión: la reserva quedó guardada en este dispositivo como ' +
        '"Registrada localmente" y se enviará sola al recuperar internet. Desde ese momento ' +
        'tendrás 3 horas para pagarla en "Mis reservas".';
      this.limpiarFormulario();
    } catch {
      this.errorMessage = 'No se pudo guardar la reserva en este dispositivo.';
    } finally {
      this.submitting = false;
    }
  }

  // NUEVO (Fase 2): el pago se confirmó; la prenda quedó apartada.
  onPagada(reserva: any): void {
    this.reservaPorPagar = null;
    this.reservaPagada = reserva;
  }

  tieneSaldo(reserva: any): boolean {
    return Number(reserva?.saldo) > 0;
  }

  // NUEVO (Fase 2): el cliente decidió pagar después (tiene 3 horas).
  onPagarDespues(): void {
    const reserva = this.reservaPorPagar;
    this.reservaPorPagar = null;
    const limite = reserva?.fecha_limite_pago ? new Date(reserva.fecha_limite_pago) : null;
    const hora = limite
      ? ` hasta las ${String(limite.getHours()).padStart(2, '0')}:${String(limite.getMinutes()).padStart(2, '0')}`
      : '';
    this.successMessage = `La Reserva #${reserva?.id_reserva} quedó pendiente de pago${hora}. ` +
      'Págala desde "Mis reservas"; si no, vencerá y las prendas no quedarán apartadas.';
    this.avisoPendientePago = true;
  }

  private limpiarFormulario(): void {
    this.items = [];
    this.selectedSucursalId = null;
    this.fechaReserva = '';
    this.horaReserva = '';
  }
}