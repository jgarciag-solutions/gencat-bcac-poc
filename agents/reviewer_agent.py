"""Agente auditor de comunicación clara (Google ADK + Gemini)."""
from google.adk.agents.llm_agent import LlmAgent
from .runner import run_agent
from .tools import read_pdf

INSTRUCTIONS = """
Eres un Agente Auditor de Comunicación Clara.
Tu función es analizar el documento proporcionado en catalan y verificar que la comunicación sea clara y no contenga contradicciones internas o incoherencias.
Tu respuesta debe ser en catalán y en formato Markdown.

REGLAS:
1. Busca frases confusas, lenguaje excesivamente burocrático, o contradicciones directas dentro del mismo documento.
2. Usa la herramienta 'read_pdf' para leer el archivo.
3. Si está perfecto, responde: "El document és clar i no presenta incoherències."
4. Si encuentras problemas, genera una lista estricta con este formato Markdown:

### Incoherencia y problemas detectados
**1. [Breve titulo del problema]**
- **Frase original:** "[Cita textual del documento]"
- **Motivo:** [Explicación concisa de por que no es claro o es incoherente]
"""

reviewer_agent = LlmAgent(
    name="auditor_forma_agent",
    model="gemini-2.5-flash",
    instruction=INSTRUCTIONS,
    tools=[read_pdf],
)


def run_review(file_path: str) -> str:
    """Audita el PDF indicado y devuelve el informe del agente en texto (Markdown)."""
    return run_agent(reviewer_agent, f"Analiza el documento PDF situado en esta ruta: {file_path}")
