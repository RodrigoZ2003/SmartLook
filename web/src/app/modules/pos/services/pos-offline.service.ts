// web/src/app/modules/pos/services/pos-offline.service.ts
//
// NUEVO (SaaS - A.5): POS sin conexión en la web.
// - Cola local (IndexedDB) de ventas hechas sin internet. Cada venta lleva
//   un UUID propio y la hora en que se hizo.
// - Estados de cada venta local (punto 5.4 del enunciado):
//     REGISTRADA  -> guardada en el dispositivo, aún no enviada.
//     ENVIADA     -> enviada al servidor, esperando su respuesta.
//     CONFIRMADA  -> el servidor la registró (queda con su número de venta).
//     RECHAZADA   -> el servidor no la aceptó (queda con el motivo).
//   Una venta nunca se borra solo por haberse intentado enviar: si el envío
//   falla vuelve a REGISTRADA (el UUID evita duplicados al reenviarla).
//   Las CONFIRMADAS quedan como historial hasta que el cajero las quite; las
//   RECHAZADAS, hasta que el cajero las descarte.
// - Copia local del catálogo y de las sucursales para buscar prendas y
//   elegir sucursal sin conexión (con la fecha en que se descargó).
// - Stock local: al guardar una venta sin conexión se resta del catálogo
//   guardado, y si la venta se descarta por rechazada se devuelve. Al volver
//   a descargar el catálogo se restan las ventas que aún no llegan al servidor.
// - Si el equipo tiene red pero el servidor no respondía (servidor caído),
//   cada 20 segundos se vuelve a consultar; cuando responde, el POS vuelve a
//   "En línea" y envía la cola sin esperar a recargar la página.
// MODIFICADO (A.6 - PWA): el UUID y la detección de fallos de red vienen de
// ConexionService (con el service worker, un fallo de red llega como 504) y
// la consulta al servidor lleva "_ping" para que nunca se responda con la
// copia guardada del catálogo.
// MODIFICADO (Fase 2 - CU08): cada venta envía el precio cobrado sin conexión
// y el correo del cliente (opcional). Nuevo estado local EN_CONFLICTO: el
// servidor registró la venta, pero con precio distinto o sin stock; queda
// para que el encargado o el administrador la resuelva.
import { Injectable } from '@angular/core';
import { BehaviorSubject, firstValueFrom } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { esErrorDeRed, nuevoUuid } from '../../../core/services/conexion.service';
import {
  ALMACEN_CACHE,
  ALMACEN_VENTAS,
  OfflineDbService
} from '../../../core/services/offline-db.service';

export type EstadoVentaLocal = 'REGISTRADA' | 'ENVIADA' | 'CONFIRMADA' | 'EN_CONFLICTO' | 'RECHAZADA';

// Detalle de un conflicto devuelto por el servidor (por prenda).
export interface ConflictoVenta {
  tipo: 'PRECIO' | 'STOCK';
  prenda: string;
  cantidad: number;
  precio_offline?: string;
  precio_servidor?: string;
  diferencia?: string;
  stock_disponible?: number;
}

export interface ItemVentaLocal {
  id_variante: number;
  nombre: string;
  precio: number;
  cantidad: number;
}

export interface VentaLocal {
  uuid: string;
  fecha_operacion: string;
  id_sucursal: number;
  sucursal: string;
  metodo_pago: string;
  correo_cliente: string | null;
  items: ItemVentaLocal[];
  total: number;
  estado: EstadoVentaLocal;
  mensaje: string | null;
  intentos: number;
  id_usuario: number | null;
  id_venta: number | null;
  fecha_confirmacion: string | null;
  tipo_conflicto: string | null;
  conflictos: ConflictoVenta[];
}

export interface ResultadoSync {
  sincronizadas: number;
  duplicadas: number;
  en_conflicto: number;
  rechazadas: number;
  error: string | null;
  fecha: string;
}

export interface VarianteLocal {
  id_variante: number;
  nombre_completo: string;
  codigo_producto: string;
  precio: number;
  cantidad: number;
}

interface EntradaCache<T> {
  clave: string;
  fecha: string;
  datos: T;
}

const MAX_POR_LOTE = 100;
const PAGINA_CATALOGO = 100;
const MAX_PAGINAS_CATALOGO = 50;
// Cada cuánto se vuelve a consultar al servidor cuando no respondía.
const INTERVALO_REINTENTO_MS = 20000;

// Quita tildes y pasa a minúsculas para buscar sin importar cómo se escribió.
function normalizar(texto: string): string {
  return (texto || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

// Ventas guardadas con la versión anterior (PENDIENTE / ENVIANDO) pasan a los
// estados nuevos para no perder ninguna.
function normalizarVenta(venta: any): VentaLocal {
  const equivalencias: { [clave: string]: EstadoVentaLocal } = {
    PENDIENTE: 'REGISTRADA',
    ENVIANDO: 'ENVIADA'
  };
  return {
    ...venta,
    estado: equivalencias[venta.estado] || venta.estado,
    id_venta: venta.id_venta ?? null,
    fecha_confirmacion: venta.fecha_confirmacion ?? null,
    correo_cliente: venta.correo_cliente ?? null,
    tipo_conflicto: venta.tipo_conflicto ?? null,
    conflictos: venta.conflictos ?? []
  };
}

function porEnviar(venta: VentaLocal): boolean {
  return venta.estado === 'REGISTRADA' || venta.estado === 'ENVIADA';
}

@Injectable({
  providedIn: 'root'
})
export class PosOfflineService {
  private enLineaSubject = new BehaviorSubject<boolean>(navigator.onLine);
  enLinea$ = this.enLineaSubject.asObservable();
  private ventasSubject = new BehaviorSubject<VentaLocal[]>([]);
  ventas$ = this.ventasSubject.asObservable();
  private sincronizandoSubject = new BehaviorSubject<boolean>(false);
  sincronizando$ = this.sincronizandoSubject.asObservable();
  private resultadoSubject = new BehaviorSubject<ResultadoSync | null>(null);
  resultado$ = this.resultadoSubject.asObservable();
  private comprobando = false;

  constructor(private db: OfflineDbService, private api: ApiService) {
    window.addEventListener('online', () => {
      this.enLineaSubject.next(true);
      this.sincronizar();
    });
    window.addEventListener('offline', () => this.enLineaSubject.next(false));
    setInterval(() => this.comprobarServidor(), INTERVALO_REINTENTO_MS);
    this.recargar();
  }

  get enLinea(): boolean {
    return this.enLineaSubject.value;
  }

  // Una petición falló por red (status 0): se trata como sin conexión.
  marcarSinConexion(): void {
    this.enLineaSubject.next(false);
  }

  esErrorDeRed(err: any): boolean {
    return esErrorDeRed(err);
  }

  // El equipo tiene red pero el POS está "Sin conexión" porque el servidor no
  // respondía: si ahora responde (con cualquier código), se vuelve a "En línea".
  private async comprobarServidor(): Promise<void> {
    if (this.enLinea || !navigator.onLine || this.comprobando) {
      return;
    }
    this.comprobando = true;
    try {
      await firstValueFrom(this.api.get<any>('/catalog/sucursales/', { page_size: 1, _ping: Date.now() }));
      this.volverEnLinea();
    } catch (err) {
      if (!this.esErrorDeRed(err)) {
        this.volverEnLinea();
      }
    } finally {
      this.comprobando = false;
    }
  }

  private volverEnLinea(): void {
    this.enLineaSubject.next(true);
    this.sincronizar();
  }

  private usuarioActual(): number | null {
    try {
      const usuario = JSON.parse(localStorage.getItem('usuario') || 'null');
      return usuario?.id_usuario ?? null;
    } catch {
      return null;
    }
  }

  // Ventas locales del usuario de la sesión (cada cajero ve y envía solo las suyas).
  private async ventasDelUsuario(): Promise<VentaLocal[]> {
    const usuario = this.usuarioActual();
    const ventas = await this.db.todos<any>(ALMACEN_VENTAS);
    return ventas.map(normalizarVenta).filter(v => v.id_usuario === usuario);
  }

  // Para mostrar: las más recientes primero.
  async recargar(): Promise<void> {
    try {
      const ventas = await this.ventasDelUsuario();
      this.ventasSubject.next(ventas.sort((a, b) => b.fecha_operacion.localeCompare(a.fecha_operacion)));
    } catch {
      this.ventasSubject.next([]);
    }
  }

  async guardarVenta(datos: {
    id_sucursal: number;
    sucursal: string;
    metodo_pago: string;
    correo_cliente?: string | null;
    items: ItemVentaLocal[];
  }): Promise<VentaLocal> {
    const venta: VentaLocal = {
      uuid: nuevoUuid(),
      fecha_operacion: new Date().toISOString(),
      id_sucursal: datos.id_sucursal,
      sucursal: datos.sucursal,
      metodo_pago: datos.metodo_pago,
      correo_cliente: (datos.correo_cliente || '').trim() || null,
      items: datos.items.map(i => ({ ...i })),
      total: datos.items.reduce((s, i) => s + i.precio * i.cantidad, 0),
      estado: 'REGISTRADA',
      mensaje: null,
      intentos: 0,
      id_usuario: this.usuarioActual(),
      id_venta: null,
      fecha_confirmacion: null,
      tipo_conflicto: null,
      conflictos: []
    };
    await this.db.guardar(ALMACEN_VENTAS, venta);
    await this.ajustarStockLocal(venta.items, -1);
    await this.recargar();
    return venta;
  }

  // Solo se descartan las rechazadas, después de que el cajero leyó el motivo.
  // Como el servidor no la registró, sus prendas vuelven al stock local.
  async descartar(venta: VentaLocal): Promise<void> {
    if (venta.estado !== 'RECHAZADA') {
      return;
    }
    await this.db.eliminar(ALMACEN_VENTAS, venta.uuid);
    await this.ajustarStockLocal(venta.items, 1);
    await this.recargar();
  }

  // Quita del dispositivo el historial de ventas que el servidor ya registró
  // (confirmadas y en conflicto: el conflicto se resuelve en el servidor).
  async limpiarConfirmadas(): Promise<void> {
    const ventas = await this.ventasDelUsuario();
    for (const venta of ventas.filter(v => v.estado === 'CONFIRMADA' || v.estado === 'EN_CONFLICTO')) {
      await this.db.eliminar(ALMACEN_VENTAS, venta.uuid);
    }
    await this.recargar();
  }

  async sincronizar(): Promise<ResultadoSync | null> {
    if (this.sincronizandoSubject.value || !navigator.onLine || !localStorage.getItem('access_token')) {
      return null;
    }
    let pendientes: VentaLocal[];
    try {
      pendientes = (await this.ventasDelUsuario())
        .filter(porEnviar)
        .sort((a, b) => a.fecha_operacion.localeCompare(b.fecha_operacion));
    } catch {
      return null;
    }
    if (pendientes.length === 0) {
      return null;
    }
    this.sincronizandoSubject.next(true);
    const resultado: ResultadoSync = {
      sincronizadas: 0, duplicadas: 0, en_conflicto: 0, rechazadas: 0, error: null,
      fecha: new Date().toISOString()
    };
    try {
      for (let i = 0; i < pendientes.length; i += MAX_POR_LOTE) {
        const lote = pendientes.slice(i, i + MAX_POR_LOTE);
        await this.enviarLote(lote, resultado);
      }
    } catch (err) {
      resultado.error = this.textoErrorSync(err);
      if (this.esErrorDeRed(err)) {
        this.marcarSinConexion();
      }
    } finally {
      this.sincronizandoSubject.next(false);
      this.resultadoSubject.next(resultado);
      await this.recargar();
    }
    return resultado;
  }

  private async enviarLote(lote: VentaLocal[], resultado: ResultadoSync): Promise<void> {
    for (const venta of lote) {
      venta.estado = 'ENVIADA';
      venta.intentos += 1;
      await this.db.guardar(ALMACEN_VENTAS, venta);
    }
    await this.recargar();
    let respuesta: any;
    try {
      respuesta = await firstValueFrom(this.api.post<any>('/sales/sync/ventas-pos/', {
        operaciones: lote.map(v => ({
          uuid: v.uuid,
          fecha_operacion: v.fecha_operacion,
          id_sucursal: v.id_sucursal,
          metodo_pago: v.metodo_pago,
          correo_cliente: v.correo_cliente || undefined,
          // CU08: el precio que se cobró sin conexión (el servidor lo compara).
          items: v.items.map(i => ({
            id_variante: i.id_variante,
            cantidad: i.cantidad,
            precio_unitario: Number(i.precio).toFixed(2)
          }))
        }))
      }));
    } catch (err) {
      // No llegó respuesta válida: todo el lote vuelve a REGISTRADA para reintentar.
      for (const venta of lote) {
        venta.estado = 'REGISTRADA';
        await this.db.guardar(ALMACEN_VENTAS, venta);
      }
      throw err;
    }
    // El servidor respondió: hay conexión.
    if (!this.enLinea) {
      this.enLineaSubject.next(true);
    }
    const porUuid = new Map<string, VentaLocal>(lote.map(v => [v.uuid, v] as [string, VentaLocal]));
    for (const r of respuesta?.resultados || []) {
      const venta = r.uuid ? porUuid.get(r.uuid) : undefined;
      if (!venta) {
        continue;
      }
      porUuid.delete(r.uuid);
      if (r.estado === 'SINCRONIZADA' || r.estado === 'DUPLICADA') {
        venta.estado = 'CONFIRMADA';
        venta.id_venta = r.id_venta ?? null;
        venta.fecha_confirmacion = new Date().toISOString();
        venta.mensaje = r.estado === 'DUPLICADA' ? 'Ya estaba registrada en el servidor.' : null;
        if (r.estado === 'SINCRONIZADA') {
          resultado.sincronizadas += 1;
        } else {
          resultado.duplicadas += 1;
        }
        if (r.mensaje && r.estado === 'SINCRONIZADA' && r.mensaje !== 'Venta registrada.') {
          venta.mensaje = r.mensaje;
        }
      } else if (r.estado === 'EN_CONFLICTO') {
        // CU08: el servidor registró la venta, pero queda para revisión.
        venta.estado = 'EN_CONFLICTO';
        venta.id_venta = r.id_venta ?? null;
        venta.fecha_confirmacion = new Date().toISOString();
        venta.mensaje = r.mensaje || 'Venta registrada en conflicto.';
        venta.tipo_conflicto = r.tipo_conflicto ?? null;
        venta.conflictos = r.conflictos || [];
        resultado.en_conflicto += 1;
      } else {
        venta.estado = 'RECHAZADA';
        venta.mensaje = r.mensaje || 'El servidor rechazó la venta.';
        resultado.rechazadas += 1;
      }
      await this.db.guardar(ALMACEN_VENTAS, venta);
    }
    // Las que no vinieron en la respuesta se reintentan después.
    for (const venta of porUuid.values()) {
      venta.estado = 'REGISTRADA';
      await this.db.guardar(ALMACEN_VENTAS, venta);
    }
  }

  private textoErrorSync(err: any): string {
    if (this.esErrorDeRed(err)) {
      return 'Sin conexión con el servidor. Las ventas siguen guardadas y se enviarán después.';
    }
    if (err?.status === 401) {
      return 'Tu sesión expiró. Inicia sesión de nuevo para enviar las ventas pendientes.';
    }
    return err?.error?.detail || err?.error?.error || 'No se pudieron enviar las ventas pendientes.';
  }

  // ---------------------------------------------------------------- catálogo y sucursales locales
  private claveCache(nombre: string): string {
    return `${nombre}_${this.usuarioActual() ?? 'anonimo'}`;
  }

  async descargarCatalogo(): Promise<EntradaCache<VarianteLocal[]>> {
    const variantes: VarianteLocal[] = [];
    for (let pagina = 1; pagina <= MAX_PAGINAS_CATALOGO; pagina++) {
      const data: any = await firstValueFrom(
        this.api.get<any>('/catalog/variantes/', { page_size: PAGINA_CATALOGO, page: pagina })
      );
      const filas: any[] = data?.results || data || [];
      for (const v of filas) {
        variantes.push({
          id_variante: v.id_variante,
          nombre_completo: v.nombre_completo,
          codigo_producto: v.codigo_producto,
          precio: Number(v.precio) || 0,
          cantidad: Number(v.cantidad) || 0
        });
      }
      if (!data?.next) {
        break;
      }
    }
    // Las ventas que aún no llegan al servidor todavía no bajaron su stock allá.
    const sinEnviar = (await this.ventasDelUsuario().catch(() => [] as VentaLocal[])).filter(porEnviar);
    const reservado = this.cantidadesPorVariante(sinEnviar.flatMap(v => v.items));
    for (const variante of variantes) {
      const cantidad = reservado.get(variante.id_variante) || 0;
      variante.cantidad = Math.max(0, variante.cantidad - cantidad);
    }
    const entrada: EntradaCache<VarianteLocal[]> = {
      clave: this.claveCache('pos_catalogo'),
      fecha: new Date().toISOString(),
      datos: variantes
    };
    await this.db.guardar(ALMACEN_CACHE, entrada);
    return entrada;
  }

  async catalogoLocal(): Promise<EntradaCache<VarianteLocal[]> | null> {
    try {
      return (await this.db.obtener<EntradaCache<VarianteLocal[]>>(
        ALMACEN_CACHE, this.claveCache('pos_catalogo')
      )) || null;
    } catch {
      return null;
    }
  }

  async buscarLocal(termino: string): Promise<VarianteLocal[]> {
    const catalogo = await this.catalogoLocal();
    const buscado = normalizar(termino.trim());
    if (!catalogo || !buscado) {
      return [];
    }
    return catalogo.datos
      .filter(v => normalizar(v.nombre_completo).includes(buscado) || normalizar(v.codigo_producto).includes(buscado))
      .slice(0, 50);
  }

  // Revisa la venta contra el stock local conocido. Devuelve el motivo si
  // alguna prenda no alcanza, o null si se puede vender.
  async validarStockLocal(items: ItemVentaLocal[]): Promise<string | null> {
    const catalogo = await this.catalogoLocal();
    if (!catalogo) {
      return null;
    }
    const pedidas = this.cantidadesPorVariante(items);
    for (const [idVariante, cantidad] of pedidas) {
      const variante = catalogo.datos.find(v => v.id_variante === idVariante);
      if (variante && cantidad > variante.cantidad) {
        return `Stock local insuficiente para ${variante.nombre_completo}: quedan ${variante.cantidad}.`;
      }
    }
    return null;
  }

  // signo -1 resta (venta guardada), +1 devuelve (venta descartada).
  private async ajustarStockLocal(items: ItemVentaLocal[], signo: number): Promise<void> {
    const catalogo = await this.catalogoLocal();
    if (!catalogo) {
      return;
    }
    const cantidades = this.cantidadesPorVariante(items);
    for (const variante of catalogo.datos) {
      const cantidad = cantidades.get(variante.id_variante);
      if (cantidad) {
        variante.cantidad = Math.max(0, variante.cantidad + signo * cantidad);
      }
    }
    await this.db.guardar(ALMACEN_CACHE, catalogo).catch(() => undefined);
  }

  private cantidadesPorVariante(items: ItemVentaLocal[]): Map<number, number> {
    const cantidades = new Map<number, number>();
    for (const item of items) {
      cantidades.set(item.id_variante, (cantidades.get(item.id_variante) || 0) + item.cantidad);
    }
    return cantidades;
  }

  async guardarSucursales(sucursales: any[]): Promise<void> {
    await this.db.guardar(ALMACEN_CACHE, {
      clave: this.claveCache('pos_sucursales'),
      fecha: new Date().toISOString(),
      datos: sucursales.map(s => ({ id_sucursal: s.id_sucursal, nombre: s.nombre }))
    });
  }

  async sucursalesLocales(): Promise<any[]> {
    try {
      const entrada = await this.db.obtener<EntradaCache<any[]>>(ALMACEN_CACHE, this.claveCache('pos_sucursales'));
      return entrada?.datos || [];
    } catch {
      return [];
    }
  }
}