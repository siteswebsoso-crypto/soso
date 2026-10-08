"""Projets autonomes : un agent travaille en arrière-plan jusqu'à ce que la tâche soit finie.

Exemple : « Jarvis, crée le site de la boulangerie Dupont avec la recette site SEO ».
Jarvis écrit un cahier des charges (JARVIS_BRIEF.md) dans un dossier dédié, puis lance un agent :

- moteur « claude-code » : la CLI Claude Code (`claude -p`), idéale pour coder des sites et des
  apps — utilisée automatiquement si elle est installée ;
- moteur « builtin » : un agent Claude intégré à Jarvis (terminal + fichiers confinés au dossier
  du projet, recherche web, questions de validation à l'utilisateur).

L'agent rend compte de ses étapes, peut vous poser des questions (à la voix, au clavier ou sur
Telegram) et vous prévient quand il a terminé.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

import anthropic

from .channels import Channel, parse_confirmation
from .config import Config
from .playbooks import PlaybookLibrary, slugify
from .tools import _clip, desktop_notify

BRIEF_FILE = "JARVIS_BRIEF.md"

WORKER_RULES = """Tu es l'agent d'exécution de J.A.R.V.I.S. Tu réalises un projet de bout en bout, en autonomie,
dans le dossier de travail courant. Le cahier des charges complet est dans JARVIS_BRIEF.md : lis-le
en premier et respecte à la lettre les recettes (instructions de l'utilisateur) qu'il contient.

- Va jusqu'au bout : produis un résultat complet et fonctionnel, pas une ébauche.
- Quand une information manque, choisis l'option la plus raisonnable et note-la dans le résumé final ;
  ne demande à l'utilisateur que les décisions vraiment bloquantes ou irréversibles (mise en ligne,
  achat, envoi d'e-mails…).
- Vérifie ton travail (build, tests, validation HTML, liens) avant de conclure.
- Termine par un résumé court, lisible à voix haute : ce qui a été fait, où le trouver, comment le
  lancer, et les points qui attendent une décision de l'utilisateur."""

CLAUDE_CODE_TOOLS = ",".join([
    "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite",
    "Bash(npm *)", "Bash(npx *)", "Bash(node *)", "Bash(pnpm *)", "Bash(yarn *)", "Bash(git *)",
    "Bash(python *)", "Bash(python3 *)", "Bash(pip *)", "Bash(mkdir *)", "Bash(ls *)",
    "Bash(cat *)", "Bash(cp *)", "Bash(mv *)", "Bash(touch *)",
])


class Project:
    def __init__(self, meta_path: Path, data: dict):
        self.meta_path = meta_path
        self.data = data
        self.stop_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def workspace(self) -> Path:
        return Path(self.data["workspace"])

    def log(self, message: str) -> None:
        with self._lock:
            self.data["log"].append({"t": datetime.now().strftime("%H:%M:%S"), "msg": message[:500]})
            self.data["log"] = self.data["log"][-300:]
            self._save()

    def set(self, **fields) -> None:
        with self._lock:
            self.data.update(fields)
            self._save()

    def _save(self) -> None:
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.meta_path)

    def status_text(self, last: int = 8) -> str:
        d = self.data
        lines = [f"Projet « {d['name']} » [{d['id']}] — {d['status']} (moteur {d['engine']})",
                 f"Dossier : {d['workspace']}"]
        if d.get("summary"):
            lines.append(f"Résumé : {d['summary']}")
        lines += [f"  {e['t']} {e['msg']}" for e in d["log"][-last:]]
        return "\n".join(lines)


class ProjectManager:
    def __init__(self, cfg: Config, root: Path, playbooks: PlaybookLibrary, channel: Channel):
        self.cfg = cfg
        self.meta_dir = root / "projects"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.playbooks = playbooks
        self.channel = channel
        self.running: dict[str, Project] = {}

    # ------------------------------------------------------------------ queries
    def all(self) -> list[Project]:
        projects = []
        for path in sorted(self.meta_dir.glob("*.json")):
            pid = path.stem
            if pid in self.running:
                projects.append(self.running[pid])
            else:
                projects.append(Project(path, json.loads(path.read_text(encoding="utf-8"))))
        return projects

    def find(self, ref: str | None) -> Project | None:
        projects = self.all()
        if not projects:
            return None
        if not ref:
            return max(projects, key=lambda p: p.data["started"])
        slug = slugify(ref)
        for p in projects:
            if p.data["id"] == ref or slugify(p.data["name"]) == slug:
                return p
        return next((p for p in projects if slug in slugify(p.data["name"])), None)

    def engine(self, requested: str | None = None) -> str:
        choice = requested or self.cfg.worker_engine
        if choice == "auto":
            return "claude-code" if shutil.which("claude") else "builtin"
        return choice

    # ------------------------------------------------------------------ actions
    def start(self, name: str, brief: str, playbooks: list[str], engine: str | None = None) -> Project:
        pid = uuid.uuid4().hex[:6]
        workspace = Path(self.cfg.projects_dir).expanduser() / slugify(name)
        workspace.mkdir(parents=True, exist_ok=True)

        sections = [f"# Projet : {name}\n\nDate : {datetime.now():%d/%m/%Y}\n\n## Demande\n\n{brief.strip()}"]
        for pb in playbooks:
            sections.append(f"## Recette : {pb}\n\n{self.playbooks.read(pb).strip()}")
        (workspace / BRIEF_FILE).write_text("\n\n".join(sections) + "\n", encoding="utf-8")

        project = Project(self.meta_dir / f"{pid}.json", {
            "id": pid, "name": name, "brief": brief, "playbooks": playbooks,
            "workspace": str(workspace), "engine": self.engine(engine), "status": "en cours",
            "started": datetime.now().isoformat(timespec="seconds"), "finished": None,
            "summary": "", "log": [],
        })
        project.set()
        self.running[pid] = project
        threading.Thread(target=self._run, args=(project,), daemon=True, name=f"projet-{pid}").start()
        return project

    def stop(self, ref: str | None) -> str:
        project = self.find(ref)
        if not project or project.data["id"] not in self.running:
            return "Aucun projet en cours ne correspond."
        project.stop_event.set()
        return f"Arrêt demandé pour « {project.data['name']} »."

    def _run(self, project: Project) -> None:
        worker = ClaudeCodeWorker if project.data["engine"] == "claude-code" else BuiltinWorker
        try:
            summary = worker(project, self.cfg, self.channel).run()
            status = "arrêté" if project.stop_event.is_set() else "terminé"
        except Exception as exc:  # noqa: BLE001
            summary, status = f"Échec : {type(exc).__name__}: {exc}", "échoué"
        project.set(status=status, summary=summary, finished=datetime.now().isoformat(timespec="seconds"))
        project.log(f"{status} — {summary[:300]}")
        self.running.pop(project.data["id"], None)
        message = f"{self.cfg.user_name}, le projet {project.data['name']} est {status}. {summary}"
        desktop_notify(f"Projet {status}", project.data["name"])
        self.channel.say(message)


# ====================================================================== moteur Claude Code

class ClaudeCodeWorker:
    def __init__(self, project: Project, cfg: Config, channel: Channel):
        self.project, self.cfg, self.channel = project, cfg, channel

    def run(self) -> str:
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("CLI Claude Code introuvable (npm install -g @anthropic-ai/claude-code)")
        cmd = [exe, "-p", f"Réalise entièrement le projet décrit dans {BRIEF_FILE}.",
               "--output-format", "stream-json", "--verbose",
               "--permission-mode", self.cfg.claude_code_permission_mode,
               "--append-system-prompt", WORKER_RULES]
        if self.cfg.claude_code_permission_mode not in ("bypassPermissions", "auto"):
            cmd += ["--allowedTools", CLAUDE_CODE_TOOLS]
        self.project.log("Démarrage de Claude Code")
        proc = subprocess.Popen(cmd, cwd=self.project.workspace, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        watcher = threading.Thread(target=self._watch_stop, args=(proc,), daemon=True)
        watcher.start()

        summary = ""
        for line in proc.stdout:  # type: ignore[union-attr]
            event = _parse_json(line)
            if event is None:
                if line.strip():
                    self.project.log(line.strip())
                continue
            if event.get("type") == "assistant":
                for block in (event.get("message") or {}).get("content", []):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        self.project.log(block["text"].strip())
                    elif block.get("type") == "tool_use":
                        self.project.log(f"→ {block.get('name')} {_short(block.get('input'))}")
            elif event.get("type") == "result":
                summary = event.get("result") or ""
                if event.get("is_error"):
                    summary = f"Échec : {summary}"
        proc.wait()
        return summary or f"Claude Code s'est arrêté (code {proc.returncode})."

    def _watch_stop(self, proc: subprocess.Popen) -> None:
        while proc.poll() is None:
            if self.project.stop_event.wait(1):
                proc.terminate()
                return


# ====================================================================== moteur intégré

def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


WORKER_TOOLS = [
    {"name": "run_shell", "description": "Exécute une commande shell dans le dossier du projet.",
     "input_schema": _obj({"command": {"type": "string"}, "timeout": {"type": "integer"}}, ["command"])},
    {"name": "write_file", "description": "Crée ou remplace un fichier (chemin relatif au projet).",
     "input_schema": _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])},
    {"name": "edit_file", "description": "Remplace un passage exact (unique) d'un fichier par un autre.",
     "input_schema": _obj({"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
                          ["path", "old", "new"])},
    {"name": "read_file", "description": "Lit un fichier du projet.",
     "input_schema": _obj({"path": {"type": "string"}}, ["path"])},
    {"name": "list_files", "description": "Liste récursivement les fichiers du projet.",
     "input_schema": _obj({}, [])},
    {"name": "report_progress", "description": "Annonce une étape importante à l'utilisateur (une phrase).",
     "input_schema": _obj({"message": {"type": "string"}}, ["message"])},
    {"name": "ask_user", "description": "Pose une question à l'utilisateur et attend sa réponse (à la voix ou "
     "au clavier). Réservé aux décisions bloquantes ou irréversibles.",
     "input_schema": _obj({"question": {"type": "string"}}, ["question"])},
]
for _tool in WORKER_TOOLS:
    _tool["eager_input_streaming"] = True


class BuiltinWorker:
    def __init__(self, project: Project, cfg: Config, channel: Channel):
        self.project, self.cfg, self.channel = project, cfg, channel
        self.root = project.workspace.resolve()
        self.client = anthropic.Anthropic()

    def run(self) -> str:
        tools = WORKER_TOOLS + [{"type": "web_search_20260209", "name": "web_search"},
                                {"type": "web_fetch_20260209", "name": "web_fetch"}]
        messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text":
            f"Voici le cahier des charges :\n\n{(self.root / BRIEF_FILE).read_text(encoding='utf-8')}\n\n"
            "Réalise le projet maintenant."}]}]
        texts: list[str] = []
        for step in range(self.cfg.worker_max_steps):
            if self.project.stop_event.is_set():
                return "Projet interrompu à la demande de l'utilisateur."
            with self.client.beta.messages.stream(
                model=self.cfg.model, max_tokens=64000, system=WORKER_RULES, tools=tools, messages=messages,
                thinking={"type": "adaptive"}, output_config={"effort": self.cfg.worker_effort},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            ) as stream:
                response = stream.get_final_message()
            messages.append({"role": "assistant", "content": response.content})
            texts = [b.text for b in response.content if b.type == "text" and b.text.strip()]
            for t in texts:
                self.project.log(t)

            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "refusal":
                return "L'agent a refusé de poursuivre ce projet."
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "user", "content": [{"type": "text", "text": "Continue."}]})
                    continue
                return " ".join(texts) or "Terminé."
            truncated = response.stop_reason == "max_tokens"
            messages.append({"role": "user", "content": [self._execute(b, truncated) for b in tool_uses]})
        return "Limite d'étapes atteinte. " + " ".join(texts)

    # -------------------------------------------------------------- outils
    def _execute(self, block, truncated: bool) -> dict:
        def result(content, error=False):
            r = {"type": "tool_result", "tool_use_id": block.id, "content": content}
            if error:
                r["is_error"] = True
            return r

        args = block.input if isinstance(block.input, dict) else {}
        problem = "réponse tronquée (max_tokens)" if truncated else _validate(block.name, args)
        if problem:
            return result(f"Entrée invalide : {problem}. Réessaie, en découpant en fichiers plus petits si besoin.",
                          error=True)
        try:
            return result(self._dispatch(block.name, args))
        except Exception as exc:  # noqa: BLE001
            return result(f"Erreur : {type(exc).__name__}: {exc}", error=True)

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "run_shell":
            self.project.log(f"$ {args['command']}")
            proc = subprocess.run(args["command"], shell=True, cwd=self.root, capture_output=True, text=True,
                                  timeout=args.get("timeout", 300))
            return _clip(f"code de sortie : {proc.returncode}\n{proc.stdout}\n{proc.stderr}".strip())
        if name == "write_file":
            path = self._safe(args["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            self.project.log(f"écrit {path.relative_to(self.root)}")
            return f"Écrit {path.relative_to(self.root)} ({len(args['content'])} caractères)"
        if name == "edit_file":
            path = self._safe(args["path"])
            text = path.read_text(encoding="utf-8")
            if text.count(args["old"]) != 1:
                raise ValueError(f"le passage apparaît {text.count(args['old'])} fois (il faut exactement 1)")
            path.write_text(text.replace(args["old"], args["new"]), encoding="utf-8")
            return f"Modifié {path.relative_to(self.root)}"
        if name == "read_file":
            return _clip(self._safe(args["path"]).read_text(encoding="utf-8", errors="replace"))
        if name == "list_files":
            files = [str(p.relative_to(self.root)) for p in self.root.rglob("*")
                     if p.is_file() and not {"node_modules", ".git"} & set(p.parts)]
            return "\n".join(sorted(files)[:500]) or "(vide)"
        if name == "report_progress":
            self.project.log(f"📣 {args['message']}")
            self.channel.say(f"Projet {self.project.data['name']} : {args['message']}")
            return "Annoncé."
        if name == "ask_user":
            self.project.log(f"❓ {args['question']}")
            answer = self.channel.ask(f"Question sur le projet {self.project.data['name']} : {args['question']}")
            if answer is None:
                return "Pas de réponse de l'utilisateur : choisis l'option la plus prudente et continue."
            approved, _ = parse_confirmation(answer)
            self.project.log(f"réponse : {answer}")
            return f"Réponse de l'utilisateur : « {answer} »" + (" (interprétée comme un accord)" if approved else "")
        raise ValueError(f"Outil inconnu : {name}")

    def _safe(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError("chemin hors du dossier du projet")
        return path


def _validate(name: str, args: dict) -> str | None:
    """Avec eager_input_streaming, l'API ne valide plus les entrées : on le fait ici."""
    schema = next((t["input_schema"] for t in WORKER_TOOLS if t["name"] == name), None)
    if schema is None:
        return None
    for key in schema["required"]:
        if key not in args:
            return f"paramètre manquant « {key} »"
    for key, value in args.items():
        expected = schema["properties"].get(key, {}).get("type")
        if expected is None:
            return f"paramètre inconnu « {key} »"
        if not isinstance(value, {"string": str, "integer": int, "boolean": bool}[expected]):
            return f"« {key} » doit être de type {expected}"
    return None


def _parse_json(line: str):
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False) if value is not None else ""
    return text[:120] + ("…" if len(text) > 120 else "")

