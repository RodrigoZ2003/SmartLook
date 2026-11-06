// web/src/app/app-routing.module.ts
//
// MODIFICADO (CU16): se agrega la ruta 'pos'.
// MODIFICADO (CU20): se agrega la ruta 'assistant-admin'.
// FIX: 'orders' y 'deliveries' estaban en el menú lateral (layout.component.html)
// pero nunca se habían registrado aquí - la ruta no existía.
// NUEVO (devoluciones): se agrega la ruta 'devoluciones'.
// NUEVO (SaaS): se agrega la ruta 'empresas' (SUPER_ADMIN y ADMIN_EMPRESA).
// NUEVO (Fase 3): la raíz muestra el catálogo público y /producto/:id su
// detalle (modules/inicio) en vez de redirigir al login; va antes del layout.
// MODIFICADO (arreglo RF02): RoleGuard decide cada pantalla con la tabla de
// roles y los privilegios de los grupos (AccesoService). En las rutas con
// subpantallas (pos, inventory, store, clients, assistant-admin) también se
// usa como canActivateChild; reservas y entregas ahora también pasan por él.
import { NgModule } from '@angular/core';
import {
  RouterModule,
  Routes
} from '@angular/router';
import { LayoutComponent } from './layout/layout.component';
import { AuthGuard } from './core/auth/auth.guard';
import { RoleGuard } from './core/auth/role.guard';
const routes: Routes = [
  {
    path: 'auth',
    loadChildren: () =>
      import('./modules/auth/auth.module')
        .then(m => m.AuthModule)
  },
  // NUEVO (Fase 3): páginas públicas sin el menú lateral: la raíz
  // (https://.../) muestra el catálogo público y /producto/:id su detalle.
  // Debe ir ANTES de la ruta del layout: si va después, '' coincide primero
  // con LayoutComponent y se ve el menú con la página vacía. Las demás rutas
  // no coinciden en este módulo y siguen con el layout.
  {
    path: '',
    loadChildren: () =>
      import('./modules/inicio/inicio.module')
        .then(m => m.InicioModule)
  },
  {
    path: '',
    component: LayoutComponent,
    children: [
      {
        path: 'dashboard',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/dashboard/dashboard.module')
            .then(m => m.DashboardModule)
      },
      {
        path: 'empresas',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE', 'ENCARGADO_SUCURSAL', 'CAJERO', 'REPARTIDOR'] },
        loadChildren: () =>
          import('./modules/empresas/empresas.module')
            .then(m => m.EmpresasModule)
      },
      {
        path: 'catalog',
        loadChildren: () =>
          import('./modules/catalog/catalog.module')
            .then(m => m.CatalogModule)
      },
      {
        path: 'cart',
        canActivate: [AuthGuard],
        loadChildren: () =>
          import('./modules/cart/cart.module')
            .then(m => m.CartModule)
      },
      {
        path: 'pos',
        canActivate: [AuthGuard, RoleGuard],
        canActivateChild: [RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/pos/pos.module')
            .then(m => m.PosModule)
      },
      {
        path: 'inventory',
        canActivate: [AuthGuard, RoleGuard],
        canActivateChild: [RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/inventory/inventory.module')
            .then(m => m.InventoryModule)
      },
      {
        path: 'store',
        canActivate: [AuthGuard, RoleGuard],
        canActivateChild: [RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/store/store.module')
            .then(m => m.StoreModule)
      },
      {
        path: 'users',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/users/users.module')
            .then(m => m.UsersModule)
      },
      {
        path: 'permissions',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/permissions/permissions.module')
            .then(m => m.PermissionsModule)
      },
      {
        path: 'bitacora',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/bitacora/bitacora.module')
            .then(m => m.BitacoraModule)
      },
      {
        path: 'clients',
        canActivate: [AuthGuard, RoleGuard],
        canActivateChild: [RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/clients/clients.module')
            .then(m => m.ClientsModule)
      },
      {
        path: 'attributes',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/attributes/attributes.module')
            .then(m => m.AttributesModule)
      },
      {
        path: 'products',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE'] },
        loadChildren: () =>
          import('./modules/products/products.module')
            .then(m => m.ProductsModule)
      },
      {
        path: 'reservations',
        canActivate: [AuthGuard, RoleGuard],
        loadChildren: () =>
          import('./modules/reservations/reservations.module')
            .then(m => m.ReservationsModule)
      },
      {
        path: 'orders',
        canActivate: [AuthGuard],
        loadChildren: () =>
          import('./modules/orders/orders.module')
            .then(m => m.OrdersModule)
      },
      {
        path: 'deliveries',
        canActivate: [AuthGuard, RoleGuard],
        loadChildren: () =>
          import('./modules/deliveries/deliveries.module')
            .then(m => m.DeliveriesModule)
      },
      {
        path: 'devoluciones',
        canActivate: [AuthGuard, RoleGuard],
        data: { rolesExcluidos: ['CLIENTE', 'CAJERO', 'REPARTIDOR'] },
        loadChildren: () =>
          import('./modules/devoluciones/devoluciones.module')
            .then(m => m.DevolucionesModule)
      },
      {
        path: 'assistant-admin',
        canActivate: [AuthGuard, RoleGuard],
        canActivateChild: [RoleGuard],
        data: { rolesExcluidos: ['CLIENTE', 'CAJERO', 'REPARTIDOR'] },
        loadChildren: () =>
          import('./modules/assistant-admin/assistant-admin.module')
            .then(m => m.AssistantAdminModule)
      },
      {
        path: 'profile',
        canActivate: [AuthGuard],
        loadChildren: () =>
          import('./modules/profile/profile.module')
            .then(m => m.ProfileModule)
      }
    ]
  },
  {
    path: '**',
    redirectTo: 'auth/login'
  }
];
@NgModule({
  imports: [
    RouterModule.forRoot(routes)
  ],
  exports: [
    RouterModule
  ]
})
export class AppRoutingModule { }