"""POC BCAC - Flujo de gobernanza documental (Flask, persistencia en JSON)."""
import json
import os
import re
import threading
from datetime import date, datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.utils import secure_filename

import gestor_conocimiento
from pdf_annotator import annotate_pdf_with_ai_results, annotate_referente_pdf
from pipeline import load_config, process_document

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
AI_LOG_FOLDER = os.path.join(BASE_DIR, "logs", "ai_responses")  # respuestas de IA no interpretables (fuera de git)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
                      "txt", "odt", "png", "jpg", "jpeg"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "poc-bcac-clave-solo-demo")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
DOCUMENTS_FILE = os.path.join(UPLOAD_FOLDER, "documents.json")
DOCS_LOCK = threading.RLock()
ID_COUNTER_FILE = os.path.join(UPLOAD_FOLDER, "id_counter.json")  # último número de ID emitido (nunca se reutiliza)
ID_RE = re.compile(r"^BCAC-[AB]-(\d+)$")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "vectores"), exist_ok=True)

# --------------------------------------------------------------------------
# Datos de referencia (usuarios y catálogos en memoria)
# --------------------------------------------------------------------------
USERS = {
    "admin": {"password": "gencat", "name": "Administrador", "role": "Administrador"},
}

S_ED = "En elaboració - Editor Departamental"
S_EC = "En elaboració - Editor Canal"
S_RD = "En validació - Pdt. Referent Departamental"
S_UF = "En validació - Pdt. Unitat Finalista"
S_GCB = "En validació - Pdt. Gestor Coneixement Cord"
S_GCC = "En validació - Pdt. Gestor Coneixement Canal"
S_PUB = "Publicat"
STATES = [S_ED, S_EC, S_RD, S_UF, S_GCB, S_GCC, S_PUB]

CONTENT_TYPES = ["Base", "Adaptat", "Referenciat"]

# Flujo secuencial según el tipo de contenido (Modelo de Contenidos).
FLOWS = {
    "Base": [S_ED, S_RD, S_UF, S_GCB, S_PUB],
    "Referenciat": [S_ED, S_RD, S_UF, S_GCB, S_PUB],
    "Adaptat": [S_EC, S_GCC, S_PUB],
}

# Estados de validación: aquí se puede aprobar o rechazar.
VALIDATION_STATES = {S_RD, S_UF, S_GCB, S_GCC}

# Pestañas del dashboard: cada rol ve los documentos en su micro-estado.
TABS = [
    {"role": "Editor Departamental", "slug": "editor-departamental", "status": S_ED},
    {"role": "Editor Canal", "slug": "editor-canal", "status": S_EC},
    {"role": "Referent Departamental", "slug": "referent-departamental", "status": S_RD},
    {"role": "Validador Finalista", "slug": "validador-finalista", "status": S_UF},
    {"role": "Gestor Coneixement Cord", "slug": "gestor-coneixement-base", "status": S_GCB},
    {"role": "Gestor Coneixement Canal", "slug": "gestor-coneixement-canal", "status": S_GCC},
    {"role": "Publicats", "slug": "publicats", "status": S_PUB},
]

ACTION_LABEL = {
    S_ED: "Aprovar",
    S_EC: "Aprovar",
    S_RD: "Aprovar",
    S_UF: "Aprovar",
    S_GCB: "Aprovar",
    S_GCC: "Aprovar",
}

# Estado inicial / destino de devolución según el tipo de contenido.
EDITOR_STATE = {"Base": S_ED, "Referenciat": S_ED, "Adaptat": S_EC}
EDITOR_STATES = {S_ED, S_EC}

TAXONOMY = {
    "Societat i ciutadania": {
        "Families": ["Titol Família Nombrosa", "Titol Família Monoparental", "Registre de parelles estables", "Formacion per a pares i mares", "Avantages per famillies nombroses i monoparentals", "Acompanyament des familles (SOAF)","Autorització viatges menors no acompanyats" ],
        "Dones": ["Equitat mesntrual", "Servesi i programes per a dones", "Violencia masclista"]
    }
}

IDIOMAS = ["Català", "Castellà"]
TIPOLOGIAS = [
    "Descripció del tràmit o servei",
    "Manual de tramitació",
    "Guia de l'atenció",
    "Resposta tipus",
    "Avís",
    "Dades de suport",
    "Font externa referenciada",
]

CANALES = ["WEB", "Xarxes", "Presencial", "012"]

DEPARTMENTS = [
    "Drets Socials i Inclusio",
    "Igualtat i Feminisme",
    "Empresa i Treball",
    "Justicia i Qualitat Democratica",
    "Cultura",
    "Salut", 
    "interiro i Securitat Publica",
    "Presidencia",
    "Esports"
]

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


DIAS_REVISION_DEFECTO = 150


def dias_revision_prevista():
    """Días entre la publicación y la revisión prevista (config.json); se relee en cada uso."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            days = json.load(fh).get("dias_revision_prevista")
        if isinstance(days, int) and not isinstance(days, bool) and days >= 0:
            return days
    except (OSError, ValueError):
        pass
    app.logger.warning("dias_revision_prevista no válido en config.json; se usan %d días.", DIAS_REVISION_DEFECTO)
    return DIAS_REVISION_DEFECTO


def departamentos_competentes():
    """Lista cerrada de departamentos (config.json); se relee en cada petición para reflejar cambios."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            items = json.load(fh).get("departamentos_competentes")
        if isinstance(items, list) and all(isinstance(i, str) for i in items) and items:
            return items
    except (OSError, ValueError):
        app.logger.warning("No se pudo leer departamentos_competentes de config.json; se usa la lista por defecto.")
    return list(DEPARTMENTS)


# --------------------------------------------------------------------------
# Persistencia en uploads/documents.json
# Cada registro es un diccionario plano (ver normalize() para la lista de campos).
# Los archivos de uploads/ que no figuren aquí se ignoran.
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
    """Completa con valores por defecto los campos que falten en un registro."""
    if "title" in doc:  # campo renombrado: title -> denominacio (registros anteriores)
        doc.setdefault("denominacio", doc.pop("title"))
    doc.setdefault("content_type", "Base")
    doc.setdefault("idioma", None)
    doc.setdefault("tipologia", [])
    doc.setdefault("taxonomy", [])
    # Origen y trazabilidad (en la raíz del registro).
    doc.setdefault("unidades_base_origen", [])
    doc.setdefault("departamentos_competentes", [])
    doc.setdefault("canal", "")
    doc.setdefault("fecha_publicacion", None)
    doc.setdefault("fecha_revision_prevista", None)
    doc.setdefault("contenidos_relacionados", [])
    doc.setdefault("version", 1)
    doc.setdefault("observations", "")
    doc.setdefault("rechazado_por_rol", "")  # rol (pestaña) desde el que se devolvió el documento
    doc.setdefault("analysis_result", None)
    doc.setdefault("analysis_done", False)
    doc.setdefault("referente_analysis_result", None)
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
            flash("Has d'iniciar sessió per continuar.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def next_document_id(content_type, docs):
    """ID automático `BCAC-B-0001`, `BCAC-A-0002`…: la letra indica Base (B) o Adaptat (A) y el número es una
    secuencia única, creciente y sin reutilizar. Se guarda el último número emitido para que retirar documentos no
    libere números; como red de seguridad también se respeta el mayor número presente en `docs`.
    Referenciat se trata como Base, igual que en el resto de la aplicación."""
    letter = "A" if content_type == "Adaptat" else "B"
    with DOCS_LOCK:
        try:
            with open(ID_COUNTER_FILE, encoding="utf-8") as fh:
                last = int(json.load(fh).get("last", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            last = 0
        present = max((int(m.group(1)) for d in docs if (m := ID_RE.match(str(d.get("id", ""))))), default=0)
        number = max(last, present) + 1
        try:
            tmp = ID_COUNTER_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"last": number}, fh)
            os.replace(tmp, ID_COUNTER_FILE)
        except OSError:
            app.logger.exception("No se pudo guardar el contador de IDs; se usará el mayor ID presente.")
    return f"BCAC-{letter}-{number:04d}"


def find_doc(docs, doc_id):
    return next((d for d in docs if d["id"] == doc_id), None)


def filename_exists(filename, docs, exclude_id=None):
    """Duplicado por nombre en documents.json o en la carpeta uploads/ (sin distinguir mayúsculas).

    `exclude_id`: documento que se está versionando; su propio archivo no cuenta como duplicado
    (permite volver a subir un archivo con el mismo nombre).
    """
    name = filename.lower()
    own = next((str(d.get("filename", "")).lower() for d in docs if d["id"] == exclude_id), None)
    if any(str(d.get("filename", "")).lower() == name for d in docs if d["id"] != exclude_id):
        return True
    return any(f.lower() == name and f.lower() != own for f in os.listdir(UPLOAD_FOLDER))


def next_status(doc):
    """Siguiente estado del flujo según content_type, o None si no hay."""
    flow = FLOWS.get(doc["content_type"], [])
    if doc["status"] in flow and flow.index(doc["status"]) < len(flow) - 1:
        return flow[flow.index(doc["status"]) + 1]
    return None


def can_advance(doc):
    return next_status(doc) is not None


def role_of_status(status):
    """Rol (nombre de la pestaña) que actúa sobre los documentos en ese estado."""
    return next((t["role"] for t in TABS if t["status"] == status), "")


def tab_anchor(status):
    """Hash (#slug) de la pestaña que muestra los documentos en ese estado."""
    return next((f"#{t['slug']}" for t in TABS if t["status"] == status), "")


def published_base_docs(docs):
    """Documentos Base publicados: los únicos que se pueden usar como fuente de un Adaptado."""
    return [d for d in docs if d["status"] == S_PUB and d["content_type"] == "Base"]


def clean_and_parse_json(llm_response: str) -> dict:
    """Parsea la respuesta JSON de un agente, tolerando fallos habituales del modelo.

    Con `output_schema` el JSON ya llega bien formado; esto es la red de seguridad: vallas Markdown, texto
    alrededor del objeto, saltos de línea sin escapar dentro de las cadenas y comas finales.
    Devuelve el diccionario, o {"error": True, "mensaje": ...} si no se puede interpretar.
    """
    error = {"error": True, "mensaje": "Error en processar la resposta de la IA."}
    cleaned = re.sub(r"```json|```", "", llm_response or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    candidates = [cleaned]
    if 0 <= start < end:  # texto extra alrededor del objeto
        candidates.append(cleaned[start:end + 1])
    candidates += [re.sub(r",\s*([}\]])", r"\1", c) for c in list(candidates)]  # comas finales
    for candidate in candidates:
        try:
            data = json.loads(candidate, strict=False)  # strict=False admite saltos de línea dentro de cadenas
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return error


def dump_ai_response(raw, kind, doc_id):
    """Guarda la respuesta completa de la IA en logs/ai_responses/ para diagnosticar; devuelve la ruta (o None)."""
    try:
        os.makedirs(AI_LOG_FOLDER, exist_ok=True)
        path = os.path.join(AI_LOG_FOLDER, f"{kind}_{doc_id}_{datetime.now():%Y%m%d_%H%M%S}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(raw or "")
        return path
    except OSError:
        app.logger.exception("No se pudo guardar la respuesta de la IA")
        return None


def run_ai_json(run, *args, kind, doc_id):
    """Ejecuta un agente y devuelve su respuesta como diccionario.

    Si la respuesta no se puede interpretar se reintenta una vez; si vuelve a fallar se guarda la respuesta
    completa en un archivo (el log solo lleva la ruta) y se devuelve el diccionario de error.
    Las excepciones del agente (red, cuota, clave…) se propagan: no se reintentan.
    """
    raw, result = "", {"error": True}
    for attempt in (1, 2):
        raw = run(*args)
        result = clean_and_parse_json(raw)
        if not result.get("error"):
            return result
        app.logger.warning("Respuesta de IA no válida (%s, documento %s, intento %d/2).", kind, doc_id, attempt)
    app.logger.warning("Respuesta completa de IA guardada en %s", dump_ai_response(raw, kind, doc_id))
    return result


def ai_agent_enabled(config_key):
    """True si el agente IA está activo en config.json (se lee en cada llamada; por defecto, activo)."""
    return bool(load_config().get(config_key, True))


def simulated_ai_result(kind):
    """Informe 'conforme' sin incoherencias, con el mismo formato que devuelve cada agente real."""
    message = "Document conforme (anàlisi simulada: agent IA desactivat)."
    if kind == "fidelitat":
        return {"fiel": True, "mensaje": message, "incoherencias": [], "simulado": True}
    return {"conforme": True, "missatge": message, "incoherencies": [], "simulado": True}


def reset_ai_analysis(doc):
    """Reinicia todos los análisis de IA del documento."""
    doc["analysis_done"] = False
    doc["analysis_result"] = None
    doc["referente_analysis_result"] = None
    doc["normative_analysis_done"] = False
    doc["normative_analysis_result"] = None
    doc["duplicity_analysis_done"] = False
    doc["duplicity_result"] = None
    doc["fidelity_analysis_done"] = False
    doc["fidelity_analysis_result"] = None


def taxonomy_paths():
    return [f"{n1} > {n2} > {n3}"
            for n1, l2 in TAXONOMY.items() for n2, l3 in l2.items() for n3 in l3]


@app.template_filter("fecha_es")
def fecha_es(value):
    """Fecha ISO (YYYY-MM-DD) -> DD-MM-YYYY para mostrarla; el JSON conserva el formato ISO."""
    try:
        return date.fromisoformat(value).strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return value or ""


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
            flash(f"Benvingut/da, {account['name']}.", "success")
            return redirect(url_for("dashboard"))
        flash("Credencials incorrectes.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Sessió tancada correctament.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    docs = load_documents()
    rows = [{**d, "department": ", ".join(d["departamentos_competentes"]),
             "can_advance": can_advance(d),
             "action": ACTION_LABEL.get(d["status"], ""),
             "badge": STATES.index(d["status"]) + 1 if d["status"] in STATES else 0}
            for d in docs]
    # Más recientes primero: los registros se añaden al final del JSON y los publicados se ordenan por su fecha
    # de publicación (el sort es estable, así que el resto conserva el orden inverso de alta).
    rows.reverse()
    rows.sort(key=lambda d: d.get("fecha_publicacion") or "", reverse=True)
    tabs = [{**t, "docs": [d for d in rows if d["status"] == t["status"]]} for t in TABS]
    return render_template("dashboard.html", tabs=tabs, validation_states=VALIDATION_STATES)


def render_upload(form, selected_sources=(), selected_tipologia=(), selected_departments=(), selected_related=(), origen="", target_doc=None):
    docs = load_documents()
    # Con documento objetivo: publicado = nueva versión; en la bandeja del editor = edición (sin cambiar de versión).
    edit_mode = target_doc is not None and target_doc["status"] != S_PUB
    back_anchor = tab_anchor(target_doc["status"]) if target_doc else ""
    return render_template("upload.html", form=form, taxonomies=taxonomy_paths(),
                           departments=departamentos_competentes(), content_types=CONTENT_TYPES,
                           canales=CANALES, published_docs=[d for d in docs if d["status"] == S_PUB],
                           selected_departments=list(selected_departments), selected_related=list(selected_related),
                           idiomas=IDIOMAS, tipologias=TIPOLOGIAS, selected_tipologia=list(selected_tipologia),
                           base_docs=published_base_docs(docs),
                           selected_sources=list(selected_sources),
                           origen=origen, target_doc=target_doc, edit_mode=edit_mode, back_anchor=back_anchor,
                           extensions=sorted(ALLOWED_EXTENSIONS))


def can_update(doc, edit):
    """¿Admite el documento la operación? Edición: devuelto a su editor; nueva versión: publicado."""
    if doc is None:
        return False
    if edit:
        return doc["status"] in EDITOR_STATES and bool(doc["observations"])
    return doc["status"] == S_PUB


def save_document_update(doc_id, file, fields, user, edit):
    """Guarda los datos del formulario sobre un documento existente.

    `edit=False`: nueva versión de un documento publicado (version += 1, vuelve a la bandeja de su editor).
    `edit=True`: edición de un documento devuelto en la bandeja de su editor (misma versión y mismo estado;
    el motivo de la devolución se mantiene hasta que se apruebe).
    Si llega un archivo nuevo, sustituye al anterior (original, PDF anotados y vectores).
    Devuelve la redirección al dashboard, o None si falla (el aviso ya se ha hecho con flash).
    """
    not_allowed = ("Només es poden editar documents retornats a l'editor." if edit
                   else "Només es pot versionar un document publicat.")
    no_longer = "El document ja no es pot editar." if edit else "El document ja no es pot versionar."
    new_name = None
    if file and file.filename:
        new_name = secure_filename(file.filename)
        if not new_name:
            flash("El nom del fitxer no és vàlid.", "error")
            return None
    folder = app.config["UPLOAD_FOLDER"]
    path = os.path.join(folder, new_name) if new_name else None

    with DOCS_LOCK:  # reserva el nombre: tras guardar el archivo, otro upload igual se detecta
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if not can_update(doc, edit):
            flash(not_allowed, "error")
            return None
        if new_name:
            if filename_exists(new_name, docs, exclude_id=doc_id):
                flash("El fitxer ja s'ha pujat anteriorment", "error")
                return None
            file.save(path)  # si se llama igual que el actual, lo sobrescribe

    # SimHash y embeddings (red) fuera del bloqueo; nunca bloquea si fallan.
    simhash, vector_file = process_document(path, doc_id) if new_name else (None, None)

    def vector_path(vf):
        return os.path.join(BASE_DIR, "vectores", os.path.basename(vf))

    old_paths = []
    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante el procesado
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if not can_update(doc, edit):
            if new_name and (doc is None or doc.get("filename") != new_name) and os.path.exists(path):
                os.remove(path)
            flash(no_longer, "error")
            return None
        if new_name:
            old_name = doc.get("filename")
            if old_name and old_name != new_name:
                old_paths.append(os.path.join(folder, old_name))
            old_paths += [os.path.join(folder, f"{doc_id}_annotated.pdf"),
                          os.path.join(folder, f"{doc_id}_referente_annotated.pdf")]
            # El vector nuevo se llama igual que el antiguo ({id}_vectors.json): solo se borra si no fue reemplazado.
            if doc.get("vector_file") and doc["vector_file"] != vector_file:
                old_paths.append(vector_path(doc["vector_file"]))
            doc["filename"], doc["simhash"], doc["vector_file"] = new_name, simhash, vector_file
        doc.update(fields)
        if not edit:
            doc["version"] = int(doc.get("version", 1)) + 1
            doc["status"] = EDITOR_STATE[doc["content_type"]]
            doc["observations"] = doc["rechazado_por_rol"] = ""
            doc["fecha_publicacion"] = doc["fecha_revision_prevista"] = None  # se rellenan al volver a publicar
            reset_ai_analysis(doc)
        doc["updated_by"] = user["username"]
        try:
            save_documents(docs)  # primero el registro: si falla, no se borra ningún archivo anterior
        except OSError:
            app.logger.exception("No se pudo guardar documents.json al actualizar %s", doc_id)
            flash("No s'han pogut desar els canvis. Torna-ho a provar.", "error")
            return None
        status, version, title = doc["status"], doc["version"], doc["denominacio"]

    for old in old_paths:
        try:
            os.remove(old)
        except FileNotFoundError:
            pass
        except OSError:
            app.logger.exception("No se pudo eliminar %s", old)
    if edit:
        done = f"Document «{title}» actualitzat."
    else:
        done = f"Nova versió {version} creada: el document torna a «{status}»."
    if new_name and not vector_file and load_config().get("embeddings_activos", True):
        flash(done.rstrip(".") + ", però no s'han generat els vectors "
              "(revisa l'API key o la quota de Gemini).", "warning")
    else:
        flash(done, "success")
    return redirect(url_for("dashboard") + tab_anchor(status))


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    user = current_user()
    form = {}
    selected_sources = []
    selected_tipologia = []
    selected_departments, selected_related = [], []
    origen = (request.form.get("origen") if request.method == "POST" else request.args.get("origen", "")) or ""
    origen = origen.strip()

    # Documento objetivo: /upload?versionar=<id> (nueva versión de un publicado) o /upload?editar=<id> (edición de un
    # devuelto). El POST los recibe en `versionar_id` / `editar_id`.
    post = request.method == "POST"
    versionar_id = (request.form.get("versionar_id") if post else request.args.get("versionar")) or ""
    editar_id = "" if versionar_id else (request.form.get("editar_id") if post else request.args.get("editar")) or ""
    edit = bool(editar_id)
    target_id = versionar_id or editar_id
    target_doc = None
    if target_id:
        target_doc = find_doc(load_documents(), target_id)
        if not can_update(target_doc, edit):
            if edit:
                flash("Només es poden editar documents retornats a l'editor.", "error")
                return redirect(url_for("dashboard") + (tab_anchor(target_doc["status"]) if target_doc else ""))
            flash("Només es pot versionar un document publicat.", "error")
            return redirect(url_for("dashboard") + tab_anchor(S_PUB))
        if request.method == "GET":
            form = {"denominacio": target_doc["denominacio"], "content_type": target_doc["content_type"],
                    "idioma": target_doc.get("idioma") or "",
                    "canal": target_doc.get("canal") or "",
                    "taxonomy": target_doc["taxonomy"][0] if target_doc["taxonomy"] else ""}
            selected_tipologia = list(target_doc["tipologia"])
            selected_departments = list(target_doc["departamentos_competentes"])
            selected_sources = list(target_doc["unidades_base_origen"])
            selected_related = list(target_doc["contenidos_relacionados"])

    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("taxonomy", "idioma", "canal")}
        # Familia «Identificación»: todos sus campos son obligatorios.
        form["denominacio"] = request.form.get("denominacio", "").strip()
        form["content_type"] = (target_doc["content_type"] if target_doc  # el tipo no cambia al versionar ni al editar
                                else request.form.get("tipo_contenido", "").strip())
        selected_tipologia = list(dict.fromkeys(request.form.getlist("tipologia")))
        # Familia «Origen y trazabilidad» (listas sin duplicados)
        selected_departments = list(dict.fromkeys(request.form.getlist("departamentos_competentes")))
        selected_sources = list(dict.fromkeys(request.form.getlist("unidades_base_origen")))
        selected_related = list(dict.fromkeys(request.form.getlist("contenidos_relacionados")))
        file = request.files.get("file")
        errors = []
        if not form["denominacio"]:
            errors.append("Falta el camp obligatori «Denominació».")
        if not form["content_type"]:
            errors.append("Falta el camp obligatori «Tipus de contingut».")
        if not form["idioma"]:
            errors.append("Falta el camp obligatori «Idioma».")
        elif form["idioma"] not in IDIOMAS:
            errors.append("L'idioma ha de ser «Català» o «Castellà».")
        if not selected_tipologia:
            errors.append("Falta el camp obligatori «Tipologia»: selecciona almenys una opció.")
        elif any(t not in TIPOLOGIAS for t in selected_tipologia):
            errors.append("Alguna opció de Tipologia no és vàlida.")
        if not file or not file.filename:
            if not target_doc:  # al versionar o editar el archivo es opcional: si no se sube, se mantiene el anterior
                errors.append("Has de seleccionar un fitxer.")
        elif not allowed_file(file.filename):
            errors.append("Tipus de fitxer no permès. Formats vàlids: "
                          + ", ".join(sorted(ALLOWED_EXTENSIONS)) + ".")
        if form["content_type"] and form["content_type"] not in CONTENT_TYPES:
            errors.append("El tipus de contingut no és vàlid.")

        # Reglas por tipo de contenido (los campos que no aplican al tipo se ignoran).
        taxonomy, source, departments, canal = [], [], [], ""
        valid_departments = departamentos_competentes()
        if form["content_type"] in ("Base", "Referenciat"):
            if not selected_departments:
                errors.append("Falta el camp obligatori «Departament competent»: selecciona'n almenys un.")
            elif any(dep not in valid_departments for dep in selected_departments):
                errors.append("Algun departament competent no és vàlid.")
            else:
                departments = selected_departments
            if form["taxonomy"] not in taxonomy_paths():
                errors.append("Selecciona una taxonomia vàlida.")
            taxonomy = [form["taxonomy"]]  # lista de un elemento; la fuente original no aplica
        elif form["content_type"] == "Adaptat":
            # Se ignora cualquier taxonomía manual: se hereda de las unidades base seleccionadas.
            available = {d["id"]: d for d in published_base_docs(load_documents())}
            if not selected_sources:
                errors.append("Falta el camp obligatori «Unitat base d'origen»: selecciona almenys un document base publicat.")
            elif any(i not in available for i in selected_sources):
                errors.append("Alguna unitat base d'origen no és un document base publicat.")
            else:
                source = selected_sources
                taxonomy = list(dict.fromkeys(t for i in source for t in available[i]["taxonomy"]))
                # El departamento tampoco se elige: se hereda de las unidades base (unión sin duplicados).
                departments = list(dict.fromkeys(dep for i in source for dep in available[i]["departamentos_competentes"]))
            if not form["canal"]:
                errors.append("Falta el camp obligatori «Canal».")
            elif form["canal"] not in CANALES:
                errors.append("El canal seleccionat no és vàlid.")
            else:
                canal = form["canal"]

        # Contenidos relacionados (todos los tipos): solo documentos publicados.
        if selected_related:
            published_ids = {d["id"] for d in load_documents() if d["status"] == S_PUB}
            if any(i not in published_ids for i in selected_related):
                errors.append("Algun contingut relacionat no és un document publicat.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_upload(form, selected_sources, selected_tipologia, selected_departments, selected_related, origen, target_doc), 400
        elif target_doc:
            fields = {"denominacio": form["denominacio"], "idioma": form["idioma"], "tipologia": selected_tipologia,
                      "taxonomy": taxonomy, "departamentos_competentes": departments,
                      "unidades_base_origen": source, "canal": canal,
                      "contenidos_relacionados": selected_related}
            response = save_document_update(target_id, file, fields, user, edit)
            if response is not None:
                return response
        else:
            filename = secure_filename(file.filename)
            if not filename:
                flash("El nom del fitxer no és vàlid.", "error")
            else:
                path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                with DOCS_LOCK:  # reserva el nombre: tras guardar el archivo, otro upload igual se detecta
                    duplicate = filename_exists(filename, load_documents())
                    if not duplicate:
                        file.save(path)
                if duplicate:
                    flash("El fitxer ja s'ha pujat anteriorment", "error")
                else:
                    doc_id = next_document_id(form["content_type"], load_documents())
                    # SimHash y embeddings (red) fuera del bloqueo; nunca bloquea la subida si fallan.
                    simhash, vector_file = process_document(path, doc_id)
                    record = {
                        "id": doc_id,
                        "filename": filename,
                        "denominacio": form["denominacio"],
                        "idioma": form["idioma"],
                        "tipologia": selected_tipologia,
                        "taxonomy": taxonomy,
                        "departamentos_competentes": departments,
                        "unidades_base_origen": source,
                        "canal": canal,
                        "contenidos_relacionados": selected_related,
                        "fecha_publicacion": None,
                        "fecha_revision_prevista": None,
                        "content_type": form["content_type"],
                        "version": 1,
                        "observations": "",
                        "rechazado_por_rol": "",
                        "analysis_result": None,
                        "analysis_done": False,
                        "referente_analysis_result": None,
                        "normative_analysis_result": None,
                        "normative_analysis_done": False,
                        "simhash": simhash,
                        "vector_file": vector_file,
                        "duplicity_result": None,
                        "duplicity_analysis_done": False,
                        "fidelity_analysis_result": None,
                        "fidelity_analysis_done": False,
                        "status": EDITOR_STATE[form["content_type"]],
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
                        flash("No s'ha pogut desar el document. Torna-ho a provar.", "error")
                        return render_upload(form, selected_sources, selected_tipologia, selected_departments, selected_related, origen, target_doc)
                    if vector_file or not load_config().get("embeddings_activos", True):
                        flash("Document pujat. El document queda en elaboració.", "success")
                    else:
                        flash("Document pujat en elaboració, però no s'han generat els vectors "
                              "(revisa l'API key o la quota de Gemini).", "warning")
                    return redirect(url_for("dashboard"))

    return render_upload(form, selected_sources, selected_tipologia, selected_departments, selected_related, origen, target_doc)


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
            flash("Aquest document no pot avançar des del seu estat actual.", "error")
            return None
        doc["status"] = new
        doc["observations"] = doc["rechazado_por_rol"] = ""
        if new == S_PUB:
            today = date.today()
            doc["fecha_publicacion"] = today.isoformat()
            doc["fecha_revision_prevista"] = (today + timedelta(days=dias_revision_prevista())).isoformat()
        return f"«{doc['denominacio']}» avançat a: {new}.", "success"
    return change_document(doc_id, action)


@app.route("/rechazar/<doc_id>", methods=["POST"])
@login_required
def rechazar(doc_id):
    reason = request.form.get("motivo", "").strip()[:500]

    def action(doc, _user):
        if doc["status"] not in VALIDATION_STATES:
            flash("Només es poden rebutjar documents en validació.", "error")
            return None
        if not reason:
            flash("Has d'indicar el motiu de la devolució.", "error")
            return None
        role = role_of_status(doc["status"])  # rol que rechaza, antes de cambiar el estado
        doc["status"] = EDITOR_STATE.get(doc["content_type"], S_ED)
        doc["observations"] = reason
        doc["rechazado_por_rol"] = role
        reset_ai_analysis(doc)
        return f"«{doc['denominacio']}» rebutjat per {role} i retornat a: {doc['status']}.", "warning"
    return change_document(doc_id, action)


@app.route("/api/documents/retirar/<doc_id>", methods=["POST"])
def api_retirar(doc_id):
    """Retira un documento publicado: borra sus archivos, su registro y las referencias a él."""
    if current_user() is None:
        return jsonify(success=False, error="Sessió no iniciada."), 401
    with DOCS_LOCK:
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(success=False, error="Document no trobat."), 404
        if doc["status"] != S_PUB:
            return jsonify(success=False, error="Només es pot retirar un document publicat."), 409

        remaining = [d for d in docs if d["id"] != doc_id]
        for other in remaining:  # integridad referencial: sin referencias huérfanas al documento retirado
            for key in ("unidades_base_origen", "contenidos_relacionados"):
                if isinstance(other.get(key), list):
                    other[key] = [i for i in other[key] if i != doc_id]
        try:
            save_documents(remaining)  # primero el registro: si falla, no se borra ningún archivo
        except OSError:
            app.logger.exception("No se pudo guardar documents.json al retirar %s", doc_id)
            return jsonify(success=False, error="No s'ha pogut actualitzar la base documental."), 500

        # Archivos del documento: el original, sus PDF anotados ({id}_...) y su archivo de vectores.
        keep = {"documents.json"} | {d.get("filename") for d in remaining}  # nunca archivos de otros documentos
        folder = app.config["UPLOAD_FOLDER"]
        targets = {doc.get("filename") or ""}
        targets.update(f for f in os.listdir(folder) if f.startswith(f"{doc_id}_"))
        paths = [os.path.join(folder, f) for f in targets if f and f not in keep]
        if doc.get("vector_file"):
            paths.append(os.path.join(BASE_DIR, "vectores", os.path.basename(doc["vector_file"])))
        for path in paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                app.logger.exception("No se pudo eliminar %s", path)
    return jsonify(success=True, message="Document i fitxers associats eliminats correctament",
                   deleted_id=doc_id)


@app.route("/api/analyze/<doc_id>", methods=["POST"])
def api_analyze(doc_id):
    """Audita con IA la claridad y coherencia de un PDF y guarda el resultado."""
    if current_user() is None:
        return jsonify(ok=False, error="Sessió no iniciada."), 401
    doc = find_doc(load_documents(), doc_id)
    if doc is None:
        return jsonify(ok=False, error="Document no trobat."), 404
    if doc["status"] != S_RD:
        return jsonify(ok=False, error="El document no està pendent del Referent Departamental."), 409
    filename = doc.get("filename") or ""
    if not filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Només es poden analitzar documents PDF."), 400
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    simulated = not ai_agent_enabled("agente_claridad_activo")
    if not simulated:
        if not os.path.isfile(path):
            return jsonify(ok=False, error="Fitxer físic no disponible"), 404
        api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
        if not api_key or "tu_api_key" in api_key:
            return jsonify(ok=False, error="Falta configurar GEMINI_API_KEY (o GOOGLE_API_KEY) al fitxer .env."), 503

    try:
        if simulated:
            result = simulated_ai_result("claredat")
        else:
            from agents.reviewer_agent import run_review  # import diferido: la app arranca sin la IA
            result = run_ai_json(run_review, path, kind="claredat", doc_id=doc_id)
    except Exception as exc:
        app.logger.exception("Fallo en el análisis IA de %s", doc_id)
        return jsonify(ok=False, error=f"No s'ha pogut completar l'anàlisi: {exc}"), 502
    if result.get("error"):  # respuesta no parseable: no se guarda como completada
        return jsonify(ok=False, error=result["mensaje"]), 502

    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante la llamada al modelo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El document ja no existeix."), 404
        doc["referente_analysis_result"] = result
        doc["analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, referente_analysis_result=result)


@app.route("/api/validate_normative/<doc_id>", methods=["POST"])
def api_validate_normative(doc_id):
    """Valida con IA un PDF contra la normativa de normativa/ y guarda el resultado."""
    if current_user() is None:
        return jsonify(ok=False, error="Sessió no iniciada."), 401
    doc = find_doc(load_documents(), doc_id)
    if doc is None:
        return jsonify(ok=False, error="Document no trobat."), 404
    if doc["status"] != S_UF:
        return jsonify(ok=False, error="El document no està pendent de la Unitat Finalista."), 409
    filename = doc.get("filename") or ""
    if not filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Només es poden validar documents PDF."), 400
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    simulated = not ai_agent_enabled("agente_normativa_activo")
    if not simulated:
        if not os.path.isfile(path):
            return jsonify(ok=False, error="Fitxer físic no disponible"), 404
        api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
        if not api_key or "tu_api_key" in api_key:
            return jsonify(ok=False, error="Falta configurar GEMINI_API_KEY (o GOOGLE_API_KEY) al fitxer .env."), 503

    try:
        if simulated:
            result = simulated_ai_result("normativa")
        else:
            from agents.tools import list_normative_pdfs
            if not list_normative_pdfs():
                return jsonify(ok=False, error="No hi ha lleis carregades a la carpeta normativa/. "
                                               "Afegeix fitxers PDF de normativa i torna-ho a provar."), 409
            from agents.normative_agent import run_normative_review  # import diferido
            result = run_ai_json(run_normative_review, path, kind="normativa", doc_id=doc_id)
    except Exception as exc:
        app.logger.exception("Fallo en la validación normativa de %s", doc_id)
        return jsonify(ok=False, error=f"No s'ha pogut completar la validació: {exc}"), 502
    if result.get("error"):  # respuesta no parseable: no se guarda como completada
        return jsonify(ok=False, error=result["mensaje"]), 502

    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante la llamada al modelo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El document ja no existeix."), 404
        doc["normative_analysis_result"] = result
        doc["normative_analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, normative_analysis_result=result)


@app.route("/api/detect_duplicity/<doc_id>", methods=["POST"])
def api_detect_duplicity(doc_id):
    """Detecta duplicidades (SimHash + similitud vectorial) y guarda el resultado."""
    if current_user() is None:
        return jsonify(ok=False, error="Sessió no iniciada."), 401
    docs = load_documents()
    doc = find_doc(docs, doc_id)
    if doc is None:
        return jsonify(ok=False, error="Document no trobat."), 404
    if doc["status"] != S_GCB:
        return jsonify(ok=False, error="El document no està pendent del Gestor Coneixement Cord."), 409
    try:
        result = gestor_conocimiento.detect_document_duplicity(
            doc_id, docs, vectors_dir=os.path.join(BASE_DIR, "vectores"),
            config_path=os.path.join(BASE_DIR, "config.json"))
    except Exception as exc:
        app.logger.exception("Fallo en la detección de duplicidades de %s", doc_id)
        return jsonify(ok=False, error=f"No s'ha pogut completar la detecció: {exc}"), 500

    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante el cálculo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El document ja no existeix."), 404
        doc["duplicity_result"] = result
        doc["duplicity_analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, duplicity_result=result)


@app.route("/api/check_fidelity/<doc_id>", methods=["POST"])
def api_check_fidelity(doc_id):
    """Comprueba con IA la fidelidad de un documento Adaptado respecto a sus fuentes Base."""
    if current_user() is None:
        return jsonify(ok=False, error="Sessió no iniciada."), 401
    docs = load_documents()
    doc = find_doc(docs, doc_id)
    if doc is None:
        return jsonify(ok=False, error="Document no trobat."), 404
    if doc["status"] != S_GCC:
        return jsonify(ok=False, error="El document no està pendent del Gestor Coneixement Canal."), 409
    folder = app.config["UPLOAD_FOLDER"]
    filename = doc.get("filename") or ""
    adapted_path = os.path.join(folder, filename)
    if not filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Només es poden comprovar documents PDF."), 400
    simulated = not ai_agent_enabled("agente_fidelidad_activo")
    if simulated:
        return save_fidelity_result(doc_id, simulated_ai_result("fidelitat"))
    if not os.path.isfile(adapted_path):
        return jsonify(ok=False, error="Fitxer físic no disponible"), 404

    sources = doc.get("unidades_base_origen") if isinstance(doc.get("unidades_base_origen"), list) else []
    if not sources:
        return jsonify(ok=False, error="Aquest document no té documents font associats; "
                                       "no hi ha res amb què comprovar-ne la fidelitat."), 409
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
        return jsonify(ok=False, error="Cap dels documents font té un PDF disponible."), 409
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key or "tu_api_key" in api_key:
        return jsonify(ok=False, error="Falta configurar GEMINI_API_KEY (o GOOGLE_API_KEY) al fitxer .env."), 503

    try:
        from agents.comprobar_fidelidad import run_fidelity_check  # import diferido
        result = run_ai_json(run_fidelity_check, adapted_path, source_paths, kind="fidelitat", doc_id=doc_id)
    except Exception as exc:
        app.logger.exception("Fallo en la comprobación de fidelidad de %s", doc_id)
        return jsonify(ok=False, error=f"No s'ha pogut completar la comprovació: {exc}"), 502
    if result.get("error"):  # respuesta no parseable: no se guarda como completada
        return jsonify(ok=False, error=result["mensaje"]), 502
    if missing:
        result["nota"] = f"{missing} document(s) font no s'han pogut incloure perquè no tenen un PDF disponible."
    return save_fidelity_result(doc_id, result)


def save_fidelity_result(doc_id, result):
    with DOCS_LOCK:  # se vuelve a leer: el JSON pudo cambiar durante la llamada al modelo
        docs = load_documents()
        doc = find_doc(docs, doc_id)
        if doc is None:
            return jsonify(ok=False, error="El document ja no existeix."), 404
        doc["fidelity_analysis_result"] = result
        doc["fidelity_analysis_done"] = True
        save_documents(docs)
    return jsonify(ok=True, fidelity_analysis_result=result)


ANNOTATED_RE = re.compile(r"(?:BCAC-[AB]-\d+|[0-9a-f]{8})(_referente)?_annotated\.pdf")  # ID actual o anterior (8 hex)


def incoherencias_of(result):
    """Lista de incoherencias de un resultado de IA (JSON); [] si no hay o el formato es antiguo."""
    if not isinstance(result, dict):
        return []
    items = result.get("incoherencies") or result.get("incoherencias") or []
    return [i for i in items if isinstance(i, dict)]


@app.route("/api/generate_annotated_pdf/<doc_id>", methods=["POST"])
def api_generate_annotated_pdf(doc_id):
    """Genera uploads/{doc_id}_annotated.pdf con las incoherencias de la IA resaltadas."""
    if current_user() is None:
        return jsonify(ok=False, error="Sessió no iniciada."), 401
    doc = find_doc(load_documents(), doc_id)
    if doc is None:
        return jsonify(ok=False, error="Document no trobat."), 404

    results = {"normative": doc.get("normative_analysis_result"), "fidelity": doc.get("fidelity_analysis_result"),
               "referente": doc.get("referente_analysis_result")}
    result_fields = {"normative": "normative_analysis_result", "fidelity": "fidelity_analysis_result",
                     "referente": "referente_analysis_result"}
    kind = request.form.get("kind")
    if kind not in results:  # sin indicar: el análisis disponible (el de su fase tiene prioridad)
        order = {S_GCC: ["fidelity", "normative", "referente"], S_RD: ["referente", "normative", "fidelity"]}
        kind = next((k for k in order.get(doc["status"], ["normative", "fidelity", "referente"]) if results[k]), None)
    if not kind or not results[kind]:
        return jsonify(ok=False, error="El document no té cap anàlisi d'IA previ."), 400
    incoherencias = incoherencias_of(results[kind])
    if not incoherencias:
        return jsonify(ok=False, error="L'anàlisi no conté incoherències per anotar."), 400

    filename = doc.get("filename") or ""
    original = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="Només es poden anotar documents PDF."), 400
    if not os.path.isfile(original):
        return jsonify(ok=False, error="Fitxer físic no disponible"), 404

    # El informe de claridad (Referente) tiene su propio PDF y su propio formato de recuadro.
    annotated_name = f"{doc_id}_referente_annotated.pdf" if kind == "referente" else f"{doc_id}_annotated.pdf"
    annotated = os.path.join(app.config["UPLOAD_FOLDER"], annotated_name)
    annotator = annotate_referente_pdf if kind == "referente" else annotate_pdf_with_ai_results
    saved, enriched = annotator(original, annotated, incoherencias)
    if not saved:
        return jsonify(ok=False, error="No s'ha pogut localitzar cap de les frases analitzades al PDF "
                                       "(és un document escanejat o el text difereix?)."), 422
    pages = [i.get("page_number") for i in enriched]
    found = sum(1 for n in pages if n)
    message = f"S'han anotat {found} de {len(pages)} frases."
    if found < len(pages):
        message += " Les restants no s'han localitzat literalment al PDF."

    with DOCS_LOCK:  # se guardan las páginas junto a cada hallazgo para poder navegar sin regenerar
        docs = load_documents()
        stored = find_doc(docs, doc_id)
        if stored is not None:
            field = result_fields[kind]
            for item, page_number in zip(incoherencias_of(stored.get(field)), pages):
                item["page_number"] = page_number
            save_documents(docs)
    version = int(os.path.getmtime(annotated))  # evita que el navegador muestre una versión en caché
    return jsonify(ok=True, pdf_url=url_for("serve_annotated", filename=annotated_name, v=version),
                   mensaje=message, incoherencias=enriched)


@app.route("/uploads/<path:filename>")
@login_required
def serve_annotated(filename):
    """Sirve solo los PDF anotados; nunca documents.json ni el resto de uploads/."""
    if not ANNOTATED_RE.fullmatch(filename):
        abort(404)
    if not os.path.isfile(os.path.join(app.config["UPLOAD_FOLDER"], filename)):
        abort(404)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, mimetype="application/pdf")


@app.route("/download/<doc_id>")
@login_required
def download(doc_id):
    doc = find_doc(load_documents(), doc_id)
    if doc is None:
        abort(404)
    path = os.path.join(app.config["UPLOAD_FOLDER"], doc.get("filename") or "")
    if not doc.get("filename") or not os.path.isfile(path):
        flash("Fitxer físic no disponible", "error")
        return redirect(url_for("dashboard"))
    return send_from_directory(app.config["UPLOAD_FOLDER"], doc["filename"])


@app.errorhandler(413)
def too_large(_e):
    flash("El fitxer supera la mida màxima permesa (16 MB).", "error")
    return redirect(url_for("upload"))


@app.errorhandler(403)
def forbidden(_e):
    flash("No tens permís per accedir a aquest recurs.", "error")
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


@app.errorhandler(404)
def not_found(_e):
    flash("Recurs no trobat.", "error")
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
