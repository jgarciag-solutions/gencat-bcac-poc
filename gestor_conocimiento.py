"""Detección de duplicidades para el Gestor Conocimiento Base (SimHash + similitud vectorial)."""
import json
import logging
import os

import numpy as np
from simhash import Simhash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Interruptor único: ignora la comparación Padre-Hijo (Base y su Adaptado derivado).
# Los hermanos (Adaptados entre sí) siempre se comparan.
EXCLUDE_PARENT_CHILD_DUPLICITY = True  # Cambiar a False para desactivar este filtro en pruebas
PUBLISHED_STATUS = "Publicat"  # solo se compara contra documentos publicados
DEFAULTS = {"simhash_max_distance": 3, "vector_similarity_threshold": 0.85}
NO_DUPLICITY = ("No s'han detectat duplicitats ni coincidències rellevants amb altres "
                "documents de la base de coneixement.")

log = logging.getLogger(__name__)


def hamming_distance(hash1, hash2) -> int:
    """Distancia Hamming entre dos SimHash (enteros o cadenas hexadecimales)."""
    to_int = lambda h: int(h, 16) if isinstance(h, str) else int(h)
    return Simhash(to_int(hash1)).distance(Simhash(to_int(hash2)))


def cosine_similarity(vec1, vec2) -> float:
    """Similitud del coseno entre dos vectores (0.0 si alguno es nulo)."""
    a, b = np.asarray(vec1, dtype=float), np.asarray(vec2, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def compute_centroid(vectors_list):
    """Vector promedio de los vectores (chunks) de un documento."""
    return np.mean(vectors_list, axis=0)


def _sources(doc: dict) -> list:
    """Fuentes de un documento (`unidades_base_origen`) siempre como lista."""
    src = doc.get("unidades_base_origen") or []
    return src if isinstance(src, list) else [src]


def is_parent_child_relationship(doc_a: dict, doc_b: dict) -> bool:
    """True si un documento es el Base del que deriva el otro (Adaptado)."""
    if not EXCLUDE_PARENT_CHILD_DUPLICITY:
        return False
    a_type, b_type = doc_a.get("content_type"), doc_b.get("content_type")
    # CASO 1: A es Base y B es un Adaptado que lo cita como fuente.
    if a_type == "Base" and b_type == "Adaptat" and doc_a.get("id") in _sources(doc_b):
        return True
    # CASO 2: A es Adaptado y B es el Base que cita como fuente.
    if a_type == "Adaptat" and b_type == "Base" and doc_b.get("id") in _sources(doc_a):
        return True
    return False  # incluye Adaptado vs Adaptado (hermanos): se comparan con normalidad


def _load_config(config_path: str) -> dict:
    path = config_path if os.path.isabs(config_path) else os.path.join(BASE_DIR, config_path)
    config = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            config.update(json.load(fh))
    except (OSError, ValueError) as exc:
        log.warning("No se pudo leer %s (%s); se usan los umbrales por defecto.", path, exc)
    return config


def _load_centroid(path: str):
    """Centroide de un archivo de vectores, o None si falta, está vacío o es inválido."""
    try:
        with open(path, encoding="utf-8") as fh:
            vectors = json.load(fh)
        return compute_centroid(vectors) if vectors else None
    except (OSError, ValueError, TypeError):
        log.warning("Archivo de vectores no utilizable: %s", path)
        return None


def _label(doc) -> str:
    return f"«{doc.get('denominacio', '(sense denominació)')}» (ID: {doc['id']})"


def detect_document_duplicity(target_doc_id, documents_data, vectors_dir="vectores",
                              config_path="config.json") -> str:
    """Busca duplicidades del documento `target_doc_id` frente al resto. Devuelve un texto Markdown."""
    target = next((d for d in documents_data if d.get("id") == target_doc_id), None)
    if target is None:
        return "No s'ha trobat el document a analitzar."
    others = [d for d in documents_data
              if d.get("id") != target_doc_id and d.get("status") == PUBLISHED_STATUS]
    config = _load_config(config_path)
    max_distance = int(config["simhash_max_distance"])
    threshold = float(config["vector_similarity_threshold"])
    vdir = vectors_dir if os.path.isabs(vectors_dir) else os.path.join(BASE_DIR, vectors_dir)
    notes = []
    if not others:
        notes.append("No hi ha altres documents publicats amb els quals comparar.")

    # PASO 1: SimHash (coincidencia exacta o casi exacta).
    if target.get("simhash"):
        matches = []
        for d in others:
            # FILTRO PADRE-HIJO (paso 1, SimHash): se omite antes de cualquier comparación.
            if is_parent_child_relationship(target, d):
                continue
            if not d.get("simhash"):
                continue
            try:
                dist = hamming_distance(target["simhash"], d["simhash"])
            except ValueError:
                continue
            if dist <= max_distance:
                matches.append((dist, d))
        if matches:
            matches.sort(key=lambda m: m[0])
            lines = ["### Duplicitat detectada (SimHash)"]
            for n, (dist, d) in enumerate(matches, 1):
                lines += [f"**{n}. Coincidència exacta o gairebé exacta amb {_label(d)}**",
                          f"- **Distància de Hamming:** {dist} (llindar: {max_distance})",
                          f"- **Estat del document en conflicte:** {d.get('status', '—')}"]
            return "\n".join(lines)
    else:
        notes.append("El document no té empremta SimHash; s'ha omès la comparació exacta.")

    # PASO 2: similitud vectorial entre centroides.
    target_centroid = _load_centroid(os.path.join(vdir, f"{target_doc_id}_vectors.json"))
    if target_centroid is None:
        notes.append("El document no té fitxer de vectors utilitzable; "
                     "s'ha omès la comparació semàntica.")
    else:
        similar, skipped = [], 0
        for d in others:
            # FILTRO PADRE-HIJO (paso 2, similitud vectorial): se omite antes de cualquier comparación.
            if is_parent_child_relationship(target, d):
                continue
            vector_file = d.get("vector_file")
            if not vector_file:
                skipped += 1
                continue
            # solo el nombre del archivo: siempre se lee dentro de la carpeta de vectores
            path = os.path.join(vdir, os.path.basename(vector_file))
            centroid = _load_centroid(path)
            if centroid is None or centroid.shape != target_centroid.shape:
                skipped += 1
                continue
            sim = cosine_similarity(target_centroid, centroid)
            if sim > threshold:
                similar.append((sim, d))
        if skipped:
            notes.append(f"{skipped} document(s) no s'han comparat perquè no tenen vectors utilitzables.")
        if similar:
            similar.sort(key=lambda m: m[0], reverse=True)
            lines = ["### Contingut similar detectat (similitud semàntica)"]
            for n, (sim, d) in enumerate(similar, 1):
                lines += [f"**{n}. Contingut similar a {_label(d)}**",
                          f"- **Similitud:** {sim * 100:.0f}% (llindar: {threshold * 100:.0f}%)",
                          f"- **Estat del document en conflicte:** {d.get('status', '—')}"]
            return "\n".join(lines + [""] + [f"> {n}" for n in notes] if notes else lines)

    if target.get("simhash") is None and target_centroid is None:
        return ("No s'ha pogut fer la detecció de duplicitats: el document no té SimHash "
                "ni vectors generats (revisa l'API key de Gemini i torna a pujar-lo).")
    return NO_DUPLICITY + ("\n\n" + "\n".join(f"> {n}" for n in notes) if notes else "")
