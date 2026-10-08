"""Preprocesamiento de documentos: normalización, SimHash, chunking y embeddings."""
import json
import logging
import os
import re

import pdfplumber
from simhash import Simhash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
VECTORS_FOLDER = os.path.join(BASE_DIR, "vectores")
EMBED_BATCH_SIZE = 100  # máximo de textos por petición a la API

DEFAULT_CONFIG = {"chunk_size": 1000, "chunk_overlap": 100, "embedding_model": "gemini-embedding-001"}

log = logging.getLogger(__name__)


def load_config() -> dict:
    """Lee config.json; si falta o es inválido, usa los valores por defecto."""
    config = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            config.update(json.load(fh))
    except (OSError, ValueError) as exc:
        log.warning("No se pudo leer config.json (%s); se usan los valores por defecto.", exc)
    return config


def extract_pdf_text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def normalize_text(text: str) -> str:
    """Minúsculas, sin saltos de línea y con los espacios múltiples colapsados."""
    return re.sub(r"\s+", " ", text.lower().replace("\r", " ").replace("\n", " ")).strip()


def compute_simhash(text: str) -> str:
    """Huella SimHash (64 bits) del texto normalizado, como cadena hexadecimal de 16 dígitos."""
    return format(Simhash(normalize_text(text)).value, "016x")


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Divide el texto en trozos de `chunk_size` caracteres con `chunk_overlap` de solape."""
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Configuración de chunking inválida: se requiere 0 <= chunk_overlap < chunk_size.")
    step = chunk_size - chunk_overlap
    chunks = []
    for start in range(0, len(text), step):
        chunks.append(text[start:start + chunk_size])
        if start + chunk_size >= len(text):
            break
    return chunks


def generate_embeddings(chunks: list[str], model: str) -> list[list[float]]:
    """Vectores de embedding (uno por chunk) con la API de Google Gemini."""
    from google import genai  # SDK oficial vigente (dependencia de google-adk)
    from google.genai import types

    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key or "tu_api_key" in api_key:
        raise RuntimeError("Falta configurar GEMINI_API_KEY (o GOOGLE_API_KEY) en el archivo .env.")
    client = genai.Client(api_key=api_key)
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        response = client.models.embed_content(
            model=model, contents=chunks[i:i + EMBED_BATCH_SIZE],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"))
        vectors.extend(list(e.values) for e in response.embeddings)
    return vectors


def process_document(path: str, doc_id: str) -> tuple:
    """Calcula SimHash y vectores de un PDF. Nunca lanza: devuelve (simhash, vector_file).

    - `simhash` es None si no es PDF o no tiene texto extraíble.
    - `vector_file` es la ruta relativa "vectores/{doc_id}_vectors.json", o None si no se
      pudieron generar los vectores (sin API key, cuota agotada, etc.). El documento se
      guarda igualmente.
    """
    if not path.lower().endswith(".pdf"):
        return None, None
    try:
        text = normalize_text(extract_pdf_text(path))
        if not text:
            log.warning("El PDF %s no tiene texto extraíble; no se calculan huella ni vectores.", path)
            return None, None
        simhash = compute_simhash(text)
    except Exception:
        log.exception("No se pudo leer el PDF %s para el preprocesamiento.", path)
        return None, None

    try:
        config = load_config()
        chunks = chunk_text(text, int(config["chunk_size"]), int(config["chunk_overlap"]))
        vectors = generate_embeddings(chunks, config["embedding_model"])
        os.makedirs(VECTORS_FOLDER, exist_ok=True)
        relative = f"vectores/{doc_id}_vectors.json"
        tmp = os.path.join(BASE_DIR, relative + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(vectors, fh)  # solo la colección de vectores
        os.replace(tmp, os.path.join(BASE_DIR, relative))
        return simhash, relative
    except Exception:
        log.exception("No se pudieron generar los vectores de %s; se guarda sin vector_file.", path)
        return simhash, None
