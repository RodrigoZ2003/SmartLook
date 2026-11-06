// web/src/app/modules/users/pages/user-management/user-management.component.ts
//
// Corregido: importa UserService desde core/services (el real, ya
// existente) y las interfaces User/Role desde core/models/user.interface
// (las reales), en vez de duplicados propios.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo se
// muestran con el permiso GESTIONAR de la pantalla (puedeGestionar).

import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { UserService } from '../../../../core/services/user.service';
import { User, Role } from '../../../../core/models/user.interface';
import { AccesoService } from '../../../../core/auth/acceso.service';

@Component({
  selector: 'app-user-management',
  templateUrl: './user-management.component.html',
  styleUrls: ['./user-management.component.scss']
})
export class UserManagementComponent implements OnInit {
  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  puedeGestionar = inject(AccesoService).puedeGestionar('usuarios');
  usuarios: User[] = [];
  roles: Role[] = [];
  userForm!: FormGroup;
  loading = false;
  showForm = false;
  editandoId: number | null = null;
  errorMessage: string | null = null;

  constructor(
    private userService: UserService,
    private fb: FormBuilder
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.loadData();
  }

  initForm(): void {
    this.userForm = this.fb.group({
      nombres: ['', Validators.required],
      apellidos: ['', Validators.required],
      correo: ['', [Validators.required, Validators.email]],
      telefono: [''],
      password: [''],
      estado: ['ACTIVO'],
      rol: ['', Validators.required]
    });
  }

  loadData(): void {
    this.loading = true;

    this.userService.getRoles().subscribe({
      next: (data: any) => {
        const todos: Role[] = data;
        // El rol CLIENTE no se gestiona desde este panel: los clientes
        // se registran ellos mismos (CU01), el admin nunca los crea ni
        // les asigna ese rol manualmente.
        this.roles = todos.filter(rol => rol.nombre !== 'CLIENTE');
      },
      error: () => this.roles = []
    });

    this.userService.getUsuarios().subscribe({
      next: (data: any) => {
        const todos: User[] = data;
        // Igual que con el selector de roles: los usuarios con rol
        // CLIENTE no se listan aquí (tienen su propia sección de
        // "Clientes"). Este panel es solo para personal administrativo.
        this.usuarios = todos.filter(
          u => !u.roles.some(rol => rol.nombre === 'CLIENTE')
        );
        this.loading = false;
      },
      error: () => {
        this.usuarios = [];
        this.loading = false;
      }
    });
  }

  nuevoUsuario(): void {
    this.editandoId = null;
    this.userForm.reset({ estado: 'ACTIVO' });
    this.userForm.get('password')?.setValidators([Validators.required, Validators.minLength(8)]);
    this.userForm.get('password')?.updateValueAndValidity();
    this.showForm = true;
  }

  editarUsuario(usuario: User): void {
    this.editandoId = usuario.id_usuario;
    this.errorMessage = null;

    this.userForm.get('password')?.clearValidators();
    this.userForm.get('password')?.updateValueAndValidity();

    this.userForm.patchValue({
      nombres: usuario.nombres,
      apellidos: usuario.apellidos,
      correo: usuario.correo,
      telefono: usuario.telefono,
      password: '',
      estado: usuario.estado,
      rol: usuario.roles[0]?.id_rol ?? ''
    });

    this.showForm = true;
  }

  cancelar(): void {
    this.showForm = false;
    this.editandoId = null;
    this.errorMessage = null;
    this.userForm.reset({ estado: 'ACTIVO' });
  }

  onSubmit(): void {
    if (this.userForm.invalid) return;

    this.errorMessage = null;
    const valores = this.userForm.value;

    if (this.editandoId) {
      const payload: any = {
        nombres: valores.nombres,
        apellidos: valores.apellidos,
        correo: valores.correo,
        telefono: valores.telefono,
        estado: valores.estado,
        rol: valores.rol
      };
      if (valores.password) {
        payload.password = valores.password;
      }

      this.userService.actualizarUsuario(this.editandoId, payload).subscribe({
        next: () => {
          this.cancelar();
          this.loadData();
        },
        error: (err) => this.errorMessage = this.extraerError(err)
      });

    } else {
      this.userService.crearUsuario({
        nombres: valores.nombres,
        apellidos: valores.apellidos,
        correo: valores.correo,
        telefono: valores.telefono,
        password: valores.password,
        rol: valores.rol
      }).subscribe({
        next: () => {
          this.cancelar();
          this.loadData();
        },
        error: (err) => this.errorMessage = this.extraerError(err)
      });
    }
  }

  eliminarUsuario(usuario: User): void {
    if (!confirm(`¿Eliminar al usuario ${usuario.nombres} ${usuario.apellidos}?`)) {
      return;
    }

    this.userService.eliminarUsuario(usuario.id_usuario).subscribe({
      next: () => this.loadData(),
      error: (err) => this.errorMessage = this.extraerError(err)
    });
  }

  private extraerError(err: any): string {
    const data = err?.error;
    if (!data) return 'Ocurrió un error inesperado.';
    if (typeof data === 'string') return data;
    const primeraClave = Object.keys(data)[0];
    const valor = data[primeraClave];
    return Array.isArray(valor) ? valor[0] : String(valor);
  }
}