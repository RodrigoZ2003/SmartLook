// web/src/app/layout/layout.component.ts
//
// CU21: además de esCliente, expone esPersonal (administración/tienda),
// esSoloRepartidor y puedeVerEntregas, para que la plantilla muestre a cada
// rol solamente su propio menú.
// MODIFICADO (CU20): se agrega puedeVerAsistente (asistente de gestión).
// NUEVO (devoluciones): se agrega puedeVerDevoluciones.
// NUEVO (SaaS): se agregan esSuperAdmin y puedeVerEmpresas (menú Empresas / Mi empresa).
// NUEVO (SaaS - A.2): la barra superior muestra la empresa del personal (leída
// del JWT) y, si tiene una asignada, su sucursal.
// NUEVO (SaaS - A.3): carga el plan de la empresa del personal para ocultar el
// asistente IA si el plan no lo incluye, muestra "Mi plan" al ADMIN_EMPRESA y
// avisa cuando la suscripción vence o cuando el backend rechaza algo por el plan.
// NUEVO (SaaS - A.5/A.6): aviso de conexión en la barra superior (sin internet, o
// mostrando información guardada que puede estar desactualizada) y envío
// automático de las operaciones sin conexión (ventas del POS y reservas del
// cliente) en cualquier pantalla, apenas vuelve la conexión.
// NUEVO (Fase 2 - CU16): campana de notificaciones con contador y lista. La ven
// el cliente, el SUPER_ADMIN y el ADMIN_EMPRESA (cajero, encargado y repartidor
// no reciben avisos). El contador se consulta cada minuto (sin push).
import { Component, OnDestroy } from '@angular/core';
import { Router } from '@angular/router';
import { Subscription, timer } from 'rxjs';
import { AuthService, EmpresaSesion } from '../core/auth/auth.service';
import { PlanService } from '../core/services/plan.service';
import { AvisoPlan, AvisoPlanService } from '../core/services/aviso-plan.service';
import { formatoFecha } from '../modules/empresas/services/empresa.service';
import { ConexionService } from '../core/services/conexion.service';
import { PosOfflineService } from '../modules/pos/services/pos-offline.service';
import { ReservaOfflineService } from '../modules/reservations/services/reserva-offline.service';
import { Notificacion, NotificacionesService } from '../core/services/notificaciones.service';
const ROLES_PERSONAL = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL', 'CAJERO'];
const ROLES_ENTREGAS = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL', 'REPARTIDOR'];
const ROLES_ASISTENTE = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];
const ROLES_DEVOLUCIONES = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL'];
const ROLES_EMPRESAS = ['SUPER_ADMIN', 'ADMIN_EMPRESA'];
// NUEVO (CU16): el personal que recibe avisos.
const ROLES_NOTIFICACIONES = ['SUPER_ADMIN', 'ADMIN_EMPRESA'];
const INTERVALO_NOTIFICACIONES_MS = 60 * 1000;
@Component({
  selector: 'app-layout',
  templateUrl: './layout.component.html',
  styleUrls: ['./layout.component.css']
})
export class LayoutComponent implements OnDestroy {
  usuario: any = null;
  esCliente = false;
  esSoloRepartidor = false;
  esPersonal = false;
  puedeVerEntregas = false;
  puedeVerAsistente = false;
  puedeVerDevoluciones = false;
  esSuperAdmin = false;
  puedeVerEmpresas = false;
  empresa: EmpresaSesion | null = null;
  sucursal: string | null = null;
  esAdminEmpresa = false;
  planIncluyeIA = true;
  aviso: AvisoPlan | null = null;
  avisoSuscripcion: string | null = null;
  suscripcionVencida = false;
  enLinea = true;
  copiaLocal: string | null = null;
  // NUEVO (CU16): campana de notificaciones.
  puedeVerNotificaciones = false;
  noLeidas = 0;
  notificaciones: Notificacion[] = [];
  panelNotificaciones = false;
  cargandoNotificaciones = false;
  private suscripciones = new Subscription();
  sidebarVisible = true;
  constructor(
    private authService: AuthService,
    private router: Router,
    private planService: PlanService,
    private avisoPlanService: AvisoPlanService,
    private conexion: ConexionService,
    private posOffline: PosOfflineService,
    private reservaOffline: ReservaOfflineService,
    private notificacionesService: NotificacionesService
  ) {
    const data = localStorage.getItem('usuario');
    if (data) {
      this.usuario = JSON.parse(data);
    }
    const roles = this.authService.obtenerRoles();
    this.esCliente = this.authService.esCliente();
    this.esSoloRepartidor =
      roles.includes('REPARTIDOR') && !roles.some(rol => ROLES_PERSONAL.includes(rol));
    this.esPersonal = !this.esCliente && !this.esSoloRepartidor;
    this.puedeVerEntregas = roles.some(rol => ROLES_ENTREGAS.includes(rol));
    this.puedeVerAsistente = roles.some(rol => ROLES_ASISTENTE.includes(rol));
    this.puedeVerDevoluciones = roles.some(rol => ROLES_DEVOLUCIONES.includes(rol));
    this.esSuperAdmin = roles.includes('SUPER_ADMIN');
    this.puedeVerEmpresas = roles.some(rol => ROLES_EMPRESAS.includes(rol));
    this.empresa = this.authService.obtenerEmpresa();
    this.sucursal = this.nombreCortoSucursal(this.usuario?.sucursal_nombre);
    this.esAdminEmpresa = roles.includes('ADMIN_EMPRESA');
    this.puedeVerNotificaciones =
      this.esCliente || roles.some(rol => ROLES_NOTIFICACIONES.includes(rol));
    this.iniciarPlan();
    this.iniciarConexion();
    this.iniciarNotificaciones();
  }
  ngOnDestroy(): void {
    this.suscripciones.unsubscribe();
  }
  // El plan solo existe para el personal de una empresa; para el resto se limpia.
  private iniciarPlan(): void {
    // Se borra lo que haya quedado de una sesión anterior antes de cargar el plan nuevo.
    this.planService.limpiar();
    this.avisoPlanService.cerrar();
    this.suscripciones.add(this.avisoPlanService.aviso$.subscribe(aviso => this.aviso = aviso));
    this.suscripciones.add(this.planService.suscripcion$.subscribe(suscripcion => {
      this.planIncluyeIA = this.planService.incluye('reportes_ia');
      this.actualizarAvisoSuscripcion(suscripcion);
    }));
    if (this.empresa) {
      this.planService.cargar().subscribe();
    }
  }
  // Aviso de conexión y envío de lo que quedó pendiente de otra sesión sin conexión.
  private iniciarConexion(): void {
    this.suscripciones.add(this.conexion.enLinea$.subscribe(enLinea => this.enLinea = enLinea));
    this.suscripciones.add(this.conexion.copiaLocal$.subscribe(fecha => this.copiaLocal = fecha));
    if (this.esCliente) {
      this.reservaOffline.sincronizar();
    } else if (this.esPersonal) {
      this.posOffline.sincronizar();
    }
  }
  // Aviso fijo cuando la suscripción venció o le quedan 7 días o menos.
  private actualizarAvisoSuscripcion(suscripcion: any): void {
    this.suscripcionVencida = !!suscripcion && !suscripcion.vigente;
    if (!suscripcion) {
      this.avisoSuscripcion = null;
    } else if (!suscripcion.vigente) {
      this.avisoSuscripcion = `La suscripción de ${suscripcion.empresa} venció el ` +
        `${formatoFecha(suscripcion.fecha_vencimiento)}. Solo puedes consultar información` +
        (this.esAdminEmpresa ? ' y renovar el plan.' : '.');
    } else if (suscripcion.dias_restantes <= 7) {
      this.avisoSuscripcion = `La suscripción de ${suscripcion.empresa} vence en ` +
        `${suscripcion.dias_restantes} día(s), el ${formatoFecha(suscripcion.fecha_vencimiento)}.`;
    } else {
      this.avisoSuscripcion = null;
    }
  }
  // ---------------------------------------------------------------- notificaciones (CU16)
  // Consulta el contador al entrar y cada minuto mientras haya conexión.
  private iniciarNotificaciones(): void {
    if (!this.puedeVerNotificaciones) {
      return;
    }
    this.suscripciones.add(timer(0, INTERVALO_NOTIFICACIONES_MS).subscribe(() => {
      if (this.enLinea) {
        this.actualizarContador();
      }
    }));
  }
  private actualizarContador(): void {
    this.notificacionesService.contador().subscribe({
      next: (r) => this.noLeidas = r?.no_leidas || 0,
      error: () => undefined
    });
  }
  alternarNotificaciones(): void {
    this.panelNotificaciones = !this.panelNotificaciones;
    if (this.panelNotificaciones) {
      this.cargarNotificaciones();
    }
  }
  cerrarNotificaciones(): void {
    this.panelNotificaciones = false;
  }
  private cargarNotificaciones(): void {
    this.cargandoNotificaciones = true;
    this.notificacionesService.listar().subscribe({
      next: (data: any) => {
        this.notificaciones = data?.results || data || [];
        this.cargandoNotificaciones = false;
        this.actualizarContador();
      },
      error: () => {
        this.cargandoNotificaciones = false;
      }
    });
  }
  // Marca el aviso como leído y lleva a su pantalla.
  abrirNotificacion(notificacion: Notificacion): void {
    this.panelNotificaciones = false;
    if (!notificacion.leida) {
      notificacion.leida = true;
      this.noLeidas = Math.max(this.noLeidas - 1, 0);
      this.notificacionesService.leer(notificacion.id_notificacion).subscribe({ error: () => undefined });
    }
    if (notificacion.enlace) {
      this.router.navigateByUrl(notificacion.enlace);
    }
  }
  marcarTodasLeidas(): void {
    this.notificacionesService.leerTodas().subscribe({
      next: () => {
        this.notificaciones.forEach(n => n.leida = true);
        this.noLeidas = 0;
      },
      error: () => undefined
    });
  }
  cerrarAviso(): void {
    this.avisoPlanService.cerrar();
  }
  // "LOOK FASHION Ventura" -> "Ventura": la empresa ya se muestra al lado.
  private nombreCortoSucursal(nombre: string | null | undefined): string | null {
    if (!nombre) {
      return null;
    }
    const prefijo = this.empresa?.nombre ? `${this.empresa.nombre} ` : '';
    if (prefijo && nombre.toUpperCase().startsWith(prefijo.toUpperCase())) {
      return nombre.slice(prefijo.length).trim() || nombre;
    }
    return nombre;
  }
  cerrarSesion(): void {
    this.authService.logout();
  }
}