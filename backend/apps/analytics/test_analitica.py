"""Pruebas de la Analítica con Machine Learning (CU09).

- Los datos sintéticos van solo a las tablas ml_*: no crean ventas, pedidos
  ni clientes; usan los clientes, prendas y sucursales reales de la empresa;
  el comando es idempotente.
- El entrenamiento crea las tres ventanas de demanda (3, 5 y 12 meses), deja
  vigente una sola con sus predicciones de 4 semanas, y la segmentación
  asigna un segmento a cada cliente con silhouette por k.
- Acceso: SUPER_ADMIN elige empresa; ADMIN_EMPRESA solo ve y reentrena la
  suya aunque pida otra; encargado, cliente y plan sin IA reciben 403.
- Exportación de los reportes de analítica.

Ejecutar:
    python manage.py test apps.analytics.test_analitica --settings=config.settings.test
"""
import io

from django.core.management import call_command
from django.test import TestCase

from apps.analytics.models import (
    CompraSimulada,
    DetalleCompraSimulada,
    EntrenamientoModelo,
    PrediccionDemanda,
    SegmentoCliente,
)
from apps.analytics.servicio_ml import entrenar_empresa
from apps.sales.models import Order, PosSale
from apps.users_auth.models import Cliente, PlanSuscripcion
from common.pruebas import (
    cliente_api,
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)

URL_DASHBOARD = "/api/analytics/dashboard/"
URL_REENTRENAR = "/api/analytics/reentrenar/"
URL_EXPORTAR = "/api/analytics/exportar/"


class AnaliticaTests(TestCase):
    """Empresa A con datos simulados y modelos entrenados; B sin datos; C sin IA."""

    @classmethod
    def setUpTestData(cls):
        """Crea las empresas, el personal, cinco clientes, genera datos y entrena A."""
        plan_con_ia = crear_plan("PRUEBA_ML_IA", 10)
        PlanSuscripcion.objects.filter(pk=plan_con_ia.pk).update(reportes_ia=True)
        plan_sin_ia = crear_plan("PRUEBA_ML_SIN_IA", 2)
        PlanSuscripcion.objects.filter(pk=plan_sin_ia.pk).update(reportes_ia=False)
        ciudad = crear_ciudad()
        cls.empresa_a = crear_empresa("Empresa ML A", "empresa-ml-a", plan_con_ia)
        cls.empresa_b = crear_empresa("Empresa ML B", "empresa-ml-b", plan_con_ia)
        cls.empresa_c = crear_empresa("Empresa ML C", "empresa-ml-c", plan_sin_ia)
        cls.sucursal_a1 = crear_sucursal(cls.empresa_a, "Sucursal MLA1", ciudad)
        cls.sucursal_a2 = crear_sucursal(cls.empresa_a, "Sucursal MLA2", ciudad)
        sucursal_b = crear_sucursal(cls.empresa_b, "Sucursal MLB1", ciudad)
        crear_prenda(cls.empresa_a, cls.sucursal_a1, "ML-A-1", 10)
        crear_prenda(cls.empresa_a, cls.sucursal_a2, "ML-A-2", 10)
        crear_prenda(cls.empresa_b, sucursal_b, "ML-B-1", 10)

        crear_usuario("admin@ml-a.test", "ADMIN_EMPRESA", cls.empresa_a)
        crear_usuario("admin@ml-b.test", "ADMIN_EMPRESA", cls.empresa_b)
        crear_usuario("admin@ml-c.test", "ADMIN_EMPRESA", cls.empresa_c)
        crear_usuario("encargado@ml-a.test", "ENCARGADO_SUCURSAL", cls.empresa_a, cls.sucursal_a1)
        crear_usuario("super@ml.test", "SUPER_ADMIN")
        for numero in range(1, 6):
            crear_usuario(f"cliente{numero}@ml.test", "CLIENTE")

        call_command("generar_datos_ml", empresa="empresa-ml-a", stdout=io.StringIO())
        cls.resumen = entrenar_empresa(cls.empresa_a)

    # ------------------------------------------------------------ datos sintéticos
    def test_datos_sinteticos_solo_en_tablas_ml(self):
        """Hay compras simuladas, pero ninguna venta ni pedido real nuevo."""
        self.assertGreater(CompraSimulada.objects.filter(id_empresa=self.empresa_a).count(), 0)
        self.assertEqual(PosSale.objects.count(), 0)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Cliente.objects.count(), 5)

    def test_datos_sinteticos_usan_clientes_prendas_y_sucursales_reales(self):
        """Clientes existentes y prendas y sucursales de la propia empresa."""
        compras = CompraSimulada.objects.filter(id_empresa=self.empresa_a)
        clientes = set(Cliente.objects.values_list("id_cliente", flat=True))
        self.assertTrue(set(compras.values_list("id_cliente_id", flat=True)) <= clientes)
        self.assertEqual(
            set(compras.values_list("id_sucursal__id_empresa", flat=True)), {self.empresa_a.id_empresa}
        )
        detalles = DetalleCompraSimulada.objects.filter(id_compra__id_empresa=self.empresa_a)
        self.assertEqual(
            set(detalles.values_list("id_producto__id_empresa", flat=True)), {self.empresa_a.id_empresa}
        )
        self.assertFalse(CompraSimulada.objects.filter(id_empresa=self.empresa_b).exists())

    def test_generar_datos_es_idempotente(self):
        """Sin --reemplazar no duplica; con --reemplazar rehace solo los simulados."""
        antes = CompraSimulada.objects.filter(id_empresa=self.empresa_a).count()
        call_command("generar_datos_ml", empresa="empresa-ml-a", stdout=io.StringIO())
        self.assertEqual(CompraSimulada.objects.filter(id_empresa=self.empresa_a).count(), antes)
        call_command("generar_datos_ml", empresa="empresa-ml-a", reemplazar=True, stdout=io.StringIO())
        self.assertEqual(CompraSimulada.objects.filter(id_empresa=self.empresa_a).count(), antes)

    # ------------------------------------------------------------ entrenamiento
    def test_entrenamiento_demanda_tres_ventanas_y_una_vigente(self):
        """3, 5 y 12 meses en la misma corrida; una vigente con métricas y predicciones."""
        demanda = EntrenamientoModelo.objects.filter(id_empresa=self.empresa_a, tipo="DEMANDA")
        self.assertEqual(sorted(demanda.values_list("ventana_meses", flat=True)), [3, 5, 12])
        self.assertEqual(demanda.filter(vigente=True).count(), 1)
        vigente = demanda.get(vigente=True)
        for metrica in ("mae", "rmse", "mae_linea_base", "importancias", "serie_prueba"):
            self.assertIn(metrica, vigente.metricas)
        self.assertGreater(vigente.filas_entrenamiento, 0)
        self.assertGreater(vigente.filas_prueba, 0)
        predicciones = PrediccionDemanda.objects.filter(id_entrenamiento=vigente)
        self.assertGreater(predicciones.count(), 0)
        self.assertEqual(predicciones.values("semana_inicio").distinct().count(), 4)
        self.assertFalse(predicciones.filter(unidades_predichas__lt=0).exists())

    def test_segmentacion_asigna_segmento_a_cada_cliente(self):
        """K-means con hasta 4 grupos, silhouette por k y un segmento por cliente."""
        seg = EntrenamientoModelo.objects.get(id_empresa=self.empresa_a, tipo="SEGMENTACION", vigente=True)
        clientes = seg.metricas["clientes"]
        self.assertGreaterEqual(clientes, 3)
        self.assertEqual(seg.metricas["k"], min(4, clientes - 1))
        self.assertIn("2", seg.metricas["silhouette"])
        segmentos = SegmentoCliente.objects.filter(id_entrenamiento=seg)
        self.assertEqual(segmentos.count(), clientes)
        self.assertEqual(segmentos.values("segmento").distinct().count(), seg.metricas["k"])
        self.assertIn("VIP", set(segmentos.values_list("segmento", flat=True)))

    # ------------------------------------------------------------ acceso y aislamiento
    def test_super_admin_elige_la_empresa(self):
        """El SUPER_ADMIN ve la empresa pedida y la lista de empresas."""
        r = cliente_api("super@ml.test").get(URL_DASHBOARD, {"empresa": self.empresa_a.id_empresa})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["empresa"]["id"], self.empresa_a.id_empresa)
        self.assertEqual(len(r.data["demanda"]["ventanas"]), 3)
        self.assertTrue(r.data["super_admin"])
        self.assertGreaterEqual(len(r.data["empresas"]), 3)

    def test_admin_empresa_solo_ve_la_suya_aunque_pida_otra(self):
        """B pide los datos de A y recibe los suyos (sin modelos)."""
        r = cliente_api("admin@ml-b.test").get(URL_DASHBOARD, {"empresa": self.empresa_a.id_empresa})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["empresa"]["id"], self.empresa_b.id_empresa)
        self.assertEqual(r.data["demanda"]["ventanas"], [])
        self.assertIsNone(r.data["segmentacion"])
        self.assertEqual(r.data["empresas"], [])

    def test_encargado_y_cliente_no_acceden(self):
        """La analítica es solo para SUPER_ADMIN y ADMIN_EMPRESA."""
        self.assertEqual(cliente_api("encargado@ml-a.test").get(URL_DASHBOARD).status_code, 403)
        self.assertEqual(cliente_api("cliente1@ml.test").get(URL_DASHBOARD).status_code, 403)

    def test_plan_sin_ia_no_accede(self):
        """Un ADMIN_EMPRESA con plan sin IA recibe 403."""
        self.assertEqual(cliente_api("admin@ml-c.test").get(URL_DASHBOARD).status_code, 403)

    def test_admin_reentrena_solo_su_empresa(self):
        """Aunque pida "todas", el ADMIN_EMPRESA solo reentrena la suya."""
        r = cliente_api("admin@ml-b.test").post(URL_REENTRENAR, {"empresa": "todas"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual([x["empresa"] for x in r.data["resultados"]], ["Empresa ML B"])

    def test_super_admin_reentrena_todas(self):
        """El SUPER_ADMIN reentrena todas las empresas activas."""
        r = cliente_api("super@ml.test").post(URL_REENTRENAR, {"empresa": "todas"}, format="json")
        self.assertEqual(r.status_code, 201)
        nombres = [x["empresa"] for x in r.data["resultados"]]
        self.assertIn("Empresa ML A", nombres)
        self.assertIn("Empresa ML B", nombres)

    # ------------------------------------------------------------ exportación
    def test_exportar_reportes_de_analitica(self):
        """Los tres reportes se exportan; reporte o formato inválido da 400."""
        api = cliente_api("admin@ml-a.test")
        for reporte in ("demanda", "segmentos", "modelos"):
            r = api.get(URL_EXPORTAR, {"reporte": reporte, "formato": "xlsx"})
            self.assertEqual(r.status_code, 200, reporte)
            self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(api.get(URL_EXPORTAR, {"reporte": "x", "formato": "pdf"}).status_code, 400)
        self.assertEqual(api.get(URL_EXPORTAR, {"reporte": "modelos", "formato": "doc"}).status_code, 400)