# backend/apps/analytics/servicio_ml.py
#
# NUEVO (Fase 3 - CU09): entrenamiento de los modelos de Machine Learning.
#
# Datos de entrada (opción C): compras simuladas (tablas ml_*) + ventas
# reales (pedidos pagados y ventas POS no anuladas). Nunca escribe en tablas
# reales: solo crea registros en ml_entrenamiento, ml_prediccion_demanda y
# ml_segmento_cliente.
#
# 1) Supervisado - Predicción de demanda (RandomForestRegressor):
#    unidades vendidas por prenda x sucursal x semana. Se entrena con 3, 5 y
#    12 meses de historial y se comparan MAE, RMSE y R² contra una línea base
#    (promedio de las últimas 4 semanas). El de menor MAE queda vigente y
#    predice las próximas 4 semanas.
# 2) No supervisado - Segmentación de clientes (K-means sobre RFM):
#    recencia, frecuencia y monto de cada cliente en la empresa (12 meses).
#    Se calcula el silhouette para k = 2..6 y se usan 4 grupos: VIP, leales,
#    ocasionales y en riesgo.

import math
import uuid
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from django.db import transaction
from django.utils import timezone
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from apps.sales.models import Order, OrderItem, PosSale, PosSaleItem

from .models import (
    CompraSimulada,
    DetalleCompraSimulada,
    EntrenamientoModelo,
    PrediccionDemanda,
    SegmentoCliente,
)

ESTADOS_PAGADOS = ("PAGADA", "ENVIADA", "ENTREGADA")
VENTANAS_MESES = (3, 5, 12)
VENTANA_SEGMENTACION = 12
SEMANAS_A_PREDECIR = 4
REZAGOS = 4
MIN_FILAS_ENTRENAMIENTO = 20
SEGMENTOS_OBJETIVO = 4
K_MAXIMO = 6
SEMILLA = 42
# Árboles poco profundos y hojas con al menos 10 semanas: con pocas ventas
# semanales un bosque más profundo memoriza el ruido.
PARAMETROS_BOSQUE = {"n_estimators": 200, "max_depth": 4, "min_samples_leaf": 10}

VARIABLES_DEMANDA = [
    "semana_sen", "semana_cos", "mes",
    "rezago_1", "rezago_2", "rezago_3", "rezago_4",
    "media_4", "media_historica",
    "sucursal", "prenda", "precio",
]
NOMBRES_VARIABLES = {
    "semana_sen": "Semana del año (seno)",
    "semana_cos": "Semana del año (coseno)",
    "mes": "Mes",
    "rezago_1": "Ventas hace 1 semana",
    "rezago_2": "Ventas hace 2 semanas",
    "rezago_3": "Ventas hace 3 semanas",
    "rezago_4": "Ventas hace 4 semanas",
    "media_4": "Promedio últimas 4 semanas",
    "media_historica": "Promedio histórico",
    "sucursal": "Sucursal",
    "prenda": "Prenda",
    "precio": "Precio",
}
NOMBRE_SEGMENTO = dict(SegmentoCliente.SEGMENTOS)


def _lunes(fecha):
    """Lunes de la semana de una fecha."""
    return fecha - timedelta(days=fecha.weekday())


def _restar_meses(fecha, meses):
    """Misma fecha (día máximo 28) N meses antes."""
    mes = fecha.month - meses
    anio = fecha.year
    while mes <= 0:
        mes += 12
        anio -= 1
    return date(anio, mes, min(fecha.day, 28))


def _fecha_local(valor):
    """Fecha local (America/La_Paz) de un DateTimeField."""
    return timezone.localtime(valor).date()


# --------------------------------------------------------------------------
# Datos de entrada
# --------------------------------------------------------------------------

def _lineas_vendidas(empresa, desde, hasta):
    """(fecha, sucursal, prenda, unidades, precio) simuladas + reales entre dos fechas."""
    lineas = []
    simuladas = DetalleCompraSimulada.objects.filter(
        id_compra__id_empresa=empresa, id_compra__fecha__gte=desde, id_compra__fecha__lte=hasta
    ).values_list(
        "id_compra__fecha", "id_compra__id_sucursal_id", "id_producto_id", "cantidad", "precio_unitario"
    )
    lineas.extend((f, s, p, c, float(pr)) for f, s, p, c, pr in simuladas)
    pedidos = OrderItem.objects.filter(
        id_orden__id_empresa=empresa, id_orden__estado__in=ESTADOS_PAGADOS,
        id_orden__id_sucursal__isnull=False,
    ).values_list(
        "id_orden__fecha_creacion", "id_orden__id_sucursal_id", "id_variante__id_producto_id",
        "cantidad", "precio_unitario",
    )
    pos = PosSaleItem.objects.filter(id_venta__id_empresa=empresa).exclude(
        id_venta__estado="ANULADA"
    ).values_list(
        "id_venta__fecha_venta", "id_venta__id_sucursal_id", "id_variante__id_producto_id",
        "cantidad", "precio_unitario",
    )
    for momento, sucursal, prenda, cantidad, precio in list(pedidos) + list(pos):
        fecha = _fecha_local(momento)
        if desde <= fecha <= hasta and cantidad > 0:
            lineas.append((fecha, sucursal, prenda, cantidad, float(precio)))
    return lineas


def _compras_por_cliente(empresa, desde, hasta):
    """{id_cliente: [(fecha, total), ...]} simuladas + reales entre dos fechas."""
    compras = defaultdict(list)
    simuladas = CompraSimulada.objects.filter(
        id_empresa=empresa, fecha__gte=desde, fecha__lte=hasta
    ).values_list("id_cliente_id", "fecha", "total")
    for cliente, fecha, total in simuladas:
        compras[cliente].append((fecha, float(total)))
    pedidos = Order.objects.filter(
        id_empresa=empresa, estado__in=ESTADOS_PAGADOS
    ).values_list("id_cliente_id", "fecha_creacion", "total")
    pos = PosSale.objects.filter(
        id_empresa=empresa, id_cliente__isnull=False
    ).exclude(estado="ANULADA").values_list("id_cliente_id", "fecha_venta", "total")
    for cliente, momento, total in list(pedidos) + list(pos):
        fecha = _fecha_local(momento)
        if desde <= fecha <= hasta:
            compras[cliente].append((fecha, float(total)))
    return compras


# --------------------------------------------------------------------------
# 1) Predicción de demanda (supervisado)
# --------------------------------------------------------------------------

def _series_semanales(lineas, primera_semana, ultima_semana):
    """Unidades por (sucursal, prenda) en cada semana, con ceros donde no hubo venta."""
    semanas = []
    semana = primera_semana
    while semana <= ultima_semana:
        semanas.append(semana)
        semana += timedelta(days=7)
    indice = {s: i for i, s in enumerate(semanas)}
    series = defaultdict(lambda: np.zeros(len(semanas)))
    precios = defaultdict(list)
    for fecha, sucursal, prenda, cantidad, precio in lineas:
        posicion = indice.get(_lunes(fecha))
        if posicion is None:
            continue
        series[(sucursal, prenda)][posicion] += cantidad
        precios[prenda].append(precio)
    precio_medio = {p: float(np.mean(v)) for p, v in precios.items()}
    return semanas, dict(series), precio_medio


def _variables(semana, historia, sucursal, prenda, precio):
    """Fila de variables para predecir una semana a partir de su historia."""
    numero = semana.isocalendar()[1]
    ultimas = historia[-REZAGOS:]
    return [
        math.sin(2 * math.pi * numero / 52),
        math.cos(2 * math.pi * numero / 52),
        semana.month,
        ultimas[-1], ultimas[-2], ultimas[-3], ultimas[-4],
        float(np.mean(ultimas)),
        float(np.mean(historia)),
        sucursal,
        prenda,
        precio,
    ]


def _tabla_demanda(semanas, series, precio_medio):
    """Filas (X, y, semana) para entrenar: cada semana con sus 4 semanas previas."""
    filas, objetivo, semana_fila = [], [], []
    for (sucursal, prenda), serie in series.items():
        for i in range(REZAGOS, len(semanas)):
            filas.append(_variables(semanas[i], list(serie[:i]), sucursal, prenda, precio_medio.get(prenda, 0)))
            objetivo.append(serie[i])
            semana_fila.append(semanas[i])
    return np.array(filas, dtype=float), np.array(objetivo, dtype=float), semana_fila


def _modelo_bosque():
    """RandomForest con los parámetros usados en todos los entrenamientos."""
    return RandomForestRegressor(**PARAMETROS_BOSQUE, random_state=SEMILLA, n_jobs=1)


def _entrenar_ventana(empresa, meses, hoy):
    """Entrena y evalúa la predicción de demanda con N meses de historial."""
    ultima_semana = _lunes(hoy) - timedelta(days=7)
    primera_semana = _lunes(_restar_meses(hoy, meses))
    lineas = _lineas_vendidas(empresa, primera_semana, ultima_semana + timedelta(days=6))
    semanas, series, precio_medio = _series_semanales(lineas, primera_semana, ultima_semana)
    X, y, semana_fila = _tabla_demanda(semanas, series, precio_medio)
    base = {
        "meses": meses, "semanas": len(semanas), "series": len(series),
        "desde": primera_semana.isoformat(), "hasta": (ultima_semana + timedelta(days=6)).isoformat(),
    }
    semanas_con_filas = sorted(set(semana_fila))
    if len(X) < MIN_FILAS_ENTRENAMIENTO or len(semanas_con_filas) < 4:
        return {"base": base, "aviso": "Pocos datos para entrenar con esta ventana.", "X": X, "y": y}
    # División temporal: el último 25% de las semanas es la prueba.
    corte = semanas_con_filas[-max(2, len(semanas_con_filas) // 4)]
    entrenamiento = np.array([s < corte for s in semana_fila])
    prueba = ~entrenamiento
    modelo = _modelo_bosque()
    modelo.fit(X[entrenamiento], y[entrenamiento])
    predicho = np.clip(modelo.predict(X[prueba]), 0, None)
    real = y[prueba]
    linea_base = X[prueba][:, VARIABLES_DEMANDA.index("media_4")]
    semanas_prueba = [s for s, es in zip(semana_fila, prueba) if es]
    total_real, total_predicho = defaultdict(float), defaultdict(float)
    for semana, valor_real, valor_predicho in zip(semanas_prueba, real, predicho):
        total_real[semana] += valor_real
        total_predicho[semana] += valor_predicho
    importancias = sorted(
        zip(VARIABLES_DEMANDA, modelo.feature_importances_), key=lambda par: par[1], reverse=True
    )
    metricas = {
        **base,
        "mae": round(float(mean_absolute_error(real, predicho)), 3),
        "rmse": round(float(math.sqrt(mean_squared_error(real, predicho))), 3),
        "r2": round(float(r2_score(real, predicho)), 3) if len(set(real)) > 1 else None,
        "mae_linea_base": round(float(mean_absolute_error(real, linea_base)), 3),
        "importancias": [
            {"variable": NOMBRES_VARIABLES[v], "importancia": round(float(i), 4)} for v, i in importancias
        ],
        "serie_prueba": [
            {"semana": s.isoformat(), "real": round(total_real[s], 2), "predicho": round(total_predicho[s], 2)}
            for s in sorted(total_real)
        ],
    }
    return {
        "metricas": metricas, "X": X, "y": y,
        "filas_entrenamiento": int(entrenamiento.sum()), "filas_prueba": int(prueba.sum()),
        "series": series, "semanas": semanas, "precio_medio": precio_medio,
    }


def _predecir_semanas(resultado, hoy):
    """Reentrena con todas las filas de la ventana y predice las próximas semanas."""
    modelo = _modelo_bosque()
    modelo.fit(resultado["X"], resultado["y"])
    primera = _lunes(hoy)
    predicciones = []
    for (sucursal, prenda), serie in resultado["series"].items():
        historia = list(serie)
        precio = resultado["precio_medio"].get(prenda, 0)
        for paso in range(SEMANAS_A_PREDECIR):
            semana = primera + timedelta(days=7 * paso)
            valor = max(0.0, float(modelo.predict([_variables(semana, historia, sucursal, prenda, precio)])[0]))
            historia.append(valor)
            predicciones.append((sucursal, prenda, semana, round(valor, 2)))
    return predicciones


def entrenar_demanda(empresa, usuario, corrida, hoy):
    """Entrena las tres ventanas, deja vigente la de menor MAE y guarda sus predicciones."""
    creados = []
    mejor = None
    for meses in VENTANAS_MESES:
        resultado = _entrenar_ventana(empresa, meses, hoy)
        metricas = resultado.get("metricas") or {**resultado["base"], "aviso": resultado["aviso"]}
        entrenamiento = EntrenamientoModelo.objects.create(
            id_empresa=empresa,
            tipo="DEMANDA",
            ventana_meses=meses,
            algoritmo="RandomForestRegressor",
            parametros={
                "corrida": corrida, **PARAMETROS_BOSQUE, "random_state": SEMILLA,
                "semanas_prediccion": SEMANAS_A_PREDECIR,
            },
            metricas=metricas,
            filas_entrenamiento=resultado.get("filas_entrenamiento", 0),
            filas_prueba=resultado.get("filas_prueba", 0),
            id_usuario=usuario,
        )
        creados.append(entrenamiento)
        if "metricas" in resultado and (mejor is None or metricas["mae"] < mejor[0].metricas["mae"]):
            mejor = (entrenamiento, resultado)
    if mejor is None:
        return creados, None
    vigente, resultado = mejor
    EntrenamientoModelo.objects.filter(id_empresa=empresa, tipo="DEMANDA", vigente=True).update(vigente=False)
    vigente.vigente = True
    vigente.save(update_fields=["vigente"])
    PrediccionDemanda.objects.bulk_create([
        PrediccionDemanda(
            id_entrenamiento=vigente, id_empresa=empresa, id_sucursal_id=sucursal,
            id_producto_id=prenda, semana_inicio=semana, unidades_predichas=valor,
        )
        for sucursal, prenda, semana, valor in _predecir_semanas(resultado, hoy)
    ])
    return creados, vigente


# --------------------------------------------------------------------------
# 2) Segmentación de clientes (no supervisado)
# --------------------------------------------------------------------------

def _nombrar_grupos(centroides):
    """Asigna VIP, en riesgo, leal y ocasional a cada grupo según su centroide RFM.

    VIP: mayor puntaje (frecuencia + monto - recencia). En riesgo: de los
    restantes, el que hace más días no compra. Leal: de los restantes, el de
    mayor frecuencia. Ocasional: el último.
    """
    rfm = np.array(centroides, dtype=float)
    desviacion = rfm.std(axis=0)
    desviacion[desviacion == 0] = 1
    z = (rfm - rfm.mean(axis=0)) / desviacion
    puntaje = z[:, 1] + z[:, 2] - z[:, 0]
    libres = list(range(len(rfm)))
    nombres = {}
    orden = [
        ("VIP", lambda i: puntaje[i]),
        ("RIESGO", lambda i: rfm[i, 0]),
        ("LEAL", lambda i: rfm[i, 1]),
        ("OCASIONAL", lambda i: -puntaje[i]),
    ]
    for segmento, criterio in orden:
        if not libres:
            break
        elegido = max(libres, key=criterio)
        nombres[elegido] = segmento
        libres.remove(elegido)
    return nombres


def entrenar_segmentacion(empresa, usuario, corrida, hoy):
    """K-means sobre RFM: silhouette k=2..6, 4 grupos y segmento de cada cliente."""
    desde = _restar_meses(hoy, VENTANA_SEGMENTACION)
    compras = _compras_por_cliente(empresa, desde, hoy)
    clientes = sorted(compras)
    rfm = []
    for cliente in clientes:
        fechas = [f for f, _ in compras[cliente]]
        rfm.append([
            (hoy - max(fechas)).days,
            len(fechas),
            sum(t for _, t in compras[cliente]),
        ])
    rfm = np.array(rfm, dtype=float)
    parametros = {"corrida": corrida, "n_init": 10, "random_state": SEMILLA, "variables": "RFM (log + estandarizado)"}
    base = {"clientes": len(clientes), "desde": desde.isoformat(), "hasta": hoy.isoformat()}
    if len(clientes) < 3:
        return EntrenamientoModelo.objects.create(
            id_empresa=empresa, tipo="SEGMENTACION", ventana_meses=VENTANA_SEGMENTACION,
            algoritmo="KMeans", parametros=parametros,
            metricas={**base, "aviso": "Se necesitan al menos 3 clientes con compras."},
            id_usuario=usuario,
        )
    # Escala logarítmica (los montos y frecuencias son muy desiguales) y estandarizado.
    X = StandardScaler().fit_transform(np.log1p(rfm))
    silhouette, inercia = {}, {}
    for k in range(2, min(K_MAXIMO, len(clientes) - 1) + 1):
        prueba = KMeans(n_clusters=k, n_init=10, random_state=SEMILLA).fit(X)
        inercia[str(k)] = round(float(prueba.inertia_), 3)
        if len(set(prueba.labels_)) > 1:
            silhouette[str(k)] = round(float(silhouette_score(X, prueba.labels_)), 3)
    k = min(SEGMENTOS_OBJETIVO, len(clientes) - 1)
    modelo = KMeans(n_clusters=k, n_init=10, random_state=SEMILLA).fit(X)
    centroides = [rfm[modelo.labels_ == g].mean(axis=0) for g in range(k)]
    nombres = _nombrar_grupos(centroides)
    resumen = []
    for grupo in range(k):
        miembros = rfm[modelo.labels_ == grupo]
        resumen.append({
            "segmento": nombres[grupo],
            "nombre": NOMBRE_SEGMENTO[nombres[grupo]],
            "clientes": int(len(miembros)),
            "recencia_media": round(float(miembros[:, 0].mean()), 1),
            "frecuencia_media": round(float(miembros[:, 1].mean()), 2),
            "monto_medio": round(float(miembros[:, 2].mean()), 2),
        })
    metricas = {
        **base,
        "k": k,
        "silhouette": silhouette,
        "inercia": inercia,
        "silhouette_k": silhouette.get(str(k)),
        "resumen": sorted(resumen, key=lambda r: list(NOMBRE_SEGMENTO).index(r["segmento"])),
    }
    if len(clientes) < 10:
        metricas["aviso"] = f"Solo {len(clientes)} clientes con compras: los grupos son orientativos."
    EntrenamientoModelo.objects.filter(id_empresa=empresa, tipo="SEGMENTACION", vigente=True).update(vigente=False)
    entrenamiento = EntrenamientoModelo.objects.create(
        id_empresa=empresa, tipo="SEGMENTACION", ventana_meses=VENTANA_SEGMENTACION,
        algoritmo="KMeans", parametros={**parametros, "n_clusters": k}, metricas=metricas,
        filas_entrenamiento=len(clientes), vigente=True, id_usuario=usuario,
    )
    SegmentoCliente.objects.bulk_create([
        SegmentoCliente(
            id_entrenamiento=entrenamiento, id_empresa=empresa, id_cliente_id=cliente,
            segmento=nombres[int(grupo)], recencia_dias=int(fila[0]), frecuencia=int(fila[1]),
            monto=round(fila[2], 2),
        )
        for cliente, grupo, fila in zip(clientes, modelo.labels_, rfm)
    ])
    return entrenamiento


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------

def entrenar_empresa(empresa, usuario=None):
    """Entrena demanda y segmentación de una empresa. Devuelve un resumen."""
    hoy = timezone.localdate()
    corrida = uuid.uuid4().hex[:12]
    with transaction.atomic():
        demanda, vigente = entrenar_demanda(empresa, usuario, corrida, hoy)
        segmentacion = entrenar_segmentacion(empresa, usuario, corrida, hoy)
    return {
        "empresa": empresa.nombre,
        "corrida": corrida,
        "demanda": [
            {
                "ventana_meses": e.ventana_meses,
                "mae": e.metricas.get("mae"),
                "rmse": e.metricas.get("rmse"),
                "r2": e.metricas.get("r2"),
                "mae_linea_base": e.metricas.get("mae_linea_base"),
                "vigente": vigente is not None and e.pk == vigente.pk,
                "aviso": e.metricas.get("aviso"),
            }
            for e in demanda
        ],
        "predicciones": vigente.predicciones.count() if vigente else 0,
        "segmentacion": {
            "clientes": segmentacion.metricas.get("clientes"),
            "k": segmentacion.metricas.get("k"),
            "silhouette": segmentacion.metricas.get("silhouette"),
            "resumen": segmentacion.metricas.get("resumen"),
            "aviso": segmentacion.metricas.get("aviso"),
        },
    }