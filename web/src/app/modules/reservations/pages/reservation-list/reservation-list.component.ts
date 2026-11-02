// web/src/app/modules/reservations/pages/reservation-list/reservation-list.component.ts
//
// Archivo NUEVO (estaba vacío). Sirve tanto para CU12 (encargado ve
// todas las reservas, con nombre de cliente, y puede confirmar/
// completar/cancelar) como CU13 (cliente ve solo las suyas y puede
// cancelar) - el backend ya filtra el queryset según el rol, aquí solo
// se decide qué botones mostrar.
// MODIFICADO (SaaS - A.5): el cliente ve también sus reservas hechas sin
// conexión con su estado (Registrada localmente, Enviada, Confirmada,
// Rechazada), puede sincronizarlas, descartar las rechazadas y quitar las
// confirmadas. Sin conexión, la lista del servidor sale de la copia guardada.
// MODIFICADO (Fase 2 - reservas con anticipo y CU17): cada reserva muestra
// lo pagado, el saldo y sus plazos. El cliente paga las pendientes de pago
// (PagoReservaComponent) y al cancelar ve cuánto se le devuelve (lo pagado
// menos el 10% del total); las canceladas o vencidas muestran su nota NR.
// El personal solo cancela reservas sin pago y completa las que no deben saldo
// (el saldo se cobra en el Punto de Venta).
import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { AuthService } from '../../../../core/auth/auth.service';
import { ConexionService } from '../../../../core/services/conexion.service';
import { ReservationService } from '../../services/reservation.service';
import {
  ReservaLocal,
  ReservaOfflineService,
  ResultadoSyncReservas
} from '../../services/reserva-offline.service';

@Component({
  selector: 'app-reservation-list',
  templateUrl: './reservation-list.component.html',
  styleUrls: ['./reservation-list.component.scss']
})
export class ReservationListComponent implements OnInit, OnDestroy {
  reservas: any[] = [];
  loading = false;
  esEncargado = false;
  actionError = '';
  actionMessage = '';
  // NUEVO (Fase 2): reserva que se está pagando y la que se está cancelando.
  idPagando: number | null = null;
  idCancelando: number | null = null;
  // NUEVO (A.5)
  enLinea = true;
  reservasLocales: ReservaLocal[] = [];
  sincronizando = false;
  resultadoSync: ResultadoSyncReservas | null = null;
  sinDatosGuardados = false;
  private suscripciones = new Subscription();

  constructor(
    private reservationService: ReservationService,
    private authService: AuthService,
    private reservaOffline: ReservaOfflineService,
    private conexion: ConexionService
  ) {}

  ngOnInit(): void {
    const roles = this.authService.obtenerRoles();
    this.esEncargado = roles.some(r =>
      ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'].includes(r)
    );
    this.suscripciones.add(this.conexion.enLinea$.subscribe(enLinea => this.enLinea = enLinea));
    if (!this.esEncargado) {
      this.suscripciones.add(this.reservaOffline.reservas$.subscribe(r => this.reservasLocales = r));
      this.suscripciones.add(this.reservaOffline.sincronizando$.subscribe(s => this.sincronizando = s));
      this.suscripciones.add(this.reservaOffline.resultado$.subscribe(resultado => {
        const nuevas = !!resultado && resultado !== this.resultadoSync &&
          resultado.sincronizadas + resultado.duplicadas > 0;
        this.resultadoSync = resultado;
        // Las reservas confirmadas ya aparecen en la lista del servidor.
        if (nuevas) {
          this.cargarReservas();
        }
      }));
      this.reservaOffline.recargar();
      this.reservaOffline.sincronizar();
    }
    this.cargarReservas();
  }

  ngOnDestroy(): void {
    this.suscripciones.unsubscribe();
  }

  get pendientes(): number {
    return this.reservasLocales.filter(r => r.estado === 'REGISTRADA' || r.estado === 'ENVIADA').length;
  }

  get confirmadas(): number {
    return this.reservasLocales.filter(r => r.estado === 'CONFIRMADA').length;
  }

  get rechazadas(): number {
    return this.reservasLocales.filter(r => r.estado === 'RECHAZADA').length;
  }

  cargarReservas(): void {
    this.loading = true;
    this.sinDatosGuardados = false;
    this.reservationService.getReservas().subscribe({
      next: (data: any) => {
        this.reservas = data.results || data;
        this.loading = false;
      },
      error: (err) => {
        this.loading = false;
        this.sinDatosGuardados = this.conexion.esErrorDeRed(err);
      }
    });
  }

  // CU17: avisa cuánto se devuelve antes de cancelar.
  cancelar(reserva: any): void {
    this.actionError = '';
    this.actionMessage = '';
    if (!confirm(this.textoConfirmarCancelacion(reserva))) {
      return;
    }
    this.idCancelando = reserva.id_reserva;
    this.reservationService.cancelarReserva(reserva.id_reserva).subscribe({
      next: (cancelada: any) => {
        this.idCancelando = null;
        this.actionMessage = cancelada?.numero_nota
          ? `Reserva #${cancelada.id_reserva} cancelada. Nota ${cancelada.numero_nota}: se devuelven ` +
            `Bs ${this.bs(cancelada.monto_devuelto)} a tu tarjeta.`
          : `Reserva #${reserva.id_reserva} cancelada.`;
        this.cargarReservas();
      },
      error: (err) => {
        this.idCancelando = null;
        this.actionError = this.conexion.esErrorDeRed(err)
          ? 'Sin conexión: la reserva no se puede cancelar ahora. Inténtalo al recuperar internet.'
          : err?.error?.error || 'No se pudo cancelar la reserva.';
      }
    });
  }

  private textoConfirmarCancelacion(reserva: any): string {
    const c = reserva.cancelacion;
    if (!c || !(Number(c.pagado) > 0)) {
      return `¿Cancelar la Reserva #${reserva.id_reserva}? Las prendas dejarán de estar reservadas.`;
    }
    return `¿Cancelar la Reserva #${reserva.id_reserva}?\n\n` +
      `Pagaste: Bs ${this.bs(c.pagado)}\n` +
      `Se retiene el ${reserva.porcentaje_retencion}% del total: Bs ${this.bs(c.retenido)}\n` +
      `Se te devuelve a la tarjeta: Bs ${this.bs(c.devuelto)}`;
  }

  // ---------------------------------------------------------------- pago (Fase 2)
  abrirPago(reserva: any): void {
    this.actionError = '';
    this.actionMessage = '';
    this.idPagando = reserva.id_reserva;
  }

  cerrarPago(): void {
    this.idPagando = null;
  }

  onPagada(reserva: any): void {
    this.idPagando = null;
    this.actionMessage = `Reserva #${reserva.id_reserva} confirmada: pagaste Bs ${this.bs(reserva.monto_pagado)}` +
      (this.tieneSaldo(reserva) ? ` y pagarás Bs ${this.bs(reserva.saldo)} al retirar.` : '.');
    this.cargarReservas();
  }

  tieneSaldo(reserva: any): boolean {
    return Number(reserva?.saldo) > 0;
  }

  tienePago(reserva: any): boolean {
    return Number(reserva?.monto_pagado) > 0;
  }

  bs(valor: any): string {
    return (Number(valor) || 0).toFixed(2);
  }

  confirmar(id: number): void {
    this.reservationService.confirmarReserva(id).subscribe({
      next: () => this.cargarReservas()
    });
  }

  completar(id: number): void {
    this.actionError = '';
    this.reservationService.completarReserva(id).subscribe({
      next: () => this.cargarReservas(),
      error: (err) => this.actionError = err?.error?.error || 'No se pudo completar la reserva.'
    });
  }

  // El personal solo cancela reservas sin pago; la cancelación con reembolso es del cliente (CU17).
  puedeCancelar(reserva: any): boolean {
    if (!reserva.puede_cancelar) {
      return false;
    }
    return !this.esEncargado || !this.tienePago(reserva);
  }

  // El personal completa a mano solo reservas confirmadas sin saldo (el saldo se cobra en el POS).
  puedeCompletar(reserva: any): boolean {
    return reserva.estado === 'CONFIRMADA' && !this.tieneSaldo(reserva);
  }

  // ---------------------------------------------------------------- reservas sin conexión
  sincronizarAhora(): void {
    this.reservaOffline.sincronizar();
  }

  descartar(reserva: ReservaLocal): void {
    if (confirm('¿Descartar esta reserva rechazada? Se borrará de este dispositivo.')) {
      this.reservaOffline.descartar(reserva);
    }
  }

  limpiarConfirmadas(): void {
    this.reservaOffline.limpiarConfirmadas();
  }

  prendas(reserva: ReservaLocal): string {
    return reserva.items.map(i => i.label).join(', ');
  }

  textoEstado(reserva: ReservaLocal): string {
    switch (reserva.estado) {
      case 'CONFIRMADA':
        // Fase 2: el servidor la recibió "Pendiente de pago" (3 horas para pagarla).
        return reserva.id_reserva ? `Recibida · Reserva #${reserva.id_reserva}` : 'Recibida';
      case 'RECHAZADA':
        return 'Rechazada';
      case 'ENVIADA':
        return 'Enviada';
      default:
        return 'Registrada localmente';
    }
  }
}