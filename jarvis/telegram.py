"""Pilotage de Jarvis depuis le téléphone via un bot Telegram (API HTTP, stdlib uniquement).

Le bot tourne sur l'ordinateur : vos messages Telegram deviennent des ordres exécutés sur la machine.
Seuls les identifiants listés dans `telegram_allowed_ids` sont écoutés.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .channels import parse_confirmation



class TelegramBot:
    def __init__(self, token: str, allowed_ids: list[int]):
        if not token:
            raise ValueError("Aucun token Telegram : renseignez telegram_token dans ~/.jarvis/config.json")
        self.base = f"https://api.telegram.org/bot{token}/"
        self.allowed = set(allowed_ids)
        self.offset = 0
        self.last_chat: int | None = None

    def _api(self, method: str, timeout: float = 40, **params) -> dict:
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + method, data=data, timeout=timeout) as resp:
            return json.loads(resp.read())

    def send(self, chat_id: int, text: str) -> None:
        for i in range(0, len(text) or 1, 4000):  # limite Telegram : 4096 caractères
            self._api("sendMessage", chat_id=chat_id, text=text[i:i + 4000] or "…")

    def broadcast(self, text: str) -> None:
        for chat_id in self.allowed:
            self.send(chat_id, text)

    def updates(self):
        """Génère (chat_id, texte) pour chaque message autorisé reçu (long polling)."""
        while True:
            try:
                res = self._api("getUpdates", offset=self.offset, timeout=30)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print(f"[telegram] réseau : {exc} — nouvel essai dans 5 s")
                time.sleep(5)
                continue
            for upd in res.get("result", []):
                self.offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = msg.get("text")
                user_id = (msg.get("from") or {}).get("id")
                if not text:
                    continue
                if user_id not in self.allowed:
                    print(f"[telegram] message ignoré de l'id {user_id} (non autorisé)")
                    self.send(msg["chat"]["id"], f"Accès refusé. Votre id Telegram est {user_id}.")
                    continue
                yield msg["chat"]["id"], text

    def approver(self) -> Callable[[str], tuple[bool, str]]:
        def ask(description: str) -> tuple[bool, str]:
            chat = self.last_chat
            if chat is None:
                return False, ""
            self.send(chat, f"⚠️ Autorisez-vous cette action ?\n\n{description}\n\n"
                            "Répondez « oui », « non », ou « non, mais … » pour corriger.")
            for chat_id, text in self.updates():
                if chat_id == chat:
                    return parse_confirmation(text)
            return False, ""
        return ask
