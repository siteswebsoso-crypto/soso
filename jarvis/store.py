"""Stockage persistant : mémoire long terme et rappels (fichiers JSON)."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path


class JsonList:
    """Liste d'objets JSON persistée sur disque, thread-safe, écriture atomique."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _write(self, items: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list[dict]:
        with self._lock:
            return self._read()

    def add(self, item: dict) -> dict:
        item = {"id": uuid.uuid4().hex[:8], **item}
        with self._lock:
            items = self._read()
            items.append(item)
            self._write(items)
        return item

    def remove(self, item_id: str) -> bool:
        with self._lock:
            items = self._read()
            kept = [i for i in items if i["id"] != item_id]
            self._write(kept)
            return len(kept) != len(items)

    def update(self, item_id: str, **fields) -> None:
        with self._lock:
            items = self._read()
            for i in items:
                if i["id"] == item_id:
                    i.update(fields)
            self._write(items)


class Store:
    def __init__(self, root: Path):
        self.memories = JsonList(root / "memory.json")
        self.reminders = JsonList(root / "reminders.json")

    def remember(self, fact: str) -> dict:
        return self.memories.add({"fact": fact, "created": datetime.now().isoformat(timespec="seconds")})

    def add_reminder(self, when: datetime, message: str) -> dict:
        return self.reminders.add(
            {"when": when.isoformat(timespec="seconds"), "message": message, "done": False}
        )

    def due_reminders(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now()
        return [
            r for r in self.reminders.all()
            if not r["done"] and datetime.fromisoformat(r["when"]) <= now
        ]
