// web/src/app/modules/attributes/pages/attribute-management/attribute-management.component.ts
//
// Archivo YA EXISTENTE. Se agregan 4 secciones más (Categorías, Marcas,
// Temporadas, Colecciones), mismo patrón que Tallas/Colores.
// MODIFICADO (arreglo RF02): los botones de crear, editar y eliminar solo se
// muestran con el permiso GESTIONAR de la pantalla (puedeGestionar).

import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { AttributeService } from '../../services/attribute.service';
import { AccesoService } from '../../../../core/auth/acceso.service';

@Component({
  selector: 'app-attribute-management',
  templateUrl: './attribute-management.component.html',
  styleUrls: ['./attribute-management.component.scss']
})
export class AttributeManagementComponent implements OnInit {
  // NUEVO (arreglo RF02): crear, editar y eliminar solo con el permiso
  // GESTIONAR de esta pantalla (SUPER_ADMIN y ADMIN_EMPRESA siempre).
  puedeGestionar = inject(AccesoService).puedeGestionar('atributos');
  tallas: any[] = [];
  colores: any[] = [];
  categorias: any[] = [];
  marcas: any[] = [];
  temporadas: any[] = [];
  colecciones: any[] = [];

  showFormTalla = false;
  showFormColor = false;
  showFormCategoria = false;
  showFormMarca = false;
  showFormTemporada = false;
  showFormColeccion = false;

  editandoTallaId: number | null = null;
  editandoColorId: number | null = null;
  editandoCategoriaId: number | null = null;
  editandoMarcaId: number | null = null;
  editandoTemporadaId: number | null = null;
  editandoColeccionId: number | null = null;

  tallaForm!: FormGroup;
  colorForm!: FormGroup;
  categoriaForm!: FormGroup;
  marcaForm!: FormGroup;
  temporadaForm!: FormGroup;
  coleccionForm!: FormGroup;

  errorTalla: string | null = null;
  errorColor: string | null = null;
  errorCategoria: string | null = null;
  errorMarca: string | null = null;
  errorTemporada: string | null = null;
  errorColeccion: string | null = null;

  constructor(
    private attributeService: AttributeService,
    private fb: FormBuilder
  ) {}

  ngOnInit(): void {
    this.tallaForm = this.fb.group({ nombre: ['', Validators.required], descripcion: [''], estado: [true] });
    this.colorForm = this.fb.group({ nombre: ['', Validators.required], codigo_hex: ['#000000'], estado: [true] });
    this.categoriaForm = this.fb.group({ nombre: ['', Validators.required], descripcion: [''], estado: [true] });
    this.marcaForm = this.fb.group({ nombre: ['', Validators.required], descripcion: [''], estado: [true] });
    this.temporadaForm = this.fb.group({
      nombre: ['', Validators.required], descripcion: [''],
      fecha_inicio: [''], fecha_fin: [''], estado: [true]
    });
    this.coleccionForm = this.fb.group({
      nombre: ['', Validators.required], descripcion: [''], anio: [''], estado: [true]
    });

    this.loadTallas();
    this.loadColores();
    this.loadCategorias();
    this.loadMarcas();
    this.loadTemporadas();
    this.loadColecciones();
  }

  private extraerError(err: any): string {
    const data = err?.error;
    if (!data) return 'Ocurrió un error inesperado.';
    if (typeof data === 'string') return data;
    const primeraClave = Object.keys(data)[0];
    const valor = data[primeraClave];
    return Array.isArray(valor) ? valor[0] : String(valor);
  }

  // ---- Tallas ----
  loadTallas(): void {
    this.attributeService.getTallas().subscribe({ next: (d: any) => this.tallas = d.results || d, error: () => this.tallas = [] });
  }
  nuevaTalla(): void { this.editandoTallaId = null; this.tallaForm.reset({ estado: true }); this.showFormTalla = true; }
  editarTalla(t: any): void { this.editandoTallaId = t.id_talla; this.errorTalla = null; this.tallaForm.patchValue(t); this.showFormTalla = true; }
  cancelarTalla(): void { this.showFormTalla = false; this.editandoTallaId = null; this.errorTalla = null; }
  guardarTalla(): void {
    if (this.tallaForm.invalid) return;
    this.errorTalla = null;
    const req = this.editandoTallaId ? this.attributeService.actualizarTalla(this.editandoTallaId, this.tallaForm.value) : this.attributeService.crearTalla(this.tallaForm.value);
    req.subscribe({ next: () => { this.cancelarTalla(); this.loadTallas(); }, error: (e) => this.errorTalla = this.extraerError(e) });
  }
  eliminarTalla(t: any): void {
    if (!confirm(`¿Eliminar la talla "${t.nombre}"?`)) return;
    this.attributeService.eliminarTalla(t.id_talla).subscribe({ next: () => this.loadTallas(), error: (e) => this.errorTalla = this.extraerError(e) });
  }

  // ---- Colores ----
  loadColores(): void {
    this.attributeService.getColores().subscribe({ next: (d: any) => this.colores = d.results || d, error: () => this.colores = [] });
  }
  nuevoColor(): void { this.editandoColorId = null; this.colorForm.reset({ estado: true, codigo_hex: '#000000' }); this.showFormColor = true; }
  editarColor(c: any): void { this.editandoColorId = c.id_color; this.errorColor = null; this.colorForm.patchValue(c); this.showFormColor = true; }
  cancelarColor(): void { this.showFormColor = false; this.editandoColorId = null; this.errorColor = null; }
  guardarColor(): void {
    if (this.colorForm.invalid) return;
    this.errorColor = null;
    const req = this.editandoColorId ? this.attributeService.actualizarColor(this.editandoColorId, this.colorForm.value) : this.attributeService.crearColor(this.colorForm.value);
    req.subscribe({ next: () => { this.cancelarColor(); this.loadColores(); }, error: (e) => this.errorColor = this.extraerError(e) });
  }
  eliminarColor(c: any): void {
    if (!confirm(`¿Eliminar el color "${c.nombre}"?`)) return;
    this.attributeService.eliminarColor(c.id_color).subscribe({ next: () => this.loadColores(), error: (e) => this.errorColor = this.extraerError(e) });
  }

  // ---- Categorías ----
  loadCategorias(): void {
    this.attributeService.getCategorias().subscribe({ next: (d: any) => this.categorias = d.results || d, error: () => this.categorias = [] });
  }
  nuevaCategoria(): void { this.editandoCategoriaId = null; this.categoriaForm.reset({ estado: true }); this.showFormCategoria = true; }
  editarCategoria(c: any): void { this.editandoCategoriaId = c.id_categoria; this.errorCategoria = null; this.categoriaForm.patchValue(c); this.showFormCategoria = true; }
  cancelarCategoria(): void { this.showFormCategoria = false; this.editandoCategoriaId = null; this.errorCategoria = null; }
  guardarCategoria(): void {
    if (this.categoriaForm.invalid) return;
    this.errorCategoria = null;
    const req = this.editandoCategoriaId ? this.attributeService.actualizarCategoria(this.editandoCategoriaId, this.categoriaForm.value) : this.attributeService.crearCategoria(this.categoriaForm.value);
    req.subscribe({ next: () => { this.cancelarCategoria(); this.loadCategorias(); }, error: (e) => this.errorCategoria = this.extraerError(e) });
  }
  eliminarCategoria(c: any): void {
    if (!confirm(`¿Eliminar la categoría "${c.nombre}"?`)) return;
    this.attributeService.eliminarCategoria(c.id_categoria).subscribe({ next: () => this.loadCategorias(), error: (e) => this.errorCategoria = this.extraerError(e) });
  }

  // ---- Marcas ----
  loadMarcas(): void {
    this.attributeService.getMarcas().subscribe({ next: (d: any) => this.marcas = d.results || d, error: () => this.marcas = [] });
  }
  nuevaMarca(): void { this.editandoMarcaId = null; this.marcaForm.reset({ estado: true }); this.showFormMarca = true; }
  editarMarca(m: any): void { this.editandoMarcaId = m.id_marca; this.errorMarca = null; this.marcaForm.patchValue(m); this.showFormMarca = true; }
  cancelarMarca(): void { this.showFormMarca = false; this.editandoMarcaId = null; this.errorMarca = null; }
  guardarMarca(): void {
    if (this.marcaForm.invalid) return;
    this.errorMarca = null;
    const req = this.editandoMarcaId ? this.attributeService.actualizarMarca(this.editandoMarcaId, this.marcaForm.value) : this.attributeService.crearMarca(this.marcaForm.value);
    req.subscribe({ next: () => { this.cancelarMarca(); this.loadMarcas(); }, error: (e) => this.errorMarca = this.extraerError(e) });
  }
  eliminarMarca(m: any): void {
    if (!confirm(`¿Eliminar la marca "${m.nombre}"?`)) return;
    this.attributeService.eliminarMarca(m.id_marca).subscribe({ next: () => this.loadMarcas(), error: (e) => this.errorMarca = this.extraerError(e) });
  }

  // ---- Temporadas ----
  loadTemporadas(): void {
    this.attributeService.getTemporadas().subscribe({ next: (d: any) => this.temporadas = d.results || d, error: () => this.temporadas = [] });
  }
  nuevaTemporada(): void { this.editandoTemporadaId = null; this.temporadaForm.reset({ estado: true }); this.showFormTemporada = true; }
  editarTemporada(t: any): void { this.editandoTemporadaId = t.id_temporada; this.errorTemporada = null; this.temporadaForm.patchValue(t); this.showFormTemporada = true; }
  cancelarTemporada(): void { this.showFormTemporada = false; this.editandoTemporadaId = null; this.errorTemporada = null; }
  guardarTemporada(): void {
    if (this.temporadaForm.invalid) return;
    this.errorTemporada = null;
    const req = this.editandoTemporadaId ? this.attributeService.actualizarTemporada(this.editandoTemporadaId, this.temporadaForm.value) : this.attributeService.crearTemporada(this.temporadaForm.value);
    req.subscribe({ next: () => { this.cancelarTemporada(); this.loadTemporadas(); }, error: (e) => this.errorTemporada = this.extraerError(e) });
  }
  eliminarTemporada(t: any): void {
    if (!confirm(`¿Eliminar la temporada "${t.nombre}"?`)) return;
    this.attributeService.eliminarTemporada(t.id_temporada).subscribe({ next: () => this.loadTemporadas(), error: (e) => this.errorTemporada = this.extraerError(e) });
  }

  // ---- Colecciones ----
  loadColecciones(): void {
    this.attributeService.getColecciones().subscribe({ next: (d: any) => this.colecciones = d.results || d, error: () => this.colecciones = [] });
  }
  nuevaColeccion(): void { this.editandoColeccionId = null; this.coleccionForm.reset({ estado: true }); this.showFormColeccion = true; }
  editarColeccion(c: any): void { this.editandoColeccionId = c.id_coleccion; this.errorColeccion = null; this.coleccionForm.patchValue(c); this.showFormColeccion = true; }
  cancelarColeccion(): void { this.showFormColeccion = false; this.editandoColeccionId = null; this.errorColeccion = null; }
  guardarColeccion(): void {
    if (this.coleccionForm.invalid) return;
    this.errorColeccion = null;
    const req = this.editandoColeccionId ? this.attributeService.actualizarColeccion(this.editandoColeccionId, this.coleccionForm.value) : this.attributeService.crearColeccion(this.coleccionForm.value);
    req.subscribe({ next: () => { this.cancelarColeccion(); this.loadColecciones(); }, error: (e) => this.errorColeccion = this.extraerError(e) });
  }
  eliminarColeccion(c: any): void {
    if (!confirm(`¿Eliminar la colección "${c.nombre}"?`)) return;
    this.attributeService.eliminarColeccion(c.id_coleccion).subscribe({ next: () => this.loadColecciones(), error: (e) => this.errorColeccion = this.extraerError(e) });
  }
}