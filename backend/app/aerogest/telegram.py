"""Dedicated Telegram bot for Aérogest alerts (AEROGEST_TG_TOKEN), separate from the scanner bot."""
from __future__ import annotations

import httpx


def _url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def send(token: str, chat_id: str, text: str, timeout: float = 15.0) -> bool:
    try:
        r = httpx.post(_url(token, "sendMessage"), timeout=timeout,
                       json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
        return r.status_code == 200 and r.json().get("ok", False)
    except Exception:
        return False


def find_start_chat(updates: list[dict]) -> str | None:
    """First private chat that sent /start."""
    for u in updates:
        m = u.get("message") or {}
        chat = m.get("chat") or {}
        if chat.get("type") == "private" and (m.get("text") or "").strip().startswith("/start"):
            return str(chat["id"])
    return None


def discover_chat_id(token: str, timeout: float = 15.0) -> str | None:
    try:
        r = httpx.get(_url(token, "getUpdates"), params={"timeout": 0}, timeout=timeout)
        return find_start_chat(r.json().get("result") or [])
    except Exception:
        return None
