"""Configuration de Jarvis Junior et accès aux secrets (Trousseau macOS)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

KEYCHAIN_SERVICE = "jarvis-junior"


def app_dir() -> Path:
    if "JUNIOR_HOME" in os.environ:
        path = Path(os.environ["JUNIOR_HOME"])
    elif platform.system() == "Darwin":
        path = Path.home() / "Library" / "Application Support" / "JarvisJunior"
    else:
        path = Path.home() / ".jarvis-junior"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Child:
    id: str
    name: str
    grade: str  # ex : "CM2", "5e"
    avatar: str = "🦊"
    color: str = "#7c5cff"
    pin_hash: str = ""
    pin_salt: str = ""
    # Une pause est proposée au bout de ce nombre de minutes de travail
    break_every: int = 25

    def set_pin(self, pin: str) -> None:
        self.pin_salt = secrets.token_hex(8)
        self.pin_hash = _hash_pin(pin, self.pin_salt)

    def check_pin(self, pin: str) -> bool:
        if not self.pin_hash:
            return True
        return secrets.compare_digest(self.pin_hash, _hash_pin(pin, self.pin_salt))

    @property
    def level(self) -> str:
        g = self.grade.lower().replace("è", "e")
        if g in {"cp", "ce1", "ce2"}:
            return f"{self.grade} (cycle 2, école élémentaire)"
        if g in {"cm1", "cm2", "6e", "6eme"}:
            return f"{self.grade} (cycle 3, consolidation)"
        if g in {"5e", "5eme", "4e", "4eme", "3e", "3eme"}:
            return f"{self.grade} (cycle 4, collège)"
        return self.grade


def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()


DEFAULT_CHILDREN = [
    Child(id="amine", name="Amine", grade="CM2", avatar="🦁", color="#ff8a3d", break_every=20),
    Child(id="ibrahim", name="Ibrahim", grade="5e", avatar="🚀", color="#3d8bff", break_every=30),
]


@dataclass
class Config:
    children: list[Child] = field(default_factory=lambda: [Child(**asdict(c)) for c in DEFAULT_CHILDREN])
    # Adresse de l'espace parents (site Netlify), ex : https://jarvis-famille.netlify.app
    cloud_url: str = ""
    parent_pin_hash: str = ""
    parent_pin_salt: str = ""
    model: str = "claude-opus-5-5"
    # Effort de réflexion pendant la séance : low = réponses rapides (recommandé à l'oral)
    tutor_effort: str = "low"
    # Voix macOS (commande `say`) ; vide = meilleure voix française installée
    voice: str = ""
    voice_rate: int = 180
    # Modèle Whisper pour la reconnaissance vocale (MLX sur puce Apple)
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"

    @classmethod
    def load(cls) -> "Config":
        path = app_dir() / "config.json"
        if not path.exists():
            cfg = cls()
            cfg.save()
            return cfg
        raw = json.loads(path.read_text(encoding="utf-8"))
        children = [Child(**c) for c in raw.pop("children", [])] or cls().children
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(children=children, **known)

    def save(self) -> None:
        path = app_dir() / "config.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        path.chmod(0o600)

    def child(self, ref: str) -> Child | None:
        ref = (ref or "").strip().lower()
        return next((c for c in self.children if ref in (c.id, c.name.lower())), None)

    def set_parent_pin(self, pin: str) -> None:
        self.parent_pin_salt = secrets.token_hex(8)
        self.parent_pin_hash = _hash_pin(pin, self.parent_pin_salt)

    def check_parent_pin(self, pin: str) -> bool:
        if not self.parent_pin_hash:
            return False
        return secrets.compare_digest(self.parent_pin_hash, _hash_pin(pin, self.parent_pin_salt))


# ---------------------------------------------------------------------- secrets

def get_secret(name: str) -> str:
    """Lit un secret : variable d'environnement, sinon Trousseau macOS, sinon fichier local protégé."""
    env = {"anthropic": "ANTHROPIC_API_KEY", "cloud": "JUNIOR_CLOUD_TOKEN"}[name]
    if os.environ.get(env):
        return os.environ[env]
    if platform.system() == "Darwin":
        res = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
                             capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.strip()
    path = app_dir() / f".{name}"
    return path.read_text().strip() if path.exists() else ""


def set_secret(name: str, value: str) -> None:
    if platform.system() == "Darwin":
        subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", name, "-w", value],
                       check=True, capture_output=True)
        return
    path = app_dir() / f".{name}"
    path.write_text(value)
    path.chmod(0o600)
