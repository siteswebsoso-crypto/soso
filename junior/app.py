"""L'application des enfants : fenêtre native (pywebview) + contrôleur de la conversation vocale."""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from .audio import Recorder, Speaker, Transcriber
from .cloud import Cloud
from .config import Config, app_dir
from .data import DONE, Store, human_date
from .llm import client as make_client
from .tutor import TutorSession

UI_DIR = Path(__file__).parent / "ui"


class Controller:
    """Orchestration d'une séance : écoute → transcription → instit → voix → écoute…

    États envoyés à l'interface : idle, listening, thinking, speaking, break, ended.
    """

    def __init__(self, cfg: Config, store: Store, emit, client=None, speaker=None, recorder=None,
                 transcriber=None):
        self.cfg, self.store, self.emit = cfg, store, emit
        self._client = client
        self.speaker = speaker or Speaker(cfg.voice, cfg.voice_rate, on_sentence=lambda s: emit("subtitle", text=s))
        self.recorder = recorder or Recorder(on_level=self._level)
        self.transcriber = transcriber or Transcriber(cfg.whisper_model)
        self.session: TutorSession | None = None
        self.state = "idle"
        self._actions: queue.Queue = queue.Queue()
        self._break_started = 0.0
        self._break_requested = False
        self._last_level = 0.0
        threading.Thread(target=self._worker, daemon=True, name="conversation").start()

    @property
    def client(self):
        if self._client is None:
            self._client = make_client()
        return self._client

    # ------------------------------------------------------------------ interface → contrôleur
    def start(self, child_id: str) -> None:
        child = self.cfg.child(child_id)
        self.transcriber.warm_up()
        self.session = TutorSession(self.cfg, self.store, child, self.client, self)
        self._actions.put(("start", None))

    def tap(self) -> None:
        """Le gros bouton : interrompt Jarvis, ou commence / termine l'écoute."""
        if self.state == "speaking":
            if self.session:
                self.session.mute_current_turn()
            self.speaker.stop()
            self._actions.put(("listen", None))
        elif self.state == "listening":
            self.recorder.stop()
        elif self.state == "idle" and self.session and not self.session.ended:
            self._actions.put(("listen", None))

    def send_text(self, text: str) -> None:
        """Saisie au clavier (secours si le micro ne marche pas)."""
        if text.strip():
            self._actions.put(("text", text.strip()))

    def end_break(self) -> None:
        if self.state == "break":
            self._actions.put(("resume", time.time() - self._break_started))

    def quit(self, wait: bool = False) -> None:
        """L'enfant quitte : arrêt de la voix et rapport aux parents.

        `wait=True` à la fermeture de la fenêtre, pour que le rapport parte avant la fin du programme.
        """
        self.speaker.stop()
        self.recorder.stop()
        session, self.session = self.session, None
        self._set("idle")
        if session and not session.ended:
            worker = threading.Thread(target=session.abort, daemon=True)
            worker.start()
            if wait:
                worker.join(timeout=30)

    # ------------------------------------------------------------------ instit → interface (UI)
    def say(self, sentence: str) -> None:
        self._set("speaking")
        self.speaker.say(sentence)

    def event(self, kind: str, **data) -> None:
        if kind == "break":
            self._break_started = time.time()
            self._break_requested = True
        self.emit(kind, **data)

    # ------------------------------------------------------------------ boucle
    def _set(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.emit("state", state=state)

    def _level(self, value: float) -> None:
        now = time.time()
        if now - self._last_level > 0.06:
            self._last_level = now
            self.emit("level", value=round(value, 2))

    def _worker(self) -> None:
        while True:
            action, arg = self._actions.get()
            session = self.session
            if session is None or session.ended:
                continue
            try:
                if action == "start":
                    self._run(session.start)
                elif action == "resume":
                    self._run(lambda: session.resume_after_break(arg))
                elif action == "text":
                    self.emit("heard", text=arg)
                    self._run(lambda: session.reply(arg))
                elif action == "listen":
                    self._listen(session)
            except Exception as exc:  # noqa: BLE001
                self.emit("error", message=str(exc))
                self._set("idle")

    def _run(self, turn) -> None:
        self._set("thinking")
        turn()
        self.speaker.wait()
        if self.session and self.session.ended:
            self._set("ended")
        elif self._break_requested:
            self._break_requested = False
            self._set("break")
        elif self._actions.empty():
            self._actions.put(("listen", None))  # conversation « mains libres »

    def _listen(self, session: TutorSession) -> None:
        self._set("listening")
        audio = self.recorder.record()
        if self.session is not session:
            return
        if audio is None:
            self._set("idle")  # l'enfant n'a rien dit : on attend qu'il touche le bouton
            return
        self._set("thinking")
        hint = f"{session.child.name}. Devoirs : " + ", ".join(
            h["subject"] for h in self.store.pending(session.child.id))
        text = self.transcriber.transcribe(audio, hint)
        if not text:
            self.emit("subtitle", text="Je n'ai pas bien entendu…")
            self._set("idle")
            return
        self.emit("heard", text=text)
        self._run(lambda: session.reply(text))


class Api:
    """Fonctions appelées depuis l'interface (JavaScript : window.pywebview.api.*)."""

    def __init__(self, cfg: Config, store: Store):
        self.cfg, self.store = cfg, store
        self.window = None
        self.controller = Controller(cfg, store, self._emit)
        self.parent_ok = False
        self.cloud = Cloud(cfg, store)
        self._last_sync = 0.0

    def refresh(self) -> dict:
        """Récupère les derniers devoirs envoyés par les parents (au plus une fois toutes les 20 s)."""
        if time.time() - self._last_sync > 20:
            self._last_sync = time.time()
            worker = threading.Thread(target=self.cloud.sync_quietly, daemon=True)
            worker.start()
            worker.join(timeout=4)  # on n'attend pas plus si le site est lent
        return {"online": self.cloud.configured}

    def _emit(self, kind: str, **data) -> None:
        if self.window:
            self.window.evaluate_js(f"window.junior && window.junior.on({json.dumps({'kind': kind, **data})})")

    # profils
    def profiles(self) -> list[dict]:
        out = []
        for c in self.cfg.children:
            tonight = self.store.tonight(c.id)
            out.append({"id": c.id, "name": c.name, "grade": c.grade, "avatar": c.avatar, "color": c.color,
                        "has_pin": bool(c.pin_hash), "count": len(tonight),
                        "minutes": sum(h["minutes"] for h in tonight)})
        return out

    def login(self, child_id: str, pin: str) -> dict:
        child = self.cfg.child(child_id)
        if not child or not child.check_pin(pin):
            return {"ok": False}
        homework = [self._hw(h) for h in self.store.pending(child.id)]
        self.controller.start(child.id)
        return {"ok": True, "homework": homework, "tonight": [h["id"] for h in self.store.tonight(child.id)]}

    def tap(self) -> None:
        self.controller.tap()

    def send_text(self, text: str) -> None:
        self.controller.send_text(text)

    def end_break(self) -> None:
        self.controller.end_break()

    def quit(self) -> None:
        self.controller.quit()

    # espace parents
    def parent_login(self, pin: str) -> bool:
        self.parent_ok = self.cfg.check_parent_pin(pin)
        return self.parent_ok

    def parent_data(self) -> dict:
        if not self.parent_ok:
            return {}
        names = {c.id: c.name for c in self.cfg.children}
        hw = [dict(self._hw(h), child_name=names.get(h["child"], h["child"]))
              for h in self.store.homework.all() if h["status"] != DONE]
        reports = [dict(r, child_name=names.get(r["child"], r["child"])) for r in self.store.reports.all()[-15:]]
        return {"homework": hw, "reports": list(reversed(reports)),
                "children": [{"id": c.id, "name": c.name} for c in self.cfg.children]}

    def parent_add(self, child_id: str, subject: str, task: str, due: str, minutes: int) -> bool:
        if not self.parent_ok:
            return False
        self.store.add_homework(child_id, subject, task, due or None, int(minutes or 15))
        return True

    def parent_delete(self, hw_id: str) -> bool:
        return self.parent_ok and self.store.delete_homework(hw_id)

    def parent_logout(self) -> None:
        self.parent_ok = False

    @staticmethod
    def _hw(h: dict) -> dict:
        return {"id": h["id"], "subject": h["subject"], "task": h["task"], "due": human_date(h["due"]),
                "minutes": h["minutes"], "status": h["status"], "kind": h["kind"]}


def main() -> None:
    import webview

    cfg = Config.load()
    api = Api(cfg, Store(app_dir()))
    window = webview.create_window("Jarvis Junior", str(UI_DIR / "index.html"), js_api=api,
                                   width=1280, height=820, min_size=(960, 640), background_color="#1b1442")
    api.window = window
    window.events.closing += lambda: api.controller.quit(wait=True)
    webview.start()
