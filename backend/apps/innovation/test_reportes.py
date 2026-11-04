"""Pruebas de los reportes de gestión (CU13 - reportes con IA y convencionales).

- Ventas netas: sin ventas anuladas, restando devoluciones completadas y
  avisando las ventas sin conexión en conflicto (igual que el dashboard).
- Aislamiento: cada empresa solo ve sus datos; el SUPER_ADMIN ve todas o la
  que elija; el encargado solo su sucursal.
- Filtros inexistentes devuelven un reporte vacío con nota (no datos ajenos).
- Exportación pedida en el chat ("descárgamelo en PDF") sin llamar a la IA.
- Plan sin IA: genera y exporta reportes convencionales, pero el asistente
  con IA responde 403.
- Las exportaciones incluyen el gráfico.

Ejecutar:
    python manage.py test apps.innovation.test_reportes --settings=config.settings.test
"""
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from apps.innovation import consultas_admin as ca
from apps.innovation.chatbot_admin import MENSAJE_SIN_REPORTE, responder_gestion
from apps.innovation.exportadores import exportar
from apps.innovation.models import ReporteAsistente
from apps.sales.models import Devolucion, PosSale
from apps.users_auth.models import PlanSuscripcion
from common.pruebas import (
    cliente_api,
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)

def kpi(resultado, etiqueta):
    """Valor de un indicador del resultado por su etiqueta."""
    return next(k["valor"] for k in resultado["kpis"] if k["etiqueta"] == etiqueta)

def crear_venta(usuario, sucursal, total, estado="REGISTRADA"):
    """Venta POS de prueba con el total y el estado indicados."""
    return PosSale.objects.create(
        id_sucursal=sucursal,
        id_usuario=usuario,
        id_empresa=sucursal.id_empresa,
        total=Decimal(total),
        metodo_pago="EFECTIVO",
        estado=estado,
    )

class ReportesGestionTests(TestCase):
    """Reportes de la Empresa A y B con ventas, devoluciones y conflictos."""

    @classmethod
    def setUpTestData(cls):
        """Dos empresas: A con dos sucursales y ventas de varios estados; B con una venta."""
        cls.plan_con_ia = crear_plan("PRUEBA_CON_IA", 10)
        PlanSuscripcion.objects.filter(pk=cls.plan_con_ia.pk).update(reportes_ia=True)
        cls.plan_sin_ia = crear_plan("PRUEBA_SIN_IA", 2)
        PlanSuscripcion.objects.filter(pk=cls.plan_sin_ia.pk).update(reportes_ia=False)
        ciudad = crear_ciudad()
        cls.empresa_a = crear_empresa("Empresa Reportes A", "empresa-reportes-a", cls.plan_con_ia)
        cls.empresa_b = crear_empresa("Empresa Reportes B", "empresa-reportes-b", cls.plan_sin_ia)
        cls.sucursal_a1 = crear_sucursal(cls.empresa_a, "Sucursal RA1", ciudad)
        cls.sucursal_a2 = crear_sucursal(cls.empresa_a, "Sucursal RA2", ciudad)
        cls.sucursal_b = crear_sucursal(cls.empresa_b, "Sucursal RB1", ciudad)
        crear_prenda(cls.empresa_a, cls.sucursal_a1, "REP-A-1", 3)
        crear_prenda(cls.empresa_b, cls.sucursal_b, "REP-B-1", 8)

        cls.admin_a = crear_usuario("admin@reportes-a.test", "ADMIN_EMPRESA", cls.empresa_a)
        cls.admin_b = crear_usuario("admin@reportes-b.test", "ADMIN_EMPRESA", cls.empresa_b)
        cls.encargado_a1 = crear_usuario(
            "encargado@reportes-a.test", "ENCARGADO_SUCURSAL", cls.empresa_a, cls.sucursal_a1
        )
        cls.super_admin = crear_usuario("super@reportes.test", "SUPER_ADMIN")

        # Empresa A: 100 normal + 30 en conflicto + 50 anulada en A1; 40 en A2.
        venta = crear_venta(cls.admin_a, cls.sucursal_a1, "100.00")
        crear_venta(cls.admin_a, cls.sucursal_a1, "30.00", "EN_CONFLICTO")
        crear_venta(cls.admin_a, cls.sucursal_a1, "50.00", "ANULADA")
        crear_venta(cls.admin_a, cls.sucursal_a2, "40.00")
        # Devolución completada de 20 sobre la venta de 100.
        Devolucion.objects.create(
            id_venta=venta,
            estado="COMPLETADA",
            monto_reembolso=Decimal("20.00"),
            fecha_completado=timezone.now(),
        )
        # Empresa B: una venta de 999 que A nunca debe ver.
        crear_venta(cls.admin_b, cls.sucursal_b, "999.00")

    # ------------------------------------------------------------ ventas netas
    def test_ventas_netas_sin_anuladas_y_restando_devoluciones(self):
        """Neto de A = 100 + 30 + 40 - 20 = 150; la anulada de 50 no cuenta."""
        r = ca.ejecutar("consultar_ventas", {"periodo": "mes", "agrupar_por": "sucursal"}, self.admin_a)
        self.assertEqual(kpi(r, "Total vendido"), 170.0)
        self.assertEqual(kpi(r, "Devoluciones"), 20.0)
        self.assertEqual(kpi(r, "Total neto"), 150.0)
        self.assertEqual(kpi(r, "Ventas realizadas"), 3)
        self.assertTrue(any("en conflicto" in n for n in r["notas"]))
        self.assertEqual(r["grafico"]["tipo"], "bar")

    def test_resumen_general_coincide_con_ventas(self):
        """El resumen usa el mismo cálculo de ventas netas."""
        r = ca.ejecutar("resumen_general", {"periodo": "mes"}, self.admin_a)
        self.assertEqual(kpi(r, "Total neto"), 150.0)

    # ------------------------------------------------------------ aislamiento
    def test_otra_empresa_no_ve_ventas_ajenas(self):
        """B solo ve su venta de 999, nunca las de A."""
        r = ca.ejecutar("consultar_ventas", {"periodo": "mes"}, self.admin_b)
        self.assertEqual(kpi(r, "Total neto"), 999.0)

    def test_personal_no_puede_pedir_otra_empresa(self):
        """Si A pide los datos de B, el reporte sale vacío con nota de acceso."""
        r = ca.ejecutar(
            "consultar_ventas", {"periodo": "mes", "empresa": "Empresa Reportes B"}, self.admin_a
        )
        self.assertEqual(kpi(r, "Total neto"), 0)
        self.assertTrue(any("No tienes acceso" in n for n in r["notas"]))

    def test_super_admin_ve_todas_o_la_empresa_elegida(self):
        """El SUPER_ADMIN ve el total de todas y puede filtrar una empresa."""
        todas = ca.ejecutar("consultar_ventas", {"periodo": "mes"}, self.super_admin)
        solo_b = ca.ejecutar(
            "consultar_ventas", {"periodo": "mes", "empresa": "Empresa Reportes B"}, self.super_admin
        )
        self.assertGreaterEqual(kpi(todas, "Total neto"), 1149.0)
        self.assertEqual(kpi(solo_b, "Total neto"), 999.0)
        self.assertIn("Empresa: Empresa Reportes B", solo_b["subtitulo"])

    def test_encargado_solo_ve_su_sucursal(self):
        """El encargado de A1 no ve la venta de 40 de A2."""
        r = ca.ejecutar("consultar_ventas", {"periodo": "mes", "sucursal": "RA2"}, self.encargado_a1)
        self.assertEqual(kpi(r, "Total neto"), 110.0)
        self.assertIn("Sucursal: Sucursal RA1", r["subtitulo"])

    # ------------------------------------------------------------ filtros y reportes
    def test_categoria_inexistente_devuelve_vacio_con_nota(self):
        """Un filtro de categoría que no existe no muestra otros datos."""
        r = ca.ejecutar("consultar_ventas", {"periodo": "mes", "categoria": "zzz"}, self.admin_a)
        self.assertEqual(r["filas"], [])
        self.assertTrue(any("No existe la categoría" in n for n in r["notas"]))

    def test_comparativo_y_menor_existencia(self):
        """El comparativo trae una fila por sucursal y menor existencia ordena de menor a mayor."""
        comparativo = ca.ejecutar("comparativo_sucursales", {"meses": 3}, self.admin_a)
        nombres = [fila[0] for fila in comparativo["filas"]]
        self.assertEqual(sorted(nombres), ["Sucursal RA1", "Sucursal RA2"])
        self.assertEqual(comparativo["grafico"]["tipo"], "bar")
        existencia = ca.ejecutar("menor_existencia", {}, self.admin_a)
        self.assertEqual(existencia["filas"][0][6], 3)

    def test_exportaciones_incluyen_el_grafico(self):
        """El HTML trae el SVG y el Excel la hoja 'Gráfico'."""
        r = ca.ejecutar("consultar_ventas", {"periodo": "mes", "agrupar_por": "sucursal"}, self.admin_a)
        html, _, _ = exportar("html", r, {"generado": "01/01/2026 10:00"})
        self.assertIn(b"<svg", html)
        xlsx, _, _ = exportar("xlsx", r, {"generado": "01/01/2026 10:00"})
        self.assertIn("Gráfico", load_workbook(io.BytesIO(xlsx)).sheetnames)
        pdf, tipo, _ = exportar("pdf", r, {"generado": "01/01/2026 10:00"})
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(tipo, "application/pdf")

    # ------------------------------------------------------------ exportar desde el chat
    def test_chat_descargar_en_pdf_sin_reporte_previo(self):
        """Sin reportes previos, pedir la descarga explica que primero pida uno."""
        r = responder_gestion(self.admin_a, "descárgamelo en PDF")
        self.assertIsNone(r["exportar"])
        self.assertEqual(r["respuesta"], MENSAJE_SIN_REPORTE)

    def test_chat_descargar_ultimo_reporte_en_pdf_y_excel(self):
        """'Descárgamelo en PDF' y 'pásalo a excel' exportan el último reporte sin usar la IA."""
        api = cliente_api("admin@reportes-a.test")
        generado = api.post(
            "/api/innovation/reportes/generar/",
            {"consulta": "consultar_ventas", "filtros": {"periodo": "mes"}},
            format="json",
        )
        self.assertEqual(generado.status_code, 201, generado.data)
        r = responder_gestion(self.admin_a, "descárgamelo en PDF")
        self.assertEqual(r["proveedor"], "sistema")
        self.assertEqual(r["exportar"]["id_reporte"], generado.data["id_reporte"])
        self.assertEqual(r["exportar"]["formato"], "pdf")
        r = responder_gestion(self.admin_a, "pásalo a excel")
        self.assertEqual(r["exportar"]["formato"], "xlsx")

    # ------------------------------------------------------------ API y planes
    def test_reporte_convencional_descarta_filtro_de_otra_empresa(self):
        """El ADMIN de A no puede usar el filtro 'empresa' para ver a B."""
        api = cliente_api("admin@reportes-a.test")
        respuesta = api.post(
            "/api/innovation/reportes/generar/",
            {
                "consulta": "consultar_ventas",
                "filtros": {"periodo": "mes", "empresa": "Empresa Reportes B"},
            },
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201)
        self.assertNotIn("empresa", respuesta.data["filtros"])
        self.assertIn("Empresa: Empresa Reportes A", respuesta.data["resultado"]["subtitulo"])

    def test_plan_sin_ia_genera_y_exporta_pero_no_usa_el_asistente(self):
        """Con el plan sin IA: reporte convencional 201, exportar 200, asistente 403."""
        api = cliente_api("admin@reportes-b.test")
        generado = api.post(
            "/api/innovation/reportes/generar/",
            {"consulta": "comparativo_sucursales", "filtros": {"meses": 3}},
            format="json",
        )
        self.assertEqual(generado.status_code, 201, generado.data)
        archivo = api.get(
            f"/api/innovation/asistente/reportes/{generado.data['id_reporte']}/exportar/",
            {"formato": "pdf"},
        )
        self.assertEqual(archivo.status_code, 200)
        self.assertEqual(archivo["Content-Type"], "application/pdf")
        asistente = api.post("/api/innovation/asistente/", {"mensaje": "ventas de hoy"}, format="json")
        self.assertEqual(asistente.status_code, 403)
        self.assertEqual(asistente.data["codigo"], "plan_no_permitido")

    def test_no_puede_exportar_reporte_de_otro_usuario(self):
        """El reporte guardado de A no se puede descargar con la sesión de B (404)."""
        reporte = ReporteAsistente.objects.create(
            id_usuario=self.admin_a,
            pregunta="prueba",
            consulta="consultar_ventas",
            filtros={},
            titulo="Ventas",
            resultado=ca.ejecutar("consultar_ventas", {"periodo": "mes"}, self.admin_a),
        )
        api_b = cliente_api("admin@reportes-b.test")
        respuesta = api_b.get(
            f"/api/innovation/asistente/reportes/{reporte.id_reporte}/exportar/", {"formato": "pdf"}
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_tipo_de_reporte_invalido(self):
        """Un tipo de reporte que no existe responde 400."""
        api = cliente_api("admin@reportes-a.test")
        respuesta = api.post(
            "/api/innovation/reportes/generar/", {"consulta": "borrar_ventas"}, format="json"
        )
        self.assertEqual(respuesta.status_code, 400)