"""Adaptateur local OpenAI -> Anthropic pour AgentRouter.

AgentRouter filtre les empreintes TLS des clients OpenAI génériques. Ce service
reçoit les appels de CV Agent, puis utilise le SDK Anthropic synchrone accepté
par AgentRouter. La clé Bearer est transmise en mémoire, jamais journalisée.
"""
import asyncio
import os

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn


TARGET = os.getenv("AGENTROUTER_TARGET", "https://agentrouter.org")
app = FastAPI(title="CV Agent — proxy AgentRouter")


def _messages(body: dict) -> tuple[str, list[dict]]:
    system_parts = []
    messages = []
    for item in body.get("messages", []):
        role = item.get("role", "user")
        content = item.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if role == "system":
            system_parts.append(str(content))
        else:
            messages.append({"role": "assistant" if role == "assistant" else "user", "content": str(content)})
    if not messages:
        messages = [{"role": "user", "content": ""}]
    return "\n\n".join(system_parts), messages


def _call(key: str, body: dict):
    system, messages = _messages(body)
    response_format = body.get("response_format") or {}
    if isinstance(response_format, dict) and response_format.get("type") == "json_object":
        json_rule = (
            "Réponds uniquement avec un objet JSON valide. "
            "N'ajoute aucun Markdown, aucune balise ``` et aucun texte hors JSON."
        )
        system = f"{system}\n\n{json_rule}" if system else json_rule
    kwargs = {
        "model": body.get("model"),
        "messages": messages,
        "max_tokens": int(body.get("max_tokens") or 4096),
    }
    if system:
        kwargs["system"] = system
    return anthropic.Anthropic(api_key=key, base_url=TARGET).messages.create(**kwargs)


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return JSONResponse({"error": {"message": "Authorization Bearer manquante"}}, status_code=401)
    key = authorization[7:].strip()
    body = await request.json()
    try:
        response = await asyncio.to_thread(_call, key, body)
    except anthropic.APIStatusError as exc:
        return JSONResponse(exc.body or {"error": {"message": str(exc)}}, status_code=exc.status_code)
    except Exception as exc:  # noqa: BLE001 - réponse contrôlée au client
        return JSONResponse({"error": {"message": str(exc), "type": "proxy_error"}}, status_code=502)

    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    return {
        "id": response.id,
        "object": "chat.completion",
        "created": 0,
        "model": response.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7187)
