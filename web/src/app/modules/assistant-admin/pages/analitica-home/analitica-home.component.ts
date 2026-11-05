// web/src/app/modules/assistant-admin/pages/analitica-home/analitica-home.component.ts
//
// NUEVO (Fase 3 - CU09): dashboard de Analítica con Machine Learning.
//   - Predicción de demanda (supervisado, RandomForest): comparación de las
//     ventanas de 3, 5 y 12 meses contra la línea base, real vs. predicho en
//     las semanas de prueba, importancia de las variables y unidades previstas
//     para las próximas 4 semanas por sucursal y prenda.
//   - Segmentación de clientes (no supervisado, K-means sobre RFM): grupos VIP,
//     leales, ocasionales y en riesgo, silhouette por k y lista de clientes.
//   - Reentrenar (SUPER_ADMIN: la empresa elegida o todas; ADMIN_EMPRESA: la
//     suya) y descargar los reportes en PDF, Excel o HTML.
// Los gráficos se calculan una sola vez al recibir los datos (no en getters):
// el componente de Chart.js se redibuja cada vez que cambia su entrada.
import { Component, OnInit } from '@angular/core';
import {
  AssistantAdminService,
  FormatoReporte,
  GraficoResultado
} from '../../services/assistant-admin.service';
import {
  AnaliticaService,
  DashboardAnalitica,
  FilaPrediccion,
  ReporteAnalitica,
  Segmento,
  VentanaDemanda
} from '../../services/analitica.service';

type Comparacion = 'mejor' | 'similar' | 'peor';

@Component({
  selector: 'app-analitica-home',
  templateUrl: './analitica-home.component.html',
  styleUrls: ['./analitica-home.component.scss']
})
export class AnaliticaHomeComponent implements OnInit {
  datos: DashboardAnalitica | null = null;
  cargando = false;
  error: string | null = null;
  mensaje: string | null = null;
  empresaSeleccionada: number | null = null;
  reentrenando: 'una' | 'todas' | null = null;
  descargando: string | null = null;
  sucursalFiltro = '';
  sucursales: string[] = [];

  graficoVentanas: GraficoResultado | null = null;
  graficoPrueba: GraficoResultado | null = null;
  graficoImportancia: GraficoResultado | null = null;
  graficoPrendas: GraficoResultado | null = null;
  graficoSegmentos: GraficoResultado | null = null;
  graficoSilhouette: GraficoResultado | null = null;

  readonly formatos: { valor: FormatoReporte; texto: string }[] = [
    { valor: 'pdf', texto: 'PDF' },
    { valor: 'xlsx', texto: 'Excel' },
    { valor: 'html', texto: 'HTML' }
  ];

  constructor(
    private analiticaService: AnaliticaService,
    private assistantAdminService: AssistantAdminService
  ) {}

  ngOnInit(): void {
    this.cargar();
  }

  get vigente(): VentanaDemanda | null {
    return this.datos?.demanda.vigente ?? null;
  }

  get filasPrediccion(): FilaPrediccion[] {
    const filas = this.datos?.demanda.predicciones.filas ?? [];
    return this.sucursalFiltro ? filas.filter(f => f.sucursal === this.sucursalFiltro) : filas;
  }

  get totalPrevisto(): number {
    return this.filasPrediccion.reduce((suma, f) => suma + f.total, 0);
  }

  cargar(): void {
    this.cargando = true;
    this.error = null;
    this.analiticaService.dashboard(this.empresaSeleccionada).subscribe({
      next: (datos) => {
        this.datos = datos;
        this.empresaSeleccionada = datos.empresa.id;
        this.sucursalFiltro = '';
        this.armarGraficos(datos);
        this.cargando = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || 'No se pudo cargar la analítica. Intenta de nuevo.';
        this.cargando = false;
      }
    });
  }

  cambiarEmpresa(): void {
    this.mensaje = null;
    this.cargar();
  }

  reentrenar(alcance: 'una' | 'todas'): void {
    if (this.reentrenando) {
      return;
    }
    this.reentrenando = alcance;
    this.mensaje = null;
    this.error = null;
    const empresa = alcance === 'todas' ? 'todas' : this.empresaSeleccionada;
    this.analiticaService.reentrenar(empresa).subscribe({
      next: (r) => {
        const nombres = r.resultados.map(x => x.empresa).join(', ');
        this.mensaje = `Modelos reentrenados con los datos actuales: ${nombres}.`;
        this.reentrenando = null;
        this.cargar();
      },
      error: (err) => {
        this.error = err?.error?.detail || 'No se pudo reentrenar. Intenta de nuevo.';
        this.reentrenando = null;
      }
    });
  }

  descargar(reporte: ReporteAnalitica, formato: FormatoReporte): void {
    if (this.descargando) {
      return;
    }
    this.descargando = `${reporte}-${formato}`;
    this.analiticaService.exportar(this.empresaSeleccionada, reporte, formato).subscribe({
      next: (respuesta) => {
        this.assistantAdminService.guardarArchivo(respuesta, formato);
        this.descargando = null;
      },
      error: () => {
        this.error = 'No se pudo descargar el archivo. Intenta de nuevo.';
        this.descargando = null;
      }
    });
  }

  // Compara el error del modelo con el de la línea base (promedio de 4 semanas).
  comparacion(v: VentanaDemanda | null): Comparacion | null {
    if (!v || v.mae === null || v.mae_linea_base === null) {
      return null;
    }
    if (v.mae < v.mae_linea_base * 0.98) {
      return 'mejor';
    }
    return v.mae > v.mae_linea_base * 1.02 ? 'peor' : 'similar';
  }

  textoComparacion(v: VentanaDemanda | null): string {
    const c = this.comparacion(v);
    if (c === 'mejor') {
      return 'Mejor que la línea base';
    }
    if (c === 'peor') {
      return 'Por debajo de la línea base';
    }
    return c === 'similar' ? 'Similar a la línea base' : '';
  }

  semanaCorta(iso: string): string {
    return `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
  }

  claseSegmento(segmento: Segmento): string {
    return `seg-${segmento.toLowerCase()}`;
  }

  private armarGraficos(datos: DashboardAnalitica): void {
    const ventanas = datos.demanda.ventanas.filter(v => !v.aviso);
    this.graficoVentanas = ventanas.length ? {
      tipo: 'bar',
      titulo: 'Error (MAE) por ventana de entrenamiento',
      etiquetas: ventanas.map(v => `${v.ventana_meses} meses`),
      series: [
        { nombre: 'Modelo', datos: ventanas.map(v => v.mae ?? 0) },
        { nombre: 'Línea base', datos: ventanas.map(v => v.mae_linea_base ?? 0) }
      ],
      formato: 'numero'
    } : null;

    const vigente = datos.demanda.vigente;
    const prueba = vigente?.serie_prueba ?? [];
    this.graficoPrueba = prueba.length ? {
      tipo: 'line',
      titulo: 'Unidades reales vs. predichas (semanas de prueba)',
      etiquetas: prueba.map(p => this.semanaCorta(p.semana)),
      series: [
        { nombre: 'Real', datos: prueba.map(p => p.real) },
        { nombre: 'Predicho', datos: prueba.map(p => p.predicho) }
      ],
      formato: 'numero'
    } : null;

    const importancias = (vigente?.importancias ?? []).slice(0, 8);
    this.graficoImportancia = importancias.length ? {
      tipo: 'barh',
      titulo: 'Importancia de las variables (%)',
      etiquetas: importancias.map(i => i.variable),
      series: [{ nombre: 'Importancia', datos: importancias.map(i => Math.round(i.importancia * 1000) / 10) }],
      formato: 'numero'
    } : null;

    const filas = datos.demanda.predicciones.filas;
    this.sucursales = Array.from(new Set(filas.map(f => f.sucursal))).sort();
    const porPrenda = new Map<string, number>();
    filas.forEach(f => porPrenda.set(f.prenda, (porPrenda.get(f.prenda) ?? 0) + f.total));
    const prendas = Array.from(porPrenda.entries()).sort((a, b) => b[1] - a[1]).slice(0, 10);
    this.graficoPrendas = prendas.length ? {
      tipo: 'barh',
      titulo: 'Unidades previstas por prenda (4 semanas, todas las sucursales)',
      etiquetas: prendas.map(p => p[0]),
      series: [{ nombre: 'Unidades', datos: prendas.map(p => Math.round(p[1] * 100) / 100) }],
      formato: 'numero'
    } : null;

    // Orden pensado para que la paleta del gráfico coincida con los colores de
    // las tarjetas: VIP azul, en riesgo rojo, leales verde y ocasionales naranja.
    const seg = datos.segmentacion;
    const orden: Segmento[] = ['VIP', 'RIESGO', 'LEAL', 'OCASIONAL'];
    const resumen = [...(seg?.resumen ?? [])].sort((a, b) => orden.indexOf(a.segmento) - orden.indexOf(b.segmento));
    this.graficoSegmentos = resumen.length ? {
      tipo: 'doughnut',
      titulo: 'Clientes por segmento',
      etiquetas: resumen.map(r => r.nombre),
      series: [{ nombre: 'Clientes', datos: resumen.map(r => r.clientes) }],
      formato: 'numero'
    } : null;

    const silhouette = Object.entries(seg?.silhouette ?? {});
    this.graficoSilhouette = silhouette.length ? {
      tipo: 'bar',
      titulo: 'Silhouette según la cantidad de grupos (k)',
      etiquetas: silhouette.map(([k]) => `k = ${k}`),
      series: [{ nombre: 'Silhouette', datos: silhouette.map(([, valor]) => valor) }],
      formato: 'numero'
    } : null;
  }
}