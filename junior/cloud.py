"""Synchronisation avec l'espace parents (site Netlify).

Le Mac récupère les devoirs et consignes envoyés par les parents, et renvoie l'avancement des
devoirs, les rapports de séance et les difficultés repérées. Il sert aussi de secours pour lire
les photos de devoirs si le serveur n'a pas pu le faire.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import Config, get_secret, set_secret
from .data import Store, now_iso

INTERVAL = 30  # secondes entre deux synchronisations (service de fond)
JOB_FALLBACK_AFTER = 120  # au-delà, le Mac lit lui-même les photos en attente


class CloudError(RuntimeError):
    pass


class Cloud:
    def __init__(self, cfg: Config, store: Store, opener=None):
        self.cfg = cfg
        self.store = store
        self.base = cfg.cloud_url.rstrip("/")
        self._open = opener or urllib.request.urlopen
        self._sync_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.base and get_secret("cloud"))

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, body=None, token: str | None = None, raw: bool = False):
        headers = {"content-type": "application/json", "user-agent": "JarvisJunior-Mac/1.0"}
        token = token or get_secret("cloud")
        if token:
            headers["authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}/api/{path}", data=data, method=method, headers=headers)
        try:
            with self._open(req, timeout=60) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read()).get("error", "")
            except Exception:  # noqa: BLE001
                message = ""
            raise CloudError(f"{exc.code} {message}".strip()) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudError(f"espace parents injoignable : {exc}") from exc
        return payload if raw else json.loads(payload or b"null")

    def login(self, password: str) -> None:
        res = self._request("POST", "login", {"name": "Mac", "password": password, "device": True}, token="-")
        set_secret("cloud", res["token"])

    # ------------------------------------------------------------------ synchronisation
    def sync(self) -> dict:
        """Envoie les changements du Mac puis applique ceux des parents. Renvoie un petit bilan."""
        with self._sync_lock:
            outgoing = self._collect()
            server = self._request("POST", "sync", outgoing["body"])
            self._mark_sent(outgoing)
            return self._apply(server)

    def sync_quietly(self) -> None:
        if not self.configured:
            return
        try:
            self.sync()
        except CloudError as exc:
            print(f"[synchro] {exc}")

    def sync_in_background(self) -> None:
        threading.Thread(target=self.sync_quietly, daemon=True, name="synchro").start()

    def _collect(self) -> dict:
        s = self.store
        homework = s.homework.all()
        reports = [r for r in s.reports.all() if not r.get("synced")]
        difficulties = [d for d in s.difficulties.all() if not d.get("synced")]
        deleted = [d["hw"] for d in s.deleted.all()]
        body = {
            "children": [{"id": c.id, "name": c.name, "grade": c.grade, "level": c.level, "avatar": c.avatar,
                          "color": c.color} for c in self.cfg.children],
            "status_updates": [{"id": h["id"], "status": h["status"], "comment": h.get("comment", ""),
                                "done_at": h.get("done_at"), "status_at": h.get("status_at")}
                               for h in homework if h.get("dirty")],
            "new_homework": [{k: h.get(k) for k in ("id", "child", "subject", "task", "due", "minutes", "kind",
                                                    "status", "status_at")} for h in homework if h.get("local_new")],
            "reports": [{"id": r["id"], "child": r["child"], "date": r["date"], "text": r["text"]} for r in reports],
            "difficulties": [{k: d[k] for k in ("id", "child", "subject", "topic", "detail", "date")} for d in difficulties],
            "deleted": deleted,
        }
        return {"body": body, "reports": {r["id"] for r in reports}, "difficulties": {d["id"] for d in difficulties},
                "dirty": {h["id"]: h.get("status_at") for h in homework if h.get("dirty") or h.get("local_new")},
                "deleted": set(deleted)}

    def _mark_sent(self, out: dict) -> None:
        s = self.store

        def homework(items):
            for h in items:
                # On ne nettoie que si rien n'a changé depuis l'envoi
                if h["id"] in out["dirty"] and h.get("status_at") == out["dirty"][h["id"]]:
                    h.pop("dirty", None)
                    h.pop("local_new", None)
        s.homework.mutate(homework)

        def flag(ids):
            def fn(items):
                for i in items:
                    if i["id"] in ids:
                        i["synced"] = True
            return fn
        s.reports.mutate(flag(out["reports"]))
        s.difficulties.mutate(flag(out["difficulties"]))
        s.deleted.mutate(lambda items: items.__setitem__(slice(None), [d for d in items if d["hw"] not in out["deleted"]]))

    def _apply(self, server: dict) -> dict:
        remote = {h["id"]: h for h in server.get("homework", [])}
        stats = {"new": 0, "updated": 0, "removed": 0}

        def merge(items):
            local = {h["id"]: h for h in items}
            for hid, r in remote.items():
                h = local.get(hid)
                if r.get("deleted"):
                    if h:
                        items.remove(h)
                        stats["removed"] += 1
                    continue
                if h is None:
                    items.append({"id": hid, "child": r["child"], "subject": r["subject"], "task": r["task"],
                                  "due": r.get("due"), "minutes": r.get("minutes", 15), "kind": r.get("kind", "exercice"),
                                  "status": r.get("status", "à faire"), "comment": r.get("comment", ""),
                                  "photo": None, "added": r.get("added") or now_iso(), "done_at": r.get("done_at"),
                                  "status_at": r.get("status_at"), "by": r.get("by", "")})
                    stats["new"] += 1
                    continue
                before = dict(h)
                for k in ("child", "subject", "task", "due", "minutes", "kind", "by"):
                    if k in r:
                        h[k] = r[k]
                if (r.get("status_at") or "") > (h.get("status_at") or "") and not h.get("dirty"):
                    h.update(status=r["status"], comment=r.get("comment", ""), done_at=r.get("done_at"),
                             status_at=r["status_at"])
                if h != before:
                    stats["updated"] += 1
        self.store.homework.mutate(merge)

        notes = server.get("notes", [])

        def replace_notes(items):
            items[:] = [{"id": n["id"], "child": n["child"], "text": n["text"], "author": n.get("author", ""),
                         "date": n.get("date", ""), "active": n.get("active", True)} for n in notes]
        self.store.parent_notes.mutate(replace_notes)
        return stats

    # ------------------------------------------------------------------ secours : lecture des photos
    def process_pending_jobs(self, client) -> int:
        """Lit les photos que le serveur n'a pas réussi à lire (si les fonctions de fond ne sont pas dispo)."""
        from .homework import extract_homework

        done = 0
        for job in self._request("GET", f"jobs?older={JOB_FALLBACK_AFTER}"):
            with tempfile.TemporaryDirectory() as tmp:
                paths = []
                for i, key in enumerate(job["photos"]):
                    data = self._request("GET", f"photo/{key}", raw=True)
                    path = Path(tmp) / f"{i}.jpg"
                    path.write_bytes(data)
                    paths.append(str(path))
                caption = " — ".join(x for x in (job.get("child") and f"enfant : {job['child']}", job.get("caption")) if x)
                try:
                    result = extract_homework(client, self.cfg, paths, caption)
                except Exception as exc:  # noqa: BLE001
                    print(f"[synchro] lecture de la photo {job['id']} impossible : {exc}")
                    continue
            self._request("POST", f"jobs/{job['id']}/result", result)
            done += 1
        return done

    def run_forever(self, client_factory) -> None:
        print(f"Jarvis Junior : synchronisation avec {self.base} toutes les {INTERVAL} s.")
        client = None
        while True:
            try:
                stats = self.sync()
                if stats["new"] or stats["updated"] or stats["removed"]:
                    print(f"[synchro] {stats}")
                if client is None:
                    client = client_factory()
                n = self.process_pending_jobs(client)
                if n:
                    print(f"[synchro] {n} photo(s) lue(s) par le Mac")
            except CloudError as exc:
                print(f"[synchro] {exc}")
            except Exception as exc:  # noqa: BLE001 - le service ne doit jamais s'arrêter
                print(f"[synchro] erreur inattendue : {exc}")
            time.sleep(INTERVAL)
