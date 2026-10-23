"""Esquemas de salida de los agentes (Pydantic).

Con `output_schema`, ADK obliga al modelo a entregar el resultado como llamada a una función con estos campos:
los argumentos se validan y se serializan con `json.dumps`, así que el JSON siempre es válido (comillas y saltos
de línea dentro de las citas literales del PDF incluidos). Los nombres de los campos NO se pueden cambiar: el
dashboard (`renderAIReport`) y `pdf_annotator.py` dependen de ellos.
"""
from pydantic import BaseModel, Field

class ClarityFinding(BaseModel):
    descripcio: str = Field(description="Explicació breu del problema detectat, en català")
    frase_analizada: str = Field(description="Cita textual literal i curta del document, sense punts suspensius")
    explicacion: str = Field(description="Motiu detallat pel qual la frase és incoherent o poc clara, en català")
    propuesta: str = Field(description="Proposta de redacció alternativa en català")


class ClarityReport(BaseModel):
    conforme: bool = Field(description="true si el document és clar i no té incoherències")
    missatge: str = Field(description="Missatge resum en català")
    incoherencies: list[ClarityFinding] = Field(default_factory=list)


class NormativeFinding(BaseModel):
    descripcio: str = Field(description="Breu descripció de la contradicció, en català")
    frase_analizada: str = Field(description="Cita textual literal i curta del document analitzat, sense punts suspensius")
    texto_infrinjido: str = Field(default="", description="Nom de la llei i cita textual de la normativa")
    fichero_fuente: str = Field(default="", description="Nom exacte del fitxer PDF de la norma, tal com apareix a la capçalera")
    explicacion: str = Field(description="Per què és incoherent, en català")


class NormativeReport(BaseModel):
    conforme: bool = Field(description="true si el document compleix la normativa")
    missatge: str = Field(description="Missatge resum en català")
    incoherencies: list[NormativeFinding] = Field(default_factory=list)


class FidelityFinding(BaseModel):
    titulo: str = Field(description="Breu títol de la incoherència, en català")
    frase_analizada: str = Field(description="Cita textual literal i curta del document adaptat, sense punts suspensius")
    texto_infrinjido: str = Field(default="", description="Nom o ID del document base i cita textual del document base")
    fichero_fuente: str = Field(default="", description="Nom exacte o ID del PDF base, tal com apareix a la capçalera")
    explicacion: str = Field(description="Explicació concisa de la manca de fidelitat, en català")


class JudgeEntry(BaseModel):
    """Veredicto del agente de fidelidad sobre una unidad del documento font."""
    id: int = Field(description="Número 'id' de la unitat del document font, tal com apareix a la llista rebuda")
    veredicte: str = Field(description="Exactament un de: 'contradiu' o 'no_contradiu'")
    chunk_id: int = Field(default=0, description="Si 'contradiu': número del fragment candidat de l'adaptat (sense la [c]); 0 si no")
    cita: str = Field(default="", description="Si 'contradiu': cita LITERAL d'UNA sola frase del fragment candidat que fonamenta la contradicció (la part mínima amb la xifra o condició), sense punts suspensius")
    dimensio: str = Field(default="", description="Si 'contradiu': dimensió en què difereixen (xifra, any, edat, territori, destinatari, ingressos, condició)")
    titol: str = Field(default="", description="Si 'contradiu': breu títol de la contradicció, en català")
    motiu: str = Field(default="", description="Si 'contradiu': per què no poden ser certes alhora, en català")


class FidelityJudgement(BaseModel):
    """Salida del agente de fidelidad: una entrada por unidad del font. El código la convierte en FidelityReport."""
    entrades: list[JudgeEntry] = Field(default_factory=list)


class FidelityReport(BaseModel):
    fiel: bool = Field(description="true si l'adaptació és totalment fidel a les fonts")
    mensaje: str = Field(description="Missatge resum en català")
    incoherencias: list[FidelityFinding] = Field(default_factory=list)
