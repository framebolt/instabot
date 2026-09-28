"""Groq API calls with sarcastic persona."""
import logging

from groq import Groq

import config

log = logging.getLogger("ai_handler")

_client = None


def _get_client():
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def generate_reply(user_message: str, sender_username: str, history: list | None = None) -> str:
    """Sync Groq call. Returns lowercase roast, max ~15 words enforced by prompt."""
    history = history or []
    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    for h in history[-5:]:
        try:
            messages.append({"role": "user", "content": f"{h.get('sender', 'user')}: {h.get('text', '')}"})
        except Exception:
            continue
    messages.append({"role": "user", "content": f"{sender_username}: {user_message}"})

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            messages=messages,
            model=config.GROQ_MODEL,
            temperature=0.9,
            max_tokens=100,
        )
        text = (resp.choices[0].message.content or "").strip().lower()
        return text if text else "lol nice try, say that again slower."
    except Exception as e:
        print(f"[ai] groq error: {e}", flush=True)
        return "lol groq died, even the ai is roasting your timing."
