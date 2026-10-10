"""L'instituteur virtuel : mène la séance de devoirs à l'oral, de l'accueil au rapport final."""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime
from typing import Protocol

from .config import Child, Config
from .data import DONE, PARTIAL, TODO, WEEKDAYS, Store
from .llm import FALLBACK, obj, validate
from .report import build_report, send_report

MAX_STEPS = 10
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class UI(Protocol):
    def say(self, sentence: str) -> None: ...
    def event(self, kind: str, **data) -> None: ...


def system_prompt(cfg: Config, store: Store, child: Child, today: date) -> str:
    tonight = store.tonight(child.id, today)
    later = [h for h in store.pending(child.id) if h not in tonight]
    notes = "\n".join(f"- {n['text']} ({n['author']}, le {n['date'][:10]})" for n in store.active_notes(child.id)) \
        or "(aucune)"
    total = sum(h["minutes"] for h in tonight)
    return f"""Tu es Jarvis, l'instituteur personnel de {child.name}, élève de {child.level}. \
Tu l'aides à faire ses devoirs du soir, uniquement à l'oral : tout ce que tu écris est lu à voix \
haute, et l'enfant te répond au micro. Nous sommes le {WEEKDAYS[today.weekday()]} {today:%d/%m/%Y}.

## Ta façon de parler
- Phrases courtes et simples, adaptées à son âge ; deux ou trois phrases maximum par réponse.
- Une seule question à la fois, puis tu attends sa réponse.
- Jamais de listes, de titres, d'émojis ni de symboles : écris comme tu parles ("trois quarts", \
"divisé par", "quatre au carré").
- Chaleureux, patient et encourageant, avec un peu d'humour. Félicite les efforts précis \
("bravo, tu as pensé à vérifier tes unités"), pas seulement le résultat.
- La reconnaissance vocale peut mal transcrire : si une réponse paraît bizarre, fais-la répéter \
gentiment plutôt que de la compter fausse.
- Si un mot, un calcul ou une règle gagne à être vu, affiche-le avec `show_on_screen`.

## Déroulé de la séance
1. Accueil : dis bonjour à {child.name} par son prénom, un petit mot d'encouragement sur sa \
journée, annonce combien de temps prendront les devoirs ce soir s'il est sérieux (environ \
{total} minutes d'après la liste), puis demande-lui s'il est prêt.
2. Choix : s'il n'y a qu'un devoir, propose-le. S'il y en a plusieurs, cite les matières et \
laisse-le choisir par lequel commencer. Appelle `set_current_homework` dès qu'un devoir commence.
3. Aide (le plus important) :
   - Tu ne donnes JAMAIS la réponse et tu ne rédiges jamais à sa place. Tu le guides par des \
questions et des indices de plus en plus précis.
   - Tu ne vois pas son cahier : demande-lui de te lire la consigne ou ce qu'il a écrit.
   - S'il bloque après trois indices, réexplique la notion avec un exemple différent et plus \
simple, puis reviens à son exercice.
   - Vérifie qu'il a compris en lui faisant expliquer avec ses mots comment il a trouvé.
   - Leçons et récitations : fais-le réciter, pose des questions de compréhension, aide-le à \
mémoriser par petits morceaux.
   - Devoir pour plus tard : s'il reste du temps, avance-le un peu (par exemple apprendre la \
première strophe ce soir).
4. Quand un devoir est fini : appelle `update_homework` (fait, ou partiel s'il n'a pas pu tout \
faire ou n'a pas vraiment compris), avec un commentaire court pour les parents. Note toute vraie \
difficulté avec `log_difficulty`.
5. Pauses : au bout d'environ {child.break_every} minutes de travail (le temps écoulé est indiqué \
dans chaque message), propose une courte pause avec `start_break`.
6. Fin : quand tout est fait (ou qu'il doit s'arrêter), remercie-le chaleureusement et dis au \
revoir, PUIS appelle `end_session` avec un rapport honnête pour les parents. Après `end_session`, \
ne dis plus rien.

## Règles
- Reste sur les devoirs et l'école. S'il parle d'autre chose, réponds d'une phrase gentille et \
ramène-le au travail.
- S'il dit qu'il a déjà fini un devoir, demande-lui de te le montrer à l'oral (lire sa réponse, \
réciter) avant de le marquer comme fait.
- S'il semble triste, fatigué ou contrarié, sois compréhensif, et signale-le aux parents dans le \
rapport. S'il évoque quelque chose de grave (danger, harcèlement, se faire mal), dis-lui avec \
douceur d'en parler tout de suite à papa ou maman, et signale-le clairement dans le rapport.
- Ne demande jamais d'informations personnelles.

## Devoirs de ce soir
{store.describe_homework(tonight)}

## Devoirs pour plus tard
{store.describe_homework(later)}

## Consignes des parents
{notes}

## Difficultés repérées les semaines précédentes (à faire retravailler si l'occasion se présente)
{store.difficulty_history(child.id)}"""


TOOLS = [
    {"name": "set_current_homework", "description": "Indique le devoir sur lequel on travaille maintenant "
     "(il est mis en avant à l'écran).",
     "input_schema": obj({"homework_id": {"type": "string"}}, ["homework_id"])},
    {"name": "update_homework", "description": "Met à jour l'état d'un devoir à la fin de son traitement.",
     "input_schema": obj({
         "homework_id": {"type": "string"},
         "status": {"type": "string", "enum": [DONE, PARTIAL, TODO]},
         "comment": {"type": "string", "description": "Une phrase pour les parents : comment ça s'est passé"},
     }, ["homework_id", "status", "comment"])},
    {"name": "log_difficulty", "description": "Note une difficulté réelle (notion mal comprise, erreur répétée).",
     "input_schema": obj({
         "subject": {"type": "string"},
         "topic": {"type": "string", "description": "La notion, ex : fractions décimales, accord du participe passé"},
         "detail": {"type": "string", "description": "Ce qui bloque précisément"},
     }, ["subject", "topic", "detail"])},
    {"name": "show_on_screen", "description": "Affiche en grand à l'écran un contenu court : un mot à "
     "épeler, un calcul posé, une règle, une conjugaison, une strophe à apprendre.",
     "input_schema": obj({"title": {"type": "string"}, "content": {"type": "string"}}, ["title", "content"])},
    {"name": "start_break", "description": "Lance une pause (l'écran affiche un minuteur).",
     "input_schema": obj({"minutes": {"type": "integer"}}, ["minutes"])},
    {"name": "end_session", "description": "Termine la séance et envoie le rapport aux deux parents.",
     "input_schema": obj({
         "summary": {"type": "string", "description": "2 ou 3 phrases : comment s'est passée la séance, "
                     "concentration, autonomie, humeur"},
         "difficulties": {"type": "array", "items": {"type": "string"},
                          "description": "Difficultés constatées ce soir, précises"},
         "to_review": {"type": "array", "items": {"type": "string"},
                       "description": "Ce que les parents pourraient faire réviser ou renforcer"},
         "finished": {"type": "boolean", "description": "Tous les devoirs de ce soir sont-ils terminés ?"},
     }, ["summary", "difficulties", "to_review", "finished"])},
]
for _t in TOOLS:
    _t["eager_input_streaming"] = True
_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}


class TutorSession:
    def __init__(self, cfg: Config, store: Store, child: Child, client, ui: UI, today: date | None = None):
        self.cfg, self.store, self.child, self.client, self.ui = cfg, store, child, client, ui
        self.today = today or date.today()
        self.system = system_prompt(cfg, store, child, self.today)
        self.homework_ids = {h["id"] for h in store.pending(child.id)}
        self.messages: list[dict] = []
        self.started = time.time()
        self.paused_seconds = 0.0
        self.ended = False
        self.report: str | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    # ------------------------------------------------------------------ API
    def minutes(self) -> int:
        return max(1, round((time.time() - self.started - self.paused_seconds) / 60))

    def start(self) -> None:
        self._turn(f"[Application] {self.child.name} vient d'ouvrir sa séance de devoirs. Accueille-le.")

    def reply(self, text: str) -> None:
        self._turn(text)

    def resume_after_break(self, seconds: float) -> None:
        self.paused_seconds += seconds
        self._turn("[Application] La pause est terminée, l'enfant est de retour.")

    def mute_current_turn(self) -> None:
        """L'enfant coupe la parole : le reste de la réponse en cours n'est pas lu."""
        self._cancel.set()

    def abort(self) -> None:
        """L'enfant ferme l'application : on fait quand même le rapport aux parents (sans parler)."""
        if self.ended:
            return
        self._cancel.set()
        with self._lock:
            if self.ended:
                return
            self._turn_locked("[Application] L'enfant a fermé l'application. N'écris rien : appelle "
                              "seulement end_session maintenant, avec finished à false si tout n'est pas fait.",
                              silent=True)
            if not self.ended:  # le modèle n'a pas coopéré : rapport minimal
                self._finish("Séance interrompue.", [], [], False)

    # ------------------------------------------------------------------ boucle
    def _turn(self, text: str) -> None:
        with self._lock:
            if self.ended:
                return
            self._cancel.clear()
            self._turn_locked(text)

    def _turn_locked(self, text: str, silent: bool = False) -> None:
        stamp = f"[{datetime.now():%H:%M} — {self.minutes()} min de séance]"
        self._append_user([{"type": "text", "text": f"{stamp} {text}"}])
        for _ in range(MAX_STEPS):
            response = self._stream(silent)
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "refusal":
                if not silent:
                    self.ui.say("Oups, je n'ai pas bien compris. On reprend nos devoirs ?")
                return
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return
            truncated = response.stop_reason == "max_tokens"
            self._append_user([self._execute(b, truncated) for b in tool_uses])
            if self.ended:
                return

    def _stream(self, silent: bool):
        buffer = ""
        with self.client.beta.messages.stream(
            model=self.cfg.model, max_tokens=8000, system=self.system, tools=TOOLS, messages=self.messages,
            thinking={"type": "adaptive"}, output_config={"effort": self.cfg.tutor_effort},
            cache_control={"type": "ephemeral"}, **FALLBACK,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                    buffer += event.delta.text
                    *sentences, buffer = SENTENCE_END.split(buffer)
                    if not silent and not self._cancel.is_set():
                        for s in sentences:
                            self.ui.say(s.strip())
                elif event.type == "content_block_stop" and buffer.strip():
                    if not silent and not self._cancel.is_set():
                        self.ui.say(buffer.strip())
                    buffer = ""
            response = stream.get_final_message()
        if buffer.strip() and not silent and not self._cancel.is_set():
            self.ui.say(buffer.strip())
        return response

    def _append_user(self, blocks: list[dict]) -> None:
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"].extend(blocks)
        else:
            self.messages.append({"role": "user", "content": blocks})

    # ------------------------------------------------------------------ outils
    def _execute(self, block, truncated: bool) -> dict:
        if truncated:
            problem = "entrée tronquée"
        elif block.name not in _SCHEMAS:
            problem = f"outil inconnu {block.name}"
        else:
            problem = validate(_SCHEMAS[block.name], block.input)
        if not problem:
            try:
                return {"type": "tool_result", "tool_use_id": block.id, "content": self._run(block.name, block.input)}
            except Exception as exc:  # noqa: BLE001
                problem = str(exc)
        return {"type": "tool_result", "tool_use_id": block.id, "content": f"Erreur : {problem}", "is_error": True}

    def _run(self, name: str, a: dict) -> str:
        if name in ("set_current_homework", "update_homework") and a["homework_id"] not in self.homework_ids:
            raise ValueError("identifiant de devoir inconnu")
        if name == "set_current_homework":
            self.ui.event("current", id=a["homework_id"])
            return "Affiché."
        if name == "update_homework":
            h = self.store.set_status(a["homework_id"], a["status"], a["comment"])
            self.ui.event("homework", item=h)
            return "Enregistré."
        if name == "log_difficulty":
            self.store.log_difficulty(self.child.id, a["subject"], a["topic"], a["detail"])
            return "Noté."
        if name == "show_on_screen":
            self.ui.event("screen", title=a["title"], content=a["content"])
            return "Affiché à l'écran."
        if name == "start_break":
            self.ui.event("break", minutes=max(1, min(a["minutes"], 15)))
            return "Pause lancée. Tu seras prévenu quand l'enfant revient."
        if name == "end_session":
            self._finish(a["summary"], a["difficulties"], a["to_review"], a["finished"])
            return "Rapport envoyé aux parents."
        raise ValueError(f"outil inconnu {name}")

    def _finish(self, summary: str, difficulties: list[str], to_review: list[str], finished: bool) -> None:
        items = [h for h in self.store.homework.all() if h["id"] in self.homework_ids]
        tonight_ids = {h["id"] for h in self.store.tonight(self.child.id, self.today)} | \
            {h["id"] for h in items if h["status"] == DONE}
        relevant = [h for h in items if h["id"] in tonight_ids or h["status"] != TODO]
        self.report = build_report(self.child, self.minutes(), relevant, summary, difficulties, to_review, finished)
        self.ended = True
        queued = send_report(self.cfg, self.store, self.child, self.report)
        self.ui.event("ended", report=self.report, parents_notified=queued)
