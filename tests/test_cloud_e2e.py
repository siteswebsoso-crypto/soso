"""Test de bout en bout : le code du Mac (Python) contre l'API de l'espace parents (Node, comme sur Netlify)."""

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from junior.cloud import Cloud, CloudError
from junior.config import Config
from junior.data import DONE, Store

PARENTS = Path(__file__).resolve().parent.parent / "parents"
pytestmark = pytest.mark.skipif(not shutil.which("node") or not (PARENTS / "node_modules").exists(),
                                reason="Node et les dépendances de parents/ sont nécessaires (npm install)")


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, PARENT_PASSWORD="mot-de-passe", PORT=str(port), NO_BACKGROUND="1")
    proc = subprocess.Popen(["node", "tests/dev-server.mjs"], cwd=PARENTS, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    yield base
    proc.terminate()


def parent(base, method, path, body=None, token=None, raw_body=None, content_type="application/json"):
    headers = {"content-type": content_type}
    if token:
        headers["authorization"] = f"Bearer {token}"
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"{base}/api/{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


@pytest.fixture
def mac(server, tmp_path, monkeypatch):
    monkeypatch.setenv("JUNIOR_HOME", str(tmp_path))
    monkeypatch.delenv("JUNIOR_CLOUD_TOKEN", raising=False)
    monkeypatch.setattr("junior.config.platform.system", lambda: "Linux")  # secrets en fichier, pas le Trousseau
    cfg = Config(cloud_url=server)
    cfg.children[0].avatar = "🐯"
    store = Store(tmp_path)
    return NS(cfg=cfg, store=store, cloud=Cloud(cfg, store))


def test_full_round_trip(server, mac):
    with pytest.raises(CloudError, match="401"):
        mac.cloud.login("faux")
    mac.cloud.login("mot-de-passe")
    assert mac.cloud.configured

    papa = parent(server, "POST", "login", {"name": "Papa", "password": "mot-de-passe"})["token"]
    maths = parent(server, "POST", "homework", {"child": "amine", "subject": "Maths", "task": "ex 3 p 52",
                                                "due": "2026-10-13", "minutes": 20}, papa)
    poesie = parent(server, "POST", "homework", {"child": "amine", "subject": "Français", "task": "poésie"}, papa)
    parent(server, "POST", "notes", {"child": "amine", "text": "Insiste sur les tables de 7"}, papa)

    # 1. Le Mac récupère les devoirs et consignes des parents
    stats = mac.cloud.sync()
    assert stats["new"] == 2
    local = {h["id"]: h for h in mac.store.homework.all()}
    assert local[maths["id"]]["task"] == "ex 3 p 52" and local[maths["id"]]["by"] == "Papa"
    assert mac.store.active_notes("amine")[0]["text"] == "Insiste sur les tables de 7"

    # 2. Séance sur le Mac : devoir fait, rapport, difficulté, ajout et suppression locaux
    mac.store.set_status(maths["id"], DONE, "réussi")
    mac.store.reports.add({"child": "amine", "date": "2026-10-12T18:40:00", "text": "✅ Amine a terminé.", "synced": False})
    mac.store.log_difficulty("amine", "Maths", "fractions", "confond 0,25 et 2,5")
    extra = mac.store.add_homework("ibrahim", "Anglais", "vocabulaire", None, 10)
    mac.store.delete_homework(poesie["id"])
    mac.cloud.sync()

    st = parent(server, "GET", "state", token=papa)
    hw = {h["id"]: h for h in st["homework"]}
    assert hw[maths["id"]]["status"] == "fait" and hw[maths["id"]]["comment"] == "réussi"
    assert extra["id"] in hw and poesie["id"] not in hw
    assert st["reports"][0]["text"] == "✅ Amine a terminé."
    assert st["difficulties"][0]["topic"] == "fractions"
    assert st["children"][0]["avatar"] == "🐯" and st["mac_seen"]
    assert all(not h.get("dirty") and not h.get("local_new") for h in mac.store.homework.all())
    assert all(r["synced"] for r in mac.store.reports.all())
    assert mac.store.deleted.all() == []

    # 3. Un nouvel envoi ne duplique rien
    mac.cloud.sync()
    assert len(parent(server, "GET", "state", token=papa)["reports"]) == 1

    # 4. Les parents corrigent : le Mac suit
    parent(server, "PATCH", f"homework/{extra['id']}", {"due": "2026-10-16", "status": "partiel"}, papa)
    mac.cloud.sync()
    h = next(x for x in mac.store.homework.all() if x["id"] == extra["id"])
    assert h["due"] == "2026-10-16" and h["status"] == "partiel"


def test_mac_reads_photos_when_server_cannot(server, mac, monkeypatch):
    mac.cloud.login("mot-de-passe")
    papa = parent(server, "POST", "login", {"name": "Maman", "password": "mot-de-passe"})["token"]
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"d.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + b"\xff\xd8photo" + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"child\"\r\n\r\nibrahim\r\n--{boundary}--\r\n").encode()
    job = parent(server, "POST", "photos", raw_body=body, token=papa, content_type=f"multipart/form-data; boundary={boundary}")
    assert parent(server, "GET", f"jobs/{job['id']}", token=papa)["status"] == "pending"

    calls = []

    def create(**kw):
        calls.append(kw)
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps({
            "child": "amine", "confidence": "probable", "remarks": "",
            "items": [{"subject": "Histoire", "task": "leçon 2", "due": "", "minutes": 10, "kind": "leçon"}]}))])

    monkeypatch.setattr("junior.cloud.JOB_FALLBACK_AFTER", 0)
    assert mac.cloud.process_pending_jobs(NS(beta=NS(messages=NS(create=create)))) == 1
    assert calls[0]["messages"][0]["content"][0]["type"] == "image"
    assert "enfant : ibrahim" in calls[0]["messages"][0]["content"][-1]["text"]
    done = parent(server, "GET", f"jobs/{job['id']}", token=papa)
    assert done["status"] == "done" and done["child"] == "ibrahim"  # le choix du parent prime
    st = parent(server, "GET", "state", token=papa)
    assert any(h["task"] == "leçon 2" and h["child"] == "ibrahim" for h in st["homework"])
