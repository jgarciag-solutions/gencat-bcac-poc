"""Modelo y parámetros de generación de cada agente, leídos de config.json (sección "agentes_ia").

Cada agente ("normativa", "claridad", "fidelidad") hereda de "defecto" y puede sobrescribir cualquier clave.
Se relee en cada ejecución, así que un cambio en config.json se aplica sin reiniciar.
"""
import json
import logging
import os

from google.genai import types

log = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULTS = {
    "model": "gemini-flash-latest",
    "temperature": 0,
    "top_p": None,
    "seed": 42,
    "thinking_budget": None,  # None = dinámico; 0 = sin razonamiento; N = tope de tokens de razonamiento
    "max_output_tokens": 32768,
}


def agent_settings(agent_key: str) -> dict:
    """Parámetros efectivos del agente: DEFAULTS < agentes_ia.defecto < agentes_ia.<agent_key>."""
    settings = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            section = json.load(fh).get("agentes_ia", {})
        settings.update(section.get("defecto", {}))
        settings.update(section.get(agent_key, {}))
    except (OSError, ValueError, AttributeError) as exc:
        log.warning("No se pudo leer agentes_ia de config.json (%s); se usan los valores por defecto.", exc)
    return settings


def agent_model(agent_key: str) -> str:
    return agent_settings(agent_key)["model"]


def generation_config(agent_key: str) -> types.GenerateContentConfig:
    s = agent_settings(agent_key)
    kwargs = {"max_output_tokens": s["max_output_tokens"]}
    for key in ("temperature", "top_p", "seed"):
        if s.get(key) is not None:
            kwargs[key] = s[key]
    if s.get("thinking_budget") is not None:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=s["thinking_budget"])
    return types.GenerateContentConfig(**kwargs)


def embedding_model() -> str:
    """Modelo de embeddings (config.json, clave `embedding_model`), el mismo que usa la detección de duplicidades."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            return json.load(fh).get("embedding_model") or "gemini-embedding-001"
    except (OSError, ValueError, AttributeError):
        return "gemini-embedding-001"
