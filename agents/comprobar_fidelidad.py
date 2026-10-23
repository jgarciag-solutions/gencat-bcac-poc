"""Agente auditor de fidelidad: contrasta un documento Adaptado con sus fuentes Base.

Para que el resultado sea reproducible, la búsqueda no la hace el modelo sino el código:
  1. El documento font se parte en unidades de texto numeradas (frases/viñetas): cobertura completa y fija.
  2. Para cada unidad se recuperan, con TF-IDF, los fragmentos del adaptado más parecidos (determinista).
  3. El modelo solo juzga, en llamadas cortas, cada unidad contra sus fragmentos candidatos y señala cuál contradice.
     La cita del adaptado se toma del fragmento elegido por `id`, así que es literal por construcción.
Las contradicciones se devuelven con el formato `FidelityReport` de siempre (dashboard y anotador de PDF no cambian).
"""
import json
import logging
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from google.adk.agents.llm_agent import LlmAgent

from .runner import run_agent
from .schemas import FidelityJudgement
from .settings import agent_model, embedding_model, generation_config
from .tools import extract_pages

log = logging.getLogger(__name__)

BATCH_SIZE = 12      # unidades del font por llamada al modelo
MAX_PARALLEL = 10     # llamadas simultáneas
EMB_K = 8            # candidatos por unidad según embeddings (semántico)
LEX_K = 8            # candidatos por unidad según TF-IDF (léxico); se unen sin duplicados
MIN_CHARS = 12       # unidades/fragmentos más cortos se ignoran

INSTRUCTIONS = """
Ets un Agent Auditor de Fidelitat i No-Contradicció Normativa.
La teva missió és comparar un 'Document Adaptat' amb el seu 'Document Font' i verificar si existeixen CONTRADICCIONS REALS de fons, xocs de regles o dades incompatibles. Tot està en català.

ENTRADA:
Rebràs una llista numerada d'UNITATS del document font. Per a cada unitat, el sistema ja t'ha buscat els FRAGMENTS CANDIDATS del document adaptat que hi són més semblants; cada fragment té un identificador [cN], la seva pàgina i la secció/títol de la pàgina on apareix. Els fragments candidats poden tractar d'un altre tema que el de la unitat (el document adaptat és un manual que parla de moltes coses): fixa't en la secció.

LA TEVA TASCA, PER A CADA UNITAT:
1. Decideix si la unitat conté una afirmació comprovable (xifra, any, edat, import, percentatge, condició, requisit, àmbit territorial o destinatari). Si no (títols, enllaços, frases genèriques), veredicte 'no_contradiu'.
2. Busca entre els fragments candidats el que tracta el MATEIX concepte, per al MATEIX supòsit (i del mateix tema/secció). Si cap no el tracta, veredicte 'no_contradiu': que l'adaptat no tracti un punt no és una contradicció.
3. Compara'ls dimensió per dimensió: xifra, any, edat, territori, destinatari, tipus d'ingressos, condició. Si el font fixa una xifra, edat, àmbit, destinatari o condició CONCRETS i l'adaptat en fixa una altra de DIFERENT per al mateix supòsit, veredicte 'contradiu' i indica a 'chunk_id' el fragment (només el número, p. ex. 123).

QUÈ ÉS UNA CONTRADICCIÓ REAL ('contradiu'):
- Dades o llindars incompatibles: edats, percentatges, imports o quantitats diferents per al mateix concepte.
- Una condició diferent: àmbit territorial, qui n'és destinatari (tots, només alguns, només a partir d'una edat), tipus d'ingressos, requisit més restrictiu o més ampli, SEMPRE que el font l'especifiqui explícitament. Que la condició de l'adaptat «encaixi dins» la del font NO n'és prou: si el font admet un àmbit, una edat o uns destinataris i l'adaptat els limita o els amplia, la persona afectada rep una resposta diferent segons el document que consulti, i això és 'contradiu'.
- Incompatibilitats directes de dret: el font diu que una situació dona dret i l'adaptat diu que no, sota les mateixes condicions.

QUÈ NO ÉS UNA CONTRADICCIÓ ('no_contradiu'):
- Ampliacions de detall operatiu o administratiu (instruccions d'atenció ciutadana 012, codis interns, tipus de suport/software, terminis de gestió interna).
- Evolucions o canvis de format que respectin el dret (p. ex. del carnet de plàstic al carnet digital).
- Una mateixa xifra o import presentat amb un any de referència diferent quan l'import és el mateix.
- Omissions, resums, enllaços o remissions en comptes de transcriure la informació: només és contradicció el que s'afirma de forma incompatible, no el que falta.
- Un requisit que l'adaptat afegeix però que el document font ja estableix en una altra unitat (mira la llista d'unitats).
- Concretar o detallar: NOMÉS quan el font és vague o calla sobre aquest punt i l'adaptat hi precisa un límit, un termini o un detall (p. ex. el font diu «separacions transitòries» i l'adaptat precisa «fins a dos anys»). Si, en canvi, el font FIXA explícitament un àmbit, una edat, un destinatari o una xifra i l'adaptat el substitueix per un altre de més estret, més ample o diferent (p. ex. el font diu «qualsevol municipi» i l'adaptat «només Barcelona»), això NO és concretar: és 'contradiu'.
- Canvis de canal o de procediment per obtenir el mateix document o tràmit (p. ex. descarregar-lo en línia en lloc de sol·licitar-lo) quan el dret no canvia.
- Diferències gramaticals (singular/plural, gènere, concordança), de puntuació o de redacció que no canvien el contingut.
- Conceptes propers però diferents: comprova que el concepte és exactament el mateix abans de comparar (p. ex. «certificat» i «duplicat», o «prestació» i «ajut» no són el mateix).
- Redaccions diferents que expressen el mateix contingut.
- Fragments il·legibles o incomplets: si no n'entens el sentit, no els facis servir.
En cas de dubte entre 'contradiu' i 'no_contradiu' per una diferència de redacció o de detall, tria 'no_contradiu'; si dubtes per una diferència en una de les dimensions de dalt, tria 'contradiu'.

SORTIDA:
- Lliura el resultat exclusivament mitjançant l'eina 'set_model_response', sense cap text fora de l'estructura.
- Una entrada a 'entrades' per CADA unitat rebuda, amb el seu 'id', en el mateix ordre.
- Per a 'no_contradiu' deixa 'chunk_id', 'dimensio', 'titol' i 'motiu' buits (chunk_id 0).
- Per a 'contradiu' omple 'chunk_id' (el número del fragment, sense la [c]), 'cita' (còpia LITERAL d'UNA sola frase d'aquest fragment, la part mínima que conté la xifra o la condició; sense punts suspensius ni paràfrasis), 'dimensio', 'titol' (breu, en català) i 'motiu' (per què no poden ser certes alhora, en català).
"""

READ_ERROR = {"fiel": False, "mensaje": "Error en la lectura del document adaptat o de les fonts.", "incoherencias": []}
CLEAN = {"fiel": True, "mensaje": "Anàlisi completada: El document adaptat no presenta contradiccions respecte a les fonts.",
         "incoherencias": []}


def _build_fidelity_agent() -> LlmAgent:
    """Se construye en cada ejecución para aplicar el modelo y los parámetros vigentes de config.json."""
    return LlmAgent(
        name="auditor_fidelidad_agent",
        model=agent_model("fidelidad"),
        instruction=INSTRUCTIONS,
        output_schema=FidelityJudgement,
        generate_content_config=generation_config("fidelidad"),
    )


# --- Segmentación en unidades ----------------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^[A-ZÀ-ÚÇ]{4,}\s+[A-ZÀ-ÚÇ]{4,}")  # «FAMÍLIES NOMBROSES - Requisits», «NOVETATS – AVISOS»…


def _clean_line(line: str) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\u200b]", "", line).strip()


def _split_units(pages: list[str]) -> list[dict]:
    """Parte el texto de cada página en frases/viñetas. Cada unidad guarda su página y el título de la página.

    Las líneas que se repiten en muchas páginas (menús de navegación de las diapositivas) se descartan: no llevan
    punto final y, si no, se pegarían delante de la primera frase de cada página.
    """
    cleaned = [[c for c in (_clean_line(ln) for ln in text.splitlines()) if c] for text in pages]
    pages_with = Counter(ln.lower() for lines in cleaned for ln in set(lines))
    limit = max(4, round(0.08 * len(pages)))
    units = []
    for number, lines in enumerate(cleaned, 1):
        title = next((ln for ln in lines if _TITLE_RE.match(ln)), "")
        lines = [ln for ln in lines if pages_with[ln.lower()] < limit and ln != title and not ln.isdigit()]
        current = ""
        for line in lines:
            if current and current[-1] in ".:;?!":  # una unidad termina en . : ; ? ! y la siguiente línea empieza otra
                units.append({"pagina": number, "titulo": title, "text": current})
                current = line
            else:
                current = f"{current} {line}".strip()
        if current:
            units.append({"pagina": number, "titulo": title, "text": current})
    return [u for u in units if len(u["text"]) >= MIN_CHARS]


def _clean_chunks(chunks: list[dict]) -> list[dict]:
    """Quita el texto repetido en muchas páginas (menús de diapositiva) y los fragmentos de menos de 4 palabras."""
    seen = Counter(re.sub(r"\s+", " ", c["text"]).strip().lower() for c in chunks)
    return [c for c in chunks
            if seen[re.sub(r"\s+", " ", c["text"]).strip().lower()] < 4 and len(c["text"].split()) >= 4]


def _source_units(source_paths: list[str]) -> list[dict]:
    """Unidades numeradas de todos los PDF font. Devuelve [] si alguno no se puede leer."""
    units = []
    for path in source_paths:
        try:
            pages = extract_pages(path)
        except Exception:
            log.warning("No se pudo leer el PDF font %s", os.path.basename(path), exc_info=True)
            return []
        units += [{**u, "fitxer": os.path.basename(path)} for u in _split_units(pages)]
    heading, source = "", None
    for i, u in enumerate(units, 1):
        u["id"] = i
        if u["fitxer"] != source:
            heading, source = "", u["fitxer"]
        u["query"] = f"{os.path.splitext(u['fitxer'])[0]} {heading} {u['text']}"  # nombre del fichero + encabezado: contexto de la consulta
        if u["text"][-1] in ":?":
            heading = u["text"]
    return units


# --- Recuperación determinista (TF-IDF) ------------------------------------------------------------------------

_STOP = set("""de la el els les i o a en per que amb un una uns unes al del dels com si no es se ha han es son sera seran
pot poden poder cal han ha hi ho li lli seu seva seus seves aquest aquesta aquests aquestes tot tots tota totes mes
quan com altre altra altres tambe sense fins des entre sobre sota fer fan ser estan esta estat""".split())


def _tokens(text: str) -> list[str]:
    """Palabras sin acentos ni mayúsculas, truncadas a 6 letras (aproxima la raíz: «residència»/«resideixin» → «reside»)."""
    plain = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    words = re.findall(r"[a-z0-9]+", plain)
    return [w[:6] for w in words if w not in _STOP and (len(w) >= 3 or w.isdigit())]


def _embed(texts: list[str], task: str) -> list[list[float]]:
    """Embeddings de Gemini (deterministas) por lotes de 100."""
    from google import genai
    from google.genai import types

    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    client = genai.Client(api_key=key)
    vectors = []
    for i in range(0, len(texts), 100):
        resp = client.models.embed_content(model=embedding_model(), contents=texts[i:i + 100],
                                           config=types.EmbedContentConfig(task_type=task))
        vectors.extend(list(e.values) for e in resp.embeddings)
    return vectors


class _EmbeddingIndex:
    """Recuperación semántica: coseno entre el embedding de la consulta y el de cada fragmento del adaptado."""

    def __init__(self, chunks: list[dict]):
        import numpy as np
        self.np = np
        mat = np.array(_embed([f"{c['titulo']}. {c['text']}" if c["titulo"] else c["text"] for c in chunks],
                              "RETRIEVAL_DOCUMENT"), dtype=float)
        self.mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12)

    def rank(self, queries: list[str], k: int) -> list[list[int]]:
        np = self.np
        q = np.array(_embed(queries, "RETRIEVAL_QUERY"), dtype=float)
        q = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-12)
        scores = q @ self.mat.T
        return [sorted(range(len(row)), key=lambda i: (-row[i], i))[:k] for row in scores]  # desempate estable


class _Index:
    """Índice TF-IDF (coseno) sobre los fragmentos del adaptado. Respaldo si fallan los embeddings."""

    def __init__(self, chunks: list[dict]):
        counts = [Counter(_tokens(f"{c['titulo']} {c['text']}")) for c in chunks]  # el título de página aporta el tema
        df = Counter(t for c in counts for t in c)
        n = len(chunks)
        self.idf = {t: math.log((n + 1) / (d + 0.5)) for t, d in df.items()}
        self.postings = defaultdict(list)
        for i, c in enumerate(counts):
            weights = {t: (1 + math.log(f)) * self.idf[t] for t, f in c.items()}
            norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
            for t, w in weights.items():
                self.postings[t].append((i, w / norm))

    def rank(self, queries: list[str], k: int) -> list[list[int]]:
        return [self.top(q, k) for q in queries]

    def top(self, text: str, k: int) -> list[int]:
        q = Counter(_tokens(text))
        weights = {t: (1 + math.log(f)) * self.idf[t] for t, f in q.items() if t in self.idf}
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        scores = defaultdict(float)
        for t, w in weights.items():
            for i, dw in self.postings[t]:
                scores[i] += (w / norm) * dw
        return [i for i, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]  # desempate estable por posición


# --- Juicio del modelo -----------------------------------------------------------------------------------------

def _batch_prompt(batch: list[dict], chunks: list[dict], cands_by_unit: dict) -> tuple[str, dict]:
    """Texto de la llamada y {chunk_id: fragmento} de los fragmentos mostrados."""
    shown, blocks = {}, []
    for u in batch:
        cands = cands_by_unit[u["id"]]
        lines = []
        for ci in cands:
            c = chunks[ci]
            shown[ci + 1] = c
            lines.append(f"  [c{ci + 1}] (pàg. {c['pagina']} · {c['titulo'] or 'sense títol'}) {c['text']}")
        blocks.append(f"[{u['id']}] UNITAT DEL FONT ({u['fitxer']}, pàg. {u['pagina']}): {u['text']}\n"
                      f"  FRAGMENTS CANDIDATS DE L'ADAPTAT:\n" + ("\n".join(lines) or "  (cap)"))
    return "UNITATS A REVISAR:\n\n" + "\n\n".join(blocks), shown


def _judge_batch(batch: list[dict], chunks: list[dict], cands_by_unit: dict) -> list[dict]:
    """Veredictos de un lote; reintenta una vez solo las unidades sin entrada. Devuelve las entradas 'contradiu' válidas."""
    prompt, shown = _batch_prompt(batch, chunks, cands_by_unit)
    ids = {u["id"] for u in batch}
    entries = {}
    for _ in range(2):
        raw = run_agent(_build_fidelity_agent(), prompt)
        try:
            data = json.loads(re.sub(r"```json|```", "", raw).strip(), strict=False)
        except ValueError:
            log.warning("Fidelidad: respuesta no interpretable en un lote.")
            continue
        for e in (data.get("entrades") or []) if isinstance(data, dict) else []:
            if isinstance(e, dict) and e.get("id") in ids:
                entries[e["id"]] = e
        missing = [u for u in batch if u["id"] not in entries]
        if not missing:
            break
        prompt, shown2 = _batch_prompt(missing, chunks, cands_by_unit)
        shown.update(shown2)
    if len(entries) < len(batch):
        log.warning("Fidelidad: %d unidades del font sin veredicto.", len(batch) - len(entries))
    by_id = {u["id"]: u for u in batch}
    found = []
    for i, e in entries.items():
        if e.get("veredicte") != "contradiu":
            continue
        chunk = shown.get(e.get("chunk_id"))
        if chunk is None:  # el modelo señaló un fragmento que no se le mostró: no se puede citar
            continue
        quote = _short_quote(e.get("cita", ""), chunk["text"])
        found.append({"id": i, "unit": by_id[i], "chunk": chunk, "entry": e, "quote": quote})
    return sorted(found, key=lambda f: f["id"])


# --- Informe ---------------------------------------------------------------------------------------------------

def _short_quote(quote: str, chunk_text: str) -> str:
    """La cita corta del modelo si es una subcadena literal del fragmento; si no, el fragmento entero."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("‘", "'")).strip().lower()
    if len(norm(quote)) >= MIN_CHARS and norm(quote) in norm(chunk_text):
        return quote.strip()
    return chunk_text


def _findings_to_report(found: list[dict], source_paths: list[str]) -> dict:
    """Convierte las contradicciones en el informe FidelityReport; una misma cita del adaptado no se repite."""
    single = os.path.basename(source_paths[0]) if len(source_paths) == 1 else ""
    findings, seen = [], set()
    for f in found:
        key = (f["chunk"]["pagina"], re.sub(r"\s+", " ", f["quote"]).strip().lower())  # misma página y misma cita
        if key in seen:
            continue
        seen.add(key)
        e = f["entry"]
        findings.append({"titulo": e.get("titol") or f"Divergència en {e.get('dimensio') or 'una condició'}",
                         "frase_analizada": f["quote"],
                         "texto_infrinjido": f["unit"]["text"],
                         "fichero_fuente": single or f["unit"]["fitxer"],
                         "explicacion": e.get("motiu", "")})
    if not findings:
        return CLEAN
    return {"fiel": False, "mensaje": "S'han detectat contradiccions entre el document adaptat i la font.",
            "incoherencias": findings}


_INDEX_CACHE: dict = {}  # (ruta, tamaño, mtime) -> (fragmentos, índice): "Torna a comprovar" no vuelve a embeber el adaptado


def _adapted_index(path: str):
    """Fragmentos del adaptado y sus índices de recuperación (semántico y léxico). Se cachea por fichero."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, int(st.st_mtime))
    if key not in _INDEX_CACHE:
        chunks = _clean_chunks(_split_units(extract_pages(path)))
        if not chunks:
            return [], None, None
        lexical = _Index(chunks)
        try:
            semantic = _EmbeddingIndex(chunks)
        except Exception:
            log.warning("Fidelidad: embeddings no disponibles; solo se usa recuperación TF-IDF.", exc_info=True)
            semantic = None
        if len(_INDEX_CACHE) >= 4:
            _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
        _INDEX_CACHE[key] = (chunks, semantic, lexical)
    return _INDEX_CACHE[key]


def _candidates(units: list[dict], semantic, lexical) -> dict:
    """{id de unidad: posiciones de fragmentos candidatos}: unión sin duplicados de la recuperación semántica y la léxica."""
    queries = [u["query"] for u in units]
    lex = lexical.rank(queries, LEX_K)
    try:
        sem = semantic.rank(queries, EMB_K) if semantic is not None else [[] for _ in units]
    except Exception:  # fallo de la API de embeddings al consultar: solo léxico
        log.warning("Fidelidad: fallo al consultar embeddings; se usa solo TF-IDF.", exc_info=True)
        sem = [[] for _ in units]
    return {u["id"]: list(dict.fromkeys(s + l)) for u, s, l in zip(units, sem, lex)}


def run_fidelity_check(adapted_pdf_path: str, source_pdf_paths: list[str]) -> str:
    """Compara el PDF adaptado con sus fuentes y devuelve el informe del agente (JSON en texto)."""
    units = _source_units(source_pdf_paths)
    try:
        chunks, semantic, lexical = _adapted_index(adapted_pdf_path)
    except Exception:
        log.warning("No se pudo leer el PDF adaptado %s", os.path.basename(adapted_pdf_path), exc_info=True)
        chunks, semantic, lexical = [], None, None
    if not units or not chunks:
        return json.dumps(READ_ERROR, ensure_ascii=False)
    cands_by_unit = _candidates(units, semantic, lexical)
    batches = [units[i:i + BATCH_SIZE] for i in range(0, len(units), BATCH_SIZE)]
    with ThreadPoolExecutor(min(MAX_PARALLEL, len(batches))) as pool:
        results = list(pool.map(lambda b: _judge_batch(b, chunks, cands_by_unit), batches))
    found = [f for batch in results for f in batch]
    return json.dumps(_findings_to_report(sorted(found, key=lambda f: f["id"]), source_pdf_paths), ensure_ascii=False)
