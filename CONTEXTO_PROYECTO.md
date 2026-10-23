# BCAC POC · Contexto técnico completo del proyecto

> **Para quién es este documento:** una IA (o una persona) que, a partir de este contenido, deba redactar
> instrucciones de modificación del código sin tener acceso previo al repositorio. Describe el estado **real**
> del código en la fecha de generación, su estructura, los contratos entre módulos y las trampas conocidas.
>
> - **Fecha de actualización:** 2026-10-21
> - **Estado del repositorio:** rama `main`, último commit `v0.4` (`1d06581`) **más cambios sin confirmar** de la refactorización
>   «bandejas de edición + máquina de estados de 7 estados» (`app.py`, `dashboard.html`, `upload.html`, `style.css`). Este documento describe el código con esos cambios.
> - **Leer primero la sección 15** («Estado del repositorio y discrepancias»): hay funcionalidades de iteraciones anteriores que **no** están en el código.

---

## 1. Qué es el proyecto

POC (prueba de concepto) de una herramienta de **gestión documental con gobernanza** (BCAC, para la Generalitat
de Catalunya, desarrollada por Ayesa Digital). Permite:

1. **Subir documentos** (sobre todo PDF) con metadatos estructurados.
2. Hacerlos pasar por un **flujo de validación por fases** (máquina de estados) con bandejas por rol.
3. Auditar los documentos con **agentes de IA** (Google ADK + Gemini): claridad, cumplimiento normativo y
   fidelidad de las adaptaciones respecto a sus documentos base.
4. Detectar **duplicidades** entre documentos publicados (SimHash + similitud de embeddings).
5. Ver los hallazgos de la IA como **tarjetas** y sobre un **PDF anotado** (resaltados + recuadros al margen).
6. **Publicar**, **versionar** o **retirar** (borrado físico) documentos.

Características de diseño de la POC:

- **Un único usuario** (`admin` / `gencat`), definido en el código. Los «roles» son solo **pestañas** del dashboard;
  no hay control de permisos por rol.
- **Sin base de datos**: todo se persiste en `uploads/documents.json` (lista de diccionarios) más archivos en disco.
- **Interfaz (plantillas, mensajes `flash`/JSON de error, informes de duplicidades, textos del PDF anotado) en catalán**; los agentes de IA responden en catalán. **Comentarios del código y este documento, en español.**
  Los valores que se guardan en el JSON (estados, tipos de contenido, idioma, tipologías, canales, departamentos, taxonomía) también están en catalán. **No hay migración de datos antiguos**: la aplicación arranca siempre con una base de documentos nueva, así que los valores guardados deben coincidir con los catálogos actuales de `app.py`.
  Los mensajes de log (`app.logger`) siguen en español (son para el desarrollador).
- Aplicación Flask de un solo proceso; sin tests automatizados.

---

## 2. Stack, ejecución y configuración

| Aspecto | Valor |
|---|---|
| Lenguaje | Python 3 (entorno en `.venv`, Python 3.14 en la máquina de desarrollo) |
| Backend | Flask ≥ 3.0 (plantillas Jinja2, sesiones de cookie) |
| IA | `google-adk` (agentes `LlmAgent`) con modelo `gemini-2.5-flash`; `google-genai` (llega con ADK) para embeddings |
| PDF | `pdfplumber` (extraer texto), `PyMuPDF` (`pymupdf`, anotar PDF) |
| Duplicidades | `simhash`, `numpy` |
| Config | `python-dotenv` (`.env`), `config.json` |
| Frontend | HTML5 + CSS3 + **JavaScript vanilla** (sin frameworks ni bundler; sin librerías externas hoy) |
| SO de desarrollo | macOS |

`requirements.txt`: `Flask>=3.0,<4.0`, `google-adk`, `pdfplumber`, `python-dotenv`, `simhash`, `numpy`, `PyMuPDF`.

**Arranque** (macOS):

```bash
cd gencat-bcac-poc
source .venv/bin/activate        # o: python3 -m venv .venv && pip install -r requirements.txt
python app.py                    # http://127.0.0.1:5000  (debug=True)
```

Tras cambiar código Python hay que **reiniciar** el servidor; tras cambiar CSS/JS inline, recargar con `Cmd+Shift+R`.

**`.env`** (no se versiona; hay un `.env.example`):

- `GEMINI_API_KEY` (o `GOOGLE_API_KEY`): clave de Gemini. Las rutas de IA aceptan cualquiera de las dos.
- `GOOGLE_GENAI_USE_ENTERPRISE`: variable del SDK de Google.
- `SECRET_KEY` (opcional; por defecto `poc-bcac-clave-solo-demo`).
- `agents/runner.py` copia `GEMINI_API_KEY` → `GOOGLE_API_KEY` si esta última no existe (el SDK lee `GOOGLE_API_KEY`).

**`config.json`** (raíz; lo leen `app.py`, `pipeline.py` y `gestor_conocimiento.py`):

```json
{
  "chunk_size": 1000,
  "chunk_overlap": 100,
  "embedding_model": "gemini-embedding-001",
  "simhash_max_distance": 3,
  "vector_similarity_threshold": 0.95,
  "dias_revision_prevista": 150,
  "departamentos_competentes": ["Drets Socials i Famílies", "Economia i Hisenda",
                                "Territori i Habitatge", "Atenció Ciutadana"]
}
```

- `embedding_model`: **no usar `text-embedding-004`** (la API ya devuelve 404); `gemini-embedding-001` funciona (3072 dimensiones).
- `dias_revision_prevista` (entero ≥ 0): días que se suman a la fecha de publicación para `fecha_revision_prevista`. Se relee en cada publicación (`dias_revision_prevista()`); si falta o no es válido se usan 150 y se avisa en el log.
- `departamentos_competentes` se relee en cada petición (`departamentos_competentes()` en `app.py`); el resto de claves lo
  leen los módulos al procesar.

---

## 3. Estructura de carpetas y archivos

```
gencat-bcac-poc/
├── app.py                    # Aplicación Flask: constantes, persistencia, rutas, validaciones (≈1060 líneas)
├── pipeline.py               # Preprocesado al subir: texto → SimHash → chunks → embeddings → vectores/
├── gestor_conocimiento.py    # Detección de duplicidades (SimHash + coseno de centroides)
├── pdf_annotator.py          # Generación de PDF anotado con PyMuPDF
├── config.json               # Umbrales, modelo de embeddings, lista de departamentos
├── requirements.txt
├── .env / .env.example       # Claves (no versionar .env)
├── .gitignore                # Ignora .venv, uploads/*, vectores/*, logs/, .env, __pycache__ (conserva .gitkeep)
├── CONTEXTO_PROYECTO.md      # Este documento
├── agents/
│   ├── runner.py             # Ejecutor síncrono de un agente ADK (run_agent); tope de 25 llamadas al modelo
│   ├── schemas.py            # Esquemas Pydantic de salida de los 3 agentes (output_schema) y límite de tokens
│   ├── tools.py              # Herramientas del LLM: read_pdf, read_all_normative_pdfs, read_multiple_pdfs
│   ├── reviewer_agent.py     # Agente de claridad (pestaña Referente)  -> run_review()
│   ├── normative_agent.py    # Agente normativo (Validador Finalista)  -> run_normative_review()
│   └── comprobar_fidelidad.py# Agente de fidelidad (Gestor Canal)      -> run_fidelity_check()
├── templates/
│   ├── base.html             # Cabecera (logo Gencat, usuario, logout), mensajes flash
│   ├── login.html
│   ├── dashboard.html        # Pestañas, tablas, filas desplegables y TODO el JavaScript del panel (≈740 líneas)
│   └── upload.html           # Formulario de alta por familias + JS de campos dinámicos
├── static/
│   ├── css/style.css         # Un único CSS (variables en :root)
│   └── img/ logo.png, logo_ayesa.png
├── uploads/                  # Archivos subidos + documents.json (BASE DE DATOS) + PDF anotados generados
├── vectores/                 # {doc_id}_vectors.json (embeddings por chunk)
├── logs/ai_responses/        # (se crea al fallar) respuestas completas de la IA no interpretables; fuera de git
└── normativa/                # PDF de leyes/normas que usa el agente normativo
```

Notas:
- `uploads/`, `vectores/` y su contenido no se versionan (solo `.gitkeep`). La normativa de ejemplo sí está en el árbol.
- `base.html` ya **no** incluye el pie con el logo de Ayesa (el CSS `.site-footer`/`.footer-logo` sigue existiendo).
- `agents/__init__.py` está vacío. Los agentes se importan **de forma diferida** dentro de las rutas para que la app
  arranque aunque falle la IA.

---

## 4. Modelo de datos (`uploads/documents.json`)

`documents.json` es una **lista JSON** de documentos. Se lee con `load_documents()` (aplica `normalize()` a cada registro)
y se escribe con `save_documents()` (escritura atómica: fichero temporal + `os.replace`, indentación 2, `ensure_ascii=False`).
Todo acceso de lectura-modificación-escritura se hace bajo `DOCS_LOCK` (`threading.RLock`).

Si el JSON está corrupto se renombra a `documents.json.corrupt` y se reinicia como `[]`. Si no existe, se crea como `[]`.

### 4.1 Campos de un documento (estructura **plana**, en la raíz del registro)

| Campo | Tipo | Origen / significado |
|---|---|---|
| `id` | str (8 hex) | `uuid.uuid4().hex[:8]` al subir |
| `filename` | str | Nombre guardado en `uploads/` (`secure_filename`, **sin prefijo**; único) |
| `title` | str | Formulario `titulo` |
| `idioma` | str | `"Català"` o `"Castellà"` |
| `tipologia` | list[str] | Subconjunto de `TIPOLOGIAS` (≥ 1) |
| `taxonomy` | list[str] | Base: `[taxonomía elegida]`. Adaptat: unión (sin duplicados) de las de sus unidades base. Rutas `N1 > N2 > N3` |
| `departamentos_competentes` | list[str] | Base y Referenciat (≥ 1); vacío en Adaptat |
| `unidades_base_origen` | list[str] | IDs de documentos Base **publicados**; solo Adaptat (≥ 1) |
| `canal` | str | `WEB`, `Xarxes`, `Presencial`, `012`; solo Adaptat, `""` en los demás |
| `contenidos_relacionados` | list[str] | IDs de documentos publicados (opcional, todos los tipos) |
| `fecha_publicacion` | str `YYYY-MM-DD` \| null | Fecha en que el documento pasó a `S_PUB` (la pone `avanzar_estado`); `null` mientras no esté publicado |
| `fecha_revision_prevista` | str `YYYY-MM-DD` \| null | `fecha_publicacion` + `dias_revision_prevista` (config.json, 150 por defecto); `null` mientras no esté publicado |
| `content_type` | str | `Base` \| `Adaptat` \| `Referenciat` (Referenciat = mismo circuito y reglas que Base) |
| `version` | int | Empieza en 1; cada nueva versión (`/upload?versionar=<id>`) suma 1 |
| `status` | str | Estado actual del flujo (ver sección 5), en catalán |
| `observations` | str | Motivo de la última devolución (rechazo); vacío al avanzar o versionar. Se muestra como `.obs-alert` en las bandejas de editor |
| `updated_by` | str | Usuario que hizo la última acción |
| `simhash` | str \| null | Huella SimHash (hex, 16 dígitos) calculada al subir un PDF con texto |
| `vector_file` | str \| null | Ruta relativa `vectores/{id}_vectors.json`, o `null` si falló la IA |
| `analysis_result` | str \| null | **Heredado**: informe de claridad antiguo en Markdown |
| `analysis_done` | bool | El análisis de claridad se ha ejecutado |
| `referente_analysis_result` | dict \| null | Informe de claridad (JSON, ver sección 13) |
| `normative_analysis_result` / `normative_analysis_done` | dict \| null / bool | Informe normativo |
| `duplicity_result` / `duplicity_analysis_done` | str (Markdown) \| null / bool | Informe de duplicidades |
| `fidelity_analysis_result` / `fidelity_analysis_done` | dict \| null / bool | Informe de fidelidad |

Los `incoherencies` de los informes JSON ganan un campo `page_number` (int o `null`) cuando se genera el PDF anotado.

### 4.2 `normalize()` (valores por defecto al leer)

Se ejecuta en cada lectura y **no** reescribe el fichero por sí sola (se persiste en la siguiente escritura). Solo rellena con `setdefault` los campos que falten
(`content_type`, `idioma`, `tipologia`, `taxonomy`, `unidades_base_origen`, `departamentos_competentes`, `canal`, `fecha_publicacion`, `fecha_revision_prevista`, `contenidos_relacionados`, `version`, `observations`,
resultados de IA y sus flags…). **No hay tablas `LEGACY_*` ni conversión de formatos antiguos** (se eliminaron: no existen datos que migrar).

> **Atención:** el código **no tolera** estados que no conozca. Un documento con un `status` fuera de `STATES`/`TABS`
> existe en el JSON pero **no aparece en ninguna pestaña** (ver sección 15).

### 4.3 Otros ficheros de datos

- `vectores/{id}_vectors.json`: lista de vectores (`list[list[float]]`), **un vector por chunk**, sin metadatos.
- `uploads/{id}_annotated.pdf` y `uploads/{id}_referente_annotated.pdf`: PDF anotados generados bajo demanda (se sobrescriben).
- Prevención de duplicados: `filename_exists()` compara el nombre (sin distinguir mayúsculas) contra `documents.json` **y** contra
  cualquier archivo de `uploads/`. Un archivo de `uploads/` que no figure en el JSON se ignora en la interfaz.

---

## 5. Dominio: tipos, estados, flujos y pestañas

### 5.1 Tipos de contenido (`CONTENT_TYPES = ["Base", "Adaptat", "Referenciat"]`)

- **Base**: contenido original. Requiere departamento(s) competente(s) y taxonomía propia.
- **Referenciat**: mismas reglas de alta y **mismo flujo** que Base (departamento ≥ 1 y taxonomía válida). Ojo: el selector de tipo de `/upload?origen=editor-departamental` solo ofrece **Base**, así que hoy Referenciat solo se puede elegir al entrar en `/upload` sin `origen` (el servidor sí lo acepta).
- **Adaptat**: adaptación de uno o varios Base **publicados** a un canal. Hereda la taxonomía; requiere canal. Solo los `Base` publicados valen como fuente.

### 5.2 Estados (constantes de `app.py`)

| Constante | Valor | `badge-N` |
|---|---|---|
| `S_ED` | `En elaboració - Editor Departamental` | 1 |
| `S_EC` | `En elaboració - Editor Canal` | 2 |
| `S_RD` | `En validació - Pdt. Referent Departamental` | 3 |
| `S_UF` | `En validació - Pdt. Unitat Finalista` | 4 |
| `S_GCB` | `En validació - Pdt. Gestor Coneixement Base` | 5 |
| `S_GCC` | `En validació - Pdt. Gestor Coneixement Canal` | 6 |
| `S_PUB` | `Publicat` | 7 |

`STATES = [S_ED, S_EC, S_RD, S_UF, S_GCB, S_GCC, S_PUB]` (el índice+1 da la clase CSS `badge-N`).
`VALIDATION_STATES = {S_RD, S_UF, S_GCB, S_GCC}` (aquí se puede **rechazar**).
`EDITOR_STATE = {"Base": S_ED, "Referenciat": S_ED, "Adaptat": S_EC}`: estado inicial al subir y destino de rechazar/versionar.

### 5.3 Flujos (`FLOWS`)

```
Base         : En elaboració Ed. Dep. → Pdt. Referent Dep. → Pdt. Unitat Finalista → Pdt. Gestor Coneixement Base → Publicat
Referenciat : (idéntico a Base)
Adaptat     : En elaboració Ed. Canal → Pdt. Gestor Coneixement Canal → Publicat
```

`next_status(doc)` devuelve el siguiente estado del flujo del `content_type` o `None`; `can_advance(doc)` = `next_status is not None`.
Todas las acciones de avance se llaman «Aprovar» (`ACTION_LABEL`).

### 5.4 Pestañas del dashboard (`TABS`, 7, en este orden)

| Pestaña (`role`) | `slug` | Muestra documentos en | Acciones y botones de IA |
|---|---|---|---|
| Editor Departamental | `editor-departamental` | `S_ED` | «Edita» (solo si el documento fue devuelto, es decir, tiene `observations`), Aprovar, enlace «Puja un nou document» (`/upload?origen=editor-departamental`). Sin rechazar ni IA |
| Editor Canal | `editor-canal` | `S_EC` | «Edita» (solo si fue devuelto), Aprovar, enlace «Puja un nou document» (`?origen=editor-canal`). Sin rechazar ni IA |
| Referent Departamental | `referent-departamental` | `S_RD` | Aprovar, Rebutja, «Analitzar amb IA» (claridad, solo PDF). Sin enlace de subida |
| Validador Finalista | `validador-finalista` | `S_UF` | Aprovar, Rebutja, «Validació normativa» (solo PDF). Sin enlace de subida |
| Gestor Coneixement Base | `gestor-coneixement-base` | `S_GCB` | Aprovar, Rebutja, «Detecció de duplicitats» |
| Gestor Coneixement Canal | `gestor-coneixement-canal` | `S_GCC` | Aprovar, Rebutja, «Comprovar Fidelitat» |
| Publicats | `publicats` | `S_PUB` | «Crea una nova versió» (enlace a `/upload?versionar=<id>`), «Retira el contingut» (borrado definitivo) |

Todas las filas tienen además «Veure Document Original» (si el archivo es pdf/png/jpg/jpeg/txt).

### 5.5 Reglas de transición

- **Avanzar** (`/avanzar_estado`): pasa al siguiente estado del flujo y vacía `observations`. Si el destino es `S_PUB`, rellena `fecha_publicacion` (hoy) y `fecha_revision_prevista` (hoy + `dias_revision_prevista`).
- **Rechazar** (`/rechazar`): solo desde `VALIDATION_STATES`; exige motivo (≤ 500 caracteres); devuelve a `EDITOR_STATE[content_type]` (`S_ED` para Base/Referenciat, `S_EC` para Adaptat),
  guarda `observations` y llama a `reset_ai_analysis(doc)`, que **reinicia los cuatro análisis de IA** (claridad —`analysis_*` y `referente_analysis_result`—, normativo, duplicidad y fidelidad).
- **Versionar** (`GET/POST /upload?versionar=<id>`, ver 7.2): solo desde `S_PUB`. El enlace de la pestaña Publicados abre el formulario de alta con los datos precargados;
  al enviarlo se hace `version += 1`, el documento vuelve a `EDITOR_STATE[content_type]`, `observations = ""`, `fecha_publicacion` y `fecha_revision_prevista` a `null` (se rellenan al volver a publicar) y `reset_ai_analysis`. No existe ya la ruta `/versionar`.
- **Editar** (`GET/POST /upload?editar=<id>`, ver 7.2.1): solo en `S_ED`/`S_EC` y **solo si el documento fue devuelto** (`observations` no vacío). Abre el mismo formulario que «nueva versión» con los datos precargados;
  al guardar **no** cambia `version`, ni `status`, ni `observations` (el motivo de devolución se mantiene hasta «Aprovar», que lo vacía), ni toca los informes de IA (ya se reiniciaron al devolver).
- **Retirar** (`/api/documents/retirar`): solo desde `S_PUB`; **borra** el registro, los archivos y las referencias (ver 7.6). No existe estado «Retirada»/«Archivo».
- Tras cualquier acción de estado la app redirige a `/dashboard#<slug>` de la pestaña de origen (`tab_anchor`).

---

## 6. Backend: organización de `app.py`

Orden de secciones del archivo:

1. **Imports y configuración** (`BASE_DIR`, `load_dotenv`, `UPLOAD_FOLDER`, `ALLOWED_EXTENSIONS`, `app.config`, `DOCS_LOCK`). Subida máx. 16 MB (`MAX_CONTENT_LENGTH`).
2. **Datos de referencia**: `USERS`, constantes de estado, `CONTENT_TYPES`, `FLOWS`, `VALIDATION_STATES`, `TABS`, `ACTION_LABEL`, `EDITOR_STATE`,
   `TAXONOMY` (árbol N1>N2>N3), `IDIOMAS`, `TIPOLOGIAS`, `CANALES`, `DEPARTMENTS` (valor por defecto)
   y `departamentos_competentes()` (lee `config.json`).
3. **Persistencia**: `ensure_documents_file`, `write_json`, `normalize`, `load_documents`, `save_documents`.
4. **Utilidades**: `allowed_file`, `current_user`, `login_required`, `find_doc`, `filename_exists`, `next_status`, `can_advance`,
   `tab_anchor`, `published_base_docs`, `clean_and_parse_json`, `run_ai_json`, `dump_ai_response`, `reset_ai_analysis`, `taxonomy_paths`, `inject_globals` (context processor: `user`, `STATES`). Filtro de plantilla `fecha_es` (ISO → `DD-MM-YYYY`).
5. **Rutas** (ver 7).

### Patrones que se repiten

- **`change_document(doc_id, action)`**: lee→localiza→ejecuta `action(doc, user)`→guarda→`flash`→redirige a la pestaña de origen. Lo usan
  `avanzar_estado` y `rechazar`. La `action` devuelve `(mensaje, categoría)` o `None` (no guarda).
- **Rutas API de IA**: comprobar sesión (JSON 401) → documento (404) → estado válido (409) → archivo PDF existente → clave API (503)
  → **ejecutar fuera del bloqueo** (llamada lenta) → `run_ai_json` (agente + `clean_and_parse_json`, con **un reintento**) → si `error`: 502 sin guardar → **releer bajo el bloqueo**,
  guardar resultado y flag `*_done` → `jsonify(ok=True, <clave>=resultado)`.
- **Errores en JSON** de las rutas `/api/...`: `{"ok": false, "error": "..."}` (la de retirar usa `{"success": false, "error": ...}`).
- Los manejadores `413/403/404` hacen `flash` + redirección (no devuelven JSON).
- **Validación de formularios**: se acumula `errors`, se hace `flash` de cada uno y se vuelve a renderizar el formulario con **HTTP 400** conservando lo escrito.

---

## 7. Rutas y endpoints

`login_required` = redirige a `/login` con aviso. «API» = comprueba la sesión a mano y responde JSON.

| Método y URL | Auth | Qué hace |
|---|---|---|
| `GET/POST /` y `/login` | no | Login (`admin`/`gencat`). Si ya hay sesión redirige al dashboard |
| `GET /logout` | no | Cierra sesión |
| `GET /dashboard` | sí | Construye las filas (ver 7.1) y renderiza `dashboard.html` con `tabs` y `validation_states` |
| `GET/POST /upload` | sí | Formulario de alta y su procesamiento (ver 7.2). Acepta `?origen=` (GET) o campo oculto `origen` (POST); `?versionar=<id>` / campo oculto `versionar_id` activan el modo «nueva versión»; `?editar=<id>` / `editar_id` el modo «edición» de un documento devuelto |
| `POST /avanzar_estado/<id>` | sí | Avanza al siguiente estado del flujo |
| `POST /rechazar/<id>` | sí | Form `motivo`; devuelve al editor del tipo y reinicia la IA |
| `POST /api/documents/retirar/<id>` | API | Borrado físico + lógico + integridad referencial (ver 7.6) |
| `POST /api/analyze/<id>` | API | Exige estado `S_RD` (409 si no). Claridad (agente Referente). Guarda `referente_analysis_result` y `analysis_done`. Respuesta `{ok, referente_analysis_result}` |
| `POST /api/validate_normative/<id>` | API | Exige estado `S_UF` y PDFs en `normativa/` (409 si no hay). Guarda `normative_analysis_result`. Respuesta `{ok, normative_analysis_result}` |
| `POST /api/detect_duplicity/<id>` | API | Exige `S_GCB`. Sin IA; llama a `gestor_conocimiento`. Guarda `duplicity_result` (Markdown). Respuesta `{ok, duplicity_result}` |
| `POST /api/check_fidelity/<id>` | API | Exige `S_GCC`, PDFs de las `unidades_base_origen`. Añade `nota` si faltan fuentes. Guarda `fidelity_analysis_result`. Respuesta `{ok, fidelity_analysis_result}` |
| `POST /api/generate_annotated_pdf/<id>` | API | Form `kind` = `normative`/`fidelity`/`referente`. Genera el PDF anotado y devuelve `{ok, pdf_url, mensaje, incoherencias}`; persiste `page_number` en el informe |
| `GET /uploads/<path>` | sí | **Solo** sirve `^[0-9a-f]{8}(_referente)?_annotated\.pdf$` (nunca `documents.json` ni originales) |
| `GET /download/<id>` | sí | Sirve el original en línea; si falta el archivo, `flash` + redirección al dashboard |

### 7.1 `/dashboard`
Para cada documento crea una fila `{**doc, department (unión de departamentos),
can_advance, action (ACTION_LABEL), badge (índice del estado+1)}`, las ordena (más recientes primero: orden inverso de alta y, estable por encima, `fecha_publicacion` descendente)
y las reparte por `TABS` comparando `status`. Ya no hay campo de fecha de alta.

### 7.2 `/upload` (POST) — validaciones
Campos del formulario: `file`, `titulo`, `tipo_contenido`, `idioma`, `tipologia` (varios), `departamentos_competentes` (varios),
`unidades_base_origen` (varios), `canal`, `contenidos_relacionados` (varios), `taxonomy`, `origen` (oculto; solo filtra el selector de tipo en la interfaz), `versionar_id` (oculto; solo al versionar).

- Obligatorios comunes: archivo (extensión permitida), título, tipo de contenido válido, idioma válido, ≥ 1 tipología válida. **No hay campo «Fecha»** (ni en el alta ni al versionar).
- **Base y Referenciat** (misma rama): ≥ 1 departamento válido (contra `config.json`); `taxonomy` ∈ `taxonomy_paths()`.
- **Adaptat**: ≥ 1 unidad base que sea un **Base publicado**; `canal` ∈ `CANALES`; la taxonomía se **hereda** (el valor enviado se ignora).
- Estado inicial: `EDITOR_STATE[tipo]` (`S_ED` para Base/Referenciat, `S_EC` para Adaptat). El servidor **no** restringe el tipo según `origen`.
- `contenidos_relacionados`, si se envían, deben ser IDs de documentos publicados.
- Los campos que no aplican al tipo se guardan vacíos (`[]` o `""`).
- Flujo de guardado: validar → bajo `DOCS_LOCK` comprobar duplicado y guardar el archivo → `process_document()` **fuera del bloqueo**
  (red) → releer, añadir el registro y guardar → `flash` (aviso amarillo si no hay vectores) → redirigir a `/dashboard`.

### 7.2.1 Modos «nueva versión» y «edición» (`save_document_update`)
- `GET /upload?versionar=<id>`: si el documento no existe o no está `S_PUB`, `flash` de error y redirección a `/dashboard#publicats`. Si vale, renderiza `upload.html` con `target_doc` y el
  formulario precargado (`form`, `selected_*` salen del documento).
- `POST` con `versionar_id`: el tipo de contenido se toma **del documento** (se ignora el enviado; el `<select>` va `disabled` y un hidden lo reenvía solo por comodidad). El archivo es **opcional**.
  Las demás validaciones son las del alta. Si pasan, `save_document_update()` (`edit=False`) hace: (1) bajo `DOCS_LOCK` comprueba `S_PUB` y, si hay archivo, `filename_exists(nombre, docs, exclude_id=id)` y guarda el archivo
  (un nombre igual al actual lo sobrescribe); (2) `process_document()` fuera del bloqueo; (3) bajo el bloqueo relee, actualiza todos los campos, suma la versión, reinicia estado/observaciones/IA y **guarda el JSON primero**;
  (4) solo entonces borra los archivos antiguos (original si cambió de nombre, `{id}_annotated.pdf`, `{id}_referente_annotated.pdf` y el vector si no fue reemplazado: el vector nuevo se llama igual que el antiguo).
  Sin archivo nuevo no se borra nada. Redirige a `/dashboard#editor-departamental` o `#editor-canal` según el tipo.
- **Edición** (`?editar=<id>`, `edit=True`): `can_update(doc, edit)` exige estado de editor y `observations` no vacío (si no, `flash` de error y vuelta a la bandeja). Mismo formulario, tipo bloqueado y archivo opcional con el mismo reemplazo (original, PDF anotados y vectores);
  la diferencia es que **no** suma versión, no cambia el estado, no limpia `observations` y no reinicia la IA. Redirige a la pestaña del editor. El formulario muestra el motivo de la devolución.
- `filename_exists(filename, docs, exclude_id=None)`: con `exclude_id` ignora el archivo del propio documento (en el JSON y en la carpeta).

### 7.3 Servicio de archivos
`/download/<id>` sirve el **original** (cualquier tipo; el navegador decide si lo muestra). `/uploads/<archivo>` solo sirve los PDF anotados.

### 7.4 Integridad al lanzar IA
Los análisis se ejecutan sin bloqueo y se releen antes de guardar; así otras peticiones no se bloquean y no se pisan cambios.

### 7.5 Seguridad (POC)
Sesión por cookie firmada con `SECRET_KEY`; credenciales en claro en el código; sin CSRF. Rutas de archivos restringidas a listas
conocidas. Las herramientas del LLM restringen las rutas que pueden leer (sección 10).

### 7.6 Retirar (`api_retirar`)
Solo `S_PUB`. Orden: (1) quitar el registro y limpiar su ID de `unidades_base_origen` y `contenidos_relacionados` en los demás
documentos; (2) **guardar el JSON primero** (si falla, no se borra nada); (3) borrar el original, los archivos de `uploads/` que empiecen
por `{id}_` y `vectores/{basename(vector_file)}`, sin tocar `documents.json` ni archivos de otros documentos.
Respuesta `{success: true, message, deleted_id}`. Un Adaptat cuya base se retira se queda con `unidades_base_origen` vacío.

---

## 8. Pipeline de procesamiento al subir (`pipeline.py`)

`process_document(path, doc_id) -> (simhash, vector_file)` — **nunca lanza excepciones**:

1. Solo procesa `.pdf`; si no, `(None, None)`.
2. `extract_pdf_text` (pdfplumber) → `normalize_text` (minúsculas, sin saltos de línea, espacios colapsados). Sin texto → `(None, None)`.
3. `compute_simhash` (librería `simhash`, 64 bits, hex de 16 dígitos).
4. `chunk_text(text, chunk_size, chunk_overlap)` con `config.json` (valida `0 ≤ overlap < size`).
5. `generate_embeddings(chunks, model)` con `google.genai` (`embed_content`, lotes de 100, `task_type=RETRIEVAL_DOCUMENT`).
   Sin clave o error de red/cuota → excepción capturada en `process_document`.
6. Guarda **solo** la lista de vectores en `vectores/{doc_id}_vectors.json` (atómico). Devuelve `(simhash, "vectores/{doc_id}_vectors.json")`.
7. Si falla algo tras calcular el SimHash, devuelve `(simhash, None)` y el documento se guarda igualmente.

---

## 9. Detección de duplicidades (`gestor_conocimiento.py`)

`detect_document_duplicity(target_doc_id, documents_data, vectors_dir, config_path) -> str` (Markdown).

- Compara el objetivo solo con documentos **publicados** (`PUBLISHED_STATUS`, hoy `"Publicat"`) distintos de sí mismo.
- **Filtro padre-hijo** (`EXCLUDE_PARENT_CHILD_DUPLICITY = True`, interruptor único en el cabecero del módulo): se ignora la comparación Base ↔ su
  Adaptat derivado (`is_parent_child_relationship`, usa `unidades_base_origen`). Los Adaptats «hermanos» sí se comparan. Se aplica al inicio de **ambos** bucles.
- **Paso 1 (SimHash):** distancia Hamming ≤ `simhash_max_distance` (3) → informe `### Duplicitat detectada (SimHash)` con tarjetas numeradas y devuelve (no hace el paso 2).
- **Paso 2 (vectorial):** centroide (`np.mean`) del objetivo vs. de cada candidato; coseno > `vector_similarity_threshold` → `### Contingut similar detectat (similitud semàntica)`.
  Los candidatos sin vectores utilizables se omiten y se cuentan en una nota.
- Sin coincidencias → texto fijo `NO_DUPLICITY` («No s'han detectat duplicitats…», con notas si faltaron datos).
- Sin SimHash **ni** vectores → mensaje «No s'ha pogut fer la detecció de duplicitats…» (no es un error de la app).
- El formato `**N. título**` + lista de `- **clave:** valor` lo convierten en tarjetas el conversor Markdown del frontend (sección 12.4).

---

## 10. Agentes de IA (`agents/`)

### 10.1 Infraestructura
- `runner.py::run_agent(agent, prompt) -> str`: crea `InMemorySessionService` + `Runner`, una sesión nueva por llamada, ejecuta con `asyncio.run` y devuelve
  el texto de la respuesta final (error si está vacía). Es **síncrono** hacia fuera.
- Modelo: `gemini-2.5-flash` en los tres agentes. Todos usan `LlmAgent(name, model, instruction, tools, output_schema, generate_content_config)`.
- **Idioma de los prompts:** las `INSTRUCTIONS` y el mensaje de usuario de los tres agentes están escritos en **catalán** (los documentos y la normativa están en catalán) y exigen que **todos los textos de los valores del JSON salgan en catalán**.
  Los nombres de las claves JSON **no** se traducen (cada agente conserva las suyas, ver sección 13); el frontend y `pdf_annotator.py` dependen de ellas. Cada módulo tiene **una sola** definición de `INSTRUCTIONS`.
- Los tres prompts piden que `frase_analizada` (y `texto_infrinjido`) sean citas **literales**, cortas y sin puntos suspensivos: `pdf_annotator.py` las busca tal cual en el PDF y, si no coinciden, no se pueden anotar.
- Las herramientas (`tools.py`) siguen devolviendo sus errores y cabeceras en castellano (`ERROR: …`, `===== LEY / NORMATIVA: … =====`, `===== DOCUMENTO FUENTE: … =====`); los prompts hacen referencia a esas cabeceras para `fichero_fuente`.
- **Salida estructurada (anti-JSON roto):** cada agente declara `output_schema` (Pydantic, en `agents/schemas.py`) junto con sus herramientas. ADK añade una herramienta interna `set_model_response`: el modelo entrega el resultado como llamada
  a función, ADK valida los argumentos y devuelve `json.dumps(...)` de ellos, así que el JSON es siempre válido aunque las citas literales del PDF lleven comillas dobles o saltos de línea (causa típica de «JSON no válido»).
  Si el modelo envía un objeto que no cumple el esquema, ADK le devuelve el error y reintenta; `runner.py` limita cada ejecución a `MAX_LLM_CALLS = 25` llamadas (por defecto serían 500) y al superarlo lanza una excepción que la ruta convierte en 502.
  `GENERATION_CONFIG` fija `max_output_tokens = 32768` (en Gemini 2.5 cuentan también los tokens de razonamiento) para que los informes largos no queden cortados. Los esquemas deben mantener los nombres de campo de la sección 13.
- **Red de seguridad en la aplicación:** `run_ai_json(run, *args, kind, doc_id)` ejecuta el agente y pasa la respuesta por `clean_and_parse_json` (quita vallas ```` ```json ````, toma de la primera `{` a la última `}`, acepta saltos de línea sin escapar
  y comas finales). Si no se puede interpretar, **reintenta una vez**; si vuelve a fallar guarda la respuesta **completa** en `logs/ai_responses/<kind>_<id>_<fecha>.txt` (el log solo lleva la ruta; contiene texto de documentos, por eso `logs/` está en `.gitignore`)
  y devuelve `{"error": True, "mensaje": ...}` → las rutas responden 502 y **no** guardan el análisis como hecho. Las excepciones del agente (red, cuota, clave, tope de llamadas) no se reintentan.

### 10.2 Herramientas (`tools.py`)
| Función | Uso | Seguridad |
|---|---|---|
| `read_pdf(file_path)` | Texto de un PDF (máx. 100 000 caracteres) | Solo rutas dentro de `uploads/`; devuelve `ERROR: ...` como texto |
| `list_normative_pdfs(folder)` | Lista de PDF de `normativa/` | — |
| `read_all_normative_pdfs(folder_path="normativa")` | Concatena todas las leyes con cabecera `===== LEY / NORMATIVA: archivo.pdf =====` (máx. 600 000) | Solo la carpeta `normativa/`; aviso amigable si está vacía |
| `read_multiple_pdfs(file_paths)` | Concatena varios PDF con cabecera `===== DOCUMENTO FUENTE: archivo.pdf =====` | Solo `uploads/` |

### 10.3 Agentes
| Agente | Invocación | Entrada (prompt) | Salida |
|---|---|---|---|
| `reviewer_agent` (`auditor_forma_agent`) | `run_review(path)` desde `/api/analyze` | Ruta del PDF | JSON de claridad: cada incoherencia con `descripcio`, `frase_analizada`, `explicacion`, `propuesta` |
| `normative_agent` (`auditor_normativo_agent`) | `run_normative_review(path)` | Ruta del PDF; lee las leyes con la herramienta | JSON normativo: `descripcio`, `frase_analizada`, `texto_infrinjido`, `explicacion`, `fichero_fuente` |
| `fidelity_agent` (`auditor_fidelidad_agent`) | `run_fidelity_check(adaptado, [fuentes])` | Ruta del adaptado + lista de rutas de las bases | JSON de fidelidad: `titulo`, `frase_analizada`, `texto_infrinjido`, `explicacion`, `fichero_fuente` |

Los esquemas completos están en la sección 13. Los tres agentes leen documentos en catalán y responden en catalán. Cada uno devuelve también un JSON de error de lectura (`conforme`/`fiel` = false, lista vacía) que la interfaz muestra como alerta.

---

## 11. Anotación de PDF (`pdf_annotator.py`)

Dos funciones públicas con el mismo núcleo (`_annotate_with_margin_boxes`):

- `annotate_pdf_with_ai_results(orig, out, incoherencias)` → recuadro con «FUENTES / NORMATIVA: … EXPLICACIÓN: …» (normativo y fidelidad).
- `annotate_referente_pdf(orig, out, incoherencias)` → recuadro con «EXPLICACIÓN: … PROPUESTA: …» (claridad).
- Ambas devuelven `(guardado: bool, lista_enriquecida)`; cada hallazgo gana `page_number` (1-indexado) o `None`.

Funcionamiento: para cada `frase_analizada` (normalizada y sin comillas/puntos suspensivos de los extremos) busca con `page.search_for` en todas las páginas;
resalta (rojo suave) todas las apariciones; **solo en la primera** añade un recuadro `FreeText` al margen con una línea que apunta al resaltado.
Para no tapar texto **amplía la página por la derecha** (`BOX_WIDTH` 200 pt + márgenes) en páginas sin rotación; altura calculada palabra a palabra; los caracteres no Latin-1
se sustituyen. Si ninguna frase se localiza devuelve `False` y no crea el archivo (la ruta responde 422). Las frases no encontradas se registran como `WARNING`.

La ruta `/api/generate_annotated_pdf` elige el anotador por `kind` y el nombre de salida: `{id}_referente_annotated.pdf` (claridad) o `{id}_annotated.pdf` (normativo/fidelidad,
compartido: se sobrescribe).

---

## 12. Frontend

### 12.1 Plantillas
- **`base.html`**: `<header class="topbar">` (logo Gencat, «BCAC · Governança documental», chip de usuario, «Tanca la sessió») solo con sesión; bloque de mensajes flash
  (`.flash.flash-{success|error|warning}`); `{% block content %}`. Variables de contexto globales: `user`, `STATES`.
- **`login.html`**: tarjeta con logo, usuario/contraseña.
- **`dashboard.html`**: `<main class="dashboard-main">` con `nav.tabs` (botones `.tab-btn`), un `<section class="tab-pane" id="pane-{slug}">` por pestaña con
  `.pane-header` y una tabla; `<dialog id="reject-dialog">` (motivo de devolución); un único `<script>` con toda la lógica.
- **`upload.html`**: formulario en una `<form class="card-body">` con **dos `<fieldset class="family-fieldset">`** («Identificación», «Origen y Trazabilidad») y, fuera de ellos,
  el campo de taxonomía. Un `<script>` gestiona la visibilidad según `tipo_contenido`.

### 12.2 Dashboard: estructura de la tabla
Columnas (11, en este orden; cabeceras en catalán: Títol, ID, Tipus de contingut, Tipologia, Idioma, Versió, Departament, Taxonomia, Publicació, Estat, Accions): Título (enlace de descarga + nombre de archivo + alerta roja `.obs-alert` con la devolución si procede), ID, Tipo de contenido, Tipología (lista separada por comas), Idioma, Versión (`vN`),
Departamento, Taxonomía, Publicación (`fecha_publicacion` y, debajo, «Revisió: `fecha_revision_prevista`» si existe; «—» si no está publicado; se muestran como `DD-MM-YYYY` con el filtro Jinja `fecha_es`, el JSON conserva `YYYY-MM-DD`), Estado (badge), Acciones (`.actions`).
Los campos vacíos se muestran como «—». Ya no se muestra la «Fuente original» (`unidades_base_origen` sigue en el JSON). Los botones se pintan con condiciones Jinja sobre `tab.status` (cadenas literales de estado) y `d.filename`.

La alerta `.obs-alert` se pinta en cualquier fila con `d.observations` (en la práctica, las bandejas de editor tras una devolución). El enlace de subida solo está en las pestañas `editor-departamental` y `editor-canal`.

> **Trampa:** la plantilla decide qué botones pintar comparando `tab.slug` (`'validador-finalista'`, `'gestor-coneixement-base'`, `'gestor-coneixement-canal'`, `'referent-departamental'`, `'publicats'`), **no** el texto del estado,
> así que traducir o renombrar un estado no rompe la plantilla; sí hay que mantener los slugs de `TABS` sincronizados con ella y con el JS (`#slug`) y con el parámetro `origen` de `/upload` (`editor-departamental`, `editor-canal`).

### 12.3 JavaScript del dashboard (todo inline en `dashboard.html`)
Bloques en orden:

1. **Pestañas**: `activate(slug)`; botones `[data-tab]`, paneles `#pane-{slug}`; hash de la URL = `#slug` (se lee al cargar y se actualiza con `history.replaceState`).
2. **Rechazar**: `.js-reject` abre el `<dialog>`; el formulario hace POST a `/rechazar/<id>`.
3. **Informes de IA** (filas desplegables):
   - `KINDS`: `analyze`, `normative`, `duplicity`, `fidelity` (clave de resultado, etiquetas, `pdfKind`).
   - Botones `.js-analyze`, `.js-normative`, `.js-duplicity`, `.js-fidelity`: si el análisis no está hecho hacen POST (estado «Cargando…»); si ya está hecho **alternan** la fila desplegable.
   - `renderAIReport(data, plain)` pinta el JSON (éxito `conforme`/`fiel` → `.alert-success`; si no `.alert-danger` con tarjetas `.incoherence-card`, bloque `.proposal` para `propuesta`,
     insignia `.page-badge`). `markdownToHtml` es un **conversor Markdown mínimo** (escapa HTML) para informes antiguos y el de duplicidades. `esc()` escapa todo.
   - El dato de cada informe viaja en el atributo `data-result` como **JSON** (`| tojson`, comillas simples); `parseStored` lo interpreta (objeto o texto). Cada pestaña muestra **solo su propio informe**: en Validador Finalista ya no se antepone el informe de claridad del Referente Departamental (se quitó el atributo `data-clarity`; el parámetro `plain` de `renderAIReport`/`renderReport` queda sin uso).
4. **Fila desplegable única por documento**: `ensureRow`/`existingRow`/`reportSlot`/`pruneRow`/`clearReport`/`insertRow`. Estructura: `<tr class="expandable-row"><td colspan><div class="report-container"/><div class="original-viewer"/>`.
5. **Documento original**: `.btn-ver-original` → `toggleOriginal` (comprueba con `HEAD` que el archivo existe antes de incrustar un `<iframe>` de `/download/<id>`);
   si ya hay visor de PDF anotado, reutiliza ese mismo `iframe` (`swapOriginal`).
6. **Retirar**: `.js-retirar` → `fetch POST /api/documents/retirar/<id>` sin confirmación; añade `.row-fade-out`, espera 350 ms, elimina fila y fila desplegable y decrementa `.tab-count`.
7. **PDF anotado** (`pdfTools`): botón «Generar y ver PDF anotado» (POST con `kind`), `iframe` con `#page=N`, sincronización con las tarjetas (clic en tarjeta → `openAtPage`), `applyPages` guarda `page_number`.
8. **Columnas redimensionables** (`DOMContentLoaded`): crea `<colgroup>`, tiradores `.col-resizer` (eventos `pointer*`). Los anchos son **porcentajes que suman 100** (`DEFAULTS = [13,7,7,10,6,5,9,10,8,11,14]`, 11 columnas):
   la tabla ocupa siempre el ancho de la ventana (**sin scroll lateral**); al arrastrar un tirador la columna vecina cede o recibe el espacio (mínimo 60 px por columna). Persistencia en
   `localStorage['bcac.dashboard.colWidths.v4']` (compartida por las pestañas; la clave se versiona al cambiar columnas o unidades; si lo guardado no suma ~100 o no tiene 11 valores se ignora).
   **Si cambia el número de columnas hay que actualizar `DEFAULTS` y la clave de `localStorage`.**

Convenciones del JS: ES5-ish con `var`, `fetch` + `.then`, errores **en línea** (sin `alert()` ni `confirm()` en las acciones de IA y retirar), todo texto dinámico se escapa.

### 12.4 JavaScript de `upload.html`
- Con `target_doc` (modo nueva versión o edición; `edit_mode` distingue): título «Crea una nova versió» / «Edita el document», botón «Desa la nova versió» / «Desa els canvis», «Cancel·la» a `/dashboard` + `back_anchor` (`#publicats` o la pestaña del editor), `file` sin `required` con el nombre del archivo actual, select de tipo `disabled` + hidden `tipo_contenido`, hidden `versionar_id` (o `editar_id` en edición).
- El selector «Tipo de contenido» se filtra con `origen` (Jinja): `editor-canal` → solo Adaptat (preseleccionado); `editor-departamental` → solo Base (preseleccionado); sin origen → los tres.
- `update()` muestra/oculta y habilita/deshabilita según `tipo_contenido` (los campos ocultos se **deshabilitan**: no se envían ni se validan):
  Base **y Referenciat** → bloque de departamentos y taxonomía manual; Adaptat → unidades base (selector múltiple), canal, y taxonomía heredada de solo lectura (`updateInherited`: unión de `data-taxonomy` de las opciones seleccionadas).
- Si no hay Base publicados y se elige Adaptat: aviso en rojo y botón de envío deshabilitado.
- Validación en el `submit` (errores en línea): ≥ 1 tipología; Base/Referenciat → ≥ 1 departamento; Adaptat → unidad base y canal.
- Estructuras HTML reutilizables: `.family-fieldset`/`.family-legend`, `.tipologia-container` + `.tipologia-item` (rejilla de casillas), `.field-error` (mensaje rojo oculto con `hidden`).

### 12.5 CSS (`static/css/style.css`, un solo archivo)
- Insignias de estado `.badge-1`…`.badge-7` con colores fijos (slate, slate oscuro, ámbar, azul, violeta, teal, verde) y borde.
- Variables en `:root` (`--color-primary` rojo corporativo, `--color-success`, `--color-danger`, `--radius`, `--shadow`…).
- Botones de la columna «Accions» (`.actions`): rejilla de **una columna** con `grid-auto-rows: 1fr`; todos ocupan el ancho de la celda y tienen la **misma altura** (si una etiqueta se parte en dos líneas, todos crecen a esa altura). Los `<form>` llevan `display: contents` para que su botón sea un elemento más de la rejilla.
- La tabla del dashboard es `table-layout: fixed; width: 100%`, sin `min-width` en `th`/`td` y con `padding: 12px 10px`; los botones de `.actions` pueden partir su texto. Así se adapta al ancho (sin scroll lateral desde ~800 px; el scroll vertical del `.table-wrap` se mantiene).
- Bloques principales: topbar y layout; botones (`.btn`, `-primary`, `-success`, `-danger`, `-outline-secondary`, `-sm`); tabla (`table-layout: fixed`, cabeceras `position: sticky`, texto con salto de línea);
  pestañas (`.tabs`, `.tab-btn.active`, `.tab-pane.active`); layout a pantalla completa (`body:has(.dashboard-main)`); alertas (`.alert-success/-danger/-neutral`), tarjetas (`.incoherence-card`, `.proposal`, `.page-badge`);
  visores (`.pdf-frame`, `.original-viewer`, `.pdf-tools`); formularios por familias; animación `.row-fade-out`.
- El atributo `hidden` solo funciona sobre `.field` gracias a la regla `.field[hidden] { display: none; }`.

---

## 13. Contratos JSON de los informes de IA

Éxito (normativo y claridad):
```json
{"conforme": true, "missatge": "…", "incoherencies": []}
```
Fidelidad usa `fiel`, `mensaje` e `incoherencias` (el frontend acepta ambos juegos de nombres: `conforme|fiel`, `missatge|mensaje`, `incoherencies|incoherencias`).

Incoherencias — por agente (campos de cada elemento de la lista):

| Agente | Campos |
|---|---|
| Claridad (`referente_analysis_result`) | `descripcio`, `frase_analizada`, `explicacion`, `propuesta`, (`page_number`) |
| Normativo (`normative_analysis_result`) | `descripcio`, `frase_analizada`, `texto_infrinjido`, `explicacion`, `fichero_fuente`, (`page_number`) |
| Fidelidad (`fidelity_analysis_result`) | `titulo`, `frase_analizada`, `texto_infrinjido`, `explicacion`, `fichero_fuente`, (`page_number`) |

Campos extra: `nota` (fidelidad, si faltaron fuentes). Error de parseo: `{"error": true, "mensaje": "Fallo al procesar la respuesta de la IA."}` (no se persiste).
El informe de **duplicidades** es **texto Markdown** (no JSON). `analysis_result` (claridad antiguo) es Markdown y solo se muestra si no hay `referente_analysis_result`.

Respuesta de `/api/generate_annotated_pdf`: `{"ok": true, "pdf_url": "/uploads/<id>[_referente]_annotated.pdf?v=<mtime>", "mensaje": "Se anotaron X de Y frases…", "incoherencias": [ …con page_number… ]}`.

---

## 14. Convenciones y decisiones de diseño (respetar al modificar)

- **Idioma**: textos de interfaz, prompts y salida de los agentes en catalán; comentarios del código y este documento en español.
- **Sin pop-ups** para resultados de IA ni para retirar: errores en línea. Validaciones de formulario: mensajes en línea y `flash`.
- **Seguridad de HTML**: el contenido que viene de la IA o de los datos se escapa (`esc`) antes de inyectarlo con `innerHTML`.
- **Escritura de datos**: siempre `load_documents()` → modificar → `save_documents()` dentro de `DOCS_LOCK`; nunca mantener el bloqueo durante llamadas a la IA.
- **Estructura plana** de `documents.json` (los campos nuevos van en la raíz); `normalize()` aporta valores por defecto — añadir allí cualquier campo nuevo.
- **Comentarios con el porqué** (no el qué); se prefiere no añadir dependencias de frontend.
- **Rutas de archivos**: nunca construir rutas con texto del cliente; usar listas conocidas / nombres validados por regex.
- **Reiniciar** el servidor tras cambios en Python o `config.json` (excepto `departamentos_competentes`, que se relee).

---

## 15. Estado del repositorio y discrepancias conocidas (leer antes de proponer cambios)

### 15.1 Historial git
`Initial commit` → `v0.1` → `V0.1`/`v0.2` → `v0.3` (15-oct) → `v0.4` (19-oct, HEAD). Encima de `v0.4` hay cambios **sin confirmar** (refactorización de 7 estados, ver sección 5, y versionado vía `/upload?versionar=<id>`, ver 7.2.1).

### 15.2 Estados desconocidos
Un `status` fuera de `STATES` no aparece en ninguna pestaña (no hay migración de estados antiguos).

### 15.3 Funcionalidades de iteraciones anteriores **no presentes** en el código
Se diseñaron e implementaron pero se perdieron al restaurar el árbol. Pueden volver a solicitarse:

1. **Familia «Clasificación»**: selector `taxonomia` (texto, obligatorio para todos los tipos, heredado y bloqueado en Adaptat) y campo opcional `clasificacion_canal`. Hoy la taxonomía es `taxonomy` (lista).
2. **Familia «Ciclo de vida»**: `estado`, `version` ("1.0", texto), `responsable`, `provisional`, `fecha_fin_vigencia`. Hoy existen solo `fecha_publicacion` y `fecha_revision_prevista` (nombres sin sufijo `_version`) y la versión es un entero.
3. ~~Eliminación del campo «Fecha» (`date`)~~: **ya hecho** (el campo ya no existe ni se guarda).
4. Config centralizada de estados en `config.json` (`estados`) y endpoint `POST /api/documents/aprobar/<id>`. Hoy los estados viven en constantes de `app.py` y se avanza con `/avanzar_estado`.
   (Las 7 bandejas y el alta por `origen` **sí** están ya implementadas, con otros nombres de estado.)

### 15.4 Otros detalles y deudas técnicas
- Cualquier usuario puede ejecutar cualquier acción de cualquier bandeja (los roles son solo pestañas); el filtro de `origen` en el alta es solo de interfaz.
- `api_analyze` exige `S_RD`; `/api/generate_annotated_pdf` prioriza el informe de claridad en `S_RD` y el de fidelidad en `S_GCC`.
- `gestor_conocimiento.PUBLISHED_STATUS` está escrito a mano (`"Publicat"`); debe coincidir con `S_PUB`.
- Al versionar **sin** archivo nuevo, los PDF anotados antiguos (`{id}_annotated.pdf`, `{id}_referente_annotated.pdf`) siguen en disco aunque los informes de IA se reinicien; se sobrescriben al volver a generarlos o desaparecen al retirar el documento.
- `analysis_result` (claridad en Markdown) es un campo heredado; el actual es `referente_analysis_result`.
- No hay tests automatizados; credenciales y usuario único en el código; sin CSRF.
- `base.html` tiene una línea en blanco donde antes estaba el pie con el logo de Ayesa.
- Las respuestas de las tarjetas de duplicidad dependen del formato Markdown que genera `gestor_conocimiento.py`; cambiarlo exige revisar `markdownToHtml` y `alertClass` en el dashboard (`SUCCESS_RE`/`DANGER_RE` reconocen los textos en catalán que generan los agentes y `gestor_conocimiento.py`).

---

## 16. Guía para redactar instrucciones de modificación

Qué archivos tocar según el tipo de cambio:

| Cambio | Archivos / puntos |
|---|---|
| **Nuevo campo de metadatos** | `upload.html` (campo + JS de visibilidad) → `app.py`: lectura en `upload()`, validación, registro, `normalize()` (valor por defecto) → `dashboard.html` si se muestra |
| **Nuevo estado o nueva fase** | Constante `S_*`, `STATES`, `FLOWS`, `VALIDATION_STATES`, `TABS`, `ACTION_LABEL`, `EDITOR_STATE` en `app.py`; orden de `api_generate_annotated_pdf`; comparaciones literales en `dashboard.html`; `PUBLISHED_STATUS` en `gestor_conocimiento.py` si cambia «publicado»; estilo `badge-N` en CSS |
| **Nueva pestaña** | Entrada en `TABS` (slug único) y, si procede, botones por estado en la plantilla; el JS de pestañas es genérico |
| **Nuevo agente de IA** | Archivo en `agents/` (con `run_*`), herramienta en `tools.py` si hace falta, ruta `/api/...` siguiendo el patrón de la sección 6, campos `*_result`/`*_done` en `normalize()`, entrada en `KINDS` y botón en el dashboard; si genera hallazgos con frases: función en `pdf_annotator.py` y `kind` en `api_generate_annotated_pdf` |
| **Cambiar un prompt** | El archivo del agente (`INSTRUCTIONS`, en catalán) y, si cambian las claves del JSON, el esquema de `agents/schemas.py`, `renderAIReport` y `pdf_annotator.py` |
| **Cambiar umbrales/modelo** | `config.json` (no requiere código) |
| **Cambiar columnas de la tabla** | `<th>`/`<td>` en `dashboard.html`, `colspan` de la fila vacía (en HTML y en el JS de retirar), `DEFAULTS` y `STORAGE_KEY` del redimensionado |
| **Cambiar reglas de validación del alta** | `upload()` en `app.py` (servidor, fuente de verdad) y el JS de `upload.html` (comodidad) |
| **Cambiar el versionado o la edición de devueltos** | `save_document_update()`, `can_update()` y la rama `target_doc` de `upload()` en `app.py`; `target_doc`/`edit_mode` en `upload.html`; enlaces en `dashboard.html` |
| **Cambiar el borrado/retirada** | `api_retirar` (orden: JSON primero, luego archivos) y `.js-retirar` |

Advertencias al instruir cambios:

1. Indicar siempre **qué estado del repositorio se asume** (ver sección 15: hay funcionalidades que no están en el código).
2. Mantener sincronizados servidor y cliente; el servidor valida, el cliente solo ayuda.
3. Tras cambios de Python: reiniciar el servidor. Tras cambios de CSS/JS: recarga forzada del navegador.
4. Verificar con el cliente de pruebas de Flask (`app.test_client()`), apuntando `A.UPLOAD_FOLDER`, `A.app.config["UPLOAD_FOLDER"]` y `A.DOCUMENTS_FILE` a una carpeta temporal para **no tocar datos reales**,
   y sustituyendo `A.process_document` / las funciones `run_*` por simulaciones para no llamar a Gemini. El JavaScript inline puede comprobarse con `osascript -l JavaScript` (sintaxis) renderizando antes las plantillas.
5. No hay control de versiones de los datos: `uploads/documents.json` no está en git; conviene copiarlo antes de pruebas destructivas (retirar borra archivos de verdad).
6. Hacer `git commit` de los cambios aceptados: una restauración del árbol descarta lo no confirmado.
