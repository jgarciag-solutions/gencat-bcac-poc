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
MARGIN = 8.0                          # separación mínima con los bordes de la página
BOX_GAP = 6.0                         # separación vertical entre recuadros
MIN_FONT_SIZE = 6.0                   # tamaño mínimo al que se reduce el texto de un recuadro muy largo
BADGE_SIZE = 13.0                     # insignia numérica junto al texto resaltado
BADGE_FILL = (0.8, 0.1, 0.1)          # rojo oscuro, a juego con el resaltado

_LATIN1_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "«": '"', "»": '"',
                             "–": "-", "—": "-", "…": "...", "ŀ": "l·", "Ŀ": "L·", "\u00a0": " "})


def _normalize(text) -> str:
    """Colapsa espacios y saltos de línea y quita comillas/puntos suspensivos de los extremos."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text.strip("\"'«»“”‘’").removeprefix("[...]").removesuffix("[...]").removeprefix("...").removesuffix("...").strip()


def _latin1(text: str) -> str:
    """El tipo de letra base del PDF solo cubre Latin-1: se sustituye lo que no encaje."""
    return str(text).translate(_LATIN1_MAP).encode("latin-1", "replace").decode("latin-1")


def _wrapped_height(text: str, width: float, fontsize: float = FONT_SIZE) -> float:
    """Alto necesario para el texto ajustado al ancho dado (palabra a palabra)."""
    lines = 0
    for paragraph in text.split("\n"):
        line = ""
        lines += 1
        for word in paragraph.split(" "):
            candidate = f"{line} {word}".strip()
            if line and fitz.get_text_length(candidate, FONT, fontsize) > width:
                lines += 1
                line = word
            else:
                line = candidate
    return lines * fontsize * LINE_HEIGHT + 2 * PAD


def _fit_box(text: str, page_height: float) -> tuple:
    """(tamaño de letra, alto) del recuadro: reduce la letra si el texto no cabría en una página."""
    width, limit = BOX_WIDTH - 2 * PAD, page_height - 2 * MARGIN
    size = FONT_SIZE
    while size > MIN_FONT_SIZE and _wrapped_height(text, width, size) > limit:
        size -= 0.5
    return size, min(_wrapped_height(text, width, size), limit)


def _layout_boxes(boxes: list, page_height: float) -> int:
    """Reparte los recuadros de una página sin que se solapen; devuelve el nº de columnas usadas.

    `boxes` es una lista de dicts con `anchor` (y del texto resaltado) y `height`; se ordena por `anchor` y se
    rellenan `column` y `top`. Cada recuadro intenta quedar a la altura de su frase; si no cabe se empuja hacia
    abajo y, si se sale de la página, el grupo se sube. Cuando una columna se llena, se abre otra a su derecha.
    """
    boxes.sort(key=lambda b: b["anchor"])
    capacity = page_height - 2 * MARGIN
    columns, current, used = [], [], 0.0
    for box in boxes:
        need = box["height"] + (BOX_GAP if current else 0.0)
        if current and used + need > capacity:
            columns.append(current)
            current, used, need = [], 0.0, box["height"]
        current.append(box)
        used += need
    if current:
        columns.append(current)
    for index, column in enumerate(columns):
        cursor = MARGIN
        for box in column:                       # hacia abajo: a la altura de su frase, sin pisar al anterior
            box["top"] = max(box["anchor"], cursor)
            cursor = box["top"] + box["height"] + BOX_GAP
        limit = page_height - MARGIN
        for box in reversed(column):             # hacia arriba: si el grupo se sale por abajo, se sube entero
            box["top"] = min(box["top"], limit - box["height"])
            limit = box["top"] - BOX_GAP
            box["column"] = index
    return len(columns)


def _widen_margin(page, columns: int = 1) -> float:
    """Amplía la página por la derecha para alojar `columns` columnas de recuadros sin tapar texto.

    Devuelve el x donde empieza la primera columna. En páginas rotadas no se amplía: los
    recuadros se colocan dentro del borde derecho de la página.
    """
    if page.rotation == 0:
        base = page.rect.width
        extra = columns * BOX_WIDTH + (columns + 1) * GUTTER
        media, crop = page.mediabox, page.cropbox
        media.x1 += extra
        crop.x1 += extra
        page.set_mediabox(media)
        page.set_cropbox(crop)
        return base + GUTTER
    return page.rect.width - columns * (BOX_WIDTH + GUTTER)


def _annotate_with_margin_boxes(original_pdf_path: str, output_pdf_path: str,
                                incoherencias_list: list, build_text) -> tuple:
    """Resalta cada `frase_analizada` y coloca un recuadro al margen con `build_text(item)`.

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
        pending = {}    # nº de página -> recuadros por colocar (se reparten al final, sin solaparse)
        found = 0
        for item in enriched:
            if not isinstance(item, dict):
                continue
            phrase = _normalize(item.get("frase_analizada"))
            if not phrase:
                continue
            text = _latin1(build_text(item))

            for page in doc:
                quads = page.search_for(phrase, quads=True)
                if not quads:
                    continue
                highlight = page.add_highlight_annot(quads)
                highlight.set_colors(stroke=HIGHLIGHT_COLOR)
                highlight.set_info(title="Auditoria IA")
                highlight.update()
                if item["page_number"] is not None:
                    continue  # recuadro solo en la primera aparición
                item["page_number"] = page.number + 1
                rect = quads[0].rect
                pending.setdefault(page.number, []).append(
                    {"text": text, "anchor": rect.y0, "rect": rect, "target": fitz.Point(rect.x1, rect.y0 + 4)})

            if item["page_number"] is not None:
                found += 1
            else:
                log.warning("Frase no encontrada de forma exacta en %s: %.120s", original_pdf_path, phrase)

        for number, boxes in pending.items():  # segunda pasada: colocar los recuadros página a página
            page = doc[number]
            boxes.sort(key=lambda b: b["anchor"])
            for n, box in enumerate(boxes, 1):  # nº en orden de lectura: une cada resaltado con su recuadro
                box["label"] = n
                box["text"] = f"{n}. {box['text']}"
                box["size"], box["height"] = _fit_box(box["text"], page.rect.height)
            columns = _layout_boxes(boxes, page.rect.height)
            first_x = _widen_margin(page, columns)
            for box in boxes:
                x = first_x + box["column"] * (BOX_WIDTH + GUTTER)
                rect = fitz.Rect(x, box["top"], x + BOX_WIDTH, box["top"] + box["height"])
                options = {}
                if box["column"] == 0:  # la flecha solo en la columna más cercana al texto: las demás cruzarían recuadros
                    options["callout"] = (box["target"], fitz.Point(rect.x0, rect.y0 + 10))
                page.add_freetext_annot(
                    rect, box["text"], fontsize=box["size"], fontname=FONT, text_color=BOX_TEXT,
                    fill_color=BOX_FILL, border_width=1, **options)  # el borde toma el color del texto
                badge_x = max(2.0, box["rect"].x0 - BADGE_SIZE - 2)
                page.add_freetext_annot(
                    fitz.Rect(badge_x, box["rect"].y0, badge_x + BADGE_SIZE, box["rect"].y0 + BADGE_SIZE - 1),
                    str(box["label"]), fontsize=7, fontname=FONT, text_color=(1, 1, 1),
                    fill_color=BADGE_FILL, border_width=0, align=fitz.TEXT_ALIGN_CENTER)

        if not found:
            return False, enriched
        doc.save(output_pdf_path, garbage=3, deflate=True)
        return True, enriched
    except Exception:
        log.exception("Error al anotar el PDF %s", original_pdf_path)
        return False, enriched
    finally:
        doc.close()


def annotate_pdf_with_ai_results(original_pdf_path: str, output_pdf_path: str,
                                 incoherencias_list: list) -> tuple:
    """Auditorías normativa y de fidelidad: el recuadro lleva las fuentes y la explicación."""
    def text(item):
        infringed = item.get("texto_infrinjido") or item.get("normativa_infringida") or ""
        return f"FONTS / NORMATIVA:\n{infringed}\n\nEXPLICACIÓ:\n{item.get('explicacion') or ''}"
    return _annotate_with_margin_boxes(original_pdf_path, output_pdf_path, incoherencias_list, text)


def annotate_referente_pdf(original_pdf_path: str, output_pdf_path: str,
                           incoherencias_list: list) -> tuple:
    """Auditoría de claridad (Referente departamental): el recuadro lleva explicación y propuesta."""
    def text(item):
        return f"EXPLICACIÓ:\n{item.get('explicacion') or ''}\n\nPROPOSTA:\n{item.get('propuesta') or ''}"
    return _annotate_with_margin_boxes(original_pdf_path, output_pdf_path, incoherencias_list, text)
