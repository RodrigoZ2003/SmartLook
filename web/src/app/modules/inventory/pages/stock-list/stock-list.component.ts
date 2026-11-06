// web/src/app/modules/inventory/pages/stock-list/stock-list.component.ts
//
// Archivo YA EXISTENTE. Se agrega el mismo formulario de "Registrar
// Movimiento" que tiene movement-history, para que el botón + esté
// disponible sin importar en qué pestaña (Stock/Movimientos) estés -
// igual que el FAB en mobile, que aparece en ambas pestañas.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo se
// muestran con el permiso GESTIONAR de la pantalla (puedeGestionar).

import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { InventoryService } from '../../services/inventory.service';
import { StockItem } from '../../../../core/models/inventory.interface';
import { AccesoService } from '../../../../core/auth/acceso.service';

@Component({
  selector: 'app-stock-list',
  templateUrl: './stock-list.component.html',
  styleUrls: ['./stock-list.component.scss']
})
export class StockListComponent implements OnInit {
  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  puedeGestionar = inject(AccesoService).puedeGestionar('inventario');
  stockItems: StockItem[] = [];
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
    this.loadStock();
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

  loadStock(): void {
    this.loading = true;
    this.inventoryService.getStockItems().subscribe({
      next: (data: any) => {
        this.stockItems = data.results || data;
        this.loading = false;
      },
      error: () => {
        this.stockItems = [];
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
        this.loadStock();
      },
      error: (err) => {
        this.guardando = false;
        this.errorMessage = err.error?.error || 'No se pudo registrar el movimiento.';
      }
    });
  }
}