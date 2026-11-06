// web/src/app/modules/permissions/pages/permission-management/permission-management.component.ts
//
// MODIFICADO (arreglo RF02 - usuarios, roles y permisos): la misma pantalla de
// antes, pero ahora los permisos que se guardan SÍ se aplican (menú, rutas y
// backend):
// - Solo se configuran ENCARGADO_SUCURSAL, CAJERO y REPARTIDOR. SUPER_ADMIN y
//   ADMIN_EMPRESA hacen todo; el cliente tiene sus pantallas de siempre.
// - Solo el SUPER_ADMIN guarda (los roles son de toda la plataforma); el
//   ADMIN_EMPRESA puede ver los permisos de cada rol.

import { Component, OnInit } from '@angular/core';
import { UserService } from '../../../../core/services/user.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { Role, Permiso } from '../../../../core/models/user.interface';

// Roles cuyos permisos se configuran aquí.
const ROLES_CONFIGURABLES = ['ENCARGADO_SUCURSAL', 'CAJERO', 'REPARTIDOR'];

@Component({
  selector: 'app-permission-management',
  templateUrl: './permission-management.component.html',
  styleUrls: ['./permission-management.component.scss']
})
export class PermissionManagementComponent implements OnInit {
  roles: Role[] = [];
  permisos: Permiso[] = [];
  idRolSeleccionado: number | null = null;
  idsPermisosAsignados: Set<number> = new Set();
  loading = false;
  guardando = false;
  puedeGuardar = false;
  errorMessage: string | null = null;
  successMessage: string | null = null;

  constructor(
    private userService: UserService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.puedeGuardar = this.authService.obtenerRoles().includes('SUPER_ADMIN');

    this.userService.getRoles().subscribe({
      next: (data) => this.roles = data.filter(rol => ROLES_CONFIGURABLES.includes(rol.nombre)),
      error: () => this.roles = []
    });

    this.userService.getPermisos().subscribe({
      next: (data) => this.permisos = data,
      error: () => this.permisos = []
    });
  }

  seleccionarRol(idRol: number): void {
    this.idRolSeleccionado = idRol || null;
    this.errorMessage = null;
    this.successMessage = null;
    if (!this.idRolSeleccionado) {
      return;
    }
    this.loading = true;

    this.userService.getRolPermisos(idRol).subscribe({
      next: (resp) => {
        this.idsPermisosAsignados = new Set(resp.permisos);
        this.loading = false;
      },
      error: () => {
        this.idsPermisosAsignados = new Set();
        this.loading = false;
      }
    });
  }

  estaAsignado(idPermiso: number): boolean {
    return this.idsPermisosAsignados.has(idPermiso);
  }

  toggle(idPermiso: number): void {
    if (this.idsPermisosAsignados.has(idPermiso)) {
      this.idsPermisosAsignados.delete(idPermiso);
    } else {
      this.idsPermisosAsignados.add(idPermiso);
    }
  }

  guardar(): void {
    if (this.idRolSeleccionado === null || !this.puedeGuardar) return;

    this.guardando = true;
    this.errorMessage = null;
    this.successMessage = null;

    const permisos = Array.from(this.idsPermisosAsignados);

    this.userService.actualizarRolPermisos(this.idRolSeleccionado, permisos).subscribe({
      next: () => {
        this.guardando = false;
        this.successMessage = 'Permisos actualizados correctamente.';
      },
      error: () => {
        this.guardando = false;
        this.errorMessage = 'No se pudieron guardar los permisos.';
      }
    });
  }
}