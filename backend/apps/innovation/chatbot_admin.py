# backend/apps/innovation/chatbot_admin.py
#
# Asistente de gestión (CU13 - reportes con IA). La IA interpreta la pregunta
# y elige UNA consulta controlada de consultas_admin con sus parámetros; el
# backend la valida y la ejecuta dentro de la empresa del usuario. La IA
# nunca toca la base de datos.
#
# MODIFICADO (Fase 3 - CU13):
# - Exportación desde el chat: "descárgamelo en PDF / Excel / HTML" exporta el
#   último reporte (o el que se acaba de generar en el mismo mensaje). Un
#   pedido que es solo de descarga se reconoce sin llamar a la IA, para que
#   funcione siempre, incluso si el proveedor de IA no responde.
# - Pedidos ambiguos, incompletos o no soportados: la IA pide una aclaración
#   en lugar de inventar una consulta.
# - Conocimiento actualizado del negocio: ventas netas, devoluciones, cambios
#   de prenda, ventas sin conexión en conflicto y anuladas, reservas con
#   anticipo, empresas y sucursales, precios actuales.
# - Menos tokens por mensaje (límite por minuto del proveedor gratuito): el
#   parámetro 'empresa' solo se envía al SUPER_ADMIN, el historial es más
#   corto, se limita la respuesta máxima (el proveedor la suma al cupo) y la
#   segunda llamada (redactar la respuesta) lleva solo el resumen.

import copy
import json
import logging
import re

from django.utils import timezone

from . import consultas_admin as ca
from .chatbot import MensajeInvalido
from .exportadores import ALIAS_FORMATO
from .herramientas_cliente import _norm
from .llm import chat
from .models import ReporteAsistente

logger = logging.getLogger(__name__)

MAX_CARACTERES_MENSAJE = 500
MAX_CONSULTAS_POR_MENSAJE = 2
INTERCAMBIOS_PREVIOS = 2
CARACTERES_HISTORIAL = 300
TEMPERATURA_CONSULTA = 0.1
MAX_TOKENS_CONSULTA = 400
MAX_TOKENS_RESPUESTA = 450
MAX_PALABRAS_SOLO_EXPORTAR = 8
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MENSAJE_SIN_DATOS = (
    "No pude consultar esa información en este momento. "
    "Intenta de nuevo o reformula la pregunta."
)
MENSAJE_SIN_RESPUESTA = "No pude preparar una respuesta. ¿Puedes reformular tu pregunta?"
MENSAJE_ACLARACION = (
    "¿Puedes darme más detalle? Por ejemplo: «ventas de este mes por sucursal», "
    "«las 10 prendas más vendidas» o «productos con menor existencia»."
)
MENSAJE_SIN_REPORTE = (
    "Todavía no tengo un reporte tuyo para descargar. Pídeme primero uno, por "
    "ejemplo «ventas de este mes por sucursal», y después dime en qué formato lo quieres."
)
MENSAJE_FORMATO = "¿En qué formato lo quieres: PDF, Excel o HTML?"
NOMBRE_FORMATO = {"pdf": "PDF", "xlsx": "Excel", "html": "HTML"}

# Palabras que indican que el usuario quiere descargar (no consultar).
_VERBO_EXPORTAR = re.compile(
    r"\b(descarg\w*|export\w*|baj\w*|pas\w*|convier\w*|convert\w*|guard\w*|"
    r"mand\w*|dame|damelo|quiero|genera\w*|imprim\w*|sac\w*)\b"
)
_FORMATO_EN_TEXTO = re.compile(r"\b(pdf|excel|xlsx|xls|html)\b")
# Palabras que indican que, además, pide datos nuevos (lo resuelve la IA).
_PIDE_DATOS = re.compile(
    r"\b(venta\w*|vend\w*|stock|inventario|existencia\w*|reserva\w*|devol\w*|cambio\w*|"
    r"categor\w*|producto\w*|prenda\w*|sucursal\w*|entrega\w*|envio\w*|precio\w*|"
    r"empresa\w*|conflict\w*|anulad\w*|semana\w*|mes|meses|ano|anio|hoy|ayer|resumen|"
    r"vestidor|compar\w*|ingreso\w*)\b"
)

SIN_CONSULTA = {
    "name": "sin_consulta",
    "description": (
        "Úsala SOLO para saludos, agradecimientos, despedidas o temas que no tienen "
        "nada que ver con el negocio. NUNCA la uses si preguntan por ventas, stock, "
        "reservas, devoluciones, cambios, entregas, precios, empresas o sucursales."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "motivo": {
                "type": "string",
                "description": "saludo, agradecimiento, despedida u otro.",
            },
        },
    },
}
EXPORTAR = {
    "name": "exportar_reporte",
    "description": (
        "Descarga un reporte en PDF, Excel o HTML. Úsala cuando el usuario pide "
        "descargar, exportar, bajar o pasar un reporte a un formato ('descárgamelo en "
        "PDF', 'pásalo a Excel'). Si en el mismo mensaje pide datos nuevos Y la "
        "descarga, llama la consulta de los datos y TAMBIÉN esta herramienta. Si solo "
        "pide la descarga, se exporta su último reporte."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "formato": {
                "type": "string",
                "enum": ["pdf", "excel", "html"],
                "description": "pdf, excel o html.",
            },
        },
        "required": ["formato"],
    },
}
ACLARAR = {
    "name": "pedir_aclaracion",
    "description": (
        "Úsala cuando NO puedes elegir una consulta: la solicitud es ambigua (no se sabe "
        "qué reporte quiere), incompleta (falta un dato imprescindible) o no soportada "
        "(pide modificar o borrar datos, datos personales de clientes, predicciones o "
        "algo que ningún reporte ofrece). No la uses si basta con los valores por "
        "defecto de una consulta (por ejemplo, si no dice el periodo)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "motivo": {
                "type": "string",
                "enum": ["ambigua", "incompleta", "no_soportada"],
                "description": "Por qué no se puede responder todavía.",
            },
            "pregunta": {
                "type": "string",
                "description": (
                    "Mensaje corto para el usuario: la pregunta que aclara lo que falta o, "
                    "si no está soportado, por qué y qué reportes sí puede pedir."
                ),
            },
        },
        "required": ["motivo", "pregunta"],
    },
}
HERRAMIENTAS = ca.HERRAMIENTAS_ADMIN + [EXPORTAR, ACLARAR, SIN_CONSULTA]

def _sin_parametro_empresa(herramienta):
    """Copia de la herramienta sin el parámetro 'empresa' (solo es del SUPER_ADMIN)."""
    copia = copy.deepcopy(herramienta)
    copia["parameters"]["properties"].pop("empresa", None)
    return copia

HERRAMIENTAS_EMPRESA = [_sin_parametro_empresa(h) for h in ca.HERRAMIENTAS_ADMIN] + [
    EXPORTAR,
    ACLARAR,
    SIN_CONSULTA,
]

CONOCIMIENTO = (
    "Conceptos del negocio (úsalos para elegir la consulta y explicar resultados):\n"
    "- Ventas netas = ventas en punto de venta (POS) no anuladas + pedidos web/app "
    "pagados (pagada, enviada o entregada) - reembolsos de devoluciones completadas.\n"
    "- Ventas sin conexión: el POS registra la venta sin internet y la sincroniza "
    "después. Si llega con precio distinto o sin stock queda EN CONFLICTO hasta que el "
    "personal la confirma o devuelve el efectivo; en ese caso queda ANULADA con nota de "
    "devolución y no cuenta como venta. Consulta: ventas_anuladas_y_conflictos.\n"
    "- Devoluciones: de un pedido con delivery entregado o de una venta POS; se "
    "reembolsa a la tarjeta o en efectivo. Cambios de prenda: otra talla o color de la "
    "misma prenda, sin reembolso. Consulta: devoluciones_y_cambios.\n"
    "- Reservas de prendas: se pagan con anticipo o pago total; la reserva hecha sin "
    "conexión tiene 3 horas para pagarse; vence una semana después de la fecha "
    "reservada; si vence o se cancela se retiene el 10%. Estados: pendiente de pago, "
    "confirmada, completada (se retiró), cancelada y vencida. Consulta: consultar_reservas.\n"
    "- Comparar sucursales en varios meses: comparativo_sucursales. Ventas por semana o "
    "gráfico semanal: consultar_ventas con agrupar_por='semana'. Categorías con más "
    "ingresos: categorias_mas_ingresos. Menor existencia: menor_existencia.\n"
    "- Precios actuales: precios_actuales. Empresas o sucursales nuevas: "
    "empresas_y_sucursales.\n"
    "- Todos los reportes se muestran en tabla y gráfico y se pueden descargar en PDF, "
    "Excel o HTML (herramienta exportar_reporte).\n"
)

def _instrucciones(usuario):
    """Instrucciones del asistente con la fecha de hoy, la plataforma y sus empresas.

    SaaS: el SUPER_ADMIN conoce todas las empresas con sus sucursales; el
    personal de una empresa solo conoce la suya.
    """
    hoy = timezone.localdate()
    return (
        "Eres el asistente de gestión de SmartLook, una plataforma de tiendas de ropa "
        "en Bolivia. Ayudas al personal a obtener reportes de ventas, inventario, "
        "reservas, devoluciones, cambios, entregas, precios, empresas y sucursales. "
        "Hablas en español, claro y breve.\n"
        f"Hoy es {DIAS[hoy.weekday()]} {hoy:%d/%m/%Y}. Los montos están en bolivianos (Bs).\n"
        "Reglas:\n"
        "- Para cualquier dato del negocio usa SIEMPRE una consulta. Nunca inventes "
        "cifras.\n"
        "- Pasa solo lo que el usuario dijo. Si no menciona un periodo, no lo pases: "
        "cada consulta ya tiene uno por defecto. Las fechas relativas ('septiembre', "
        "'la semana pasada', 'del 1 al 15') conviértelas a desde/hasta con formato "
        "AAAA-MM-DD; un mes sin año es del año actual (o del anterior si aún no llegó).\n"
        "- Si pide descargar o exportar, usa exportar_reporte (junto con la consulta si "
        "también pide datos nuevos).\n"
        "- Si la solicitud es ambigua, incompleta o no soportada, usa pedir_aclaracion.\n"
        "- No pidas ni menciones datos personales de clientes.\n"
        "- Si preguntan por datos a los que el usuario no tiene acceso (otra empresa), "
        "usa pedir_aclaracion con motivo no_soportada.\n"
        + CONOCIMIENTO
        + ca.contexto_plataforma(usuario)
    )

def _instrucciones_respuesta(resumen=None):
    """Instrucciones para redactar la respuesta final, sin llamar herramientas.

    Se usan en la segunda llamada al modelo. Van cortas a propósito (menos
    tokens): el resumen ya trae la empresa, el periodo y las notas. No incluyen
    la regla de 'usa siempre una consulta': con ella el modelo intentaba llamar
    otra función y el proveedor rechazaba la petición.
    """
    base = (
        "Eres el asistente de gestión de SmartLook, una plataforma de tiendas de ropa "
        "en Bolivia. Hablas en español, claro y breve. No llames a ninguna función ni "
        "herramienta: responde solo con texto plano, sin tablas, sin títulos y sin "
        "markdown (nada de ** ni #). Los montos están en bolivianos (Bs). No pidas ni "
        "menciones datos personales de clientes.\n"
    )
    if resumen is None:
        return base + (
            "Responde al mensaje del usuario. Si pregunta por datos del negocio, "
            "pídele que lo formule como un reporte concreto (ventas, inventario, "
            "reservas, devoluciones...)."
        )
    return base + (
        "Con estos resultados reales calculados por el sistema, responde en 2 o 3 "
        "frases con las cifras clave. Usa los nombres de los indicadores tal como "
        "vienen e indica de qué empresa son (está en el subtítulo). No menciones "
        "consultas, herramientas ni JSON. Si hay 'notas', menciónalas. La tabla y el "
        "gráfico se muestran aparte y se pueden descargar en PDF, Excel y HTML:\n"
        + json.dumps(resumen, ensure_ascii=False)
    )

def _historial(usuario):
    """Últimas preguntas del usuario con su respuesta, de la más antigua a la nueva."""
    reportes = list(
        ReporteAsistente.objects.filter(id_usuario=usuario).order_by(
            "-fecha_creacion", "-id_reporte"
        )[:INTERCAMBIOS_PREVIOS]
    )
    mensajes = []
    for r in reversed(reportes):
        respuesta = (r.resultado or {}).get("respuesta") or r.titulo
        mensajes.append({"role": "user", "content": r.pregunta})
        mensajes.append({"role": "assistant", "content": respuesta[:CARACTERES_HISTORIAL]})
    return mensajes

def _formato(valor):
    """Formato normalizado (pdf, xlsx o html) o None si no es válido."""
    return ALIAS_FORMATO.get(_norm(valor))

def _formato_en_mensaje(mensaje):
    """Formato pedido en el texto si el usuario quiere descargar, o None."""
    texto = _norm(mensaje)
    encontrado = _FORMATO_EN_TEXTO.search(texto)
    if not encontrado:
        return None
    palabras = re.findall(r"[a-z0-9]+", texto)
    if _VERBO_EXPORTAR.search(texto) or len(palabras) <= 3:
        return _formato(encontrado.group(1))
    return None

def _es_solo_exportar(mensaje):
    """True si el mensaje solo pide descargar (sin pedir datos nuevos)."""
    texto = _norm(mensaje)
    palabras = re.findall(r"[a-z0-9]+", texto)
    return (
        _formato_en_mensaje(mensaje) is not None
        and len(palabras) <= MAX_PALABRAS_SOLO_EXPORTAR
        and not _PIDE_DATOS.search(texto)
    )

def _ultimo_reporte(usuario):
    """Último reporte guardado del usuario, o None."""
    return ReporteAsistente.objects.filter(id_usuario=usuario).order_by(
        "-fecha_creacion", "-id_reporte"
    ).first()

def _preparar_exportacion(formato, reporte):
    """(texto, exportar) para descargar un reporte en el formato pedido."""
    if formato is None:
        return MENSAJE_FORMATO, None
    if reporte is None:
        return MENSAJE_SIN_REPORTE, None
    exportar = {
        "id_reporte": reporte.id_reporte,
        "formato": formato,
        "titulo": reporte.titulo,
    }
    texto = f"Listo, te descargo «{reporte.titulo}» en {NOMBRE_FORMATO[formato]}."
    return texto, exportar

def _respuesta(texto, proveedor, modelo, resultados=None, exportar=None, aclaracion=None):
    """Respuesta uniforme del asistente."""
    return {
        "respuesta": texto,
        "resultados": resultados or [],
        "exportar": exportar,
        "aclaracion": aclaracion,
        "proveedor": proveedor,
        "modelo": modelo,
    }

def _ejecutar_consultas(llamadas, usuario):
    """Ejecuta las consultas pedidas por el modelo (sin repetir ni pasarse).

    Devuelve (resultados, errores): resultados es una lista de
    (llamada, resultado); errores, los nombres de las consultas que fallaron.
    """
    resultados, errores, vistas = [], [], set()
    for llamada in llamadas:
        if len(resultados) + len(errores) >= MAX_CONSULTAS_POR_MENSAJE:
            break
        clave = (llamada["nombre"], json.dumps(llamada["argumentos"], sort_keys=True))
        if clave in vistas:
            continue
        vistas.add(clave)
        try:
            resultado = ca.ejecutar(llamada["nombre"], llamada["argumentos"], usuario)
        except Exception:
            logger.exception("Falló la consulta de gestión %s", llamada["nombre"])
            errores.append(llamada["nombre"])
            continue
        resultados.append((llamada, resultado))
    return resultados, errores

def _guardar(usuario, mensaje, llamada, resultado, respuesta):
    """Guarda el resultado como reporte y devuelve el reporte creado."""
    return ReporteAsistente.objects.create(
        id_usuario=usuario,
        pregunta=mensaje,
        consulta=llamada["nombre"],
        filtros=llamada["argumentos"],
        titulo=resultado["titulo"][:200],
        resultado=dict(resultado, respuesta=respuesta),
    )

def responder_gestion(usuario, mensaje):
    """Responde una pregunta del personal y guarda los reportes generados.

    Devuelve {"respuesta", "resultados", "exportar", "aclaracion", "proveedor",
    "modelo"}. Cada elemento de "resultados" es {"id_reporte", "consulta",
    "resultado"}. "exportar" es {"id_reporte", "formato", "titulo"} cuando el
    usuario pidió descargar (la web descarga ese reporte en ese formato) y
    "aclaracion" es el motivo cuando la IA pidió más detalle.
    """
    mensaje = (mensaje or "").strip()
    if not mensaje:
        raise MensajeInvalido("Escribe tu pregunta.")
    if len(mensaje) > MAX_CARACTERES_MENSAJE:
        raise MensajeInvalido(
            f"La pregunta no puede superar los {MAX_CARACTERES_MENSAJE} caracteres."
        )

    # Pedido solo de descarga: se resuelve sin la IA (siempre funciona).
    if _es_solo_exportar(mensaje):
        texto, exportar = _preparar_exportacion(
            _formato_en_mensaje(mensaje), _ultimo_reporte(usuario)
        )
        return _respuesta(texto, "sistema", None, exportar=exportar)

    conversacion = (
        [{"role": "system", "content": _instrucciones(usuario)}]
        + _historial(usuario)
        + [{"role": "user", "content": mensaje}]
    )
    herramientas = HERRAMIENTAS if ca._es_super_admin(usuario) else HERRAMIENTAS_EMPRESA
    r = chat(
        conversacion,
        herramientas=herramientas,
        temperatura=TEMPERATURA_CONSULTA,
        max_tokens=MAX_TOKENS_CONSULTA,
        forzar_herramienta=True,
    )
    llamadas = r["llamadas"] or []
    consultas = [ll for ll in llamadas if ll["nombre"] in ca.CONSULTAS]
    exportes = [ll for ll in llamadas if ll["nombre"] == EXPORTAR["name"]]
    aclaracion = next((ll for ll in llamadas if ll["nombre"] == ACLARAR["name"]), None)

    # Respaldo: si el texto pide una descarga y la IA no la eligió, se agrega.
    formato_texto = _formato_en_mensaje(mensaje)
    if not exportes and formato_texto:
        exportes = [{"nombre": EXPORTAR["name"], "argumentos": {"formato": formato_texto}}]

    if aclaracion and not consultas and not exportes:
        argumentos = aclaracion["argumentos"] if isinstance(aclaracion["argumentos"], dict) else {}
        texto = (argumentos.get("pregunta") or "").strip() or MENSAJE_ACLARACION
        return _respuesta(
            texto, r["proveedor"], r["modelo"], aclaracion=argumentos.get("motivo") or "ambigua"
        )

    resultados, errores = _ejecutar_consultas(consultas, usuario)
    if consultas and not resultados and errores:
        return _respuesta(MENSAJE_SIN_DATOS, r["proveedor"], r["modelo"])

    texto = None
    if resultados:
        resumen = [
            {"consulta": ll["nombre"], **ca.resumen_para_modelo(res)}
            for ll, res in resultados
        ]
        r = chat(
            [
                {"role": "system", "content": _instrucciones_respuesta(resumen)},
                {"role": "user", "content": mensaje},
            ],
            max_tokens=MAX_TOKENS_RESPUESTA,
        )
        texto = r["texto"] or MENSAJE_SIN_RESPUESTA
    elif not exportes:
        r = chat(
            [
                {"role": "system", "content": _instrucciones_respuesta()},
                {"role": "user", "content": mensaje},
            ],
            max_tokens=MAX_TOKENS_RESPUESTA,
        )
        texto = r["texto"] or MENSAJE_SIN_RESPUESTA

    guardados, reportes = [], []
    for llamada, resultado in resultados:
        reporte = _guardar(usuario, mensaje, llamada, resultado, texto)
        reportes.append(reporte)
        guardados.append(
            {
                "id_reporte": reporte.id_reporte,
                "consulta": llamada["nombre"],
                "resultado": resultado,
            }
        )

    exportar = None
    if exportes:
        argumentos = exportes[0]["argumentos"] if isinstance(exportes[0]["argumentos"], dict) else {}
        formato = _formato(argumentos.get("formato")) or formato_texto
        reporte = reportes[0] if reportes else _ultimo_reporte(usuario)
        texto_exportar, exportar = _preparar_exportacion(formato, reporte)
        texto = f"{texto}\n\n{texto_exportar}" if texto else texto_exportar

    return _respuesta(texto, r["proveedor"], r["modelo"], guardados, exportar)