// web/src/app/modules/products/pages/product-management/product-management.component.ts
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo se
// muestran con el permiso GESTIONAR de la pantalla (puedeGestionar).
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { ProductService } from '../../services/product.service';
import { AttributeService } from '../../../attributes/services/attribute.service';
import { AccesoService } from '../../../../core/auth/acceso.service';

@Component({
  selector: 'app-product-management',
  templateUrl: './product-management.component.html',
  styleUrls: ['./product-management.component.scss']
})
export class ProductManagementComponent implements OnInit {
  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  puedeGestionar = inject(AccesoService).puedeGestionar('productos');
  productos: any[] = [];
  categorias: any[] = [];
  marcas: any[] = [];
  temporadas: any[] = [];
  colecciones: any[] = [];
  tallas: any[] = [];
  colores: any[] = [];
  loading = false;
  showForm = false;
  editandoId: number | null = null;
  errorMessage: string | null = null;
  productForm!: FormGroup;

  // ---- Variantes (Paso C) ----
  productoExpandidoId: number | null = null;
  showFormVariante = false;
  editandoVarianteId: number | null = null;
  errorVariante: string | null = null;
  varianteForm!: FormGroup;

  constructor(
    private productService: ProductService,
    private attributeService: AttributeService,
    private fb: FormBuilder
  ) {}

  ngOnInit(): void {
    this.productForm = this.fb.group({
      id_categoria: ['', Validators.required],
      id_marca: [''],
      id_temporada: [''],
      id_coleccion: [''],
      nombre: ['', Validators.required],
      tipo_prenda: ['', Validators.required],
      descripcion: [''],
      imagen_producto: [''],
      estado: ['ACTIVO']
    });

    this.varianteForm = this.fb.group({
      id_talla: ['', Validators.required],
      id_color: ['', Validators.required],
      codigo_producto: ['', Validators.required],
      precio: ['', [Validators.required, Validators.min(0)]],
      cantidad: [0, [Validators.required, Validators.min(0)]],
      imagen_variante: [''],
      estado: ['DISPONIBLE']
    });

    this.loadData();
  }

  loadData(): void {
    this.loading = true;
    this.attributeService.getCategorias().subscribe({ next: (d: any) => this.categorias = d.results || d, error: () => this.categorias = [] });
    this.attributeService.getMarcas().subscribe({ next: (d: any) => this.marcas = d.results || d, error: () => this.marcas = [] });
    this.attributeService.getTemporadas().subscribe({ next: (d: any) => this.temporadas = d.results || d, error: () => this.temporadas = [] });
    this.attributeService.getColecciones().subscribe({ next: (d: any) => this.colecciones = d.results || d, error: () => this.colecciones = [] });
    this.attributeService.getTallas().subscribe({ next: (d: any) => this.tallas = d.results || d, error: () => this.tallas = [] });
    this.attributeService.getColores().subscribe({ next: (d: any) => this.colores = d.results || d, error: () => this.colores = [] });
    this.productService.getProductos().subscribe({
      next: (d: any) => {
        this.productos = d.results || d;
        this.loading = false;
      },
      error: () => {
        this.productos = [];
        this.loading = false;
      }
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

  // ---- Producto ----
  nuevoProducto(): void {
    this.editandoId = null;
    this.errorMessage = null;
    this.productForm.reset({ estado: 'ACTIVO' });
    this.showForm = true;
  }

  editarProducto(producto: any): void {
    this.editandoId = producto.id_producto;
    this.errorMessage = null;
    this.productForm.patchValue({
      id_categoria: producto.categoria?.id_categoria,
      id_marca: producto.marca?.id_marca ?? '',
      id_temporada: producto.temporada?.id_temporada ?? '',
      id_coleccion: producto.coleccion?.id_coleccion ?? '',
      nombre: producto.nombre,
      tipo_prenda: producto.tipo_prenda,
      descripcion: producto.descripcion,
      imagen_producto: producto.imagen_producto,
      estado: producto.estado
    });
    this.showForm = true;
  }

  cancelar(): void {
    this.showForm = false;
    this.editandoId = null;
    this.errorMessage = null;
    this.productForm.reset({ estado: 'ACTIVO' });
  }

  private limpiarPayload(valores: any): any {
    const datos = { ...valores };
    ['id_marca', 'id_temporada', 'id_coleccion'].forEach(campo => {
      if (datos[campo] === '') datos[campo] = null;
    });
    return datos;
  }

  onSubmit(): void {
    if (this.productForm.invalid) return;
    this.errorMessage = null;
    const datos = this.limpiarPayload(this.productForm.value);
    const peticion = this.editandoId
      ? this.productService.actualizarProducto(this.editandoId, datos)
      : this.productService.crearProducto(datos);
    peticion.subscribe({
      next: () => {
        this.cancelar();
        this.loadData();
      },
      error: (err) => this.errorMessage = this.extraerError(err)
    });
  }

  eliminarProducto(producto: any): void {
    if (!confirm(`¿Eliminar el producto "${producto.nombre}"?`)) return;
    this.productService.eliminarProducto(producto.id_producto).subscribe({
      next: () => this.loadData(),
      error: (err) => this.errorMessage = this.extraerError(err)
    });
  }

  // ---- Variantes ----
  toggleVariantes(producto: any): void {
    if (this.productoExpandidoId === producto.id_producto) {
      this.productoExpandidoId = null;
    } else {
      this.productoExpandidoId = producto.id_producto;
      this.showFormVariante = false;
    }
  }

  nuevaVariante(): void {
    this.editandoVarianteId = null;
    this.errorVariante = null;
    this.varianteForm.reset({ cantidad: 0, estado: 'DISPONIBLE' });
    this.showFormVariante = true;
  }

  editarVariante(variante: any): void {
    this.editandoVarianteId = variante.id_variante;
    this.errorVariante = null;
    this.varianteForm.patchValue({
      id_talla: variante.talla?.id_talla,
      id_color: variante.color?.id_color,
      codigo_producto: variante.codigo_producto,
      precio: variante.precio,
      cantidad: variante.cantidad,
      imagen_variante: variante.imagen_variante,
      estado: variante.estado
    });
    this.showFormVariante = true;
  }

  cancelarVariante(): void {
    this.showFormVariante = false;
    this.editandoVarianteId = null;
    this.errorVariante = null;
  }

  guardarVariante(): void {
    if (this.varianteForm.invalid || this.productoExpandidoId === null) return;
    this.errorVariante = null;
    const datos = { ...this.varianteForm.value, id_producto: this.productoExpandidoId };
    const peticion = this.editandoVarianteId
      ? this.productService.actualizarVariante(this.editandoVarianteId, datos)
      : this.productService.crearVariante(datos);
    peticion.subscribe({
      next: () => {
        this.cancelarVariante();
        this.loadData();
      },
      error: (err) => this.errorVariante = this.extraerError(err)
    });
  }

  eliminarVariante(variante: any): void {
    if (!confirm(`¿Eliminar la variante "${variante.codigo_producto}"?`)) return;
    this.productService.eliminarVariante(variante.id_variante).subscribe({
      next: () => this.loadData(),
      error: (err) => this.errorVariante = this.extraerError(err)
    });
  }
}