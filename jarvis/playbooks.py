"""Recettes : vos instructions réutilisables (ex : « site vitrine full SEO »).

Chaque recette est un fichier Markdown dans ~/.jarvis/playbooks/. Jarvis les lit quand une tâche
s'y rapporte et les transmet à l'agent qui exécute le projet.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.request
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent / "recettes"


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "sans-nom"


class PlaybookLibrary:
    def __init__(self, root: Path, seed: bool = True):
        self.root = root
        if not self.root.exists():
            self.root.mkdir(parents=True)
            if seed:  # premières recettes d'exemple, à modifier librement
                for example in EXAMPLES_DIR.glob("*.md"):
                    (self.root / example.name).write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.md"))

    def summary(self) -> str:
        lines = []
        for name in self.names():
            first = next((l.strip("# ").strip() for l in self.path(name).read_text(encoding="utf-8").splitlines()
                          if l.strip()), "")
            lines.append(f"- {name} : {first[:120]}")
        return "\n".join(lines) or "(aucune recette)"

    def path(self, name: str) -> Path:
        return self.root / f"{slugify(name)}.md"

    def find(self, name: str) -> str | None:
        """Retrouve une recette même si le nom est approximatif (dicté à la voix)."""
        wanted = slugify(name)
        names = self.names()
        if wanted in names:
            return wanted
        words = set(wanted.split("-"))
        scored = sorted(((len(words & set(n.split("-"))), n) for n in names), reverse=True)
        if scored and scored[0][0] > 0:
            return scored[0][1]
        return None

    def read(self, name: str) -> str:
        found = self.find(name)
        if not found:
            raise FileNotFoundError(f"Recette introuvable : {name}. Disponibles : {', '.join(self.names()) or 'aucune'}")
        return self.path(found).read_text(encoding="utf-8")

    def save(self, name: str, content: str, append: bool = False) -> str:
        path = self.path(name)
        if append and path.exists():
            content = path.read_text(encoding="utf-8").rstrip() + "\n\n" + content
        path.write_text(content.strip() + "\n", encoding="utf-8")
        return path.stem

    def import_from(self, name: str, source: str) -> str:
        """Importe une recette depuis un fichier local ou une URL publique (Google Docs, GitHub, Notion…)."""
        if source.startswith(("http://", "https://")):
            url = _export_url(source)
            req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            if "<html" in content[:2000].lower():
                content = _html_to_text(content)
        else:
            content = Path(source).expanduser().read_text(encoding="utf-8")
        return self.save(name, content)


def _export_url(url: str) -> str:
    """Convertit les liens de partage courants en lien de texte brut."""
    m = re.match(r"https://docs\.google\.com/document/d/([^/]+)", url)
    if m:
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/blob/(.+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}"
    return url


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li)>", "\n", html)
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
