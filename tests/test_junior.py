import json
import threading
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from junior.app import Api, Controller
from junior.config import Config
from junior.daemon import Daemon
from junior.data import DONE, PARTIAL, Store, human_date, next_school_day
from junior.homework import save_extraction
from junior.parent_agent import ParentAgent
from junior.report import build_report
from junior.tutor import TutorSession

THURSDAY = date(2026, 10, 8)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNIOR_HOME", str(tmp_path))
    monkeypatch.delenv("JUNIOR_TELEGRAM_TOKEN", raising=False)
    cfg = Config(parent_ids=[111, 222], parent_names={"111": "Papa", "222": "Maman"})
    cfg.children[0].set_pin("1234")
    store = Store(tmp_path)
    return NS(cfg=cfg, store=store, tmp=tmp_path)


# ------------------------------------------------------------------ fausses API

def text_delta(t):
    return NS(type="content_block_delta", delta=NS(type="text_delta", text=t))


class FakeStream:
    def __init__(self, response, chunks):
        self.response, self.chunks = response, chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for c in self.chunks:
            yield text_delta(c)
        yield NS(type="content_block_stop")

    def get_final_message(self):
        return self.response


def turn(text="", tools=(), stop=None):
    content = ([NS(type="text", text=text)] if text else []) + [
        NS(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(tools)]
    return NS(stop_reason=stop or ("tool_use" if tools else "end_turn"), content=content)


class FakeClient:
    """Rejoue une liste de réponses ; le texte est découpé en morceaux pour simuler le streaming."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream, create=self._create))

    def _stream(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        text = "".join(b.text for b in r.content if b.type == "text")
        return FakeStream(r, [text[i:i + 7] for i in range(0, len(text), 7)])

    def _create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


class FakeUI:
    def __init__(self):
        self.said, self.events = [], []

    def say(self, s):
        self.said.append(s)

    def event(self, kind, **data):
        self.events.append((kind, data))


# ------------------------------------------------------------------ données

def test_dates_and_tonight(env):
    assert next_school_day(date(2026, 10, 9)) == date(2026, 10, 12)  # vendredi → lundi
    assert human_date("2026-10-09", THURSDAY) == "pour demain"
    assert human_date("2026-10-13", THURSDAY) == "pour mardi"
    s = env.store
    a = s.add_homework("amine", "Maths", "ex 3 p 52", "2026-10-09", 20)
    b = s.add_homework("amine", "Histoire", "leçon", "2026-10-14", 10)
    s.add_homework("ibrahim", "Anglais", "vocabulaire", "2026-10-09", 15)
    assert [h["id"] for h in s.tonight("amine", THURSDAY)] == [a["id"]]
    assert [h["id"] for h in s.pending("amine")] == [a["id"], b["id"]]


def test_pins(env):
    amine = env.cfg.children[0]
    assert amine.check_pin("1234") and not amine.check_pin("0000")
    assert env.cfg.children[1].check_pin("")  # pas de code défini
    assert not env.cfg.check_parent_pin("1234")
    env.cfg.set_parent_pin("9876")
    assert env.cfg.check_parent_pin("9876")
    env.cfg.save()
    assert Config.load().children[0].check_pin("1234")


def test_save_extraction_and_unknown_dates(env):
    result = {"child": "Ibrahim", "confidence": "probable", "remarks": "", "items": [
        {"subject": "Maths", "task": "ex 12 p 80", "due": "2026-10-09", "minutes": 25, "kind": "exercice"},
        {"subject": "SVT", "task": "apprendre la leçon", "due": "", "minutes": 15, "kind": "leçon"},
    ]}
    items = save_extraction(env.store, env.cfg, result, "photo.jpg")
    assert [h["child"] for h in items] == ["ibrahim", "ibrahim"]
    assert items[1]["due"] is None


# ------------------------------------------------------------------ séance

def test_tutor_full_session(env, monkeypatch):
    sent = []
    monkeypatch.setattr("junior.report.get_secret", lambda name: "TOKEN")
    monkeypatch.setattr("junior.report.Telegram", lambda token: NS(send=lambda chat, text: sent.append((chat, text))))
    s = env.store
    maths = s.add_homework("amine", "Mathématiques", "ex 3 et 4 p 52", "2026-10-09", 20)
    poesie = s.add_homework("amine", "Français", "poésie strophe 1", "2026-10-09", 15)
    s.add_note("amine", "Insiste sur les tables de 7", "Maman")
    s.log_difficulty("amine", "Maths", "fractions", "confond numérateur et dénominateur")

    client = FakeClient([
        turn("Bonjour Amine ! J'espère que ta journée était chouette. Ce soir on en a pour 35 minutes. Tu es prêt ?"),
        turn("Super, on commence par les maths.", [("set_current_homework", {"homework_id": maths["id"]}),
                                                   ("show_on_screen", {"title": "Calcul", "content": "3/4 = ?"})]),
        turn("Lis-moi la consigne."),
        turn("Bravo !", [("update_homework", {"homework_id": maths["id"], "status": DONE, "comment": "réussi"}),
                         ("log_difficulty", {"subject": "Maths", "topic": "fractions", "detail": "hésite encore"}),
                         ("update_homework", {"homework_id": poesie["id"], "status": PARTIAL, "comment": "1 vers sur 4"})]),
        turn("Merci Amine, à demain !", [("end_session", {"summary": "Bonne séance.", "difficulties": ["fractions"],
                                                          "to_review": ["revoir la poésie"], "finished": False})]),
    ])
    ui = FakeUI()
    session = TutorSession(env.cfg, s, env.cfg.children[0], client, ui, today=THURSDAY)

    # Le prompt contient le niveau, les devoirs, la consigne des parents et l'historique
    for expected in ("CM2 (cycle 3", "ex 3 et 4 p 52", "tables de 7", "fractions : 1 fois", "35 minutes"):
        assert expected in session.system

    session.start()
    assert ui.said[0] == "Bonjour Amine !"  # lu phrase par phrase, dès la première
    assert ui.said[-1] == "Tu es prêt ?"
    session.reply("oui")
    assert ("current", {"id": maths["id"]}) in ui.events
    assert ("screen", {"title": "Calcul", "content": "3/4 = ?"}) in ui.events
    session.reply("j'ai fini")
    session.reply("c'est fini pour ce soir")

    assert session.ended
    assert ui.events[-1][0] == "ended" and ui.events[-1][1]["parents_notified"] == 2
    assert [c for c, _ in sent] == [111, 222]
    report = sent[0][1]
    assert "Rapport de devoirs — Amine" in report
    assert "✔︎ Mathématiques" in report and "◐ Français" in report
    assert "fractions" in report and "revoir la poésie" in report
    assert s.reports.all()[0]["child"] == "amine"
    assert len([d for d in s.difficulties.all() if d["topic"] == "fractions"]) == 2

    # Les requêtes restent en ajout seul et respectent l'alternance des rôles
    roles = [m["role"] for m in client.calls[-1]["messages"]]
    assert all(a != b for a, b in zip(roles, roles[1:]))
    assert client.calls[0]["output_config"] == {"effort": "low"}
    assert client.calls[0]["fallbacks"] == "default"
    assert all(t.get("eager_input_streaming") for t in client.calls[0]["tools"])


def test_tutor_rejects_bad_tool_input_and_unknown_homework(env):
    client = FakeClient([
        turn("", [("update_homework", {"homework_id": "zzz", "status": DONE, "comment": "x"}),
                  ("start_break", {"minutes": "cinq"})]),
        turn("On continue."),
    ])
    session = TutorSession(env.cfg, env.store, env.cfg.children[0], client, FakeUI(), today=THURSDAY)
    session.reply("salut")
    results = session.messages[2]["content"]
    assert all(r.get("is_error") for r in results)
    assert "inconnu" in results[0]["content"] and "integer" in results[1]["content"]


def test_tutor_abort_sends_report_silently(env):
    h = env.store.add_homework("amine", "Maths", "ex 1", "2026-10-09", 10)
    client = FakeClient([
        turn("Bonjour !"),
        turn("Je ne devrais pas parler.", [("end_session", {"summary": "Arrêt en cours de route.", "difficulties": [],
                                                           "to_review": [], "finished": False})]),
    ])
    ui = FakeUI()
    session = TutorSession(env.cfg, env.store, env.cfg.children[0], client, ui, today=THURSDAY)
    session.start()
    session.abort()
    assert "Je ne devrais pas parler." not in ui.said
    assert session.ended and "arrêté la séance" in session.report and "✗ Maths" in session.report
    assert h["id"]


def test_report_wording():
    child = Config().children[1]
    hw = [{"subject": "Maths", "task": "ex 1", "status": DONE, "comment": ""}]
    assert build_report(child, 30, hw, "", [], [], True).startswith("✅ Ibrahim a terminé ses devoirs (30 min).")


# ------------------------------------------------------------------ contrôleur (boucle vocale)

class FakeSpeaker:
    def __init__(self):
        self.said = []

    def say(self, s):
        self.said.append(s)

    def stop(self):
        pass

    def wait(self, timeout=None):
        return True


class FakeRecorder:
    def __init__(self, clips):
        self.clips = list(clips)

    def record(self):
        return self.clips.pop(0) if self.clips else None

    def stop(self):
        pass


class FakeTranscriber:
    def warm_up(self):
        pass

    def transcribe(self, audio, hint=""):
        return audio  # dans ce test, l'« audio » est déjà du texte


def test_controller_hands_free_loop(env):
    env.store.add_homework("amine", "Maths", "ex 1", "2026-10-09", 10)
    client = FakeClient([turn("Bonjour Amine. Tu es prêt ?"), turn("Génial, on y va.")])
    events = []
    ctl = Controller(env.cfg, env.store, lambda kind, **d: events.append((kind, d)), client=client,
                     speaker=FakeSpeaker(), recorder=FakeRecorder(["oui je suis prêt"]),
                     transcriber=FakeTranscriber())
    ctl.start("amine")
    deadline = time.time() + 5
    while ("state", {"state": "idle"}) not in events[3:] and time.time() < deadline:
        time.sleep(0.02)
    states = [d["state"] for k, d in events if k == "state"]
    # accueil → écoute automatique → réflexion → réponse → écoute → silence → attente
    assert states[:6] == ["thinking", "speaking", "listening", "thinking", "speaking", "listening"]
    assert states[-1] == "idle"
    assert ("heard", {"text": "oui je suis prêt"}) in events
    assert ctl.speaker.said == ["Bonjour Amine.", "Tu es prêt ?", "Génial, on y va."]


def test_api_login_and_parent_space(env):
    api = Api.__new__(Api)
    api.cfg, api.store, api.window, api.parent_ok = env.cfg, env.store, None, False
    api.controller = NS(start=lambda cid: None)
    env.store.add_homework("amine", "Maths", "ex 1", None, 10)
    assert api.profiles()[0]["has_pin"] is True
    assert api.login("amine", "0000") == {"ok": False}
    assert api.login("amine", "1234")["ok"]
    assert api.parent_data() == {}
    env.cfg.set_parent_pin("4321")
    assert not api.parent_login("1111") and api.parent_login("4321")
    assert api.parent_add("ibrahim", "SVT", "leçon", "", 10)
    assert len(api.parent_data()["homework"]) == 2


# ------------------------------------------------------------------ Telegram (parents)

class FakeTelegram:
    def __init__(self, tmp):
        self.sent, self.tmp = [], tmp

    def send(self, chat, text):
        self.sent.append((chat, text))

    def typing(self, chat):
        pass

    def updates(self, offset, timeout=30):
        return []

    def download(self, file_id, dest):
        p = Path(str(dest) + ".jpg")
        p.write_bytes(b"\xff\xd8fake")
        return p


def test_daemon_photo_to_homework(env, monkeypatch):
    extraction = {"child": "inconnu", "confidence": "incertain", "remarks": "", "items": [
        {"subject": "Maths", "task": "ex 5 p 20", "due": "2026-10-09", "minutes": 20, "kind": "exercice"}]}
    monkeypatch.setattr("junior.daemon.extract_homework", lambda client, cfg, paths, caption: dict(
        extraction, child="amine" if "amine" in caption.lower() else "inconnu"))
    tg = FakeTelegram(env.tmp)
    d = Daemon(env.cfg, env.store, tg, client=None)
    photo = lambda uid, caption="": {"update_id": 1, "message": {
        "message_id": 9, "chat": {"id": uid}, "from": {"id": uid, "first_name": "X"},
        "photo": [{"file_id": "small"}, {"file_id": "big"}], "caption": caption}}

    d.process([photo(111, "Amine")])
    assert env.store.pending("amine")[0]["task"] == "ex 5 p 20"
    to_sender = [t for c, t in tg.sent if c == 111][0]
    assert "pour Amine" in to_sender and "~20 min" in to_sender
    assert any(c == 222 and "Papa a envoyé les devoirs d'Amine" in t for c, t in tg.sent)  # l'autre parent

    tg.sent.clear()
    d.process([photo(111)])  # sans légende et enfant introuvable : on demande
    assert "C'est pour Amine ou Ibrahim ?" in tg.sent[0][1]
    assert env.store.pending("inconnu")

    tg.sent.clear()
    d.process([{"update_id": 3, "message": {"message_id": 1, "chat": {"id": 999}, "from": {"id": 999},
                                             "text": "coucou"}}])
    assert "réservé aux parents" in tg.sent[0][1]


def test_parent_agent_corrects_homework(env):
    h = env.store.add_homework("inconnu", "Maths", "ex 5", None, 20)
    client = FakeClient([
        turn("", [("update_homework", {"id": h["id"], "child": "ibrahim", "due": "2026-10-13"}),
                  ("add_note", {"child": "ibrahim", "text": "contrôle d'histoire jeudi"})]),
        turn("C'est corrigé : le devoir est pour Ibrahim, pour mardi."),
    ])
    agent = ParentAgent(env.cfg, env.store, client)
    reply = agent.handle(111, "Papa", "c'est pour Ibrahim, pour mardi. Et il a un contrôle d'histoire jeudi",
                         context="je viens d'enregistrer depuis une photo : ...")
    assert reply.startswith("C'est corrigé")
    item = env.store.pending("ibrahim")[0]
    assert item["due"] == "2026-10-13"
    assert env.store.active_notes("ibrahim")[0]["author"] == "Papa"
    first_user = client.calls[0]["messages"][0]["content"][0]["text"]
    assert "message de Papa" in first_user and "Contexte" in first_user
