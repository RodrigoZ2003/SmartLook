# backend/apps/innovation/exportadores.py
#
# Exporta un resultado de reporte a PDF, Excel (xlsx) o HTML con formato de
# reporte convencional (título, contexto, indicadores, tabla y notas).
#
# MODIFICADO (Fase 3 - CU13): si el resultado trae "grafico", se incluye el
# gráfico en los tres formatos: en el PDF con los gráficos de ReportLab, en el
# Excel como gráfico nativo en la hoja "Gráfico" (con sus datos) y en el HTML
# como SVG dibujado en el servidor (sin librerías ni recursos externos).
# Tipos: bar (barras), barh (barras horizontales), line (líneas) y doughnut.

import html
import io
import math
import re
import unicodedata

from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.doughnut import Doughnut
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

COLOR_OSCURO = "1A1A2E"
COLOR_ACENTO = "0F3460"
COLOR_ZEBRA = "F4F5F8"
MAX_COLUMNAS_VERTICAL = 5
KPIS_POR_FILA = 4
# NUEVO (CU13): colores de las series (los mismos que usa la web).
PALETA = (
    "0F3460", "E94560", "16A085", "F39C12", "8E44AD",
    "2980B9", "D35400", "27AE60", "C0392B", "7F8C8D",
)
MAX_ETIQUETA = 22

TIPOS_MIME = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html; charset=utf-8",
}
ALIAS_FORMATO = {"excel": "xlsx", "xls": "xlsx", "xlsx": "xlsx", "pdf": "pdf", "html": "html"}

class FormatoInvalido(Exception):
    """El formato pedido no es pdf, xlsx (excel) ni html."""

# ---------------------------------------------------------------- utilidades
def formatear(valor, tipo):
    """Texto de un valor según su tipo: dinero 'Bs 1,234.50', número, texto."""
    if valor is None:
        return ""
    if tipo == "dinero":
        return f"Bs {float(valor):,.2f}"
    if tipo == "numero":
        numero = float(valor)
        return str(int(numero)) if numero.is_integer() else f"{numero:.2f}"
    return str(valor)

def _nombre_archivo(titulo, generado, extension):
    """Nombre de archivo sin tildes ni espacios, con la fecha de generación."""
    limpio = unicodedata.normalize("NFD", str(titulo or "reporte"))
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn").lower()
    base = re.sub(r"[^a-z0-9]+", "_", limpio).strip("_")[:50] or "reporte"
    m = re.match(r"(\d\d)/(\d\d)/(\d{4}) (\d\d):(\d\d)", str(generado or ""))
    sello = f"{m.group(3)}{m.group(2)}{m.group(1)}_{m.group(4)}{m.group(5)}" if m else "reporte"
    return f"{base}_{sello}.{extension}"

def _lineas_cabecera(resultado, meta):
    """Textos de contexto que van bajo el título: periodo, pregunta y fecha."""
    lineas = []
    if resultado.get("subtitulo"):
        lineas.append(resultado["subtitulo"])
    if meta.get("pregunta"):
        lineas.append(f"Pregunta: {meta['pregunta']}")
    if meta.get("generado"):
        lineas.append(f"Generado: {meta['generado']}")
    return lineas

# ---------------------------------------------------------------- gráficos
def _color(indice):
    """Color hexadecimal (sin #) de la serie o porción número 'indice'."""
    return PALETA[indice % len(PALETA)]

def _tiene_grafico(resultado):
    """True si el resultado trae un gráfico con al menos un valor distinto de cero."""
    g = resultado.get("grafico")
    if not g or not g.get("etiquetas") or not g.get("series"):
        return False
    return any(v for s in g["series"] for v in s["datos"])

def _corta(texto, largo=MAX_ETIQUETA):
    """Recorta una etiqueta larga con puntos suspensivos."""
    texto = str(texto)
    return texto if len(texto) <= largo else texto[: largo - 1] + "…"

def _valor_eje(valor, formato):
    """Texto corto para el eje o las etiquetas del gráfico."""
    if formato == "dinero":
        return f"Bs {valor:,.0f}"
    return f"{valor:,.0f}" if float(valor).is_integer() else f"{valor:,.1f}"

def _limites(g):
    """(mínimo, máximo) del eje de valores, incluyendo siempre el cero."""
    valores = [v for s in g["series"] for v in s["datos"]]
    minimo, maximo = min(0, min(valores)), max(0, max(valores))
    if maximo == minimo:
        maximo = minimo + 1
    return minimo, maximo

# ---- SVG (HTML)
def _svg_leyenda(series, x, y):
    """Leyenda horizontal (cuadro de color + nombre) para varias series."""
    e = html.escape
    partes, posicion = [], x
    for i, s in enumerate(series):
        partes.append(f'<rect x="{posicion}" y="{y - 9}" width="10" height="10" rx="2" fill="#{_color(i)}"/>')
        partes.append(f'<text x="{posicion + 14}" y="{y}" font-size="11" fill="#444">{e(_corta(s["nombre"], 28))}</text>')
        posicion += 30 + 7 * min(len(s["nombre"]), 28)
    return partes

def _svg_vertical(g, ancho, alto):
    """Barras verticales agrupadas o líneas, con ejes y cuadrícula."""
    e = html.escape
    etiquetas, series = g["etiquetas"], g["series"]
    varias = len(series) > 1
    girar = len(etiquetas) > 6
    izq, der, arriba, abajo = 78, 20, 34 if varias else 16, 110 if girar else 50
    w, h = ancho - izq - der, alto - arriba - abajo
    minimo, maximo = _limites(g)
    escala = h / (maximo - minimo)
    y_de = lambda v: arriba + (maximo - v) * escala
    partes = []
    for i in range(6):
        valor = minimo + (maximo - minimo) * i / 5
        y = y_de(valor)
        partes.append(f'<line x1="{izq}" y1="{y:.1f}" x2="{izq + w}" y2="{y:.1f}" stroke="#e5e6ec"/>')
        partes.append(
            f'<text x="{izq - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="#6b6459">'
            f"{e(_valor_eje(valor, g['formato']))}</text>"
        )
    n = len(etiquetas)
    grupo = w / n
    for j, etiqueta in enumerate(etiquetas):
        cx = izq + grupo * (j + 0.5)
        if girar:
            partes.append(
                f'<text x="{cx:.1f}" y="{arriba + h + 14}" font-size="10" fill="#444" '
                f'text-anchor="end" transform="rotate(-35 {cx:.1f} {arriba + h + 14})">{e(_corta(etiqueta))}</text>'
            )
        else:
            partes.append(
                f'<text x="{cx:.1f}" y="{arriba + h + 18}" font-size="11" fill="#444" '
                f'text-anchor="middle">{e(_corta(etiqueta, 16))}</text>'
            )
    if g["tipo"] == "line":
        for i, s in enumerate(series):
            puntos = [(izq + grupo * (j + 0.5), y_de(v)) for j, v in enumerate(s["datos"])]
            trazo = " ".join(f"{x:.1f},{y:.1f}" for x, y in puntos)
            partes.append(f'<polyline points="{trazo}" fill="none" stroke="#{_color(i)}" stroke-width="2.5"/>')
            for x, y in puntos:
                partes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#{_color(i)}"/>')
    else:
        ancho_barra = grupo * 0.7 / len(series)
        cero = y_de(0)
        for i, s in enumerate(series):
            for j, v in enumerate(s["datos"]):
                x = izq + grupo * j + grupo * 0.15 + ancho_barra * i
                y = min(cero, y_de(v))
                alto_barra = abs(y_de(v) - cero)
                partes.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{ancho_barra:.1f}" height="{alto_barra:.1f}" '
                    f'rx="3" fill="#{_color(i)}"><title>{e(str(etiquetas[j]))}: {e(_valor_eje(v, g["formato"]))}</title></rect>'
                )
    partes.append(f'<line x1="{izq}" y1="{arriba + h}" x2="{izq + w}" y2="{arriba + h}" stroke="#999"/>')
    if varias:
        partes.extend(_svg_leyenda(series, izq, 16))
    return partes

def _svg_horizontal(g, ancho):
    """Barras horizontales (rankings), de la primera etiqueta arriba a la última abajo."""
    e = html.escape
    etiquetas, datos = g["etiquetas"], g["series"][0]["datos"]
    izq, der, fila = 220, 90, 28
    alto = 20 + fila * len(etiquetas)
    _, maximo = _limites(g)
    w = ancho - izq - der
    partes = []
    for j, (etiqueta, v) in enumerate(zip(etiquetas, datos)):
        y = 10 + fila * j
        largo = max(0, v) / maximo * w
        partes.append(
            f'<text x="{izq - 10}" y="{y + 15}" font-size="11" text-anchor="end" fill="#444">{e(_corta(etiqueta, 32))}</text>'
        )
        partes.append(f'<rect x="{izq}" y="{y + 3}" width="{largo:.1f}" height="17" rx="3" fill="#{_color(0)}"/>')
        partes.append(
            f'<text x="{izq + largo + 6:.1f}" y="{y + 15}" font-size="11" fill="#1e1a16">{e(_valor_eje(v, g["formato"]))}</text>'
        )
    return partes, alto

def _svg_dona(g, ancho, alto):
    """Gráfico de dona con su leyenda y porcentajes."""
    e = html.escape
    etiquetas, datos = g["etiquetas"], [max(0, v) for v in g["series"][0]["datos"]]
    total = sum(datos) or 1
    cx, cy, r, r_int = 150, alto / 2, 115, 68
    partes, angulo = [], -math.pi / 2
    for i, v in enumerate(datos):
        if not v:
            continue
        fin = angulo + 2 * math.pi * v / total
        if v == total:
            fin -= 0.0001
        grande = 1 if fin - angulo > math.pi else 0
        p = [
            (cx + r * math.cos(angulo), cy + r * math.sin(angulo)),
            (cx + r * math.cos(fin), cy + r * math.sin(fin)),
            (cx + r_int * math.cos(fin), cy + r_int * math.sin(fin)),
            (cx + r_int * math.cos(angulo), cy + r_int * math.sin(angulo)),
        ]
        partes.append(
            f'<path d="M{p[0][0]:.1f},{p[0][1]:.1f} A{r},{r} 0 {grande} 1 {p[1][0]:.1f},{p[1][1]:.1f} '
            f'L{p[2][0]:.1f},{p[2][1]:.1f} A{r_int},{r_int} 0 {grande} 0 {p[3][0]:.1f},{p[3][1]:.1f} Z" '
            f'fill="#{_color(i)}"/>'
        )
        angulo = fin
    partes.append(
        f'<text x="{cx}" y="{cy + 5}" font-size="14" font-weight="bold" text-anchor="middle" '
        f'fill="#1a1a2e">{e(_valor_eje(sum(datos), g["formato"]))}</text>'
    )
    for i, (etiqueta, v) in enumerate(zip(etiquetas, datos)):
        y = 30 + 24 * i
        if y > alto - 10:
            break
        partes.append(f'<rect x="300" y="{y - 10}" width="12" height="12" rx="2" fill="#{_color(i)}"/>')
        partes.append(
            f'<text x="320" y="{y}" font-size="12" fill="#444">{e(_corta(etiqueta, 34))} · '
            f"{e(_valor_eje(v, g['formato']))} ({v * 100 / total:.1f}%)</text>"
        )
    return partes

def _svg_grafico(g, ancho=860):
    """SVG autocontenido del gráfico de un resultado."""
    e = html.escape
    alto = 360
    if g["tipo"] == "barh":
        partes, alto = _svg_horizontal(g, ancho)
    elif g["tipo"] == "doughnut":
        alto = max(280, 40 + 24 * len(g["etiquetas"]))
        partes = _svg_dona(g, ancho, alto)
    else:
        partes = _svg_vertical(g, ancho, alto)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ancho} {alto}" width="100%" '
        f'role="img" aria-label="{e(g["titulo"])}" font-family="Arial, Helvetica, sans-serif">'
        + "".join(partes)
        + "</svg>"
    )

# ---- ReportLab (PDF)
def _dibujo_pdf(g, ancho):
    """Drawing de ReportLab con el gráfico del resultado."""
    etiquetas = [_corta(x) for x in g["etiquetas"]]
    series = g["series"]
    minimo, maximo = _limites(g)
    formato_eje = lambda v: _valor_eje(v, g["formato"])  # noqa: E731
    titulo = String(0, 0, g["titulo"], fontName="Helvetica-Bold", fontSize=10,
                    fillColor=colors.HexColor(f"#{COLOR_OSCURO}"))

    if g["tipo"] == "doughnut":
        alto = max(6 * cm, (len(etiquetas) * 0.55 + 1.2) * cm)
        dibujo = Drawing(ancho, alto)
        dona = Doughnut()
        lado = min(alto - 1.2 * cm, 5.5 * cm)
        dona.x, dona.y, dona.width, dona.height = 0.3 * cm, (alto - lado) / 2 - 0.3 * cm, lado, lado
        dona.data = [max(0, v) for v in series[0]["datos"]]
        dona.labels = None
        dona.innerRadiusFraction = 0.55
        for i in range(len(dona.data)):
            dona.slices[i].fillColor = colors.HexColor(f"#{_color(i)}")
            dona.slices[i].strokeColor = colors.white
        total = sum(dona.data) or 1
        leyenda = Legend()
        leyenda.x, leyenda.y = lado + 1.2 * cm, alto - 1.2 * cm
        leyenda.fontSize, leyenda.alignment, leyenda.deltay = 8, "right", 12
        leyenda.fontName = "Helvetica"
        leyenda.colorNamePairs = [
            (colors.HexColor(f"#{_color(i)}"), f"{etiqueta} · {formato_eje(v)} ({v * 100 / total:.1f}%)")
            for i, (etiqueta, v) in enumerate(zip(etiquetas, dona.data))
        ]
        dibujo.add(dona)
        dibujo.add(leyenda)
    elif g["tipo"] == "barh":
        alto = max(5 * cm, (len(etiquetas) * 0.6 + 1.4) * cm)
        dibujo = Drawing(ancho, alto)
        barras = HorizontalBarChart()
        barras.x, barras.y = 4.6 * cm, 0.6 * cm
        barras.width, barras.height = ancho - 5.4 * cm, alto - 1.6 * cm
        barras.data = [tuple(reversed(series[0]["datos"]))]
        barras.categoryAxis.categoryNames = list(reversed(etiquetas))
        barras.categoryAxis.labels.fontSize = 7.5
        barras.categoryAxis.labels.fontName = "Helvetica"
        barras.valueAxis.labels.fontName = "Helvetica"
        barras.valueAxis.valueMin, barras.valueAxis.valueMax = minimo, maximo
        barras.valueAxis.labels.fontSize = 7
        barras.valueAxis.labelTextFormat = formato_eje
        barras.bars[0].fillColor = colors.HexColor(f"#{_color(0)}")
        barras.bars.strokeColor = None
        dibujo.add(barras)
    else:
        alto = 7.5 * cm
        dibujo = Drawing(ancho, alto)
        girar = len(etiquetas) > 6
        if g["tipo"] == "line":
            grafico = HorizontalLineChart()
            grafico.joinedLines = 1
        else:
            grafico = VerticalBarChart()
            grafico.groupSpacing = 6
            grafico.bars.strokeColor = None
        grafico.x, grafico.y = 1.9 * cm, 2.0 * cm if girar else 1.0 * cm
        grafico.width = ancho - 2.4 * cm
        grafico.height = alto - grafico.y - (1.4 * cm if len(series) > 1 else 0.9 * cm)
        grafico.data = [tuple(s["datos"]) for s in series]
        grafico.categoryAxis.categoryNames = etiquetas
        grafico.categoryAxis.labels.fontSize = 7
        grafico.categoryAxis.labels.fontName = "Helvetica"
        grafico.valueAxis.labels.fontName = "Helvetica"
        if girar:
            grafico.categoryAxis.labels.angle = 35
            grafico.categoryAxis.labels.boxAnchor = "ne"
        grafico.valueAxis.valueMin, grafico.valueAxis.valueMax = minimo, maximo
        grafico.valueAxis.labels.fontSize = 7
        grafico.valueAxis.labelTextFormat = formato_eje
        for i in range(len(series)):
            color = colors.HexColor(f"#{_color(i)}")
            if g["tipo"] == "line":
                grafico.lines[i].strokeColor = color
                grafico.lines[i].strokeWidth = 2
                grafico.lines[i].symbol = makeMarker("FilledCircle", size=4, fillColor=color)
            else:
                grafico.bars[i].fillColor = color
        dibujo.add(grafico)
        if len(series) > 1:
            leyenda = Legend()
            leyenda.x, leyenda.y = 1.9 * cm, alto - 0.9 * cm
            leyenda.fontSize, leyenda.columnMaximum, leyenda.dx = 7.5, 1, 8
            leyenda.fontName = "Helvetica"
            leyenda.alignment = "right"
            leyenda.colorNamePairs = [
                (colors.HexColor(f"#{_color(i)}"), _corta(s["nombre"], 30)) for i, s in enumerate(series)
            ]
            dibujo.add(leyenda)
    titulo.x, titulo.y = 0, alto - 0.35 * cm
    dibujo.add(titulo)
    return dibujo

# ---- openpyxl (Excel)
def _hoja_grafico(wb, g):
    """Hoja 'Gráfico' con los datos del gráfico y un gráfico nativo de Excel."""
    ws = wb.create_sheet("Gráfico")
    series, etiquetas = g["series"], g["etiquetas"]
    relleno = PatternFill("solid", fgColor=COLOR_OSCURO)
    ws.append([g["titulo"]])
    ws["A1"].font = Font(bold=True, size=13, color=COLOR_OSCURO)
    ws.append(["Categoría"] + [s["nombre"] for s in series])
    for celda in ws[2]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno
    for j, etiqueta in enumerate(etiquetas):
        ws.append([etiqueta] + [s["datos"][j] for s in series])
        for i in range(len(series)):
            celda = ws.cell(row=ws.max_row, column=2 + i)
            celda.number_format = _formato_excel(g["formato"], celda.value)
    ws.column_dimensions["A"].width = min(max(len(str(x)) for x in etiquetas) + 3, 45)
    for i in range(len(series)):
        ws.column_dimensions[get_column_letter(2 + i)].width = 16

    ultima = 2 + len(etiquetas)
    datos = Reference(ws, min_col=2, min_row=2, max_col=1 + len(series), max_row=ultima)
    categorias = Reference(ws, min_col=1, min_row=3, max_row=ultima)
    if g["tipo"] == "doughnut":
        grafico = DoughnutChart()
        grafico.holeSize = 55
        grafico.add_data(Reference(ws, min_col=2, min_row=2, max_row=ultima), titles_from_data=True)
        grafico.set_categories(categorias)
        serie = grafico.series[0]
        for j in range(len(etiquetas)):
            punto = DataPoint(idx=j)
            punto.graphicalProperties.solidFill = _color(j)
            serie.dPt.append(punto)
    else:
        grafico = LineChart() if g["tipo"] == "line" else BarChart()
        if g["tipo"] in ("bar", "barh"):
            grafico.type = "bar" if g["tipo"] == "barh" else "col"
            grafico.grouping = "clustered"
        grafico.add_data(datos, titles_from_data=True)
        grafico.set_categories(categorias)
        for i, serie in enumerate(grafico.series):
            if g["tipo"] == "line":
                serie.graphicalProperties.line.solidFill = _color(i)
                serie.graphicalProperties.line.width = 28000
                serie.smooth = False
            else:
                serie.graphicalProperties.solidFill = _color(i)
                serie.graphicalProperties.line.solidFill = _color(i)
        grafico.x_axis.delete = False
        grafico.y_axis.delete = False
        grafico.y_axis.numFmt = _formato_excel(g["formato"], 1)
        if g["tipo"] == "barh":
            grafico.x_axis.scaling.orientation = "maxMin"
        if len(series) == 1:
            grafico.legend = None
    grafico.title = g["titulo"]
    grafico.height = 9.5 if g["tipo"] != "barh" else max(9.5, 0.7 * len(etiquetas) + 3)
    grafico.width = 20
    ws.add_chart(grafico, f"{get_column_letter(len(series) + 3)}2")

# ---------------------------------------------------------------- HTML
def exportar_html(resultado, meta):
    """Documento HTML autocontenido (estilos incluidos, sin recursos externos)."""
    e = html.escape
    columnas = resultado["columnas"]
    partes = [
        "<!DOCTYPE html>",
        '<html lang="es">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(resultado['titulo'])} - SmartLook</title>",
        "<style>",
        "body{font-family:Arial,Helvetica,sans-serif;margin:32px;color:#1e1a16;background:#fff}",
        f"h1{{margin:0 0 4px;color:#{COLOR_OSCURO}}}",
        ".marca{color:#6b6459;font-size:13px;margin-bottom:16px}",
        ".ctx{color:#555;font-size:14px;margin:2px 0}",
        ".kpis{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}",
        ".kpi{border:1px solid #dcdde4;border-radius:10px;padding:10px 18px;min-width:150px}",
        ".kpi span{display:block;font-size:12px;color:#6b6459}",
        f".kpi strong{{display:block;font-size:20px;color:#{COLOR_ACENTO};margin-top:2px}}",
        "table{border-collapse:collapse;width:100%;margin-top:8px;font-size:14px}",
        f"th{{background:#{COLOR_OSCURO};color:#fff;text-align:left;padding:9px 10px}}",
        "td{padding:8px 10px;border-bottom:1px solid #e5e6ec}",
        f"tbody tr:nth-child(even) td{{background:#{COLOR_ZEBRA}}}",
        ".num{text-align:right}",
        ".grafico{border:1px solid #dcdde4;border-radius:12px;padding:16px;margin:8px 0 20px;max-width:900px}",
        f".grafico h3{{margin:0 0 10px;font-size:15px;color:#{COLOR_OSCURO}}}",
        ".nota{margin-top:14px;padding:10px 14px;background:#fff8e6;border-left:4px solid #ff9800;font-size:14px}",
        ".vacio{margin-top:16px;color:#6b6459}",
        ".pie{margin-top:28px;font-size:12px;color:#8a8fa0}",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{e(resultado['titulo'])}</h1>",
        '<div class="marca">SmartLook · Reporte de gestión</div>',
    ]
    for linea in _lineas_cabecera(resultado, meta):
        partes.append(f'<p class="ctx">{e(linea)}</p>')

    if resultado["kpis"]:
        partes.append('<div class="kpis">')
        for k in resultado["kpis"]:
            partes.append(
                f'<div class="kpi"><span>{e(k["etiqueta"])}</span>'
                f'<strong>{e(formatear(k["valor"], k["tipo"]))}</strong></div>'
            )
        partes.append("</div>")

    # NUEVO (CU13): gráfico del reporte como SVG.
    if _tiene_grafico(resultado):
        partes.append('<div class="grafico">')
        partes.append(f'<h3>{e(resultado["grafico"]["titulo"])}</h3>')
        partes.append(_svg_grafico(resultado["grafico"]))
        partes.append("</div>")

    if resultado["filas"]:
        partes.append("<table><thead><tr>")
        for c in columnas:
            clase = ' class="num"' if c["tipo"] in ("numero", "dinero") else ""
            partes.append(f"<th{clase}>{e(c['nombre'])}</th>")
        partes.append("</tr></thead><tbody>")
        for fila in resultado["filas"]:
            partes.append("<tr>")
            for c, valor in zip(columnas, fila):
                clase = ' class="num"' if c["tipo"] in ("numero", "dinero") else ""
                partes.append(f"<td{clase}>{e(formatear(valor, c['tipo']))}</td>")
            partes.append("</tr>")
        partes.append("</tbody></table>")
    else:
        partes.append('<p class="vacio">Sin filas para mostrar.</p>')

    for nota in resultado["notas"]:
        partes.append(f'<div class="nota">{e(nota)}</div>')
    partes.append('<p class="pie">Generado con el asistente de gestión de SmartLook.</p>')
    partes.extend(["</body>", "</html>"])
    return "\n".join(partes).encode("utf-8")

# ---------------------------------------------------------------- Excel
def exportar_excel(resultado, meta):
    """Libro de Excel con cabecera, indicadores y la tabla con formato numérico."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"
    negrita = Font(bold=True)
    relleno = PatternFill("solid", fgColor=COLOR_OSCURO)
    borde = Border(bottom=Side(style="thin", color="DDDDDD"))

    ws.append([resultado["titulo"]])
    ws["A1"].font = Font(bold=True, size=15, color=COLOR_OSCURO)
    for linea in _lineas_cabecera(resultado, meta):
        ws.append([linea])
    ws.append([])

    if resultado["kpis"]:
        ws.append(["Indicador", "Valor"])
        fila_cab = ws.max_row
        for celda in ws[fila_cab][:2]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = relleno
        for k in resultado["kpis"]:
            ws.append([k["etiqueta"], k["valor"]])
            celda = ws.cell(row=ws.max_row, column=2)
            celda.number_format = _formato_excel(k["tipo"], k["valor"])
            celda.alignment = Alignment(horizontal="right")
        ws.append([])

    columnas = resultado["columnas"]
    ws.append([c["nombre"] for c in columnas])
    fila_tabla = ws.max_row
    for celda in ws[fila_tabla]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for fila in resultado["filas"]:
        ws.append(list(fila))
        for indice, c in enumerate(columnas, start=1):
            celda = ws.cell(row=ws.max_row, column=indice)
            celda.border = borde
            if c["tipo"] in ("numero", "dinero"):
                celda.number_format = _formato_excel(c["tipo"], celda.value)
                celda.alignment = Alignment(horizontal="right")
    if resultado["filas"]:
        ws.freeze_panes = ws.cell(row=fila_tabla + 1, column=1)
        ws.auto_filter.ref = (
            f"A{fila_tabla}:{get_column_letter(len(columnas))}{ws.max_row}"
        )
    else:
        ws.append(["Sin filas para mostrar."])

    for nota in resultado["notas"]:
        ws.append([])
        ws.append([f"Nota: {nota}"])
        ws.cell(row=ws.max_row, column=1).font = Font(italic=True, color="B26A00")

    # Ancho de columnas según el contenido de la tabla (sin contar el título).
    for indice in range(1, max(len(columnas), 2) + 1):
        letra = get_column_letter(indice)
        ancho = 10
        for fila in ws.iter_rows(min_row=fila_tabla, min_col=indice, max_col=indice):
            for celda in fila:
                if celda.value is not None:
                    ancho = max(ancho, min(len(str(celda.value)) + 3, 45))
        ws.column_dimensions[letra].width = ancho
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 10, 28)

    # NUEVO (CU13): hoja con el gráfico nativo de Excel.
    if _tiene_grafico(resultado):
        _hoja_grafico(wb, resultado["grafico"])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

def _formato_excel(tipo, valor):
    """Formato numérico de Excel según el tipo del dato."""
    if tipo == "dinero":
        return '"Bs" #,##0.00'
    if isinstance(valor, float) and not float(valor).is_integer():
        return "0.00"
    return "0"

# ---------------------------------------------------------------- PDF
def exportar_pdf(resultado, meta):
    """PDF A4 (horizontal si la tabla es ancha) con indicadores y tabla paginada."""
    columnas = resultado["columnas"]
    horizontal = len(columnas) > MAX_COLUMNAS_VERTICAL
    pagina = landscape(A4) if horizontal else A4
    ancho_util = pagina[0] - 3 * cm

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("Titulo", parent=estilos["Title"], alignment=0,
                            textColor=colors.HexColor(f"#{COLOR_OSCURO}"), fontSize=20, spaceAfter=2)
    marca = ParagraphStyle("Marca", parent=estilos["Normal"], fontSize=9,
                           textColor=colors.HexColor("#6B6459"), spaceAfter=8)
    contexto = ParagraphStyle("Contexto", parent=estilos["Normal"], fontSize=10,
                              textColor=colors.HexColor("#444444"), leading=13)
    celda = ParagraphStyle("Celda", parent=estilos["Normal"], fontSize=8.5, leading=10.5)
    celda_num = ParagraphStyle("CeldaNum", parent=celda, alignment=2)
    cabecera = ParagraphStyle("Cabecera", parent=celda, textColor=colors.white,
                              fontName="Helvetica-Bold")
    cabecera_num = ParagraphStyle("CabeceraNum", parent=cabecera, alignment=2)
    nota_estilo = ParagraphStyle("Nota", parent=estilos["Normal"], fontSize=9,
                                 textColor=colors.HexColor("#8A5A00"), leading=12, spaceBefore=6)
    esc = html.escape

    elementos = [
        Paragraph(esc(resultado["titulo"]), titulo),
        Paragraph("SmartLook · Reporte de gestión", marca),
    ]
    for linea in _lineas_cabecera(resultado, meta):
        elementos.append(Paragraph(esc(linea), contexto))
    elementos.append(Spacer(1, 0.4 * cm))

    if resultado["kpis"]:
        kpi_estilo_e = ParagraphStyle("KpiE", parent=celda, textColor=colors.HexColor("#6B6459"), fontSize=8)
        kpi_estilo_v = ParagraphStyle("KpiV", parent=celda, fontSize=13, leading=16,
                                      fontName="Helvetica-Bold",
                                      textColor=colors.HexColor(f"#{COLOR_ACENTO}"))
        bloques = []
        for k in resultado["kpis"]:
            bloques.append([
                Paragraph(esc(k["etiqueta"]), kpi_estilo_e),
                Paragraph(esc(formatear(k["valor"], k["tipo"])), kpi_estilo_v),
            ])
        filas_kpi = [bloques[i:i + KPIS_POR_FILA] for i in range(0, len(bloques), KPIS_POR_FILA)]
        for fila in filas_kpi:
            while len(fila) < KPIS_POR_FILA:
                fila.append("")
        tabla_kpi = Table(filas_kpi, colWidths=[ancho_util / KPIS_POR_FILA] * KPIS_POR_FILA)
        tabla_kpi.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DCDDE4")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DCDDE4")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elementos.extend([tabla_kpi, Spacer(1, 0.5 * cm)])

    # NUEVO (CU13): gráfico del reporte antes de la tabla.
    if _tiene_grafico(resultado):
        elementos.extend([_dibujo_pdf(resultado["grafico"], ancho_util), Spacer(1, 0.5 * cm)])

    if resultado["filas"]:
        numericas = [c["tipo"] in ("numero", "dinero") for c in columnas]
        datos = [[
            Paragraph(esc(c["nombre"]), cabecera_num if num else cabecera)
            for c, num in zip(columnas, numericas)
        ]]
        pesos = [max(6, min(len(c["nombre"]), 30)) for c in columnas]
        for fila in resultado["filas"]:
            renglon = []
            for indice, (c, valor) in enumerate(zip(columnas, fila)):
                texto = formatear(valor, c["tipo"])
                pesos[indice] = max(pesos[indice], min(len(texto), 34))
                renglon.append(Paragraph(esc(texto), celda_num if numericas[indice] else celda))
            datos.append(renglon)
        total = float(sum(pesos))
        anchos = [ancho_util * p / total for p in pesos]
        tabla = Table(datos, colWidths=anchos, repeatRows=1)
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{COLOR_OSCURO}")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(f"#{COLOR_ZEBRA}")]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E6EC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla)
    else:
        elementos.append(Paragraph("Sin filas para mostrar.", contexto))

    for nota in resultado["notas"]:
        elementos.append(Paragraph(f"Nota: {esc(nota)}", nota_estilo))

    generado = meta.get("generado", "")

    def pie(lienzo, documento):
        lienzo.saveState()
        lienzo.setFont("Helvetica", 8)
        lienzo.setFillColor(colors.HexColor("#8A8FA0"))
        lienzo.drawString(1.5 * cm, 0.9 * cm, f"SmartLook · {generado}")
        lienzo.drawRightString(pagina[0] - 1.5 * cm, 0.9 * cm, f"Página {documento.page}")
        lienzo.restoreState()

    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=pagina, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.6 * cm, title=resultado["titulo"], author="SmartLook",
    )
    documento.build(elementos, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()

# ---------------------------------------------------------------- entrada
def exportar(formato, resultado, meta):
    """Genera el archivo pedido. Devuelve (contenido, tipo_mime, nombre_archivo)."""
    clave = ALIAS_FORMATO.get(str(formato or "").strip().lower())
    if clave is None:
        raise FormatoInvalido(f"Formato no válido: {formato}. Usa pdf, xlsx o html.")
    meta = meta or {}
    generadores = {"pdf": exportar_pdf, "xlsx": exportar_excel, "html": exportar_html}
    contenido = generadores[clave](resultado, meta)
    nombre = _nombre_archivo(resultado.get("titulo"), meta.get("generado"), clave)
    return contenido, TIPOS_MIME[clave], nombre