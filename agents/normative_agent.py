"""Agente auditor normativo: contrasta un documento con las leyes de normativa/."""
from google.adk.agents.llm_agent import LlmAgent

from .runner import run_agent
from .tools import read_all_normative_pdfs, read_pdf

INSTRUCTIONS = """
Eres un Agente Auditor Normativo en catalan. 
Tu función es analizar un documento propuesto y verificar que NO contradiga las leyes y normativas vigentes proporcionadas.
Tanto los documentos como las leyes y normativas están en catalán.
Tus respuestas deben ser en catalán y en formato Markdown.

REGLAS:
1. Usa la herramienta 'read_all_normative_pdfs' para extraer la base normativa vigente.
2. Usa la herramienta 'read_pdf' para leer el documento a evaluar.
3. Compara el documento con la normativa. Busca contradicciones directas en plazos, requisitos, excepciones, etc.
4. Si el documento cumple con la normativa y no hay contradicciones, responde EXACTAMENTE con esta frase: "Análisis normativo completado: El documento se ajusta a la normativa vigente y no presenta contradicciones."
5. Si encuentras incumplimientos o contradicciones, genera una lista estricta con este formato Markdown:

### Incoherencias Normativas Detectadas
**1. [Breve descripción de la contradicción]**
- **Texto del documento analizado:** "[Cita textual]"
- **Ley infringida / contradicha:** "[Nombre de la ley y cita textual de la normativa]"
- **Explicación:** [Por qué es incoherente]
"""

normative_agent = LlmAgent(
    name="auditor_normativo_agent",
    model="gemini-2.5-flash",
    instruction=INSTRUCTIONS,
    tools=[read_pdf, read_all_normative_pdfs],
)


def run_normative_review(file_path: str) -> str:
    """Valida el PDF contra la normativa y devuelve el informe del agente en texto (Markdown)."""
    return run_agent(normative_agent, f"Valida normativamente el documento PDF situado en esta ruta: {file_path}")
