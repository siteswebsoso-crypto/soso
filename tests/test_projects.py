import json
import sys
import textwrap
import time
from types import SimpleNamespace as NS

import pytest

from jarvis.channels import Channel, parse_confirmation
from jarvis.config import Config
from jarvis.playbooks import PlaybookLibrary
from jarvis.projects import BRIEF_FILE, BuiltinWorker, ProjectManager, _validate


@pytest.fixture
def env(tmp_path):
    cfg = Config(projects_dir=str(tmp_path / "projets"), worker_engine="builtin")
    said = []
    channel = Channel(said.append)
    lib = PlaybookLibrary(tmp_path / "playbooks")
    pm = ProjectManager(cfg, tmp_path, lib, channel)
    return NS(cfg=cfg, said=said, channel=channel, lib=lib, pm=pm, tmp=tmp_path)


def wait_done(pm, project, timeout=10):
    end = time.time() + timeout
    while project.data["id"] in pm.running and time.time() < end:
        time.sleep(0.05)
    assert project.data["id"] not in pm.running


@pytest.mark.parametrize("answer,expected", [
    ("oui", (True, "")),
    ("Oui vas-y", (True, "")),
    ("oui mais ajoute une page blog", (True, "oui mais ajoute une page blog")),
    ("non", (False, "non")),
    ("non, mets plutôt du bleu", (False, "non, mets plutôt du bleu")),
    ("ouvre google", (False, "ouvre google")),
    (None, (False, "")),
])
def test_parse_confirmation(answer, expected):
    assert parse_confirmation(answer) == expected


def test_playbooks_seeded_and_fuzzy(env):
    assert "site-vitrine-seo" in env.lib.names()
    assert "SEO" in env.lib.read("recette site SEO")  # nom dicté approximatif
    env.lib.save("Post LinkedIn", "# Post LinkedIn\nTon pro.")
    env.lib.save("post linkedin", "Toujours 3 hashtags.", append=True)
    assert env.lib.read("linkedin").endswith("Toujours 3 hashtags.\n")
    with pytest.raises(FileNotFoundError):
        env.lib.read("inexistant")


def test_channel_ask_is_answered_by_next_input(env):
    import threading
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", env.channel.ask("Quelle couleur ?", timeout=5)))
    t.start()
    while env.channel.pending is None:
        time.sleep(0.01)
    assert env.channel.deliver("bleu marine")
    t.join()
    assert out["a"] == "bleu marine" and env.said == ["Quelle couleur ?"]
    assert env.channel.deliver("rien en attente") is False


def test_validate_tool_input():
    assert _validate("write_file", {"path": "a", "content": "b"}) is None
    assert "manquant" in _validate("write_file", {"path": "a"})
    assert "type" in _validate("run_shell", {"command": 3})


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def test_builtin_worker_builds_project(env, monkeypatch):
    responses = [
        NS(stop_reason="tool_use", content=[
            NS(type="text", text="Je crée la page."),
            NS(type="tool_use", id="1", name="write_file", input={"path": "site/index.html", "content": "<h1>Dupont</h1>"}),
            NS(type="tool_use", id="2", name="write_file", input={"path": "../evasion.txt", "content": "x"}),
            NS(type="tool_use", id="3", name="ask_user", input={"question": "Je mets en ligne ?"}),
        ]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="Site prêt dans site/.")]),
    ]
    calls = []

    def stream(**kw):
        calls.append(kw)
        return FakeStream(responses.pop(0))

    monkeypatch.setattr("jarvis.projects.anthropic.Anthropic", lambda: NS(beta=NS(messages=NS(stream=stream))))
    # Répond à la question du projet dès qu'elle arrive
    import threading
    def answer():
        while env.channel.pending is None:
            time.sleep(0.01)
        env.channel.deliver("non, attends ma validation demain")
    threading.Thread(target=answer, daemon=True).start()

    project = env.pm.start("Site Boulangerie Dupont", "Boulangerie à Lyon 3", ["site SEO"])
    wait_done(env.pm, project)

    ws = project.workspace
    assert (ws / "site" / "index.html").read_text() == "<h1>Dupont</h1>"
    assert not (ws.parent / "evasion.txt").exists()
    brief = (ws / BRIEF_FILE).read_text()
    assert "Boulangerie à Lyon 3" in brief and "Recette : site SEO" in brief and "LocalBusiness" in brief
    results = calls[1]["messages"][2]["content"]
    assert results[1]["is_error"] and "hors du dossier" in results[1]["content"]
    assert "attends ma validation" in results[2]["content"]
    assert project.data["status"] == "terminé"
    assert any("est terminé" in s and "Site prêt" in s for s in env.said)
    assert env.pm.find("boulangerie dupont").data["id"] == project.data["id"]


def test_claude_code_worker_parses_stream(env, monkeypatch, tmp_path):
    fake = tmp_path / "claude"
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Je lis le brief."},
                                                       {"type": "tool_use", "name": "Write", "input": {"file_path": "index.html"}}]}},
        {"type": "result", "result": "Site généré.", "is_error": False},
    ]
    fake.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, sys, pathlib
        pathlib.Path("args.json").write_text(json.dumps(sys.argv[1:]))
        for e in {events!r}:
            print(json.dumps(e), flush=True)
    """))
    fake.chmod(0o755)
    monkeypatch.setattr("jarvis.projects.shutil.which", lambda name: str(fake))

    project = env.pm.start("Site Test", "Un test", [], engine="claude-code")
    wait_done(env.pm, project)
    assert project.data["summary"] == "Site généré."
    args = json.loads((project.workspace / "args.json").read_text())
    assert args[0] == "-p" and "--allowedTools" in args and "stream-json" in args
    assert any("Write" in e["msg"] for e in project.data["log"])
