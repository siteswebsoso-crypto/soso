"""Client minimal de l'API Telegram Bot (bibliothèque standard uniquement)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path


class Telegram:
    def __init__(self, token: str):
        if not token:
            raise ValueError("Token Telegram manquant (lancez : python -m junior setup)")
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, http_timeout: float = 40, **params) -> dict:
        data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
        with urllib.request.urlopen(self.base + method, data=data, timeout=http_timeout) as resp:
            res = json.loads(resp.read())
        if not res.get("ok"):
            raise RuntimeError(f"Telegram {method} : {res}")
        return res["result"]

    def updates(self, offset: int, timeout: int = 30) -> list[dict]:
        return self.call("getUpdates", http_timeout=timeout + 10, offset=offset, timeout=timeout)

    def send(self, chat_id: int, text: str) -> None:
        for i in range(0, max(len(text), 1), 4000):
            self.call("sendMessage", chat_id=chat_id, text=text[i:i + 4000] or "…")

    def typing(self, chat_id: int) -> None:
        try:
            self.call("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:  # noqa: BLE001 - purement cosmétique
            pass

    def download(self, file_id: str, dest: Path) -> Path:
        info = self.call("getFile", file_id=file_id)
        url = f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}"
        dest = dest.with_suffix(Path(info["file_path"]).suffix or ".jpg")
        with urllib.request.urlopen(url, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return dest


def image_file_id(message: dict) -> str | None:
    """Renvoie l'identifiant de l'image d'un message (photo, ou image envoyée comme fichier)."""
    if message.get("photo"):
        return message["photo"][-1]["file_id"]  # la plus grande taille
    doc = message.get("document") or {}
    if (doc.get("mime_type") or "").startswith("image/"):
        return doc["file_id"]
    return None
