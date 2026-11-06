// web/src/app/modules/store/pages/city-management/city-management.component.ts
//
// Archivo NUEVO.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo se
// muestran con el permiso GESTIONAR de la pantalla (puedeGestionar).

import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { BranchService } from '../../services/branch.service';
import { Country } from '../../../../core/models/branch.interface';
import { AccesoService } from '../../../../core/auth/acceso.service';

@Component({
  selector: 'app-city-management',
  templateUrl: './city-management.component.html',
  styleUrls: ['./city-management.component.scss']
})
export class CityManagementComponent implements OnInit {
  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  puedeGestionar = inject(AccesoService).puedeGestionar('sucursales');
  countries: Country[] = [];
  cities: any[] = [];
  cityForm!: FormGroup;
  loading = false;
  showForm = false;
  editandoId: number | null = null;
  errorMessage: string | null = null;

  constructor(
    private branchService: BranchService,
    private fb: FormBuilder
  ) {}

  ngOnInit(): void {
    this.cityForm = this.fb.group({
      id_pais: ['', Validators.required],
      nombre: ['', Validators.required],
      estado: [true]
    });

    this.loadData();
  }

  loadData(): void {
    this.loading = true;
    this.branchService.getCountries().subscribe({
      next: (data: any) => this.countries = data.results || data,
      error: () => this.countries = []
    });
    this.branchService.getCities().subscribe({
      next: (data: any) => {
        this.cities = data.results || data;
        this.loading = false;
      },
      error: () => {
        this.cities = [];
        this.loading = false;
      }
    });
  }

  nuevaCiudad(): void {
    this.editandoId = null;
    this.errorMessage = null;
    this.cityForm.reset({ estado: true });
    this.showForm = true;
  }

  editarCiudad(city: any): void {
    this.editandoId = city.id_ciudad;
    this.errorMessage = null;
    this.cityForm.patchValue({
      id_pais: city.pais?.id_pais,
      nombre: city.nombre,
      estado: city.estado
    });
    this.showForm = true;
  }

  cancelar(): void {
    this.showForm = false;
    this.editandoId = null;
    this.errorMessage = null;
    this.cityForm.reset({ estado: true });
  }

  onSubmit(): void {
    if (this.cityForm.invalid) return;
    this.errorMessage = null;

    const peticion = this.editandoId
      ? this.branchService.updateCity(this.editandoId, this.cityForm.value)
      : this.branchService.createCity(this.cityForm.value);

    peticion.subscribe({
      next: () => {
        this.cancelar();
        this.loadData();
      },
      error: (err) => {
        this.errorMessage = err.error?.nombre?.[0]
          || err.error?.id_pais?.[0]
          || 'No se pudo guardar la ciudad.';
      }
    });
  }

  eliminarCiudad(city: any): void {
    if (!confirm(`¿Eliminar la ciudad "${city.nombre}"?`)) return;
    this.branchService.deleteCity(city.id_ciudad).subscribe({
      next: () => this.loadData(),
      error: () => this.errorMessage = 'No se pudo eliminar la ciudad.'
    });
  }
}