// web/src/app/core/services/notificaciones.service.ts
//
// NUEVO (Fase 2 - CU16): centro de notificaciones (campana de la barra
// superior). Sin push: la web consulta el contador cada minuto.
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface Notificacion {
  id_notificacion: number;
  tipo: string;
  tipo_display: string;
  titulo: string;
  mensaje: string;
  enlace: string | null;
  leida: boolean;
  fecha_creacion: string;
  fecha_lectura: string | null;
}

@Injectable({
  providedIn: 'root'
})
export class NotificacionesService {
  constructor(private api: ApiService) {}

  // Cantidad de avisos sin leer (también genera los recordatorios de reservas).
  contador(): Observable<{ no_leidas: number }> {
    return this.api.get<{ no_leidas: number }>('/auth/notificaciones/contador/');
  }

  // Últimos avisos del usuario, del más reciente al más antiguo.
  listar(): Observable<any> {
    return this.api.get('/auth/notificaciones/', { page_size: 20 });
  }

  leer(id: number): Observable<Notificacion> {
    return this.api.post<Notificacion>(`/auth/notificaciones/${id}/leer/`, {});
  }

  leerTodas(): Observable<any> {
    return this.api.post('/auth/notificaciones/leer-todas/', {});
  }
}