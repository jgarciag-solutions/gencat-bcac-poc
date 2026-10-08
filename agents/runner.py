"""Ejecución síncrona de un agente ADK con un único mensaje de usuario."""
import asyncio
import os
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "bcac_poc"


async def _run(agent, prompt: str) -> str:
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    session = await session_service.create_session(app_name=APP_NAME, user_id="admin",
                                                   session_id=uuid.uuid4().hex)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    answer = ""
    async for event in runner.run_async(user_id="admin", session_id=session.id, new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            answer = "".join(p.text or "" for p in event.content.parts).strip()
    if not answer:
        raise RuntimeError("El agente no devolvió ninguna respuesta.")
    return answer


def run_agent(agent, prompt: str) -> str:
    """Ejecuta `agent` con `prompt` y devuelve su respuesta final en texto."""
    # google-genai lee GOOGLE_API_KEY; se acepta también GEMINI_API_KEY del .env.
    key = os.environ.get("GEMINI_API_KEY")
    if key and not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = key
    return asyncio.run(_run(agent, prompt))
