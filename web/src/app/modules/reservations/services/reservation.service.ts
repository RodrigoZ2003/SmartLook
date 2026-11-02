// web/src/app/modules/reservations/services/reservation.service.ts
// MODIFICADO (Fase 2 - reservas con anticipo): pagar la reserva con Stripe
// (anticipo o total) y cancelarla con reembolso (CU17).
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';

export type TipoPagoReserva = 'ANTICIPO' | 'TOTAL';

@Injectable({
  providedIn: 'root'
})
export class ReservationService {
  constructor(private apiService: ApiService) {}

  // Crea la reserva "Pendiente de pago" (3 horas para pagarla).
  crearReserva(data: any): Observable<any> {
    return this.apiService.post('/reservations/reservas/', data);
  }

  // El backend vence antes de listar las reservas cuyo plazo pasó.
  getReservas(params?: any): Observable<any> {
    return this.apiService.get('/reservations/reservas/', params);
  }

  // Crea el cobro en Stripe por el anticipo o el total; devuelve { reserva, pago: { client_secret, referencia_pago, monto } }.
  iniciarPago(id: number, tipoPago: TipoPagoReserva): Observable<any> {
    return this.apiService.post(`/reservations/reservas/${id}/iniciar-pago/`, { tipo_pago: tipoPago });
  }

  // Confirma el pago hecho en Stripe: la reserva queda CONFIRMADA y la prenda apartada.
  pagar(id: number, referenciaPago: string): Observable<any> {
    return this.apiService.post(`/reservations/reservas/${id}/pagar/`, { referencia_pago: referenciaPago });
  }

  // CU17: si está pagada, se devuelve lo pagado menos el 10% del total.
  cancelarReserva(id: number, motivo: string = ''): Observable<any> {
    return this.apiService.post(`/reservations/reservas/${id}/cancelar/`, { motivo });
  }

  confirmarReserva(id: number): Observable<any> {
    return this.apiService.post(`/reservations/reservas/${id}/confirmar/`, {});
  }

  completarReserva(id: number): Observable<any> {
    return this.apiService.post(`/reservations/reservas/${id}/completar/`, {});
  }
}