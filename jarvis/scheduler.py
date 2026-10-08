"""Déclenche les rappels à l'heure prévue, en tâche de fond."""

from __future__ import annotations

import threading
from typing import Callable

from .store import Store


class ReminderScheduler(threading.Thread):
    def __init__(self, store: Store, notify: Callable[[str], None], interval: float = 15.0):
        super().__init__(daemon=True, name="jarvis-reminders")
        self.store = store
        self.notify = notify
        self.interval = interval
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(self.interval):
            self.tick()

    def tick(self) -> None:
        for reminder in self.store.due_reminders():
            self.store.reminders.update(reminder["id"], done=True)
            try:
                self.notify(reminder["message"])
            except Exception as exc:  # noqa: BLE001 - un canal en panne ne doit pas tuer le thread
                print(f"[rappel] échec de notification : {exc}")

    def stop(self) -> None:
        self._halt.set()
