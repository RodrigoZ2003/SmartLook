# backend/apps/innovation/llm.py
#
# NUEVO (CU18/CU19/CU20): cliente de IA para el asistente.
# Groq es el proveedor principal y Gemini el respaldo. Si el principal falla
# (429, 5xx, tiempo agotado, clave inválida o respuesta vacía) se intenta con
# el otro. Claves y modelos vienen de settings (variables de entorno); las
# claves nunca se escriben en los logs.
# MODIFICADO (Fase 3): OpenAI como tercer respaldo (Groq -> Gemini -> OpenAI).
# Solo se usa si los dos primeros fallan y si OPENAI_API_KEY está configurada.
# Groq y OpenAI comparten el mismo formato de API (_llamar_compatible_openai).
#
# Uso:
#   from apps.innovation.llm import chat
#   r = chat([{"role": "system", "content": "..."},
#             {"role": "user", "content": "Hola"}])
#   r["texto"], r["llamadas"], r["proveedor"], r["modelo"]
#
# Herramientas (opcional): lista de {"name", "description", "parameters"} con
# "parameters" en JSON Schema. Si el modelo decide usar una, llega en
# r["llamadas"] como [{"nombre": ..., "argumentos": {...}}]. Con
# forzar_herramienta=True el modelo está obligado a elegir una herramienta
# (no puede responder de memoria).

import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
)

MENSAJE_NO_DISPONIBLE = (
    "El asistente no está disponible en este momento. "
    "Intenta de nuevo en unos minutos."
)


class ServicioIANoDisponible(Exception):
    """Ningún proveedor de IA pudo responder."""


def _limpiar(texto):
    """Cambia espacios especiales por espacios normales y recorta el texto."""
    if not texto:
        return ""
    for raro in ("\u202f", "\u00a0", "\u2009"):
        texto = texto.replace(raro, " ")
    return texto.strip()


def _llamar_compatible_openai(
    url, clave, modelo, mensajes, herramientas, temperatura, max_tokens, forzar
):
    """
    Llama a una API con formato OpenAI (Groq u OpenAI).
    Devuelve (texto, llamadas).
    """
    cuerpo = {
        "model": modelo,
        "messages": mensajes,
        "temperature": temperatura,
        "max_tokens": max_tokens,
    }
    # Solo los modelos gpt-oss de Groq aceptan reasoning_effort.
    if modelo.startswith("openai/gpt-oss"):
        cuerpo["reasoning_effort"] = "low"
    if herramientas:
        cuerpo["tools"] = [{"type": "function", "function": h} for h in herramientas]
        cuerpo["tool_choice"] = "required" if forzar else "auto"

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {clave}"},
        json=cuerpo,
        timeout=settings.AI_TIMEOUT_SEG,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]

    llamadas = []
    for tc in msg.get("tool_calls") or []:
        args = tc["function"].get("arguments") or "{}"
        llamadas.append(
            {"nombre": tc["function"]["name"], "argumentos": json.loads(args)}
        )
    return _limpiar(msg.get("content")), llamadas


def _llamar_groq(mensajes, herramientas, temperatura, max_tokens, forzar):
    """Llama a Groq (proveedor principal). Devuelve (texto, llamadas)."""
    return _llamar_compatible_openai(
        GROQ_URL,
        settings.GROQ_API_KEY,
        settings.GROQ_MODEL,
        mensajes,
        herramientas,
        temperatura,
        max_tokens,
        forzar,
    )


def _llamar_openai(mensajes, herramientas, temperatura, max_tokens, forzar):
    """Llama a OpenAI (tercer respaldo). Devuelve (texto, llamadas)."""
    return _llamar_compatible_openai(
        OPENAI_URL,
        settings.OPENAI_API_KEY,
        settings.OPENAI_MODEL,
        mensajes,
        herramientas,
        temperatura,
        max_tokens,
        forzar,
    )


def _llamar_gemini(mensajes, herramientas, temperatura, max_tokens, forzar):
    """Llama a Gemini (respaldo). Devuelve (texto, llamadas)."""
    sistema = [m["content"] for m in mensajes if m["role"] == "system"]
    contenidos = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in mensajes
        if m["role"] != "system"
    ]
    cuerpo = {
        "contents": contenidos,
        "generationConfig": {
            "temperature": temperatura,
            "maxOutputTokens": max_tokens,
        },
    }
    if sistema:
        cuerpo["systemInstruction"] = {"parts": [{"text": "\n\n".join(sistema)}]}
    # Con 2.5 se apaga el razonamiento: baja la respuesta de ~6 s a ~3 s.
    if "2.5" in settings.GEMINI_MODEL:
        cuerpo["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    if herramientas:
        cuerpo["tools"] = [{"functionDeclarations": herramientas}]
        if forzar:
            cuerpo["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}

    resp = requests.post(
        GEMINI_URL.format(modelo=settings.GEMINI_MODEL),
        headers={"x-goog-api-key": settings.GEMINI_API_KEY},
        json=cuerpo,
        timeout=settings.AI_TIMEOUT_SEG,
    )
    resp.raise_for_status()
    candidatos = resp.json().get("candidates") or []
    if not candidatos:
        raise ValueError("Gemini no devolvió candidatos")

    textos, llamadas = [], []
    for parte in candidatos[0].get("content", {}).get("parts", []):
        if "text" in parte:
            textos.append(parte["text"])
        elif "functionCall" in parte:
            fc = parte["functionCall"]
            llamadas.append(
                {"nombre": fc["name"], "argumentos": fc.get("args") or {}}
            )
    return _limpiar("".join(textos)), llamadas


def _proveedores():
    """Proveedores con clave configurada, en orden: principal y respaldos."""
    lista = []
    if settings.GROQ_API_KEY:
        lista.append(("groq", settings.GROQ_MODEL, _llamar_groq))
    if settings.GEMINI_API_KEY:
        lista.append(("gemini", settings.GEMINI_MODEL, _llamar_gemini))
    if settings.OPENAI_API_KEY:
        lista.append(("openai", settings.OPENAI_MODEL, _llamar_openai))
    return lista


def _detalle_error(exc):
    """Estado HTTP y mensaje breve del proveedor, para el registro (sin claves)."""
    respuesta = getattr(exc, "response", None)
    if respuesta is None:
        return "-", ""
    cuerpo = (respuesta.text or "")[:300].replace("\n", " ")
    return respuesta.status_code, cuerpo


def chat(
    mensajes,
    herramientas=None,
    temperatura=0.4,
    max_tokens=800,
    forzar_herramienta=False,
):
    """
    Envía la conversación al proveedor principal y, si falla, a los de respaldo
    (Groq -> Gemini -> OpenAI).
    mensajes: lista de {"role": "system"|"user"|"assistant", "content": str}.
    forzar_herramienta: obliga al modelo a elegir una de las herramientas.
    Devuelve {"texto", "llamadas", "proveedor", "modelo"} o lanza
    ServicioIANoDisponible si ninguno pudo responder.
    """
    ultimo_error = None
    for nombre, modelo, funcion in _proveedores():
        try:
            texto, llamadas = funcion(
                mensajes, herramientas, temperatura, max_tokens, forzar_herramienta
            )
        except Exception as exc:
            estado, detalle = _detalle_error(exc)
            logger.warning(
                "IA: %s falló (%s, estado %s) %s",
                nombre,
                type(exc).__name__,
                estado,
                detalle,
            )
            ultimo_error = exc
            continue
        if not texto and not llamadas:
            logger.warning("IA: %s devolvió una respuesta vacía", nombre)
            continue
        return {
            "texto": texto,
            "llamadas": llamadas,
            "proveedor": nombre,
            "modelo": modelo,
        }
    raise ServicioIANoDisponible(MENSAJE_NO_DISPONIBLE) from ultimo_error