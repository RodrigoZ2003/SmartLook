"""Pruebas de los traspasos entre sucursales (CU07).

- Solicitar: ADMIN_EMPRESA entre sus sucursales; el encargado solo hacia su
  sucursal; el cajero no puede; no se pide más stock del que hay; no entre
  empresas ni hacia la misma sucursal. Avisa a los administradores.
- Aprobar (ADMIN_EMPRESA o SUPER_ADMIN): sale el stock del origen y queda en
  tránsito; si el stock ya no alcanza no se aprueba ni se mueve nada; no se
  aprueba dos veces.
- Recibir (encargado de destino, ADMIN_EMPRESA o SUPER_ADMIN): entra el
  stock completo en el destino.
- Rechazar con motivo obligatorio y cancelar, solo mientras está solicitado.
- Aislamiento: otra empresa no ve ni toca los traspasos (404).
- Sugerencias a partir de la predicción de demanda (solo administradores).

Ejecutar:
    python manage.py test apps.inventory.test_traspasos --settings=config.settings.test
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import EntrenamientoModelo, PrediccionDemanda
from apps.inventory.models import InventoryMovement, StockItem, Traspaso
from apps.users_auth.models import Notificacion, PlanSuscripcion
from common.pruebas import (
    cliente_api,
    crear_ciudad,
    crear_empresa,
    crear_plan,
    crear_prenda,
    crear_sucursal,
    crear_usuario,
)

URL = "/api/inventory/traspasos/"


class TraspasosTests(TestCase):
    """Empresa A con tres sucursales y stock en A1; empresa B aparte."""

    @classmethod
    def setUpTestData(cls):
        """Empresas, sucursales, una prenda con 10 unidades en A1 y el personal."""
        plan = crear_plan("PRUEBA_TRASPASOS", 10)
        PlanSuscripcion.objects.filter(pk=plan.pk).update(reportes_ia=True)
        ciudad = crear_ciudad()
        cls.empresa_a = crear_empresa("Empresa Traspasos A", "empresa-traspasos-a", plan)
        cls.empresa_b = crear_empresa("Empresa Traspasos B", "empresa-traspasos-b", plan)
        cls.a1 = crear_sucursal(cls.empresa_a, "Sucursal TA1", ciudad)
        cls.a2 = crear_sucursal(cls.empresa_a, "Sucursal TA2", ciudad)
        cls.a3 = crear_sucursal(cls.empresa_a, "Sucursal TA3", ciudad)
        cls.b1 = crear_sucursal(cls.empresa_b, "Sucursal TB1", ciudad)
        cls.variante = crear_prenda(cls.empresa_a, cls.a1, "TRAS-A-1", 10)
        crear_prenda(cls.empresa_b, cls.b1, "TRAS-B-1", 10)

        cls.admin_a = crear_usuario("admin@traspasos-a.test", "ADMIN_EMPRESA", cls.empresa_a)
        crear_usuario("admin@traspasos-b.test", "ADMIN_EMPRESA", cls.empresa_b)
        crear_usuario("encargado2@traspasos-a.test", "ENCARGADO_SUCURSAL", cls.empresa_a, cls.a2)
        crear_usuario("encargado3@traspasos-a.test", "ENCARGADO_SUCURSAL", cls.empresa_a, cls.a3)
        crear_usuario("cajero@traspasos-a.test", "CAJERO", cls.empresa_a, cls.a2)
        crear_usuario("super@traspasos.test", "SUPER_ADMIN")

    def solicitar(self, correo, origen, destino, cantidad=3):
        """POST de una solicitud con la prenda de prueba."""
        return cliente_api(correo).post(URL, {
            "id_sucursal_origen": origen.id_sucursal,
            "id_sucursal_destino": destino.id_sucursal,
            "observacion": "Falta en vitrina",
            "lineas": [{"id_variante": self.variante.id_variante, "cantidad": cantidad}],
        }, format="json")

    def stock(self, sucursal):
        """Unidades de la prenda de prueba en una sucursal."""
        item = StockItem.objects.filter(id_sucursal=sucursal, id_variante=self.variante).first()
        return item.cantidad if item else 0

    # ------------------------------------------------------------ solicitar
    def test_encargado_solicita_hacia_su_sucursal_y_avisa(self):
        """El encargado de A2 pide de A1 a A2; se avisa al admin y al SUPER_ADMIN."""
        r = self.solicitar("encargado2@traspasos-a.test", self.a1, self.a2)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["estado"], "SOLICITADO")
        self.assertEqual(r.data["unidades"], 3)
        self.assertEqual(self.stock(self.a1), 10)
        avisos = Notificacion.objects.filter(clave=f"traspaso-{r.data['id']}-SOLICITADO", tipo="TRASPASO")
        self.assertEqual(
            set(avisos.values_list("id_usuario__correo", flat=True)),
            {"admin@traspasos-a.test", "super@traspasos.test"},
        )

    def test_encargado_no_pide_hacia_otra_sucursal(self):
        """El encargado de A2 no puede pedir hacia A3."""
        r = self.solicitar("encargado2@traspasos-a.test", self.a1, self.a3)
        self.assertEqual(r.status_code, 403)

    def test_cajero_no_puede_solicitar(self):
        """El cajero no usa traspasos."""
        self.assertEqual(self.solicitar("cajero@traspasos-a.test", self.a1, self.a2).status_code, 403)

    def test_no_se_pide_mas_stock_del_que_hay(self):
        """Pedir 11 de 10 unidades se rechaza."""
        r = self.solicitar("admin@traspasos-a.test", self.a1, self.a2, cantidad=11)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Stock insuficiente", r.data["detail"])

    def test_misma_sucursal_u_otra_empresa_no(self):
        """Origen y destino iguales, o sucursales de otra empresa, se rechazan."""
        self.assertEqual(self.solicitar("admin@traspasos-a.test", self.a1, self.a1).status_code, 400)
        self.assertEqual(self.solicitar("admin@traspasos-b.test", self.a1, self.b1).status_code, 400)
        self.assertEqual(self.solicitar("super@traspasos.test", self.a1, self.b1).status_code, 400)

    # ------------------------------------------------------------ aprobar y recibir
    def test_flujo_completo_aprobar_y_recibir(self):
        """Aprobar saca 3 de A1 (en tránsito); recibir las pone en A2."""
        id_traspaso = self.solicitar("encargado2@traspasos-a.test", self.a1, self.a2).data["id"]
        self.assertEqual(cliente_api("encargado2@traspasos-a.test").post(f"{URL}{id_traspaso}/aprobar/").status_code, 403)
        r = cliente_api("admin@traspasos-a.test").post(f"{URL}{id_traspaso}/aprobar/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "EN_TRANSITO")
        self.assertEqual(self.stock(self.a1), 7)
        self.assertEqual(self.stock(self.a2), 0)
        self.assertTrue(InventoryMovement.objects.filter(
            id_sucursal=self.a1, tipo_movimiento="SALIDA", cantidad=3, motivo__contains=f"#{id_traspaso}"
        ).exists())
        self.assertEqual(cliente_api("admin@traspasos-a.test").post(f"{URL}{id_traspaso}/aprobar/").status_code, 400)
        self.assertEqual(cliente_api("encargado3@traspasos-a.test").post(f"{URL}{id_traspaso}/recibir/").status_code, 404)
        r = cliente_api("encargado2@traspasos-a.test").post(f"{URL}{id_traspaso}/recibir/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "RECIBIDO")
        self.assertEqual(self.stock(self.a2), 3)
        self.assertTrue(InventoryMovement.objects.filter(
            id_sucursal=self.a2, tipo_movimiento="ENTRADA", cantidad=3
        ).exists())
        self.assertEqual(cliente_api("encargado2@traspasos-a.test").post(f"{URL}{id_traspaso}/recibir/").status_code, 400)

    def test_no_se_aprueba_si_el_stock_ya_no_alcanza(self):
        """Si el stock bajó después de solicitar, no se aprueba ni se mueve nada."""
        id_traspaso = self.solicitar("admin@traspasos-a.test", self.a1, self.a2, cantidad=5).data["id"]
        StockItem.objects.filter(id_sucursal=self.a1, id_variante=self.variante).update(cantidad=2)
        r = cliente_api("super@traspasos.test").post(f"{URL}{id_traspaso}/aprobar/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Traspaso.objects.get(pk=id_traspaso).estado, "SOLICITADO")
        self.assertEqual(self.stock(self.a1), 2)

    # ------------------------------------------------------------ rechazar y cancelar
    def test_rechazo_con_motivo_obligatorio(self):
        """Sin motivo no se rechaza; rechazado ya no se puede aprobar."""
        id_traspaso = self.solicitar("encargado2@traspasos-a.test", self.a1, self.a2).data["id"]
        api = cliente_api("admin@traspasos-a.test")
        self.assertEqual(api.post(f"{URL}{id_traspaso}/rechazar/", {"motivo": " "}, format="json").status_code, 400)
        r = api.post(f"{URL}{id_traspaso}/rechazar/", {"motivo": "Hay stock en camino"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["estado"], "RECHAZADO")
        self.assertEqual(r.data["motivo_rechazo"], "Hay stock en camino")
        self.assertEqual(api.post(f"{URL}{id_traspaso}/aprobar/").status_code, 400)
        self.assertEqual(self.stock(self.a1), 10)

    def test_cancelar_solo_mientras_esta_solicitado(self):
        """El solicitante cancela su pedido; uno en tránsito ya no se cancela."""
        api = cliente_api("encargado2@traspasos-a.test")
        id_1 = self.solicitar("encargado2@traspasos-a.test", self.a1, self.a2).data["id"]
        r = api.post(f"{URL}{id_1}/cancelar/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["estado"], "CANCELADO")
        id_2 = self.solicitar("encargado2@traspasos-a.test", self.a1, self.a2).data["id"]
        cliente_api("admin@traspasos-a.test").post(f"{URL}{id_2}/aprobar/")
        self.assertEqual(api.post(f"{URL}{id_2}/cancelar/").status_code, 400)

    # ------------------------------------------------------------ aislamiento
    def test_otra_empresa_no_ve_ni_toca_los_traspasos(self):
        """B no los lista ni puede aprobarlos; el encargado de A3 no ve los de A1 a A2."""
        id_traspaso = self.solicitar("admin@traspasos-a.test", self.a1, self.a2).data["id"]
        api_b = cliente_api("admin@traspasos-b.test")
        self.assertEqual(api_b.get(URL).data, [])
        self.assertEqual(api_b.get(f"{URL}{id_traspaso}/").status_code, 404)
        self.assertEqual(api_b.post(f"{URL}{id_traspaso}/aprobar/").status_code, 404)
        self.assertEqual(cliente_api("encargado3@traspasos-a.test").get(URL).data, [])
        ids_super = [t["id"] for t in cliente_api("super@traspasos.test").get(URL).data]
        self.assertIn(id_traspaso, ids_super)

    # ------------------------------------------------------------ sugerencias
    def test_sugerencia_desde_la_prediccion_de_demanda(self):
        """Demanda prevista de 5 en A2 sin stock y 10 en A1: sugiere llevar 5 de A1 a A2."""
        entrenamiento = EntrenamientoModelo.objects.create(
            id_empresa=self.empresa_a, tipo="DEMANDA", ventana_meses=5,
            algoritmo="RandomForestRegressor", vigente=True,
        )
        lunes = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        for semana in range(4):
            PrediccionDemanda.objects.create(
                id_entrenamiento=entrenamiento, id_empresa=self.empresa_a, id_sucursal=self.a2,
                id_producto=self.variante.id_producto, semana_inicio=lunes + timedelta(days=7 * semana),
                unidades_predichas=Decimal("1.25"),
            )
        r = cliente_api("admin@traspasos-a.test").get(f"{URL}sugerencias/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["sugerencias"]), 1)
        sugerencia = r.data["sugerencias"][0]
        self.assertEqual(sugerencia["id_sucursal_origen"], self.a1.id_sucursal)
        self.assertEqual(sugerencia["id_sucursal_destino"], self.a2.id_sucursal)
        self.assertEqual(sugerencia["cantidad_sugerida"], 5)
        self.assertEqual(sugerencia["variantes"][0]["id_variante"], self.variante.id_variante)
        self.assertEqual(cliente_api("encargado2@traspasos-a.test").get(f"{URL}sugerencias/").status_code, 403)
        self.solicitar("admin@traspasos-a.test", self.a1, self.a2, cantidad=5)
        r = cliente_api("admin@traspasos-a.test").get(f"{URL}sugerencias/")
        self.assertEqual(r.data["sugerencias"], [])