// web/src/app/modules/assistant-admin/components/grafico-reporte/grafico-reporte.component.ts
//
// NUEVO (Fase 3 - CU13): dibuja con Chart.js el gráfico que calcula el
// backend para cada reporte (barras, barras horizontales, líneas o dona).
// Lo usan el asistente con IA y los reportes convencionales. Los colores son
// los mismos que usan las exportaciones a PDF, Excel y HTML.
// El gráfico se crea fuera de la detección de cambios de Angular
// (runOutsideAngular): sus animaciones y redimensionamientos no deben
// disparar ciclos de Angular. El contenedor tiene alto fijo y min-width: 0
// para que Chart.js no lo agrande sin fin.
import {
  AfterViewInit,
  Component,
  ElementRef,
  Input,
  NgZone,
  OnChanges,
  OnDestroy,
  ViewChild
} from '@angular/core';
import Chart from 'chart.js/auto';
import { GraficoResultado } from '../../services/assistant-admin.service';

export const PALETA_GRAFICOS = [
  '#0F3460', '#E94560', '#16A085', '#F39C12', '#8E44AD',
  '#2980B9', '#D35400', '#27AE60', '#C0392B', '#7F8C8D'
];

const FORMATO_NUMERO = new Intl.NumberFormat('es-BO', { maximumFractionDigits: 2 });

@Component({
  selector: 'app-grafico-reporte',
  template: `
    <div class="grafico" *ngIf="tieneDatos">
      <h4>{{ grafico?.titulo }}</h4>
      <div class="lienzo" [style.height.px]="alto">
        <canvas #lienzo></canvas>
      </div>
    </div>
  `,
  styles: [`
    :host {
      display: block;
      min-width: 0;
    }
    .grafico {
      background: #ffffff;
      border: 1px solid #e2e5ec;
      border-radius: 14px;
      padding: 1rem 1.2rem;
    }
    h4 {
      margin: 0 0 0.75rem;
      font-size: 0.9rem;
      color: #1a1a2e;
    }
    .lienzo {
      position: relative;
      width: 100%;
      min-width: 0;
      overflow: hidden;
    }
  `]
})
export class GraficoReporteComponent implements OnChanges, AfterViewInit, OnDestroy {
  @Input() grafico: GraficoResultado | null | undefined = null;
  @ViewChild('lienzo') lienzo?: ElementRef<HTMLCanvasElement>;

  private chart: Chart | null = null;
  private pendiente: ReturnType<typeof setTimeout> | null = null;

  constructor(private ngZone: NgZone) {}

  get tieneDatos(): boolean {
    return !!this.grafico && this.grafico.series.some(serie => serie.datos.some(valor => valor !== 0));
  }

  get alto(): number {
    if (!this.grafico) {
      return 0;
    }
    if (this.grafico.tipo === 'barh') {
      return Math.max(220, 60 + 34 * this.grafico.etiquetas.length);
    }
    return this.grafico.tipo === 'doughnut' ? 300 : 320;
  }

  ngAfterViewInit(): void {
    this.programarDibujo();
  }

  ngOnChanges(): void {
    this.programarDibujo();
  }

  ngOnDestroy(): void {
    if (this.pendiente) {
      clearTimeout(this.pendiente);
    }
    this.chart?.destroy();
  }

  // Espera a que Angular pinte (o quite) el <canvas> y dibuja una sola vez,
  // fuera de la zona de Angular.
  private programarDibujo(): void {
    if (this.pendiente) {
      clearTimeout(this.pendiente);
    }
    this.pendiente = setTimeout(() => {
      this.pendiente = null;
      this.ngZone.runOutsideAngular(() => this.dibujar());
    });
  }

  private formatear(valor: number): string {
    const texto = FORMATO_NUMERO.format(valor);
    return this.grafico?.formato === 'dinero' ? `Bs ${texto}` : texto;
  }

  private dibujar(): void {
    this.chart?.destroy();
    this.chart = null;
    const g = this.grafico;
    const lienzo = this.lienzo?.nativeElement;
    if (!g || !lienzo || !this.tieneDatos) {
      return;
    }
    const dona = g.tipo === 'doughnut';
    const linea = g.tipo === 'line';
    const horizontal = g.tipo === 'barh';
    const varias = g.series.length > 1;

    const datasets = g.series.map((serie, i) => {
      const color = PALETA_GRAFICOS[i % PALETA_GRAFICOS.length];
      return {
        label: serie.nombre,
        data: serie.datos,
        backgroundColor: dona
          ? g.etiquetas.map((_, j) => PALETA_GRAFICOS[j % PALETA_GRAFICOS.length])
          : linea ? `${color}22` : color,
        borderColor: dona ? '#ffffff' : color,
        borderWidth: linea ? 2.5 : dona ? 2 : 0,
        borderRadius: dona || linea ? 0 : 6,
        maxBarThickness: 46,
        fill: linea && !varias,
        tension: 0.3,
        pointRadius: linea ? 4 : 0,
        pointHoverRadius: 6,
        pointBackgroundColor: color
      };
    });

    const formatear = (valor: number | string) => this.formatear(Number(valor));
    const ejeValores = {
      beginAtZero: true,
      grid: { color: '#eef0f4' },
      ticks: { callback: formatear }
    };
    const ejeCategorias = {
      grid: { display: false },
      ticks: { autoSkip: true, maxRotation: 40 }
    };

    // Se arma como objeto genérico: Chart.js tipa cada tipo de gráfico distinto.
    const configuracion: any = {
      type: dona ? 'doughnut' : linea ? 'line' : 'bar',
      data: { labels: g.etiquetas, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 150,
        indexAxis: horizontal ? 'y' : 'x',
        animation: { duration: 700 },
        interaction: { mode: dona ? 'nearest' : 'index', intersect: false },
        plugins: {
          legend: {
            display: dona || varias,
            position: dona ? 'right' : 'top',
            labels: { usePointStyle: true, boxWidth: 10, padding: 14 }
          },
          tooltip: {
            callbacks: {
              label: (contexto: any) => {
                const valor = horizontal ? contexto.parsed.x : dona ? contexto.parsed : contexto.parsed.y;
                const nombre = dona ? contexto.label : contexto.dataset.label;
                return ` ${nombre}: ${this.formatear(Number(valor))}`;
              }
            }
          }
        }
      }
    };
    if (dona) {
      configuracion.options.cutout = '62%';
    } else {
      configuracion.options.scales = horizontal
        ? { x: ejeValores, y: ejeCategorias }
        : { x: ejeCategorias, y: ejeValores };
    }
    try {
      this.chart = new Chart(lienzo, configuracion);
    } catch (error) {
      console.error('No se pudo dibujar el gráfico del reporte', error);
    }
  }
}