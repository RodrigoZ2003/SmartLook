// web/src/app/core/auth/acceso.service.ts
//
// NUEVO (arreglo RF02 - usuarios, roles y permisos): decide qué pantallas ve
// cada usuario (menú y rutas) y si puede crear, editar o eliminar en ellas.
//
// - SUPER_ADMIN y ADMIN_EMPRESA: todo.
// - CLIENTE: sus pantallas de siempre (catálogo y reservas).
// - ENCARGADO_SUCURSAL, CAJERO y REPARTIDOR: los permisos marcados para su rol
//   en "Permisos por rol". VER_x muestra la pantalla (solo consulta) y
//   GESTIONAR_x también los botones y formularios.
// - El backend vuelve a validar todo; aquí solo se decide qué se muestra.
// Los permisos llegan en el login (usuario.privilegios) y se refrescan con
// GET /api/auth/mis-privilegios/ al abrir el panel.
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, map, of } from 'rxjs';
import { environment } from '../../../environments/environment';

export type Modulo =
  | 'dashboard' | 'catalogo' | 'reservas' | 'pos' | 'cambios' | 'devoluciones'
  | 'entregas' | 'reportes' | 'asistente' | 'analitica' | 'inventario'
  | 'traspasos' | 'sucursales' | 'proveedores' | 'productos' | 'atributos'
  | 'usuarios' | 'permisos' | 'clientes' | 'fidelidad' | 'bitacora' | 'empresas';

interface Regla {
  // true si el cliente también usa esta pantalla.
  cliente: boolean;
  // Permisos del rol (null si la pantalla no tiene ese nivel).
  ver: string | null;
  gestionar: string | null;
}

const ADMIN = ['SUPER_ADMIN', 'ADMIN_EMPRESA'];

function regla(cliente: boolean, ver: string | null, gestionar: string | null): Regla {
  return { cliente, ver, gestionar };
}

const REGLAS: Record<Modulo, Regla> = {
  dashboard: regla(false, 'VER_DASHBOARD', null),
  catalogo: regla(true, 'CONSULTAR_CATALOGO', null),
  reservas: regla(true, 'VER_RESERVAS', 'GESTIONAR_RESERVAS'),
  pos: regla(false, null, 'REGISTRAR_VENTAS'),
  cambios: regla(false, null, 'GESTIONAR_CAMBIOS'),
  devoluciones: regla(false, 'VER_DEVOLUCIONES', 'GESTIONAR_DEVOLUCIONES'),
  entregas: regla(false, 'VER_ENTREGAS', 'GESTIONAR_ENTREGAS'),
  reportes: regla(false, 'VER_REPORTES', null),
  asistente: regla(false, null, 'USAR_ASISTENTE'),
  analitica: regla(false, 'VER_ANALITICA', null),
  inventario: regla(false, 'VER_INVENTARIO', 'GESTIONAR_INVENTARIO'),
  traspasos: regla(false, 'VER_TRASPASOS', 'GESTIONAR_TRASPASOS'),
  sucursales: regla(false, 'VER_SUCURSALES', 'GESTIONAR_SUCURSALES'),
  productos: regla(false, 'VER_PRODUCTOS', 'GESTIONAR_PRODUCTOS'),
  proveedores: regla(false, 'VER_PROVEEDORES', 'GESTIONAR_PROVEEDORES'),
  atributos: regla(false, 'VER_ATRIBUTOS', 'GESTIONAR_ATRIBUTOS'),
  usuarios: regla(false, 'VER_USUARIOS', 'GESTIONAR_USUARIOS'),
  permisos: regla(false, null, 'GESTIONAR_ROLES'),
  clientes: regla(false, 'VER_CLIENTES', null),
  fidelidad: regla(false, 'VER_FIDELIDAD', null),
  bitacora: regla(false, 'VER_BITACORA', null),
  // Empresas y Mi plan: solo SUPER_ADMIN y ADMIN_EMPRESA.
  empresas: regla(false, null, null)
};

// Ruta de la web -> pantalla. Gana el primer prefijo que coincida.
const RUTAS: [string, Modulo][] = [
  ['/dashboard', 'dashboard'],
  ['/empresas', 'empresas'],
  ['/pos/cambios', 'cambios'],
  ['/pos/devoluciones', 'devoluciones'],
  ['/pos', 'pos'],
  ['/devoluciones', 'devoluciones'],
  ['/deliveries', 'entregas'],
  ['/reservations', 'reservas'],
  ['/assistant-admin/reportes', 'reportes'],
  ['/assistant-admin/analitica', 'analitica'],
  ['/assistant-admin', 'asistente'],
  ['/inventory/traspasos', 'traspasos'],
  ['/inventory', 'inventario'],
  ['/store/proveedores', 'proveedores'],
  ['/store', 'sucursales'],
  ['/products', 'productos'],
  ['/attributes', 'atributos'],
  ['/users', 'usuarios'],
  ['/permissions', 'permisos'],
  ['/clients/fidelidad', 'fidelidad'],
  ['/clients', 'clientes'],
  ['/bitacora', 'bitacora']
];

@Injectable({
  providedIn: 'root'
})
export class AccesoService {
  private apiUrl = `${environment.apiUrl}/auth`;
  // Se vuelve a leer localStorage solo si cambió (otro inicio de sesión).
  private ultimoTexto: string | null = null;
  private roles = new Set<string>();
  private privilegios = new Set<string>();

  constructor(private http: HttpClient) {}

  private cargar(): void {
    const texto = localStorage.getItem('usuario');
    if (texto === this.ultimoTexto) {
      return;
    }
    this.ultimoTexto = texto;
    this.roles = new Set();
    this.privilegios = new Set();
    if (!texto) {
      return;
    }
    try {
      const usuario = JSON.parse(texto);
      (usuario?.roles ?? []).forEach((rol: any) => this.roles.add(rol?.nombre));
      (usuario?.privilegios ?? []).forEach((p: string) => this.privilegios.add(p));
    } catch {
      // Sesión dañada: sin roles ni privilegios.
    }
  }

  private tieneRol(roles: string[]): boolean {
    this.cargar();
    return roles.some(rol => this.roles.has(rol));
  }

  /** true si el rol del usuario tiene marcado ese permiso. */
  tienePrivilegio(nombre: string | null): boolean {
    this.cargar();
    return !!nombre && this.privilegios.has(nombre);
  }

  /** true si el usuario puede ver la pantalla (opción de menú y ruta). */
  puedeVer(modulo: Modulo): boolean {
    const r = REGLAS[modulo];
    return this.tieneRol(ADMIN)
      || (r.cliente && this.tieneRol(['CLIENTE']))
      || this.tienePrivilegio(r.ver)
      || this.tienePrivilegio(r.gestionar);
  }

  /** true si además puede crear, editar y eliminar en esa pantalla. */
  puedeGestionar(modulo: Modulo): boolean {
    const r = REGLAS[modulo];
    return this.tieneRol(ADMIN)
      || (r.cliente && this.tieneRol(['CLIENTE']))
      || this.tienePrivilegio(r.gestionar);
  }

  /** Pantalla a la que pertenece una ruta de la web (o null si no se controla). */
  moduloDeRuta(url: string): Modulo | null {
    const ruta = (url || '').split('?')[0];
    const encontrada = RUTAS.find(([prefijo]) => ruta === prefijo || ruta.startsWith(prefijo + '/'));
    return encontrada ? encontrada[1] : null;
  }

  /** Primera pantalla permitida del usuario (para redirigir lo no permitido). */
  inicio(): string {
    if (this.tieneRol(['CLIENTE'])) {
      return '/catalog';
    }
    if (this.puedeVer('dashboard')) {
      return '/dashboard';
    }
    if (this.puedeVer('entregas')) {
      return '/deliveries';
    }
    return '/catalog';
  }

  /**
   * Vuelve a pedir los permisos del rol del usuario y los guarda en la sesión
   * (así un cambio en "Permisos por rol" se nota sin cerrar sesión).
   */
  refrescar(): Observable<string[]> {
    if (!localStorage.getItem('access_token')) {
      return of([]);
    }
    return this.http.get<any>(`${this.apiUrl}/mis-privilegios/`).pipe(
      map(respuesta => {
        const privilegios: string[] = respuesta?.privilegios ?? [];
        const texto = localStorage.getItem('usuario');
        if (texto) {
          try {
            const usuario = JSON.parse(texto);
            usuario.privilegios = privilegios;
            localStorage.setItem('usuario', JSON.stringify(usuario));
          } catch {
            // Si la sesión no se puede leer, se deja como estaba.
          }
        }
        return privilegios;
      }),
      catchError(() => of([]))
    );
  }
}