from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from jarvis.brain import Jarvis
from jarvis.config import Config
from jarvis.scheduler import ReminderScheduler
from jarvis.store import Store
from jarvis.tools import Toolbox
from jarvis.voice import strip_wake_word


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    return Store(tmp_path)


def test_file_tools(store, tmp_path):
    tb = Toolbox(store)
    target = tmp_path / "notes" / "todo.txt"
    tb.run("write_file", {"path": str(target), "content": "acheter du lait\n"})
    tb.run("write_file", {"path": str(target), "content": "appeler maman\n", "append": True})
    assert tb.run("read_file", {"path": str(target)}) == "acheter du lait\nappeler maman\n"
    assert str(target) in tb.run("find_files", {"root": str(tmp_path), "pattern": "*.TXT"})
    assert "[dossier] notes/" in tb.run("list_dir", {"path": str(tmp_path)})


def test_shell(store):
    out = Toolbox(store).run("run_shell", {"command": "echo bonjour"})
    assert "code de sortie : 0" in out and "bonjour" in out


def test_memory_and_reminders(store):
    tb = Toolbox(store)
    tb.run("remember", {"fact": "Aime le café noir"})
    mem_id = store.memories.all()[0]["id"]
    assert "café noir" in tb.run("list_memories", {})
    tb.run("forget", {"id": mem_id})
    assert store.memories.all() == []

    soon = (datetime.now() + timedelta(hours=1)).isoformat(timespec="minutes")
    assert "programmé" in tb.run("add_reminder", {"when": soon, "message": "réunion"})
    assert "réunion" in tb.run("list_reminders", {})


def test_scheduler_fires_due_reminders_once(store):
    store.add_reminder(datetime.now() - timedelta(minutes=1), "boire de l'eau")
    store.add_reminder(datetime.now() + timedelta(days=1), "plus tard")
    fired = []
    sched = ReminderScheduler(store, fired.append)
    sched.tick()
    sched.tick()
    assert fired == ["boire de l'eau"]


def test_wake_word():
    assert strip_wake_word("Jarvis, ouvre Spotify", "jarvis") == "ouvre Spotify"
    assert strip_wake_word("hey jarvis quelle heure est-il", "jarvis") == "quelle heure est-il"
    assert strip_wake_word("jarvis", "jarvis") == ""
    assert strip_wake_word("ouvre Spotify", "jarvis") is None


# ---------------------------------------------------------------- boucle agentique simulée

def _resp(stop, *blocks):
    return NS(stop_reason=stop, content=list(blocks))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _jarvis(monkeypatch, store, responses, approve):
    monkeypatch.setattr("jarvis.brain.anthropic.Anthropic", lambda: FakeClient(responses))
    return Jarvis(Config(web_search=False), store, approve)


def test_agent_loop_runs_tools_and_asks_approval(store, monkeypatch):
    asked = []
    responses = [
        _resp("tool_use",
              NS(type="text", text="Je regarde."),
              NS(type="tool_use", id="t1", name="remember", input={"fact": "Habite à Lyon"}),
              NS(type="tool_use", id="t2", name="run_shell", input={"command": "echo hi"})),
        _resp("end_turn", NS(type="text", text="C'est noté, Monsieur.")),
    ]
    j = _jarvis(monkeypatch, store, responses, lambda d: asked.append(d) or False)

    assert j.ask("Je vis à Lyon, et lance echo hi") == "C'est noté, Monsieur."
    assert asked == ["Exécuter : echo hi"]
    assert store.memories.all()[0]["fact"] == "Habite à Lyon"

    # Les deux résultats d'outils repartent dans un seul message « user »
    results = j.messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert results[1]["is_error"] is True and "refusé" in results[1]["content"]
    # Paramètres envoyés à l'API
    call = j.client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["fallbacks"] == "default"


def test_agent_loop_handles_unknown_tool_and_refusal(store, monkeypatch):
    responses = [
        _resp("tool_use", NS(type="tool_use", id="x", name="nope", input={})),
        _resp("refusal"),
    ]
    j = _jarvis(monkeypatch, store, responses, lambda d: True)
    assert "pas pouvoir" in j.ask("fais un truc")
    assert j.messages[2]["content"][0]["is_error"] is True
