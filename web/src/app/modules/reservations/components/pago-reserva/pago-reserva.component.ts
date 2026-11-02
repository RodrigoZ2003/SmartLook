// web/src/app/modules/reservations/components/pago-reserva/pago-reserva.component.ts
//
// NUEVO (Fase 2 - reservas con anticipo): pago de una reserva con Stripe.
// El cliente elige pagar el anticipo (porcentaje de la tienda) o el total;
// se crea el cobro en el backend, se confirma la tarjeta con Stripe y luego
// se avisa al backend para que confirme la reserva y aparte las prendas.
// Se usa al crear la reserva y desde "Mis reservas" (reservas sin pagar).
import {
  AfterViewInit, Component, ElementRef, EventEmitter, Input, OnDestroy, Output, ViewChild
} from '@angular/core';
import { loadStripe, Stripe, StripeCardElement } from '@stripe/stripe-js';
import { environment } from '../../../../../environments/environment';
import { ReservationService, TipoPagoReserva } from '../../services/reservation.service';

@Component({
  selector: 'app-pago-reserva',
  templateUrl: './pago-reserva.component.html',
  styleUrls: ['./pago-reserva.component.scss']
})
export class PagoReservaComponent implements AfterViewInit, OnDestroy {
  // Reserva "Pendiente de pago" tal como la devuelve el backend (con opciones_pago).
  @Input() reserva: any;
  @Output() pagada = new EventEmitter<any>();
  @Output() cerrar = new EventEmitter<void>();
  @ViewChild('tarjeta') tarjetaRef?: ElementRef<HTMLDivElement>;

  tipoPago: TipoPagoReserva = 'ANTICIPO';
  pagando = false;
  error = '';

  private stripe: Stripe | null = null;
  private tarjeta: StripeCardElement | null = null;

  constructor(private reservationService: ReservationService) {}

  async ngAfterViewInit(): Promise<void> {
    this.stripe = await loadStripe(environment.stripePublishableKey);
    if (this.stripe && this.tarjetaRef) {
      this.tarjeta = this.stripe.elements().create('card');
      this.tarjeta.mount(this.tarjetaRef.nativeElement);
    }
  }

  ngOnDestroy(): void {
    this.tarjeta?.destroy();
  }

  get opciones(): any[] {
    return this.reserva?.opciones_pago || [];
  }

  get montoElegido(): number {
    const opcion = this.opciones.find(o => o.tipo === this.tipoPago);
    return Number(opcion?.monto) || 0;
  }

  get saldoAlRetirar(): number {
    return Math.max((Number(this.reserva?.monto_total) || 0) - this.montoElegido, 0);
  }

  etiqueta(opcion: any): string {
    return opcion.tipo === 'TOTAL'
      ? 'Pagar el total'
      : `Pagar el anticipo (${Number(opcion.porcentaje)}%)`;
  }

  async pagar(): Promise<void> {
    if (!this.stripe || !this.tarjeta || this.pagando) {
      return;
    }
    this.pagando = true;
    this.error = '';
    this.reservationService.iniciarPago(this.reserva.id_reserva, this.tipoPago).subscribe({
      next: async (data: any) => {
        const resultado = await this.stripe!.confirmCardPayment(data.pago.client_secret, {
          payment_method: { card: this.tarjeta! }
        });
        if (resultado.error) {
          this.error = resultado.error.message || 'La tarjeta fue rechazada.';
          this.pagando = false;
          return;
        }
        this.confirmar(data.pago.referencia_pago);
      },
      error: (err) => {
        this.error = err?.error?.error || 'No se pudo iniciar el pago. Intenta nuevamente.';
        this.pagando = false;
      }
    });
  }

  private confirmar(referencia: string): void {
    this.reservationService.pagar(this.reserva.id_reserva, referencia).subscribe({
      next: (reserva) => {
        this.pagando = false;
        this.pagada.emit(reserva);
      },
      error: (err) => {
        this.error = err?.error?.error || 'El pago se hizo, pero no se pudo confirmar la reserva. Revisa "Mis reservas".';
        this.pagando = false;
      }
    });
  }
}