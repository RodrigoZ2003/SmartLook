// web/src/app/modules/inventory/pages/movement-history/movement-history.component.ts
//
// Archivo YA EXISTENTE. Se agrega el formulario para registrar
// movimientos (antes solo mostraba el historial, sin poder crear
// ninguno desde la UI - el método registerMovement() del servicio
// existía pero nadie lo llamaba).
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo se
// muestran con el permiso GESTIONAR de la pantalla (puedeGestionar).

import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { InventoryService } from '../../services/inventory.service';
import { InventoryMovement } from '../../../../core/models/inventory.interface';
import { AccesoService } from '../../../../core/auth/acceso.service';

@Component({
  selector: 'app-movement-history',
  templateUrl: './movement-history.component.html',
  styleUrls: ['./movement-history.component.scss']
})
export class MovementHistoryComponent implements OnInit {
  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  puedeGestionar = inject(AccesoService).puedeGestionar('inventario');
  movements: InventoryMovement[] = [];
  sucursales: any[] = [];
  variantes: any[] = [];
  loading = false;
  showForm = false;
  guardando = false;
  errorMessage: string | null = null;
  movementForm!: FormGroup;

  constructor(
    private inventoryService: InventoryService,
    private fb: FormBuilder
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.loadMovements();
    this.loadSelectores();
  }

  initForm(): void {
    this.movementForm = this.fb.group({
      id_sucursal: ['', Validators.required],
      id_variante: ['', Validators.required],
      tipo_movimiento: ['ENTRADA', Validators.required],
      cantidad: ['', [Validators.required, Validators.min(1)]],
      motivo: ['']
    });
  }

  loadSelectores(): void {
    this.inventoryService.getSucursales().subscribe({
      next: (data: any) => this.sucursales = data.results || data,
      error: () => this.sucursales = []
    });
    this.inventoryService.getVariantes().subscribe({
      next: (data: any) => this.variantes = data.results || data,
      error: () => this.variantes = []
    });
  }

  etiquetaVariante(v: any): string {
    const talla = v.talla?.nombre || '';
    const color = v.color?.nombre || '';
    return `${v.codigo_producto} · ${talla} · ${color}`;
  }

  loadMovements(): void {
    this.loading = true;
    this.inventoryService.getMovements().subscribe({
      next: (data: any) => {
        this.movements = data.results || data;
        this.loading = false;
      },
      error: () => {
        this.movements = [];
        this.loading = false;
      }
    });
  }

  onSubmit(): void {
    if (this.movementForm.invalid) return;

    this.guardando = true;
    this.errorMessage = null;

    this.inventoryService.registerMovement(this.movementForm.value).subscribe({
      next: () => {
        this.guardando = false;
        this.showForm = false;
        this.movementForm.reset({ tipo_movimiento: 'ENTRADA' });
        this.loadMovements();
      },
      error: (err) => {
        this.guardando = false;
        this.errorMessage = err.error?.error || 'No se pudo registrar el movimiento.';
      }
    });
  }
}