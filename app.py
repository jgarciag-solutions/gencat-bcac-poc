"""POC BCAC - Flujo de gobernanza documental (Flask, persistencia en JSON)."""
import json
import os
import threading
import uuid
from datetime import date
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.utils import secure_filename

import gestor_conocimiento
from pipeline import process_document

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
                      "txt", "odt", "png", "jpg", "jpeg"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "poc-bcac-clave-solo-demo")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
DOCUMENTS_FILE = os.path.join(UPLOAD_FOLDER, "documents.json")
DOCS_LOCK = threading.RLock()
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "vectores"), exist_ok=True)

# --------------------------------------------------------------------------
# Datos de referencia (usuarios y catálogos en memoria)
# --------------------------------------------------------------------------
USERS = {
    "admin": {"password": "gencat", "name": "Administrador", "role": "Administrador"},
}

S_ELAB = "En elaboración"
S_UF = "En validación - Pte. Unidad Finalista"
S_GC = "En validación - Pte. Gestor Conocimiento"
S_RC = "En validación - Pte. Responsable Canal"
S_PUB = "Publicada"
S_RET = "Retirada"
STATES = [S_ELAB, S_UF, S_GC, S_RC, S_PUB, S_RET]

CONTENT_TYPES = ["Base", "Adaptado"]

# Flujo secuencial según el tipo de contenido (Modelo de Contenidos).
FLOWS = {
    "Base": [S_ELAB, S_UF, S_GC, S_PUB],
    "Adaptado": [S_ELAB, S_RC, S_PUB],
}

# Estados de validación: aquí se puede aprobar o rechazar.
VALIDATION_STATES = {S_UF, S_GC, S_RC}

# Pestañas del dashboard: cada rol ve los documentos en su micro-estado.
TABS = [
    {"role": "Referente Departamental", "status": S_ELAB},
    {"role": "Validador Finalista", "status": S_UF},
    {"role": "Gestor del Conocimiento", "status": S_GC},
    {"role": "Responsable de Canal", "status": S_RC},
    {"role": "Publicados", "status": S_PUB},
    {"role": "Archivo", "status": S_RET},
]

ACTION_LABEL = {
    S_ELAB: "Enviar a validación",
    S_UF: "Aprobar",
    S_GC: "Aprobar",
    S_RC: "Aprobar",
}

# Estados del modelo anterior -> micro-estados actuales (migración al leer el JSON).
LEGACY_STATUS = {
    "1. Pendiente Supervisión": S_ELAB,
    "2. Pendiente Validación Base": S_UF,
    "3. Pendiente Revisión GC": S_GC,
    "4. Pendiente Adaptación Canal": S_RC,
    "5. Publicado": S_PUB,
}

TAXONOMY = {
    "Trámites": {
        "Familia": ["Familia Numerosa", "Familia Monoparental", "Ayudas por hijo"],
        "Vivienda": ["Ayudas al alquiler", "Cédula de habitabilidad"],
    },
    "Fiscalidad": {
        "Tributos": ["Tasas", "IRPF autonómico"],
    },
}

DEPARTMENTS = [
    "Derechos Sociales y Familias",
    "Economía y Hacienda",
    "Territorio y Vivienda",
    "Atención Ciudadana",
]

# --------------------------------------------------------------------------
# Persistencia en uploads/documents.json
# Campos de cada registro: id, filename, title, taxonomy, source, department,
# date, status, updated_by. Los archivos de uploads/ que no figuren aquí se ignoran.
# --------------------------------------------------------------------------
def ensure_documents_file():
    """Crea documents.json como lista vacía si no existe."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    if not os.path.exists(DOCUMENTS_FILE):
        write_json([])


def write_json(docs):
    tmp = DOCUMENTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(docs, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, DOCUMENTS_FILE)  # escritura atómica


def normalize(doc):
    """Completa los campos nuevos y migra estados antiguos de registros previos."""
    doc["status"] = LEGACY_STATUS.get(doc.get("status"), doc.get("status"))
    tax = doc.get("taxonomy")
    doc["taxonomy"] = [tax] if isinstance(tax, str) and tax else (tax if isinstance(tax, list) else [])
    doc.setdefault("content_type", "Base")
    doc.setdefault("version", 1)
    doc.setdefault("observations", "")
    doc.setdefault("analysis_result", None)
    doc.setdefault("analysis_done", False)
    doc.setdefault("normative_analysis_result", None)
    doc.setdefault("normative_analysis_done", False)
    doc.setdefault("simhash", None)
    doc.setdefault("vector_file", None)
    doc.setdefault("duplicity_result", None)
    doc.setdefault("duplicity_analysis_done", False)
    doc.setdefault("fidelity_analysis_result", None)
    doc.setdefault("fidelity_analysis_done", False)
    return doc


def load_documents():
    with DOCS_LOCK:
        ensure_documents_file()
        try:
            with open(DOCUMENTS_FILE, encoding="utf-8") as fh:
                docs = json.load(fh)
            if not isinstance(docs, list):
                raise ValueError("documents.json no contiene una lista")
            return [normalize(d) for d in docs]
        except (ValueError, OSError):
            # JSON corrupto: se conserva una copia y se reinicia como lista vacía.
            os.replace(DOCUMENTS_FILE, DOCUMENTS_FILE + ".corrupt")
            write_json([])
            return []


def save_documents(docs):
    with DOCS_LOCK:
        write_json(docs)


ensure_documents_file()


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def current_user():
    username = session.get("username")
    if not username or username not in USERS:
        return None
    return {"username": username, **USERS[username]}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Debes iniciar sesión para continuar.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def find_doc(docs, doc_id):
    return next((d for d in docs if d["id"] == doc_id), None)


def filename_exists(filename, docs):
    """Duplicado por nombre en documents.json o en la carpeta uploads/ (sin distinguir mayúsculas)."""
    name = filename.lower()
    if any(str(d.get("filename", "")).lower() == name for d in docs):
        return True
    return any(f.lower() == name for f in os.listdir(UPLOAD_FOLDER))


def next_status(doc):
    """Siguiente estado del flujo según content_type, o None si no hay."""
    flow = FLOWS.get(doc["content_type"], [])
    if doc["status"] in flow and flow.index(doc["status"]) < len(flow) - 1:
        return flow[flow.index(doc["status"]) + 1]
    return None


def can_advance(doc):
    return next_status(doc) is not None


def tab_anchor(status):
    return f"#tab-{STATES.index(status) + 1}" if status in STATES else ""


def published_base_docs(docs):
    """Documentos Base publicados: los únicos que se pueden usar como fuente de un Adaptado."""
    return [d for d in docs if d["status"] == S_PUB and d["content_type"] == "Base"]


def source_titles(doc, titles):
    """Fuente original legible: títulos de los documentos origen (o texto libre en registros antiguos)."""
    src = doc.get("source")
    if isinstance(src, list):
        return [titles.get(i, i) for i in src]
    return [src] if src else []


def taxonomy_paths():
    return [f"{n1} > {n2} > {n3}"
            for n1, l2 in TAXONOMY.items() for n2, l3 in l2.items() for n3 in l3]


@app.context_processor
def inject_globals():
    return {"user": current_user(), "STATES": STATES}


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        account = USERS.get(username)
        if account and account["password"] == password:
            session.clear()
            session["username"] = username
            flash(f"Bienvenido, {account['name']}.", "success")
            return redirect(url_for("dashboard"))
        flash("Credenciales incorrectas.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    docs = load_documents()
    titles = {d["id"]: d["title"] for d in docs}
    rows = [{**d, "source_titles": source_titles(d, titles), "can_advance": can_advance(d),
             "action": ACTION_LABEL.get(d["status"], ""),
             "badge": STATES.index(d["status"]) + 1 if d["status"] in STATES else 0}
            for d in docs]
    rows.sort(key=lambda d: d["date"], reverse=True)
    tabs = [{**t, "docs": [d for d in rows if d["status"] == t["status"]]} for t in TABS]
    return render_template("dashboard.html", tabs=tabs, validation_states=VALIDATION_STATES)


def render_upload(form, selected_sources=()):
    return render_template("upload.html", form=form, taxonomies=taxonomy_paths(),
                           departments=DEPARTMENTS, content_types=CONTENT_TYPES,
                           base_docs=published_base_docs(load_documents()),
                           selected_sources=list(selected_sources),
                           today=date.today().isoformat(), extensions=sorted(ALLOWED_EXTENSIONS))


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    user = current_user()
    form = {}
    selected_sources = []
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip()
                for k in ("title", "taxonomy", "department", "date", "content_type")}
        selected_sources = list(dict.fromkeys(request.form.getlist("source")))  # sin duplicados
        file = request.files.get("file")
        errors = []
        if not file or not file.filename:
            errors.append("Debes seleccionar un archivo.")
        elif not allowed_file(file.filename):
            errors.append("Tipo de archivo no permitido. Formatos válidos: "
                          + ", ".join(sorted(ALLOWED_EXTENSIONS)) + ".")
        if not all(form[k] for k in ("title", "department", "date", "content_type")):
            errors.append("Todos los campos de metadatos son obligatorios.")
        if form["content_type"] and form["content_type"] not in CONTENT_TYPES:
            errors.append("El tipo de contenido no es válido.")
        if form["department"] and form["department"] not in DEPARTMENTS:
            errors.append("El departamento seleccionado no es válido.")
        if form["date"]:
            try:
                date.fromisoformat(form["date"])
            except ValueError:
                errors.append("La fecha no es válida.")

        # Reglas de herencia según el tipo de contenido.
        taxonomy, source = [], []
        if form["content_type"] == "Base":
            if form["taxonomy"] not in taxonomy_paths():
                errors.append("Selecciona una taxonomía válida.")
            taxonomy = [form["taxonomy"]]  # lista de un elemento; la fuente original no aplica
        elif form["content_type"] == "Adaptado":
            # Se ignora cualquier taxonomía manual: se hereda de las fuentes seleccionadas.
            available = {d["id"]: d for d in published_base_docs(load_documents())}
            if not selected_sources:
                errors.append("Selecciona al menos un documento base publicado como fuente original.")
            elif any(i not in available for i in selected_sources):
                errors.append("Alguna fuente original no es un documento base publicado.")
            else:
                source = selected_sources
                taxonomy = list(dict.fromkeys(t for i in source for t in available[i]["taxonomy"]))

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            filename = secure_filename(file.filename)
            if not filename:
                flash("El nombre del archivo no es válido.", "error")
            else:
                path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                with DOCS_LOCK:  # reserva el nombre: tras guardar el archivo, otro upload igual se detecta
                    duplicate = filename_exists(filename, load_documents())
                    if not duplicate:
                        file.save(path)
                if duplicate:
                    flash("El archivo ya ha sido subido anteriormente", "warning")
                else:
                    doc_id = uuid.uuid4().hex[:8]
                    # SimHash y embeddings (red) fuera del bloqueo; nunca bloquea la subida si fallan.
                    simhash, vector_file = process_document(path, doc_id)
                    record = {
                        "id": doc_id,
                        "filename": filename,
                        "title": form["title"],
                        "taxonomy": taxonomy,
                        "source": source,
                        "department": form["department"],
                        "date": form["date"],
                        "content_type": form["content_type"],
                        "version": 1,
                        "observations": "",
                        "analysis_result": None,
                        "analysis_done": False,
                        "normative_analysis_result": None,
                        "normative_analysis_done": False,
                        "simhash": simhash,
                        "vector_file": vector_file,
                        "duplicity_result": None,
                        "duplicity_analysis_done": False,
                        "fidelity_analysis_result": None,
                        "fidelity_analysis_done": False,
                        "status": S_ELAB,
                        "updated_by": user["username"],
                    }
                    try:
                        with DOCS_LOCK:
                            docs = load_documents()
                            docs.append(record)
                            save_documents(docs)
                    except OSError:
                        os.remove(path)
                        if vector_file:
                            os.remove(os.path.join(BASE_DIR, vector_file))
                        flash("No se pudo guardar el documento. Inténtalo de nuevo.", "error")
                        return render_upload(form, selected_sources)
                    if vector_file:
                        flash("Documento subido. El documento queda «En elaboración».", "success")
                    else:
                        flash("Documento subido «En elaboración», pero no se generaron los vectores "
                              "(revisa la API key o la cuota de Gemini).", "warning")
                    return redirect(url_for("dashboard"))

    return render_upload(form, selected_sources)


def change_document(doc_id, action):
    """Lee, modifica y guarda un documento de forma atómica.

    `action(doc, user)` devuelve (mensaje, categoría) o None; si devuelve None
    no se guarda. Siempre redirige al dashboard, a la pestaña de origen.
    """
    user = current_user()
    with DOCS_LOCK:
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            abort(404)
        origin = tab_anchor(doc["status"])
        result = action(doc, user)
        if result is None:
            return redirect(url_for("dashboard") + origin)
        doc["updated_by"] = user["username"]
        save_documents(docs)
    flash(*result)
    return redirect(url_for("dashboard") + origin)


@app.route("/avanzar_estado/<doc_id>", methods=["POST"])
@login_required
def avanzar_estado(doc_id):
    def action(doc, _user):
        new = next_status(doc)
        if new is None:
            flash("Este documento no puede avanzar desde su estado actual.", "error")
            return None
        doc["status"] = new
        if new != S_ELAB:
            doc["observations"] = ""
        return f"«{doc['title']}» avanzado a: {new}.", "success"
    return change_document(doc_id, action)


@app.route("/rechazar/<doc_id>", methods=["POST"])
@login_required
def rechazar(doc_id):
    reason = request.form.get("motivo", "").strip()[:500]

    def action(doc, _user):
        if doc["status"] not in VALIDATION_STATES:
            flash("Solo se pueden rechazar documentos en validación.", "error")
            return None
        if not reason:
            flash("Debes indicar el motivo de la devolución.", "error")
            return None
        doc["status"] = S_ELAB
        doc["observations"] = reason
        doc["normative_analysis_done"], doc["normative_analysis_result"] = False, None
        doc["duplicity_analysis_done"], doc["duplicity_result"] = False, None
        doc["fidelity_analysis_done"], doc["fidelity_analysis_result"] = False, None
        return f"«{doc['title']}» devuelto a elaboración.", "warning"
    return change_document(doc_id, action)


@app.route("/versionar/<doc_id>", methods=["POST"])
@login_required
def versionar(doc_id):
    def action(doc, _user):
        if doc["status"] != S_PUB:
            flash("Solo se puede versionar un documento publicado.", "error")
            return None
        doc["status"] = S_ELAB
        doc["version"] = int(doc.get("version", 1)) + 1
        doc["observations"] = ""
        doc["normative_analysis_done"], doc["normative_analysis_result"] = False, None
        doc["duplicity_analysis_done"], doc["duplicity_result"] = False, None
        doc["fidelity_analysis_done"], doc["fidelity_analysis_result"] = False, None
        return f"«{doc['title']}»: nueva versión {doc['version']} en elaboración.", "success"
    return change_document(doc_id, action)


@app.route("/retirar/<doc_id>", methods=["POST"])
@login_required
def retirar(doc_id):
    def action(doc, _user):
        if doc["status"] != S_PUB:
            flash("Solo se puede retirar un documento publicado.", "error")
            return None
        doc["status"] = S_RET
        return f"«{doc['title']}» retirado y enviado a Archivo.", "success"
    return change_document(doc_id, action)


@app.route("/api/analyze/<doc_id>", methods=["POST"])
def api_analyze(doc_id):
    """Audita con IA la claridad y coherencia de un PDF y guarda el resultado."""
    if current_user() is None:
        return jsonify(ok=False, error="Sesión no iniciada."), 401
    doc = find_doc(load_documents(), doc_id)
    if doc is None:
        return jsonify(ok=False, error="Documento no encontrado."), 404
    filename = doc.get("filename") or ""
    if not filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Solo se pueden analizar documentos PDF."), 400
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.isfile(path):
        return jsonify(ok=False, error="Archivo físico no disponible"), 404
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key or "tu_api_key" in api_key:
        return jsonify(ok=False, error="Falta configurar GEMINI_API_KEY (o GOOGLE_API_KEY) en el archivo .env."), 503

    try:
        from agents.reviewer_agent import run_review  # import diferido: la app arranca sin la IA
        result = run_review(path)
    except Exception as exc:
        app.logger.exception("Fallo en el análisis IA de %s", doc_id)
        return jsonify(ok=False, error=f"No se pudo completar el análisis: {exc}"), 502

    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante la llamada al modelo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El documento ya no existe."), 404
        doc["analysis_result"] = result
        doc["analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, analysis_result=result)


@app.route("/api/validate_normative/<doc_id>", methods=["POST"])
def api_validate_normative(doc_id):
    """Valida con IA un PDF contra la normativa de normativa/ y guarda el resultado."""
    if current_user() is None:
        return jsonify(ok=False, error="Sesión no iniciada."), 401
    doc = find_doc(load_documents(), doc_id)
    if doc is None:
        return jsonify(ok=False, error="Documento no encontrado."), 404
    if doc["status"] != S_UF:
        return jsonify(ok=False, error="El documento no está pendiente de la Unidad Finalista."), 409
    filename = doc.get("filename") or ""
    if not filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Solo se pueden validar documentos PDF."), 400
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.isfile(path):
        return jsonify(ok=False, error="Archivo físico no disponible"), 404
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key or "tu_api_key" in api_key:
        return jsonify(ok=False, error="Falta configurar GEMINI_API_KEY (o GOOGLE_API_KEY) en el archivo .env."), 503

    try:
        from agents.tools import list_normative_pdfs
        if not list_normative_pdfs():
            return jsonify(ok=False, error="No hay leyes cargadas en la carpeta normativa/. "
                                           "Añade archivos PDF de normativa y vuelve a intentarlo."), 409
        from agents.normative_agent import run_normative_review  # import diferido
        result = run_normative_review(path)
    except Exception as exc:
        app.logger.exception("Fallo en la validación normativa de %s", doc_id)
        return jsonify(ok=False, error=f"No se pudo completar la validación: {exc}"), 502

    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante la llamada al modelo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El documento ya no existe."), 404
        doc["normative_analysis_result"] = result
        doc["normative_analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, normative_analysis_result=result)


@app.route("/api/detect_duplicity/<doc_id>", methods=["POST"])
def api_detect_duplicity(doc_id):
    """Detecta duplicidades (SimHash + similitud vectorial) y guarda el resultado."""
    if current_user() is None:
        return jsonify(ok=False, error="Sesión no iniciada."), 401
    docs = load_documents()
    doc = find_doc(docs, doc_id)
    if doc is None:
        return jsonify(ok=False, error="Documento no encontrado."), 404
    if doc["status"] != S_GC:
        return jsonify(ok=False, error="El documento no está pendiente del Gestor del Conocimiento."), 409
    try:
        result = gestor_conocimiento.detect_document_duplicity(
            doc_id, docs, vectors_dir=os.path.join(BASE_DIR, "vectores"),
            config_path=os.path.join(BASE_DIR, "config.json"))
    except Exception as exc:
        app.logger.exception("Fallo en la detección de duplicidades de %s", doc_id)
        return jsonify(ok=False, error=f"No se pudo completar la detección: {exc}"), 500

    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante el cálculo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El documento ya no existe."), 404
        doc["duplicity_result"] = result
        doc["duplicity_analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, duplicity_result=result)


@app.route("/api/check_fidelity/<doc_id>", methods=["POST"])
def api_check_fidelity(doc_id):
    """Comprueba con IA la fidelidad de un documento Adaptado respecto a sus fuentes Base."""
    if current_user() is None:
        return jsonify(ok=False, error="Sesión no iniciada."), 401
    docs = load_documents()
    doc = find_doc(docs, doc_id)
    if doc is None:
        return jsonify(ok=False, error="Documento no encontrado."), 404
    if doc["status"] != S_RC:
        return jsonify(ok=False, error="El documento no está pendiente del Responsable de Canal."), 409
    folder = app.config["UPLOAD_FOLDER"]
    filename = doc.get("filename") or ""
    adapted_path = os.path.join(folder, filename)
    if not filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Solo se pueden comprobar documentos PDF."), 400
    if not os.path.isfile(adapted_path):
        return jsonify(ok=False, error="Archivo físico no disponible"), 404

    sources = doc.get("source") if isinstance(doc.get("source"), list) else []
    if not sources:
        return jsonify(ok=False, error="Este documento no tiene documentos fuente asociados; "
                                       "no hay nada con lo que comprobar su fidelidad."), 409
    by_id = {d["id"]: d for d in docs}
    source_paths, missing = [], 0
    for sid in sources:
        src = by_id.get(sid)
        path = os.path.join(folder, (src or {}).get("filename") or "")
        if src and path.lower().endswith(".pdf") and os.path.isfile(path):
            source_paths.append(path)
        else:
            missing += 1
    if not source_paths:
        return jsonify(ok=False, error="Ninguno de los documentos fuente tiene un PDF disponible."), 409
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key or "tu_api_key" in api_key:
        return jsonify(ok=False, error="Falta configurar GEMINI_API_KEY (o GOOGLE_API_KEY) en el archivo .env."), 503

    try:
        from agents.comprobar_fidelidad import run_fidelity_check  # import diferido
        result = run_fidelity_check(adapted_path, source_paths)
    except Exception as exc:
        app.logger.exception("Fallo en la comprobación de fidelidad de %s", doc_id)
        return jsonify(ok=False, error=f"No se pudo completar la comprobación: {exc}"), 502
    if missing:
        result += f"\n\n> Nota: {missing} documento(s) fuente no se pudieron incluir por no tener un PDF disponible."

    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante la llamada al modelo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El documento ya no existe."), 404
        doc["fidelity_analysis_result"] = result
        doc["fidelity_analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, fidelity_analysis_result=result)


@app.route("/download/<doc_id>")
@login_required
def download(doc_id):
    doc = find_doc(load_documents(), doc_id)
    if doc is None:
        abort(404)
    path = os.path.join(app.config["UPLOAD_FOLDER"], doc.get("filename") or "")
    if not doc.get("filename") or not os.path.isfile(path):
        flash("Archivo físico no disponible", "error")
        return redirect(url_for("dashboard"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], doc["filename"])


@app.errorhandler(413)
def too_large(_e):
    flash("El archivo supera el tamaño máximo permitido (16 MB).", "error")
    return redirect(url_for("upload"))


@app.errorhandler(403)
def forbidden(_e):
    flash("No tienes permiso para acceder a este recurso.", "error")
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


@app.errorhandler(404)
def not_found(_e):
    flash("Recurso no encontrado.", "error")
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
