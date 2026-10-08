"""Les outils que Jarvis peut utiliser sur la machine.

Chaque outil est une fonction Python enregistrée avec son schéma JSON.
Les outils marqués `dangerous=True` demandent une confirmation avant exécution.
"""

from __future__ import annotations

import base64
import fnmatch
import io
import os
import platform
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .store import Store

MAX_OUTPUT = 12_000


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    func: Callable[..., Any]
    dangerous: bool = False

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n… [tronqué, {len(text) - MAX_OUTPUT} caractères de plus]"


def _path(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser()


def _open_with_os(target: str) -> None:
    system = platform.system()
    if system == "Windows":
        os.startfile(target)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Toolbox:
    def __init__(self, store: Store):
        self.store = store
        self.tools: dict[str, Tool] = {}
        self._register_all()

    # ------------------------------------------------------------------ registry
    def add(self, name: str, description: str, schema: dict, dangerous: bool = False):
        def deco(func):
            self.tools[name] = Tool(name, description, schema, func, dangerous)
            return func
        return deco

    def definitions(self) -> list[dict]:
        return [t.definition() for t in self.tools.values()]

    def describe_call(self, name: str, args: dict) -> str:
        if name == "run_shell":
            return f"Exécuter : {args.get('command')}" + (f"  (dans {args['cwd']})" if args.get("cwd") else "")
        if name == "write_file":
            mode = "Ajouter à" if args.get("append") else "Écrire"
            return f"{mode} {args.get('path')} ({len(args.get('content', ''))} caractères)"
        return f"{name}({args})"

    def run(self, name: str, args: dict) -> Any:
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"Outil inconnu : {name}")
        return tool.func(**args)

    # ------------------------------------------------------------------ tools
    def _register_all(self) -> None:
        store = self.store

        @self.add(
            "run_shell",
            "Exécute une commande dans le terminal de l'utilisateur (PowerShell/cmd sous Windows, "
            "sh sous macOS/Linux) et renvoie stdout/stderr. Pour lancer des scripts, git, gérer "
            "des fichiers, installer des paquets, contrôler le système, etc.",
            _obj({
                "command": {"type": "string", "description": "La commande à exécuter"},
                "cwd": {"type": "string", "description": "Dossier de travail (optionnel)"},
                "timeout": {"type": "integer", "description": "Délai max en secondes (défaut 120)"},
            }, ["command"]),
            dangerous=True,
        )
        def run_shell(command: str, cwd: str | None = None, timeout: int = 120) -> str:
            if platform.system() == "Windows":
                argv = ["powershell", "-NoProfile", "-Command", command]
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                      cwd=_path(cwd) if cwd else None)
            else:
                proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                                      timeout=timeout, cwd=_path(cwd) if cwd else None)
            out = f"code de sortie : {proc.returncode}\n"
            if proc.stdout:
                out += f"--- stdout ---\n{proc.stdout}"
            if proc.stderr:
                out += f"\n--- stderr ---\n{proc.stderr}"
            return _clip(out)

        @self.add(
            "open",
            "Ouvre une URL dans le navigateur, un fichier/dossier avec l'application par défaut, "
            "ou lance une application par son nom (ex : 'Spotify', 'calculator', 'code').",
            _obj({"target": {"type": "string", "description": "URL, chemin ou nom d'application"}}, ["target"]),
        )
        def open_target(target: str) -> str:
            if target.startswith(("http://", "https://", "mailto:")):
                webbrowser.open(target)
                return f"Ouvert dans le navigateur : {target}"
            p = _path(target)
            if p.exists():
                _open_with_os(str(p))
                return f"Ouvert : {p}"
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["open", "-a", target])
            elif system == "Windows":
                subprocess.Popen(["cmd", "/c", "start", "", target])
            else:
                exe = shutil.which(target) or shutil.which(target.lower())
                if not exe:
                    return f"Application introuvable : {target}"
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            return f"Application lancée : {target}"

        @self.add(
            "list_dir",
            "Liste le contenu d'un dossier (nom, type, taille).",
            _obj({"path": {"type": "string", "description": "Dossier, ex : ~/Documents"}}, ["path"]),
        )
        def list_dir(path: str) -> str:
            p = _path(path)
            lines = []
            for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:300]:
                if entry.is_dir():
                    lines.append(f"[dossier] {entry.name}/")
                else:
                    lines.append(f"{entry.name}  ({entry.stat().st_size} o)")
            return "\n".join(lines) or "(dossier vide)"

        @self.add(
            "read_file",
            "Lit un fichier texte et renvoie son contenu.",
            _obj({"path": {"type": "string"}}, ["path"]),
        )
        def read_file(path: str) -> str:
            return _clip(_path(path).read_text(encoding="utf-8", errors="replace"))

        @self.add(
            "write_file",
            "Crée ou modifie un fichier texte (notes, scripts, listes…).",
            _obj({
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean", "description": "Ajouter à la fin au lieu d'écraser"},
            }, ["path", "content"]),
            dangerous=True,
        )
        def write_file(path: str, content: str, append: bool = False) -> str:
            p = _path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a" if append else "w", encoding="utf-8") as f:
                f.write(content)
            return f"{'Ajouté à' if append else 'Écrit'} {p}"

        @self.add(
            "find_files",
            "Cherche des fichiers par motif de nom (ex : '*.pdf', '*facture*') dans un dossier, récursivement.",
            _obj({
                "root": {"type": "string", "description": "Dossier de départ, ex : ~"},
                "pattern": {"type": "string"},
            }, ["root", "pattern"]),
        )
        def find_files(root: str, pattern: str) -> str:
            hits = []
            for dirpath, dirnames, filenames in os.walk(_path(root)):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
                for name in filenames:
                    if fnmatch.fnmatch(name.lower(), pattern.lower()):
                        hits.append(os.path.join(dirpath, name))
                        if len(hits) >= 100:
                            return "\n".join(hits) + "\n… (100 premiers résultats)"
            return "\n".join(hits) or "Aucun fichier trouvé."

        @self.add(
            "system_info",
            "Infos sur la machine : OS, CPU, RAM, disque, batterie, heure.",
            _obj({}),
        )
        def system_info() -> str:
            info = {
                "os": f"{platform.system()} {platform.release()}",
                "machine": platform.machine(),
                "python": sys.version.split()[0],
                "heure": datetime.now().strftime("%A %d %B %Y %H:%M"),
                "dossier_perso": str(Path.home()),
            }
            total, used, free = shutil.disk_usage(Path.home())
            info["disque"] = f"{free // 2**30} Go libres / {total // 2**30} Go"
            try:
                import psutil
                info["cpu"] = f"{psutil.cpu_percent(interval=0.5)}% ({os.cpu_count()} cœurs)"
                vm = psutil.virtual_memory()
                info["ram"] = f"{vm.percent}% utilisée sur {vm.total // 2**30} Go"
                bat = psutil.sensors_battery()
                if bat:
                    info["batterie"] = f"{bat.percent:.0f}%{' (en charge)' if bat.power_plugged else ''}"
            except ImportError:
                info["note"] = "installer psutil pour CPU/RAM/batterie"
            return "\n".join(f"{k}: {v}" for k, v in info.items())

        @self.add(
            "screenshot",
            "Prend une capture de l'écran de l'utilisateur pour voir ce qu'il y a dessus.",
            _obj({}),
        )
        def screenshot() -> list[dict]:
            from PIL import ImageGrab  # pip install Pillow
            img = ImageGrab.grab()
            img.thumbnail((1568, 1568))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=80)
            data = base64.standard_b64encode(buf.getvalue()).decode()
            return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}]

        @self.add(
            "clipboard",
            "Lit le presse-papiers (sans 'text') ou y copie du texte (avec 'text').",
            _obj({"text": {"type": "string", "description": "Texte à copier (optionnel)"}}),
        )
        def clipboard(text: str | None = None) -> str:
            import pyperclip  # pip install pyperclip
            if text is None:
                return pyperclip.paste() or "(presse-papiers vide)"
            pyperclip.copy(text)
            return "Copié dans le presse-papiers."

        @self.add(
            "notify",
            "Affiche une notification sur le bureau.",
            _obj({"title": {"type": "string"}, "message": {"type": "string"}}, ["title", "message"]),
        )
        def notify(title: str, message: str) -> str:
            desktop_notify(title, message)
            return "Notification envoyée."

        @self.add(
            "remember",
            "Mémorise durablement un fait sur l'utilisateur ou ses préférences "
            "(ex : 'Son médecin s'appelle Dr Martin', 'Préfère les réunions le matin').",
            _obj({"fact": {"type": "string"}}, ["fact"]),
        )
        def remember(fact: str) -> str:
            item = store.remember(fact)
            return f"Mémorisé (id {item['id']})."

        @self.add(
            "forget",
            "Oublie un fait mémorisé, par son id.",
            _obj({"id": {"type": "string"}}, ["id"]),
        )
        def forget(id: str) -> str:
            return "Oublié." if store.memories.remove(id) else "Id introuvable."

        @self.add(
            "list_memories",
            "Liste tout ce qui est mémorisé sur l'utilisateur.",
            _obj({}),
        )
        def list_memories() -> str:
            items = store.memories.all()
            return "\n".join(f"[{m['id']}] {m['fact']}" for m in items) or "Aucun souvenir."

        @self.add(
            "add_reminder",
            "Programme un rappel. Jarvis préviendra l'utilisateur à l'heure dite "
            "(notification, voix, Telegram). L'heure est au format ISO local, ex : 2026-10-09T08:30.",
            _obj({
                "when": {"type": "string", "description": "Date et heure ISO 8601, heure locale"},
                "message": {"type": "string"},
            }, ["when", "message"]),
        )
        def add_reminder(when: str, message: str) -> str:
            dt = datetime.fromisoformat(when)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            item = store.add_reminder(dt, message)
            return f"Rappel {item['id']} programmé pour le {dt:%d/%m/%Y à %H:%M}."

        @self.add(
            "list_reminders",
            "Liste les rappels à venir.",
            _obj({}),
        )
        def list_reminders() -> str:
            items = [r for r in store.reminders.all() if not r["done"]]
            items.sort(key=lambda r: r["when"])
            return "\n".join(f"[{r['id']}] {r['when']} — {r['message']}" for r in items) or "Aucun rappel."

        @self.add(
            "cancel_reminder",
            "Annule un rappel par son id.",
            _obj({"id": {"type": "string"}}, ["id"]),
        )
        def cancel_reminder(id: str) -> str:
            return "Rappel annulé." if store.reminders.remove(id) else "Id introuvable."


def desktop_notify(title: str, message: str) -> None:
    """Notification bureau, avec repli selon l'OS si plyer n'est pas installé."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="Jarvis", timeout=10)
        return
    except Exception:
        pass
    system = platform.system()
    try:
        if system == "Darwin":
            script = f'display notification {_applescript_str(message)} with title {_applescript_str(title)}'
            subprocess.run(["osascript", "-e", script], check=False)
        elif system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], check=False)
    except OSError:
        pass


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
