"""Service d'arrière-plan : reçoit les photos de devoirs et les messages des parents sur Telegram.

Lancé automatiquement à l'ouverture de session (LaunchAgent), il fonctionne même quand
l'application des enfants est fermée.
"""

from __future__ import annotations

import time
import urllib.error
from datetime import datetime

from .config import Config, app_dir, get_secret
from .data import Store, human_date
from .homework import _date_or_none, extract_homework, save_extraction
from .llm import client as make_client
from .parent_agent import ParentAgent
from .telegram_api import Telegram, image_file_id

HELP = ("Envoyez-moi une photo des devoirs (cahier de textes, Pronote…), avec le prénom en légende si "
        "vous voulez. Vous pouvez aussi m'écrire : « qu'a fait Amine ce soir ? », « insiste sur les "
        "tables de 7 », « enlève la poésie »…")


def de(name: str) -> str:
    """« de Ibrahim » → « d'Ibrahim »."""
    return f"d'{name}" if name[:1].lower() in "aeiouyhéèêâîôû" else f"de {name}"


class Daemon:
    def __init__(self, cfg: Config, store: Store, tg: Telegram, client):
        self.cfg, self.store, self.tg, self.client = cfg, store, tg, client
        self.agent = ParentAgent(cfg, store, client)
        self.offset = 0
        self.context: dict[int, str] = {}  # dernière extraction, pour les corrections du parent

    def author(self, user: dict) -> str:
        return self.cfg.parent_names.get(str(user.get("id"))) or user.get("first_name") or "un parent"

    def run(self) -> None:
        print("Jarvis Junior : service Telegram démarré.")
        while True:
            try:
                updates = self.tg.updates(self.offset)
            except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
                print(f"[telegram] {exc} — nouvel essai dans 10 s")
                time.sleep(10)
                continue
            self.process(updates)

    def process(self, updates: list[dict]) -> None:
        albums: dict[str, list[dict]] = {}
        for upd in updates:
            self.offset = max(self.offset, upd["update_id"] + 1)
            msg = upd.get("message")
            if not msg:
                continue
            user = msg.get("from") or {}
            if user.get("id") not in self.cfg.parent_ids:
                self.tg.send(msg["chat"]["id"], f"Accès réservé aux parents. Votre identifiant : {user.get('id')}")
                continue
            if image_file_id(msg):
                key = msg.get("media_group_id") or f"single-{msg['message_id']}"
                albums.setdefault(key, []).append(msg)
            elif msg.get("text"):
                self.on_text(msg)
        for key, msgs in albums.items():
            if not key.startswith("single-"):
                msgs += self._rest_of_album(key)
            self.on_photos(msgs)

    def _rest_of_album(self, group_id: str) -> list[dict]:
        """Les photos d'un même envoi peuvent arriver en plusieurs fois : on attend la suite."""
        extra = []
        try:
            for upd in self.tg.updates(self.offset, timeout=2):
                msg = upd.get("message") or {}
                if msg.get("media_group_id") == group_id:
                    self.offset = max(self.offset, upd["update_id"] + 1)
                    extra.append(msg)
        except Exception:  # noqa: BLE001
            pass
        return extra

    def on_photos(self, msgs: list[dict]) -> None:
        chat_id = msgs[0]["chat"]["id"]
        author = self.author(msgs[0].get("from") or {})
        caption = " ".join(m.get("caption", "") for m in msgs).strip()
        self.tg.typing(chat_id)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        paths = [str(self.tg.download(image_file_id(m), self.store.root / "photos" / f"{stamp}-{i}"))
                 for i, m in enumerate(msgs)]
        try:
            result = extract_homework(self.client, self.cfg, paths, caption)
        except Exception as exc:  # noqa: BLE001
            self.tg.send(chat_id, f"Je n'ai pas réussi à lire cette image ({exc}). Pouvez-vous réessayer ?")
            return
        child = self.cfg.child(result["child"])
        items = save_extraction(self.store, self.cfg, result, paths[0]) if child else [
            self.store.add_homework("inconnu", i["subject"], i["task"], _date_or_none(i["due"]), i["minutes"], i["kind"],
                                    paths[0]) for i in result["items"]]
        if not items:
            self.tg.send(chat_id, "Je ne vois pas de devoirs sur cette image. " +
                         (result["remarks"] or "Pouvez-vous en envoyer une plus nette ?"))
            return
        listing = "\n".join(f"• {h['subject']} — {h['task']} ({human_date(h['due'])}, ~{h['minutes']} min)"
                            for h in items)
        total = sum(h["minutes"] for h in items)
        if child:
            guess = "" if result["confidence"] == "sûr" or caption else " (j'ai deviné d'après le niveau)"
            text = f"📚 Devoirs enregistrés pour {child.name}{guess} :\n{listing}\n\nTotal estimé : ~{total} min."
        else:
            names = " ou ".join(c.name for c in self.cfg.children)
            text = f"📚 J'ai trouvé ces devoirs :\n{listing}\n\nC'est pour {names} ?"
        if result["remarks"]:
            text += f"\n\nℹ️ {result['remarks']}"
        text += "\n\nRépondez pour corriger si besoin (« c'est pour jeudi », « enlève la poésie »…)."
        self.tg.send(chat_id, text)
        self.context[chat_id] = "je viens d'enregistrer depuis une photo : " + "; ".join(
            f"[{h['id']}] {h['child']} — {h['subject']} : {h['task']} ({h['due'] or 'sans date'})" for h in items)
        for other in self.cfg.parent_ids:  # l'autre parent est tenu au courant
            if other != chat_id:
                who = de(child.name) if child else "d'un des enfants"
                self.tg.send(other, f"ℹ️ {author} a envoyé les devoirs {who} :\n{listing}")

    def on_text(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        text = msg["text"].strip()
        if text in ("/start", "/aide", "/help"):
            self.tg.send(chat_id, f"Bonjour ! Je suis Jarvis Junior. {HELP}")
            return
        self.tg.typing(chat_id)
        try:
            reply = self.agent.handle(chat_id, self.author(msg.get("from") or {}), text,
                                      self.context.pop(chat_id, ""))
        except Exception as exc:  # noqa: BLE001
            reply = f"Désolé, une erreur est survenue : {exc}"
        self.tg.send(chat_id, reply)


def main() -> None:
    cfg = Config.load()
    token = get_secret("telegram")
    if not token:
        print("Pas de token Telegram configuré : lancez « python -m junior setup ».")
        return
    Daemon(cfg, Store(app_dir()), Telegram(token), make_client()).run()
