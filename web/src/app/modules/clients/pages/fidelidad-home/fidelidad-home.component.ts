// web/src/app/modules/clients/pages/fidelidad-home/fidelidad-home.component.ts
//
// NUEVO (Fase 3 - CU18): Clientes > Fidelidad.
//   - SUPER_ADMIN: configura la regla (compras requeridas en el mes, porcentaje
//     de descuento y si está activa) y ve a los clientes de todas las empresas.
//   - ADMIN_EMPRESA: ve la regla vigente y a los clientes de su empresa con su
//     progreso del mes, los descuentos usados y cuánto asumió la empresa.
import { Component, OnInit } from '@angular/core';
import {
  EstadoFidelidad,
  FidelidadService,
  FilaFidelidad,
  MonitoreoFidelidad
} from '../../../../core/services/fidelidad.service';

@Component({
  selector: 'app-fidelidad-home',
  templateUrl: './fidelidad-home.component.html',
  styleUrls: ['./fidelidad-home.component.scss']
})
export class FidelidadHomeComponent implements OnInit {
  datos: MonitoreoFidelidad | null = null;
  loading = false;
  error: string | null = null;
  mes = '';
  busqueda = '';

  // Formulario de la regla (solo SUPER_ADMIN).
  compras = 5;
  porcentaje = 50;
  activa = true;
  guardando = false;
  mensaje: string | null = null;
  errorRegla: string | null = null;

  constructor(private fidelidad: FidelidadService) {}

  ngOnInit(): void {
    const hoy = new Date();
    this.mes = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}`;
    this.cargar();
  }

  get superAdmin(): boolean {
    return !!this.datos?.super_admin;
  }

  get mesActual(): boolean {
    const hoy = new Date();
    return this.mes === `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}`;
  }

  get filas(): FilaFidelidad[] {
    const termino = this.busqueda.trim().toLowerCase();
    const filas = this.datos?.clientes ?? [];
    if (!termino) {
      return filas;
    }
    return filas.filter(f =>
      (f.cliente || '').toLowerCase().includes(termino) ||
      (f.correo || '').toLowerCase().includes(termino) ||
      f.empresa.toLowerCase().includes(termino)
    );
  }

  cargar(): void {
    this.loading = true;
    this.error = null;
    this.fidelidad.monitoreo(this.mes).subscribe({
      next: (datos) => {
        this.datos = datos;
        this.compras = datos.regla.compras_requeridas;
        this.porcentaje = datos.regla.porcentaje;
        this.activa = datos.regla.activa;
        this.loading = false;
      },
      error: (err) => {
        this.datos = null;
        this.error = err?.error?.detail || err?.error?.error || 'No se pudo cargar la información de fidelidad.';
        this.loading = false;
      }
    });
  }

  guardarRegla(): void {
    this.mensaje = null;
    this.errorRegla = null;
    if (!Number.isInteger(this.compras) || this.compras < 1 || this.compras > 50) {
      this.errorRegla = 'Las compras requeridas deben estar entre 1 y 50.';
      return;
    }
    if (!(this.porcentaje >= 1 && this.porcentaje <= 100)) {
      this.errorRegla = 'El porcentaje debe estar entre 1 y 100.';
      return;
    }
    this.guardando = true;
    this.fidelidad.guardarRegla({
      compras_requeridas: this.compras,
      porcentaje: this.porcentaje,
      activa: this.activa
    }).subscribe({
      next: (regla) => {
        this.guardando = false;
        const ganaron = regla.ganaron_ahora || 0;
        this.mensaje = regla.activa
          ? `Regla guardada: ${regla.compras_requeridas} compras en el mes = ${regla.porcentaje}% de descuento.` +
            (ganaron ? ` ${ganaron} cliente(s) ganaron el descuento ahora y ya fueron notificados.` : '')
          : 'Regla guardada: el descuento por fidelidad está desactivado.';
        this.cargar();
      },
      error: (err) => {
        this.guardando = false;
        this.errorRegla = err?.error?.error || err?.error?.detail || 'No se pudo guardar la regla.';
      }
    });
  }

  avance(fila: FilaFidelidad): number {
    return Math.min(100, Math.round((fila.compras / Math.max(fila.requeridas, 1)) * 100));
  }

  claseEstado(estado: EstadoFidelidad): string {
    return `estado estado--${estado.toLowerCase()}`;
  }
}