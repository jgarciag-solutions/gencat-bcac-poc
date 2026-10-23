"""Herramientas disponibles para los agentes."""
import os

import pdfplumber

try:
    import pymupdf  # PyMuPDF >= 1.24.3
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, "uploads")
NORMATIVE_FOLDER = os.path.join(PROJECT_ROOT, "normativa")
MAX_CHARS = 400_000  # manuales largos (p. ej. 114 págs. ≈ 160.000 caracteres): un corte antes de tiempo falsea la comparación
MAX_NORMATIVE_CHARS = 600_000


def extract_pages(path: str) -> list[str]:
    """Texto de cada página del PDF.

    Usa PyMuPDF, que respeta el orden de lectura de los PDF de diapositivas con cuadros solapados; pdfplumber los
    desordena (mezcla letras de cuadros distintos y pierde líneas), así que solo queda como respaldo.
    """
    if pymupdf is not None:
        try:
            with pymupdf.open(path) as doc:
                return [page.get_text() for page in doc]
        except Exception:
            pass  # PDF que PyMuPDF no abre: se intenta con pdfplumber
    with pdfplumber.open(path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def read_pdf(file_path: str) -> str:
    """Extrae y devuelve el texto de un archivo PDF almacenado en uploads/.

    Args:
        file_path: Ruta física del PDF dentro de la carpeta uploads/.

    Returns:
        El texto del documento, o un mensaje de error si no se puede leer.
    """
    real = os.path.realpath(file_path)
    # El agente solo puede leer archivos dentro de uploads/ (evita lecturas arbitrarias).
    if os.path.commonpath([real, os.path.realpath(UPLOAD_FOLDER)]) != os.path.realpath(UPLOAD_FOLDER):
        return "ERROR: ruta no permitida; solo se pueden leer archivos de uploads/."
    if not real.lower().endswith(".pdf") or not os.path.isfile(real):
        return "ERROR: el archivo no existe o no es un PDF."
    try:
        text = "\n\n".join(extract_pages(real)).strip()
    except Exception as exc:  # PDF corrupto, protegido, etc.
        return f"ERROR: no se pudo leer el PDF ({exc})."
    if not text:
        return "ERROR: el PDF no contiene texto extraíble (¿es una imagen escaneada?)."
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n[... texto truncado ...]"
    return text


def list_normative_pdfs(folder_path: str = NORMATIVE_FOLDER) -> list:
    """Nombres de los PDF de normativa disponibles (ordenados)."""
    if not os.path.isdir(folder_path):
        return []
    return sorted(f for f in os.listdir(folder_path) if f.lower().endswith(".pdf"))


def read_all_normative_pdfs(folder_path: str = "normativa") -> str:
    """Lee todos los PDF de la carpeta de normativa y devuelve el texto concatenado.

    Cada ley va precedida de una cabecera con el nombre de su archivo.

    Args:
        folder_path: Carpeta de normativa (por defecto "normativa", en la raíz del proyecto).

    Returns:
        El texto de todas las leyes, o un aviso si no hay normativa cargada.
    """
    # Solo se admite la carpeta normativa/ del proyecto, sea cual sea el argumento recibido.
    folder = os.path.realpath(os.path.join(PROJECT_ROOT, folder_path))
    if folder != os.path.realpath(NORMATIVE_FOLDER):
        return "ERROR: solo se puede leer la carpeta normativa/."
    names = list_normative_pdfs(folder)
    if not names:
        return "AVISO: no hay leyes cargadas en la carpeta normativa/. Añade archivos PDF para poder validar."

    parts, total = [], 0
    for name in names:
        try:
            text = "\n".join(extract_pages(os.path.join(folder, name))).strip()
        except Exception as exc:  # PDF corrupto o protegido: se informa y se continúa
            text = f"[No se pudo leer este PDF: {exc}]"
        chunk = f"===== LEY / NORMATIVA: {name} =====\n{text or '[PDF sin texto extraíble]'}\n"
        if total + len(chunk) > MAX_NORMATIVE_CHARS:
            parts.append(f"===== {name} omitida: se alcanzó el límite de texto normativo =====\n")
            continue
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts)


def read_multiple_pdfs(file_paths: list[str]) -> str:
    """Extrae el texto de varios PDF de uploads/ y lo devuelve concatenado.

    Cada documento va precedido de una cabecera con su nombre de archivo.

    Args:
        file_paths: Rutas físicas de los PDF dentro de la carpeta uploads/.

    Returns:
        El texto de todos los documentos, indicando cuál es cuál; los que no se
        puedan leer se señalan en su propia sección.
    """
    upload_root = os.path.realpath(UPLOAD_FOLDER)
    parts, total = [], 0
    for file_path in file_paths:
        real = os.path.realpath(file_path)
        name = os.path.basename(real)
        header = f"===== DOCUMENTO FUENTE: {name} ====="
        if os.path.commonpath([real, upload_root]) != upload_root:
            text = "[ERROR: ruta no permitida; solo se pueden leer archivos de uploads/.]"
        elif not real.lower().endswith(".pdf") or not os.path.isfile(real):
            text = "[ERROR: el archivo no existe o no es un PDF.]"
        else:
            try:
                text = "\n".join(extract_pages(real)).strip()
            except Exception as exc:  # PDF corrupto o protegido: se informa y se continúa
                text = f"[ERROR: no se pudo leer el PDF ({exc}).]"
            text = text or "[PDF sin texto extraíble]"
            if total + len(text) > MAX_NORMATIVE_CHARS:
                text = "[Omitido: se alcanzó el límite de texto de las fuentes.]"
            total += len(text)
        parts.append(f"{header}\n{text}\n")
    return "\n".join(parts) if parts else "ERROR: no se indicó ningún documento."
