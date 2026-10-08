"""Canaux de communication : comment Jarvis vous parle et vous pose des questions.

Le même mécanisme sert au clavier, à la voix et à Telegram. Les agents qui travaillent en
arrière-plan (projets) passent par `ask()` : la question est annoncée, et votre prochaine
réponse (tapée, dite ou envoyée) lui est transmise au lieu de partir comme nouvel ordre.
"""

from __future__ import annotations

import re
import threading
from typing import Callable


class PendingQuestion:
    def __init__(self, question: str):
        self.question = question
        self.answer: str | None = None
        self._event = threading.Event()

    def resolve(self, answer: str) -> None:
        self.answer = answer
        self._event.set()

    def wait(self, timeout: float) -> str | None:
        self._event.wait(timeout)
        return self.answer


class Channel:
    def __init__(self, say: Callable[[str], None]):
        self._say = say
        self._ask_lock = threading.Lock()
        self.pending: PendingQuestion | None = None

    def say(self, text: str) -> None:
        try:
            self._say(text)
        except Exception as exc:  # noqa: BLE001 - un canal en panne ne doit pas bloquer un projet
            print(f"[canal] {exc}")

    def ask(self, question: str, timeout: float = 1800) -> str | None:
        """Pose une question depuis un thread d'arrière-plan et attend la réponse (None si pas de réponse)."""
        with self._ask_lock:  # une question à la fois
            pending = PendingQuestion(question)
            self.pending = pending
            try:
                self.say(question)
                return pending.wait(timeout)
            finally:
                self.pending = None

    def deliver(self, text: str) -> bool:
        """À appeler par la boucle principale : True si le texte répondait à une question en attente."""
        pending = self.pending
        if pending is None:
            return False
        pending.resolve(text)
        return True


YES_WORDS = ("oui", "ok", "okay", "vas-y", "vas y", "go", "lance", "confirme", "valide", "d'accord",
             "parfait", "c'est bon", "yes", "allez")
NO_WORDS = ("non", "attends", "stop", "annule", "pas", "no")


def parse_confirmation(answer: str | None) -> tuple[bool, str]:
    """Interprète une réponse libre : « oui », « non », « non, mais ajoute un blog »…

    Renvoie (approuvé, remarque) — la remarque est transmise à Claude pour qu'il ajuste.
    """
    if not answer:
        return False, ""
    text = answer.strip().lower()
    first = text.replace(",", " ").replace(".", " ").split()[:1]
    if first and first[0] in NO_WORDS:
        return False, answer.strip()
    if any(re.search(rf"(^|\W){re.escape(w)}(\W|$)", text) for w in YES_WORDS):
        rest = answer.strip()
        return True, rest if len(rest.split()) > 2 else ""
    return False, answer.strip()
