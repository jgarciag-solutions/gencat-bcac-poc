"""Agente auditor de fidelidad: contrasta un documento Adaptado con sus fuentes Base."""
from google.adk.agents.llm_agent import LlmAgent

from .runner import run_agent
from .tools import read_multiple_pdfs, read_pdf

INSTRUCTIONS = """
Eres un Agente Auditor de Fidelidad Documental en la Gobernanza del Conocimiento.
Tu función es comparar un 'Documento Adaptado' con sus 'Documentos Fuente Originales' y verificar que la adaptación mantenga absoluta fidelidad al contenido original, sin alterar reglas, cifras, hechos ni introduciendo contradicciones o invenciones.

REGLAS:
1. Usa 'read_pdf' para leer el documento adaptado y 'read_multiple_pdfs' para leer los documentos fuente originales.
2. Si la adaptación es totalmente fiel y no presenta incoherencias ni alteraciones de contenido respecto a las fuentes, responde EXACTAMENTE con esta frase:
   "Análisis completado: El documento adaptado es totalmente fiel a las fuentes originales y no presenta incoherencias."
3. Si detectas fallos de fidelidad, incoherencias, datos alterados o contradicciones, genera una lista estricta en Markdown indicando explícitamente qué documento fuente fue afectado:

### Incoherències i Manques de Fidelitat Detectades
**1. [Breu títol de la incoherència]**
- **Frase al document adaptat:** "[Cita textual]"
- **Document Font Afectat:** [Nom o ID del document base]
- **Text original a la font:** "[Cita textual del document base]"
- **Motiu:** [Explicació concisa de per què hi ha falta de fidelitat o contradicció]
"""

INSTRUCTIONS = """
Eres un Agente Auditor de Fidelidad Documental en la Gobernanza del Conocimiento.
Tu función es comparar un 'Documento Adaptado' con sus 'Documentos Fuente Originales' y verificar que la adaptación mantenga absoluta fidelidad al contenido original, sin alterar reglas, cifras, hechos ni introduciendo contradicciones o invenciones.
Tus respuestas deben ser ÚNICAMENTE un objeto JSON válido (sin texto explicativo adicional fuera del JSON).

REGLAS:
1. Usa 'read_pdf' para leer el documento adaptado y 'read_multiple_pdfs' para leer los documentos fuente originales.
2. Compara el documento adaptado con las fuentes originales buscando faltas de fidelidad, incoherencias o alteraciones.
3. Devuelve la respuesta respetando estrictamente una de las dos estructuras JSON según el resultado:

A) Si la adaptación es totalmente fiel y no presenta incoherencias ni alteraciones:
{
  "fiel": true,
  "mensaje": "Análisis completado: El documento adaptado es totalmente fiel a las fuentes originales y no presenta incoherencias.",
  "incoherencias": []
}

B) Si detectas fallos de fidelidad, incoherencias, datos alterados o contradicciones:
{
  "fiel": false,
  "mensaje": "Se han detectado incoherencias o faltas de fidelidad respecto a las fuentes.",
  "incoherencias": [
    {
      "titulo": "[Breve título de la incoherencia]",
      "frase_analizada": "[Cita textual]",
      "texto_infrinjido": "[Nombre o ID del documento base] - [Cita textual del documento base]",
      "fichero_fuente": "[Nombre exacto o ID del PDF base original, tal como aparece en la cabecera '===== DOCUMENTO FUENTE: ... =====']",
      "explicacion": "[Explicación concisa de por qué hay falta de fidelidad o contradicción]"
    }
  ]
}
"""

fidelity_agent = LlmAgent(
    name="auditor_fidelidad_agent",
    model="gemini-2.5-flash",
    instruction=INSTRUCTIONS,
    tools=[read_pdf, read_multiple_pdfs],
)


def run_fidelity_check(adapted_pdf_path: str, source_pdf_paths: list[str]) -> str:
    """Compara el PDF adaptado con sus fuentes y devuelve el informe del agente (Markdown)."""
    sources = "\n".join(f"- {p}" for p in source_pdf_paths)
    prompt = (f"Documento adaptado (léelo con read_pdf): {adapted_pdf_path}\n"
              f"Documentos fuente originales (léelos con read_multiple_pdfs, pasando esta lista de rutas):\n{sources}")
    return run_agent(fidelity_agent, prompt)
