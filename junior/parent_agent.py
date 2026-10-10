"""L'assistant des parents sur Telegram : gère les devoirs, les consignes et les questions."""

from __future__ import annotations

import time
from datetime import date

from .config import Config
from .data import DONE, PARTIAL, TODO, WEEKDAYS, Store, human_date
from .llm import FALLBACK, obj, text_of, validate

MAX_STEPS = 12
CONVERSATION_TTL = 3 * 3600  # au-delà, nouvelle conversation


def _tools(cfg: Config) -> list[dict]:
    child_ids = [c.id for c in cfg.children]
    return [
        {"name": "list_homework", "description": "Liste les devoirs non terminés (d'un enfant, ou de tous).",
         "input_schema": obj({"child": {"type": "string", "enum": child_ids + ["inconnu", "tous"]}})},
        {"name": "add_homework", "description": "Ajoute un devoir.",
         "input_schema": obj({
             "child": {"type": "string", "enum": child_ids},
             "subject": {"type": "string"}, "task": {"type": "string"},
             "due": {"type": "string", "description": "AAAA-MM-JJ"},
             "minutes": {"type": "integer"},
             "kind": {"type": "string", "enum": ["exercice", "leçon", "récitation", "lecture", "rédaction",
                                                  "révision contrôle", "autre"]},
         }, ["child", "subject", "task"])},
        {"name": "update_homework", "description": "Modifie un devoir (enfant, matière, consigne, date, durée, statut).",
         "input_schema": obj({
             "id": {"type": "string"}, "child": {"type": "string", "enum": child_ids},
             "subject": {"type": "string"}, "task": {"type": "string"}, "due": {"type": "string"},
             "minutes": {"type": "integer"}, "status": {"type": "string", "enum": [TODO, DONE, PARTIAL]},
         }, ["id"])},
        {"name": "delete_homework", "description": "Supprime un devoir.",
         "input_schema": obj({"id": {"type": "string"}}, ["id"])},
        {"name": "add_note", "description": "Enregistre une consigne pour les prochaines séances "
         "(ex : « insiste sur les tables de 7 », « Ibrahim a un contrôle d'histoire jeudi »).",
         "input_schema": obj({"child": {"type": "string", "enum": child_ids + ["tous"]},
                              "text": {"type": "string"}}, ["child", "text"])},
        {"name": "list_notes", "description": "Liste les consignes actives.", "input_schema": obj({})},
        {"name": "remove_note", "description": "Retire une consigne devenue inutile.",
         "input_schema": obj({"id": {"type": "string"}}, ["id"])},
        {"name": "recent_reports", "description": "Derniers rapports de séance d'un enfant.",
         "input_schema": obj({"child": {"type": "string", "enum": child_ids}}, ["child"])},
        {"name": "difficulties", "description": "Difficultés repérées chez un enfant (30 derniers jours).",
         "input_schema": obj({"child": {"type": "string", "enum": child_ids}}, ["child"])},
    ]


class ParentAgent:
    def __init__(self, cfg: Config, store: Store, client):
        self.cfg = cfg
        self.store = store
        self.client = client
        self.tools = _tools(cfg)
        self.conversations: dict[int, dict] = {}

    def system_prompt(self) -> str:
        kids = ", ".join(f"{c.name} ({c.grade}, id « {c.id} »)" for c in self.cfg.children)
        return f"""Tu es Jarvis Junior, l'assistant qui aide les enfants de la famille à faire leurs \
devoirs : {kids}. Tu parles ici aux parents, sur Telegram. Tu peux gérer la liste des devoirs, \
enregistrer leurs consignes pour les prochaines séances et répondre à leurs questions sur le travail \
et les difficultés des enfants. Réponds en français, de façon brève et claire (c'est une messagerie). \
Quand un parent corrige une liste de devoirs que tu viens d'enregistrer (« c'est pour Ibrahim », \
« enlève la poésie », « c'est pour jeudi »), applique la correction avec tes outils puis confirme \
en une phrase."""

    def handle(self, chat_id: int, author: str, text: str, context: str = "") -> str:
        conv = self.conversations.get(chat_id)
        if conv is None or time.time() - conv["t"] > CONVERSATION_TTL:
            conv = {"t": time.time(), "messages": []}
            self.conversations[chat_id] = conv
        conv["t"] = time.time()
        today = date.today()
        prefix = f"[{WEEKDAYS[today.weekday()]} {today:%d/%m/%Y} — message de {author}]"
        if context:
            prefix += f"\n[Contexte : {context}]"
        messages = conv["messages"]
        self._append_user(messages, [{"type": "text", "text": f"{prefix}\n{text}"}])

        for _ in range(MAX_STEPS):
            response = self.client.beta.messages.create(
                model=self.cfg.model, max_tokens=4000, system=self.system_prompt(), tools=self.tools,
                messages=messages, thinking={"type": "adaptive"}, output_config={"effort": "low"},
                cache_control={"type": "ephemeral"}, **FALLBACK,
            )
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                return text_of(response) or "C'est noté."
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                schema = next((t["input_schema"] for t in self.tools if t["name"] == block.name), None)
                problem = validate(schema, block.input) if schema else f"outil inconnu {block.name}"
                try:
                    content, error = (problem, True) if problem else (self._run(block.name, block.input, author), False)
                except Exception as exc:  # noqa: BLE001
                    content, error = f"Erreur : {exc}", True
                result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
                if error:
                    result["is_error"] = True
                results.append(result)
            self._append_user(messages, results)
        return "Je n'ai pas réussi à tout traiter, pouvez-vous reformuler ?"

    @staticmethod
    def _append_user(messages: list[dict], blocks: list[dict]) -> None:
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": "user", "content": blocks})

    def _run(self, name: str, a: dict, author: str) -> str:
        s = self.store
        if name == "list_homework":
            who = a.get("child", "tous")
            items = [h for h in s.homework.all() if h["status"] != DONE and who in ("tous", h["child"])]
            return "\n".join(f"[{h['id']}] {self._name(h['child'])} — {h['subject']} : {h['task']} "
                             f"({human_date(h['due'])}, ~{h['minutes']} min, {h['status']})" for h in items) \
                or "Aucun devoir en attente."
        if name == "add_homework":
            h = s.add_homework(a["child"], a["subject"], a["task"], a.get("due") or None,
                               a.get("minutes", 15), a.get("kind", "exercice"))
            return f"Ajouté [{h['id']}]."
        if name == "update_homework":
            fields = {k: v for k, v in a.items() if k != "id"}
            if not any(h["id"] == a["id"] for h in s.homework.all()):
                return "Id introuvable."
            s.homework.update(a["id"], **fields)
            return "Modifié."
        if name == "delete_homework":
            return "Supprimé." if s.homework.remove(a["id"]) else "Id introuvable."
        if name == "add_note":
            n = s.add_note(a["child"], a["text"], author)
            return f"Consigne [{n['id']}] enregistrée."
        if name == "list_notes":
            notes = [n for n in s.parent_notes.all() if n.get("active", True)]
            return "\n".join(f"[{n['id']}] {self._name(n['child'])} : {n['text']} ({n['author']})" for n in notes) \
                or "Aucune consigne."
        if name == "remove_note":
            s.parent_notes.update(a["id"], active=False)
            return "Consigne retirée."
        if name == "recent_reports":
            reports = [r for r in s.reports.all() if r["child"] == a["child"]][-3:]
            return "\n\n".join(f"{r['date'][:16]} :\n{r['text']}" for r in reports) or "Aucun rapport."
        if name == "difficulties":
            return s.difficulty_history(a["child"])
        raise ValueError(f"Outil inconnu : {name}")

    def _name(self, child_id: str) -> str:
        c = self.cfg.child(child_id)
        return c.name if c else child_id
