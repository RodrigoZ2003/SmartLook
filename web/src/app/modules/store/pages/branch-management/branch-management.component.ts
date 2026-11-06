// web/src/app/modules/store/pages/branch-management/branch-management.component.ts
//
// Archivo YA EXISTENTE. Se agrega edición y eliminación (antes
// onSubmit() solo llamaba a createBranch(), nunca a updateBranch()
// aunque el servicio ya lo tenía).
// MODIFICADO (SaaS): el SUPER_ADMIN ve la columna Empresa y, al registrar una
// sucursal, elige la empresa (el backend la exige con "id_empresa"). El
// personal de una empresa sigue igual: sus sucursales se crean en su empresa.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo se
// muestran con el permiso GESTIONAR de la pantalla (puedeGestionar).
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { BranchService } from '../../services/branch.service';
import { Country, City } from '../../../../core/models/branch.interface';
import { AuthService } from '../../../../core/auth/auth.service';
import { EmpresaService, mensajeDeError } from '../../../empresas/services/empresa.service';
import { AccesoService } from '../../../../core/auth/acceso.service';
@Component({
  selector: 'app-branch-management',
  templateUrl: './branch-management.component.html',
  styleUrls: ['./branch-management.component.scss']
})
export class BranchManagementComponent implements OnInit {
  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  puedeGestionar = inject(AccesoService).puedeGestionar('sucursales');
  countries: Country[] = [];
  cities: City[] = [];
  // any: la lista trae además id_empresa y empresa_nombre (SaaS).
  branches: any[] = [];
  empresas: any[] = [];
  esSuperAdmin = false;
  branchForm!: FormGroup;
  loading = false;
  showForm = false;
  editandoId: number | null = null;
  errorMessage: string | null = null;
  constructor(
    private branchService: BranchService,
    private fb: FormBuilder,
    private authService: AuthService,
    private empresaService: EmpresaService
  ) {}
  ngOnInit(): void {
    this.esSuperAdmin = this.authService.obtenerRoles().includes('SUPER_ADMIN');
    this.initForm();
    this.loadData();
  }
  initForm(): void {
    this.branchForm = this.fb.group({
      id_ciudad: ['', Validators.required],
      nombre: ['', Validators.required],
      direccion: ['', Validators.required],
      telefono: [''],
      fecha_apertura: ['']
    });
    if (this.esSuperAdmin) {
      this.branchForm.addControl('id_empresa', this.fb.control('', Validators.required));
    }
  }
  loadData(): void {
    this.loading = true;
    this.branchService.getCountries().subscribe({
      next: (data: any) => this.countries = data.results || data,
      error: () => this.countries = []
    });
    this.branchService.getCities().subscribe({
      next: (data: any) => this.cities = data.results || data,
      error: () => this.cities = []
    });
    if (this.esSuperAdmin) {
      this.empresaService.listar().subscribe({
        next: (data: any) => this.empresas = data.results || data,
        error: () => this.empresas = []
      });
    }
    this.branchService.getBranches().subscribe({
      next: (data: any) => {
        this.branches = data.results || data;
        this.loading = false;
      },
      error: () => {
        this.branches = [];
        this.loading = false;
      }
    });
  }
  nuevaSucursal(): void {
    this.editandoId = null;
    this.errorMessage = null;
    this.branchForm.reset({ id_empresa: '' });
    this.branchForm.get('id_empresa')?.enable();
    this.showForm = true;
  }
  editarSucursal(branch: any): void {
    this.editandoId = branch.id_sucursal;
    this.errorMessage = null;
    this.branchForm.patchValue({
      id_ciudad: branch.ciudad?.id_ciudad,
      nombre: branch.nombre,
      direccion: branch.direccion,
      telefono: branch.telefono,
      fecha_apertura: branch.fecha_apertura,
      id_empresa: branch.id_empresa
    });
    // Una sucursal no se mueve de empresa al editarla.
    this.branchForm.get('id_empresa')?.disable();
    this.showForm = true;
  }
  cancelar(): void {
    this.showForm = false;
    this.editandoId = null;
    this.errorMessage = null;
    this.branchForm.reset();
  }
  onSubmit(): void {
    if (this.branchForm.invalid) return;
    this.errorMessage = null;
    const peticion = this.editandoId
      ? this.branchService.updateBranch(this.editandoId, this.branchForm.value)
      : this.branchService.createBranch(this.branchForm.value);
    peticion.subscribe({
      next: () => {
        this.cancelar();
        this.loadData();
      },
      error: (err) => {
        // Incluye el límite de sucursales del plan (403) y la empresa faltante.
        this.errorMessage = mensajeDeError(err, 'No se pudo guardar la sucursal.');
      }
    });
  }
  eliminarSucursal(branch: any): void {
    if (!confirm(`¿Eliminar la sucursal "${branch.nombre}"?`)) return;
    this.branchService.deleteBranch(branch.id_sucursal).subscribe({
      next: () => this.loadData(),
      error: () => this.errorMessage = 'No se pudo eliminar la sucursal.'
    });
  }
}