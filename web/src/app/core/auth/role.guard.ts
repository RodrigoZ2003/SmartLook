// web/src/app/core/auth/role.guard.ts
// CU21: un usuario cuyo único rol operativo es REPARTIDOR solo puede entrar a
// las rutas marcadas con data: { permitirRepartidor: true } (Entregas).
// MODIFICADO (arreglo RF02): si la ruta pertenece a una pantalla controlada
// (ver AccesoService), decide con la tabla de roles + los privilegios de los
// grupos del usuario; lo no permitido lo manda a su pantalla de inicio. Se usa
// también como canActivateChild para revisar cada subruta (/inventory/traspasos...).
import { Injectable } from '@angular/core';
import {
  ActivatedRouteSnapshot,
  CanActivate,
  CanActivateChild,
  Router,
  RouterStateSnapshot
} from '@angular/router';
import { AuthService } from './auth.service';
import { AccesoService } from './acceso.service';

const ROLES_PERSONAL = ['SUPER_ADMIN', 'ADMIN_EMPRESA', 'ENCARGADO_SUCURSAL', 'CAJERO'];

@Injectable({
  providedIn: 'root'
})
export class RoleGuard implements CanActivate, CanActivateChild {
  constructor(
    private authService: AuthService,
    private acceso: AccesoService,
    private router: Router
  ) {}

  canActivate(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): boolean {
    return this.verificar(route, state.url);
  }

  canActivateChild(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): boolean {
    return this.verificar(route, state.url);
  }

  private verificar(route: ActivatedRouteSnapshot, url: string): boolean {
    // NUEVO (arreglo RF02): pantallas controladas por roles y grupos.
    const modulo = this.acceso.moduloDeRuta(url);
    if (modulo) {
      if (this.acceso.puedeVer(modulo)) {
        return true;
      }
      this.router.navigate([this.acceso.inicio()]);
      return false;
    }

    const rolesExcluidos: string[] = route.data['rolesExcluidos'] ?? [];
    const rolesUsuario = this.authService.obtenerRoles();

    const esSoloRepartidor =
      rolesUsuario.includes('REPARTIDOR') &&
      !rolesUsuario.some(rol => ROLES_PERSONAL.includes(rol));

    if (esSoloRepartidor && !route.data['permitirRepartidor']) {
      // Un repartidor que intenta entrar a una pantalla administrativa
      // se manda a su propia vista (Entregas).
      this.router.navigate(['/deliveries']);
      return false;
    }

    const tieneRolExcluido = rolesUsuario.some(
      rol => rolesExcluidos.includes(rol)
    );

    if (tieneRolExcluido) {
      // Un CLIENTE que intenta entrar a una vista administrativa
      // se manda a su propia vista (catálogo), no al login.
      this.router.navigate(['/catalog']);
      return false;
    }

    return true;
  }
}