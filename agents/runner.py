"""Ejecución síncrona de un agente ADK con un único mensaje de usuario."""
import asyncio
import os
import uuid

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "bcac_poc"
# Tope de llamadas al modelo por ejecución (lectura de PDF + respuesta final ocupan unas 4): si el modelo insistiera
# en una respuesta que no cumple el esquema, ADK reintentaría hasta 500 veces.
MAX_LLM_CALLS = 25
# Gemini devuelve a veces MALFORMED_FUNCTION_CALL al entregar el resultado estructurado (fallo transitorio):
# se reintenta la ejecución completa en lugar de dar el análisis por fallido.
MAX_ATTEMPTS = 3


class _EmptyAnswer(RuntimeError):
    def __init__(self, error_code: str = ""):
        super().__init__("El agente no devolvió ninguna respuesta" + (f" ({error_code})." if error_code else "."))


async def _run(agent, prompt: str) -> str:
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    session = await session_service.create_session(app_name=APP_NAME, user_id="admin",
                                                   session_id=uuid.uuid4().hex)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    answer, error = "", ""
    async for event in runner.run_async(user_id="admin", session_id=session.id, new_message=message,
                                        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS)):
        if event.is_final_response() and event.content and event.content.parts:
            answer = "".join(p.text or "" for p in event.content.parts).strip()
        elif event.is_final_response() and event.error_code:
            error = event.error_code
    if not answer:
        raise _EmptyAnswer(error)
    return answer


def run_agent(agent, prompt: str) -> str:
    """Ejecuta `agent` con `prompt` y devuelve su respuesta final en texto."""
    # google-genai lee GOOGLE_API_KEY; se acepta también GEMINI_API_KEY del .env.
    key = os.environ.get("GEMINI_API_KEY")
    if key and not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = key
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return asyncio.run(_run(agent, prompt))
        except _EmptyAnswer:
            if attempt == MAX_ATTEMPTS:
                raise
