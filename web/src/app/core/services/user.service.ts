// web/src/app/core/services/user.service.ts
//
// MODIFICADO: getUsuarios() y getClientes() traen TODAS las páginas del
// backend (antes solo la primera, de 20: los usuarios nuevos no aparecían).

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { EMPTY, Observable, expand, map, reduce } from 'rxjs';
import { environment } from '../../../environments/environment';

const TAMANO_PAGINA = 100;

@Injectable({
  providedIn: 'root'
})
export class UserService {

  private apiUrl = `${environment.apiUrl}/auth`;

  constructor(
    private http: HttpClient
  ) {}

  // Pide la página 1 y sigue con la 2, 3... mientras el backend indique que hay más.
  private todasLasPaginas(ruta: string, params: { [clave: string]: string } = {}): Observable<any[]> {
    const pedir = (pagina: number) => this.http.get<any>(`${this.apiUrl}${ruta}`, {
      params: { ...params, page_size: TAMANO_PAGINA, page: pagina }
    });
    return pedir(1).pipe(
      expand((respuesta: any, indice: number) =>
        respuesta && !Array.isArray(respuesta) && respuesta.next ? pedir(indice + 2) : EMPTY
      ),
      reduce(
        (todos: any[], respuesta: any) =>
          todos.concat(Array.isArray(respuesta) ? respuesta : (respuesta?.results ?? [])),
        [] as any[]
      )
    );
  }

  getUsuarios(): Observable<any[]> {
    return this.todasLasPaginas('/usuarios/');
  }

  getRoles(): Observable<any[]> {

    return this.http.get<any>(
      `${this.apiUrl}/roles/`
    ).pipe(

      map(response => {

        return response.results ?? response;

      })

    );

  }

  crearUsuario(data:any): Observable<any>{

    return this.http.post<any>(
      `${this.apiUrl}/usuarios/`,
      data
    );

  }

  actualizarUsuario(id: number, data: any): Observable<any> {

    return this.http.patch<any>(
      `${this.apiUrl}/usuarios/${id}/`,
      data
    );

  }

  eliminarUsuario(id: number): Observable<any> {

    return this.http.delete<any>(
      `${this.apiUrl}/usuarios/${id}/`
    );

  }

  getPermisos(): Observable<any[]> {

    return this.http.get<any>(
      `${this.apiUrl}/permisos/`
    ).pipe(

      map(response => {

        return response.results ?? response;

      })

    );

  }

  getRolPermisos(idRol: number): Observable<{ permisos: number[] }> {

    return this.http.get<{ permisos: number[] }>(
      `${this.apiUrl}/roles/${idRol}/permisos/`
    );

  }

  actualizarRolPermisos(idRol: number, permisos: number[]): Observable<{ permisos: number[] }> {

    return this.http.put<{ permisos: number[] }>(
      `${this.apiUrl}/roles/${idRol}/permisos/`,
      { permisos }
    );

  }

  getBitacora(): Observable<any[]> {

    return this.http.get<any>(
      `${this.apiUrl}/bitacora/`
    ).pipe(

      map(response => {

        return response.results ?? response;

      })

    );

  }

  getClientes(): Observable<any[]> {
    return this.todasLasPaginas('/usuarios/', { rol: 'CLIENTE' });
  }

}