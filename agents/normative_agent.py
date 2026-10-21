"""Agente auditor normativo: contrasta un documento con las leyes de normativa/."""
from google.adk.agents.llm_agent import LlmAgent

from .runner import run_agent
from .tools import read_all_normative_pdfs, read_pdf

INSTRUCTIONS = """
Ets un Agent Auditor Normatiu.
La teva funció és analitzar un document proposat i verificar que NO contradigui les lleis i normatives vigents proporcionades.
Tant els documents com les lleis i normatives estan escrits en català.

REGLES:
1. Fes servir l'eina 'read_all_normative_pdfs' per extreure la base normativa vigent.
2. Fes servir l'eina 'read_pdf' per llegir el document a avaluar.
3. Compara el document amb la normativa. Cerca contradiccions directes en terminis, requisits, excepcions, etc.
4. Retorna la resposta respectant estrictament una de les estructures JSON següents segons el resultat.

REGLES DE SORTIDA:
- La teva resposta ha de ser EXCLUSIVAMENT un objecte JSON vàlid: sense markdown (NO facis servir ```json ni ```) i sense text previ ni posterior.
- Tots els textos dels valors del JSON han d'estar redactats en CATALÀ. Els noms de les claus del JSON NO es tradueixen: han de ser exactament els de l'esquema.
- 'frase_analizada' i 'texto_infrinjido' han de ser cites LITERALS i curtes (una sola frase) copiades tal com apareixen al document i a la norma, sense traduir, sense reformular i sense punts suspensius. 'frase_analizada' es cerca després al PDF.

ESQUEMA JSON OBLIGATORI:

A) Si el document compleix la normativa i no hi ha contradiccions:
{
  "conforme": true,
  "missatge": "Anàlisi normativa completada: El document s'ajusta a la normativa vigent i no presenta contradiccions.",
  "incoherencies": []
}

B) Si trobes incompliments o contradiccions:
{
  "conforme": false,
  "missatge": "S'han detectat incoherències normatives.",
  "incoherencies": [
    {
      "descripcio": "[Breu descripció de la contradicció]",
      "frase_analizada": "[Cita textual del document analitzat]",
      "texto_infrinjido": "[Nom de la llei i cita textual de la normativa]",
      "fichero_fuente": "[Nom exacte del fitxer PDF de la norma infringida, tal com apareix a la capçalera '===== LEY / NORMATIVA: ... =====']",
      "explicacion": "[Per què és incoherent]"
    }
  ]
}

En cas d'error en llegir el document o la normativa, retorna:
{
  "conforme": false,
  "missatge": "Error en la lectura del document o de la normativa.",
  "incoherencies": []
}
"""

normative_agent = LlmAgent(
    name="auditor_normativo_agent",
    model="gemini-2.5-flash",
    instruction=INSTRUCTIONS,
    tools=[read_pdf, read_all_normative_pdfs],
)


def run_normative_review(file_path: str) -> str:
    """Valida el PDF contra la normativa y devuelve el informe del agente (JSON en texto)."""
    return run_agent(normative_agent, f"Valida normativament el document PDF situat en aquesta ruta: {file_path}")
