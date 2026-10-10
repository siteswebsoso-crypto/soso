"""Données de Jarvis Junior : devoirs, difficultés, consignes des parents, rapports."""

from __future__ import annotations

import contextlib
import json
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows : verrou entre processus indisponible (verrou de thread seulement)
    fcntl = None

TODO, DONE, PARTIAL = "à faire", "fait", "partiel"

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def utc_now() -> str:
    """Horodatage UTC au format de l'espace parents (comparaisons entre le Mac et Netlify)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def human_date(iso: str | None, today: date | None = None) -> str:
    if not iso:
        return "sans date"
    today = today or date.today()
    d = date.fromisoformat(iso)
    delta = (d - today).days
    if delta == 0:
        return "pour aujourd'hui"
    if delta == 1:
        return "pour demain"
    if 1 < delta < 7:
        return f"pour {WEEKDAYS[d.weekday()]}"
    if delta < 0:
        return f"en retard (le {d:%d/%m})"
    return f"pour le {WEEKDAYS[d.weekday()]} {d:%d/%m}"


def next_school_day(today: date | None = None) -> date:
    """Le prochain jour de classe (le vendredi soir, c'est lundi)."""
    d = (today or date.today()) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class SharedList:
    """Liste JSON partagée entre l'application et le service de fond (verrou de fichier + écriture atomique)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def _locked(self):
        with self._lock, open(self.path.with_suffix(".lock"), "w") as lockfile:
            if fcntl:
                fcntl.flock(lockfile, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(lockfile, fcntl.LOCK_UN)

    def _read(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write(self, items: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list[dict]:
        with self._locked():
            return self._read()

    def mutate(self, fn):
        """Lecture-modification-écriture atomique : `fn(items)` modifie la liste et peut renvoyer un résultat."""
        with self._locked():
            items = self._read()
            result = fn(items)
            self._write(items)
            return result

    def add(self, item: dict) -> dict:
        item = {"id": uuid.uuid4().hex[:8], **item}
        self.mutate(lambda items: items.append(item))
        return item

    def remove(self, item_id: str) -> bool:
        def fn(items):
            before = len(items)
            items[:] = [i for i in items if i["id"] != item_id]
            return len(items) != before
        return self.mutate(fn)

    def update(self, item_id: str, **fields) -> None:
        def fn(items):
            for i in items:
                if i["id"] == item_id:
                    i.update(fields)
        self.mutate(fn)


class Store:
    def __init__(self, root: Path):
        self.root = root
        (root / "photos").mkdir(parents=True, exist_ok=True)
        self.homework = SharedList(root / "homework.json")
        self.difficulties = SharedList(root / "difficulties.json")
        self.parent_notes = SharedList(root / "parent_notes.json")
        self.reports = SharedList(root / "reports.json")
        self.deleted = SharedList(root / "deleted.json")  # suppressions faites sur le Mac, à transmettre

    # ------------------------------------------------------------------ devoirs
    def add_homework(self, child_id: str, subject: str, task: str, due: str | None = None,
                     minutes: int = 15, kind: str = "exercice", photo: str | None = None) -> dict:
        """Devoir créé sur le Mac : il sera envoyé à l'espace parents à la prochaine synchronisation."""
        return self.homework.add({
            "child": child_id, "subject": subject, "task": task, "due": due, "minutes": int(minutes),
            "kind": kind, "status": TODO, "comment": "", "photo": photo, "added": now_iso(), "done_at": None,
            "status_at": utc_now(), "local_new": True,
        })

    def delete_homework(self, hw_id: str) -> bool:
        removed = self.homework.remove(hw_id)
        if removed:
            self.deleted.add({"hw": hw_id})
        return removed

    def pending(self, child_id: str) -> list[dict]:
        items = [h for h in self.homework.all() if h["child"] == child_id and h["status"] != DONE]
        return sorted(items, key=lambda h: (h["due"] or "9999-12-31", h["added"]))

    def tonight(self, child_id: str, today: date | None = None) -> list[dict]:
        """Devoirs à traiter ce soir : ceux à rendre d'ici le prochain jour de classe, plus les retards."""
        limit = next_school_day(today).isoformat()
        return [h for h in self.pending(child_id) if h["due"] is None or h["due"] <= limit]

    def set_status(self, hw_id: str, status: str, comment: str = "") -> dict | None:
        fields = {"status": status, "comment": comment, "status_at": utc_now(), "dirty": True}
        if status == DONE:
            fields["done_at"] = utc_now()
        self.homework.update(hw_id, **fields)
        return next((h for h in self.homework.all() if h["id"] == hw_id), None)

    def describe_homework(self, items: list[dict]) -> str:
        if not items:
            return "(aucun devoir enregistré)"
        return "\n".join(
            f"- [{h['id']}] {h['subject']} : {h['task']} — {human_date(h['due'])}, ~{h['minutes']} min"
            f" ({h['kind']}, {h['status']}{' : ' + h['comment'] if h['comment'] else ''})"
            for h in items
        )

    # ------------------------------------------------------------------ suivi
    def log_difficulty(self, child_id: str, subject: str, topic: str, detail: str) -> dict:
        return self.difficulties.add({"child": child_id, "subject": subject, "topic": topic,
                                      "detail": detail, "date": now_iso(), "synced": False})

    def difficulty_history(self, child_id: str, days: int = 30) -> str:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        items = [d for d in self.difficulties.all() if d["child"] == child_id and d["date"] >= since]
        if not items:
            return "(rien de signalé ces 30 derniers jours)"
        counts: dict[tuple[str, str], list[dict]] = {}
        for d in items:
            counts.setdefault((d["subject"], d["topic"].lower()), []).append(d)
        lines = []
        for (subject, _), group in sorted(counts.items(), key=lambda kv: -len(kv[1])):
            last = group[-1]
            lines.append(f"- {subject} / {last['topic']} : {len(group)} fois, dernière le "
                         f"{last['date'][:10]} — {last['detail']}")
        return "\n".join(lines)

    def active_notes(self, child_id: str) -> list[dict]:
        return [n for n in self.parent_notes.all() if n["child"] in (child_id, "tous") and n.get("active", True)]

    def add_note(self, child_id: str, text: str, author: str) -> dict:
        return self.parent_notes.add({"child": child_id, "text": text, "author": author,
                                      "date": now_iso(), "active": True})
