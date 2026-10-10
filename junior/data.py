"""Données de Jarvis Junior : devoirs, difficultés, consignes des parents, rapports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from jarvis.store import JsonList

TODO, DONE, PARTIAL = "à faire", "fait", "partiel"

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


class Store:
    def __init__(self, root: Path):
        self.root = root
        (root / "photos").mkdir(parents=True, exist_ok=True)
        self.homework = JsonList(root / "homework.json")
        self.difficulties = JsonList(root / "difficulties.json")
        self.parent_notes = JsonList(root / "parent_notes.json")
        self.reports = JsonList(root / "reports.json")

    # ------------------------------------------------------------------ devoirs
    def add_homework(self, child_id: str, subject: str, task: str, due: str | None = None,
                     minutes: int = 15, kind: str = "exercice", photo: str | None = None) -> dict:
        return self.homework.add({
            "child": child_id, "subject": subject, "task": task, "due": due, "minutes": int(minutes),
            "kind": kind, "status": TODO, "comment": "", "photo": photo, "added": now_iso(), "done_at": None,
        })

    def pending(self, child_id: str) -> list[dict]:
        items = [h for h in self.homework.all() if h["child"] == child_id and h["status"] != DONE]
        return sorted(items, key=lambda h: (h["due"] or "9999-12-31", h["added"]))

    def tonight(self, child_id: str, today: date | None = None) -> list[dict]:
        """Devoirs à traiter ce soir : ceux à rendre d'ici le prochain jour de classe, plus les retards."""
        limit = next_school_day(today).isoformat()
        return [h for h in self.pending(child_id) if h["due"] is None or h["due"] <= limit]

    def set_status(self, hw_id: str, status: str, comment: str = "") -> dict | None:
        fields = {"status": status, "comment": comment}
        if status == DONE:
            fields["done_at"] = now_iso()
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
                                      "detail": detail, "date": now_iso()})

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
