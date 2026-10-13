"""Genera copias de un PDF con las incoherencias de la IA resaltadas y explicadas al margen."""
import logging
import re

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24.3
except ImportError:  # versiones antiguas
    import fitz

log = logging.getLogger(__name__)

HIGHLIGHT_COLOR = (1.0, 0.65, 0.65)   # resaltado: rojo suave
BOX_FILL = (1.0, 0.96, 0.80)          # recuadro: amarillo suave
BOX_TEXT = (0.1, 0.1, 0.1)            # texto oscuro
FONT, FONT_SIZE, LINE_HEIGHT = "helv", 8.0, 1.25
BOX_WIDTH = 200.0                     # ancho del recuadro (pt)
GUTTER = 12.0                         # separación con el texto de la página
PAD = 4.0                             # holgura interior para que el texto no se recorte

_LATIN1_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "«": '"', "»": '"',
                             "–": "-", "—": "-", "…": "...", "ŀ": "l·", "Ŀ": "L·", "\u00a0": " "})


def _normalize(text) -> str:
    """Colapsa espacios y saltos de línea y quita comillas/puntos suspensivos de los extremos."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text.strip("\"'«»“”‘’").removeprefix("[...]").removesuffix("[...]").removeprefix("...").removesuffix("...").strip()


def _latin1(text: str) -> str:
    """El tipo de letra base del PDF solo cubre Latin-1: se sustituye lo que no encaje."""
    return str(text).translate(_LATIN1_MAP).encode("latin-1", "replace").decode("latin-1")


def _wrapped_height(text: str, width: float) -> float:
    """Alto necesario para el texto ajustado al ancho dado (palabra a palabra)."""
    lines = 0
    for paragraph in text.split("\n"):
        line = ""
        lines += 1
        for word in paragraph.split(" "):
            candidate = f"{line} {word}".strip()
            if line and fitz.get_text_length(candidate, FONT, FONT_SIZE) > width:
                lines += 1
                line = word
            else:
                line = candidate
    return lines * FONT_SIZE * LINE_HEIGHT + 2 * PAD


def _widen_margin(page) -> float:
    """Amplía la página por la derecha para alojar los recuadros sin tapar texto.

    Devuelve el x donde empieza el margen. En páginas rotadas no se amplía: los
    recuadros se colocan dentro del borde derecho de la página.
    """
    if page.rotation == 0:
        base = page.rect.width
        media, crop = page.mediabox, page.cropbox
        media.x1 += BOX_WIDTH + 2 * GUTTER
        crop.x1 += BOX_WIDTH + 2 * GUTTER
        page.set_mediabox(media)
        page.set_cropbox(crop)
        return base + GUTTER
    return page.rect.width - BOX_WIDTH - GUTTER


def annotate_pdf_with_ai_results(original_pdf_path: str, output_pdf_path: str,
                                 incoherencias_list: list) -> tuple:
    """Resalta cada `frase_analizada` y coloca su explicación completa en un recuadro al margen.

    Devuelve (guardado, incoherencias_con_pagina): `guardado` es True si se escribió el PDF
    con al menos una anotación; cada hallazgo de la lista lleva `page_number` (1-indexado,
    None si no se localizó). Las frases no encontradas se registran como advertencia.
    """
    enriched = [dict(item, page_number=None) if isinstance(item, dict) else item
                for item in incoherencias_list or []]
    try:
        doc = fitz.open(original_pdf_path)
    except Exception:
        log.exception("No se pudo abrir el PDF %s", original_pdf_path)
        return False, enriched
    try:
        margin_x = {}   # página -> x del margen (se amplía una sola vez por página)
        next_y = {}     # página -> siguiente y libre en el margen
        found = 0
        for item in enriched:
            if not isinstance(item, dict):
                continue
            phrase = _normalize(item.get("frase_analizada"))
            if not phrase:
                continue
            infringed = item.get("texto_infrinjido") or item.get("normativa_infringida") or ""
            explanation = item.get("explicacion") or ""
            text = _latin1(f"FUENTES / NORMATIVA:\n{infringed}\n\nEXPLICACIÓN:\n{explanation}")

            for page in doc:
                quads = page.search_for(phrase, quads=True)
                if not quads:
                    continue
                highlight = page.add_highlight_annot(quads)
                highlight.set_colors(stroke=HIGHLIGHT_COLOR)
                highlight.set_info(title="Auditoría IA")
                highlight.update()
                if item["page_number"] is not None:
                    continue  # recuadro solo en la primera aparición
                item["page_number"] = page.number + 1

                if page.number not in margin_x:
                    margin_x[page.number] = _widen_margin(page)
                top = max(quads[0].rect.y0, next_y.get(page.number, 0))
                height = min(_wrapped_height(text, BOX_WIDTH - 2 * PAD), page.rect.height - 20)
                top = min(top, page.rect.height - height - 10)  # sin salirse por abajo
                rect = fitz.Rect(margin_x[page.number], top, margin_x[page.number] + BOX_WIDTH, top + height)
                box = page.add_freetext_annot(
                    rect, text, fontsize=FONT_SIZE, fontname=FONT, text_color=BOX_TEXT,
                    fill_color=BOX_FILL, border_width=1,  # el borde toma el color del texto
                    callout=(fitz.Point(quads[0].rect.x1, quads[0].rect.y0 + 4),
                             fitz.Point(rect.x0, rect.y0 + 10)))
                next_y[page.number] = rect.y1 + 6

            if item["page_number"] is not None:
                found += 1
            else:
                log.warning("Frase no encontrada de forma exacta en %s: %.120s", original_pdf_path, phrase)

        if not found:
            return False, enriched
        doc.save(output_pdf_path, garbage=3, deflate=True)
        return True, enriched
    except Exception:
        log.exception("Error al anotar el PDF %s", original_pdf_path)
        return False, enriched
    finally:
        doc.close()

