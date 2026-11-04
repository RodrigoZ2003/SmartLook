// web/src/app/modules/assistant-admin/pages/assistant-admin-home/assistant-admin-home.component.ts
//
// NUEVO (CU20): pantalla del asistente de gestión (SUPER_ADMIN, ADMIN_EMPRESA
// y ENCARGADO_SUCURSAL). Chat por texto o voz a la izquierda; resultado de la
// pregunta y descargas a la derecha; historial de reportes abajo.
// MODIFICADO (Fase 3 - CU13): el resultado muestra su gráfico (Chart.js) y,
// si en el chat se pide "descárgamelo en PDF / Excel / HTML", el archivo se
// descarga solo (el backend indica qué reporte y en qué formato).
import { Component, ElementRef, NgZone, OnDestroy, OnInit, ViewChild } from '@angular/core';
import {
  AssistantAdminService,
  ExportacionPedida,
  FormatoReporte,
  ReporteDetalle,
  ReporteGenerado,
  ReporteResumen
} from '../../services/assistant-admin.service';

interface ParteTexto {
  texto: string;
  negrita: boolean;
}

interface MensajeChat {
  esUsuario: boolean;
  partes: ParteTexto[];
  error: boolean;
}

// Tipos mínimos de la Web Speech API (no forman parte de lib.dom estable).
interface SpeechRecognitionEvento {
  results: { [i: number]: { [j: number]: { transcript: string } } };
}
interface SpeechRecognitionInstancia {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((ev: SpeechRecognitionEvento) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
}

@Component({
  selector: 'app-assistant-admin-home',
  templateUrl: './assistant-admin-home.component.html',
  styleUrls: ['./assistant-admin-home.component.scss']
})
export class AssistantAdminHomeComponent implements OnInit, OnDestroy {
  @ViewChild('lista') lista?: ElementRef<HTMLDivElement>;

  entrada = '';
  mensajes: MensajeChat[] = [];
  enviando = false;
  escuchando = false;
  reconocimientoDisponible = false;

  reporteActivo: ReporteDetalle | ReporteGenerado | null = null;
  descargando: FormatoReporte | null = null;

  reportes: ReporteResumen[] = [];
  cargandoReportes = true;

  readonly maxCaracteres = 500;
  readonly sugerencias = [
    'Ventas de este mes por sucursal',
    'Compará las sucursales de los últimos tres meses',
    'Gráfico de ventas por semana de este año',
    'Productos con menor existencia'
  ];

  private reconocimiento: SpeechRecognitionInstancia | null = null;
  private temporizadorVoz: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private assistantAdminService: AssistantAdminService,
    private ngZone: NgZone
  ) {}

  ngOnInit(): void {
    this.cargarReportes();
    this.iniciarReconocimientoVoz();
  }

  ngOnDestroy(): void {
    if (this.temporizadorVoz) {
      clearTimeout(this.temporizadorVoz);
    }
    this.reconocimiento?.abort();
  }

  enviar(texto?: string): void {
    const mensaje = (texto ?? this.entrada).trim();
    if (!mensaje || this.enviando) {
      return;
    }
    this.mensajes.push(this.crearMensaje(true, mensaje));
    this.entrada = '';
    this.enviando = true;
    this.irAlFinal();

    this.assistantAdminService.preguntar(mensaje).subscribe({
      next: (respuesta) => {
        this.mensajes.push(this.crearMensaje(false, respuesta.respuesta));
        if (respuesta.resultados.length > 0) {
          this.reporteActivo = respuesta.resultados[0];
          this.cargarReportes();
        }
        // NUEVO (CU13): descarga pedida en el chat.
        if (respuesta.exportar) {
          this.exportarPedido(respuesta.exportar);
        }
        this.enviando = false;
        this.irAlFinal();
      },
      error: (err) => {
        const detalle = err?.error?.detail;
        this.mensajes.push(
          this.crearMensaje(
            false,
            detalle || 'No pude responder en este momento. Intenta de nuevo en unos minutos.',
            true
          )
        );
        this.enviando = false;
        this.irAlFinal();
      }
    });
  }

  alternarMicrofono(): void {
    if (!this.reconocimiento) {
      return;
    }
    if (this.escuchando) {
      this.detenerReconocimiento();
      return;
    }
    this.entrada = '';
    this.escuchando = true;
    this.reconocimiento.start();
    // Corte de seguridad: si el navegador no detecta el silencio y se queda
    // escuchando, se corta solo a los 8 segundos.
    this.temporizadorVoz = setTimeout(() => this.detenerReconocimiento(), 8000);
  }

  abrirReporte(resumen: ReporteResumen): void {
    this.assistantAdminService.obtenerReporte(resumen.id_reporte).subscribe({
      next: (detalle) => (this.reporteActivo = detalle),
      error: () => undefined
    });
  }

  descargar(formato: FormatoReporte): void {
    const reporte = this.reporteActivo;
    if (!reporte) {
      return;
    }
    this.descargarReporte(reporte.id_reporte, formato);
  }

  // NUEVO (CU13): muestra el reporte pedido en el chat (si no es el que está
  // en pantalla) y lo descarga en el formato indicado.
  private exportarPedido(pedido: ExportacionPedida): void {
    if (this.reporteActivo?.id_reporte !== pedido.id_reporte) {
      this.assistantAdminService.obtenerReporte(pedido.id_reporte).subscribe({
        next: (detalle) => (this.reporteActivo = detalle),
        error: () => undefined
      });
    }
    this.descargarReporte(pedido.id_reporte, pedido.formato);
  }

  private descargarReporte(idReporte: number, formato: FormatoReporte): void {
    if (this.descargando) {
      return;
    }
    this.descargando = formato;
    this.assistantAdminService.descargarReporte(idReporte, formato).subscribe({
      next: (respuesta) => {
        this.assistantAdminService.guardarArchivo(respuesta, formato);
        this.descargando = null;
      },
      error: () => {
        this.mensajes.push(this.crearMensaje(false, 'No pude descargar el archivo. Intenta de nuevo.', true));
        this.descargando = null;
        this.irAlFinal();
      }
    });
  }

  private cargarReportes(): void {
    this.cargandoReportes = true;
    this.assistantAdminService.listarReportes().subscribe({
      next: (lista) => {
        this.reportes = lista;
        this.cargandoReportes = false;
      },
      error: () => (this.cargandoReportes = false)
    });
  }

  private crearMensaje(esUsuario: boolean, texto: string, error = false): MensajeChat {
    return { esUsuario, partes: this.aPartes(texto), error };
  }

  // El modelo responde con un Markdown mínimo: viñetas ("* ", "- ") y **negrita**.
  private aPartes(texto: string): ParteTexto[] {
    const limpio = (texto || '').replace(/^[ \t]*[*-][ \t]+/gm, '• ');
    const partes: ParteTexto[] = [];
    const patron = /\*\*(.+?)\*\*/g;
    let ultimo = 0;
    let coincidencia: RegExpExecArray | null;
    while ((coincidencia = patron.exec(limpio)) !== null) {
      if (coincidencia.index > ultimo) {
        partes.push({ texto: limpio.slice(ultimo, coincidencia.index), negrita: false });
      }
      partes.push({ texto: coincidencia[1], negrita: true });
      ultimo = coincidencia.index + coincidencia[0].length;
    }
    if (ultimo < limpio.length) {
      partes.push({ texto: limpio.slice(ultimo), negrita: false });
    }
    return partes;
  }

  private irAlFinal(): void {
    setTimeout(() => {
      const el = this.lista?.nativeElement;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }, 0);
  }

  private detenerReconocimiento(): void {
    if (this.temporizadorVoz) {
      clearTimeout(this.temporizadorVoz);
      this.temporizadorVoz = null;
    }
    // abort() corta de inmediato, sin esperar un resultado. Es más fiable
    // que stop() cuando el navegador no detectó el fin del silencio.
    this.reconocimiento?.abort();
    this.escuchando = false;
  }

  private iniciarReconocimientoVoz(): void {
    const global = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionInstancia;
      webkitSpeechRecognition?: new () => SpeechRecognitionInstancia;
    };
    const Motor = global.SpeechRecognition ?? global.webkitSpeechRecognition;
    if (!Motor) {
      this.reconocimientoDisponible = false;
      return;
    }
    const instancia = new Motor();
    instancia.lang = 'es-ES';
    instancia.continuous = false;
    instancia.interimResults = false;
    instancia.onresult = (ev) => {
      this.ngZone.run(() => {
        this.entrada = ev.results[0][0].transcript;
        this.detenerReconocimiento();
      });
    };
    instancia.onerror = () => this.ngZone.run(() => this.detenerReconocimiento());
    instancia.onend = () => this.ngZone.run(() => this.detenerReconocimiento());
    this.reconocimiento = instancia;
    this.reconocimientoDisponible = true;
  }
}