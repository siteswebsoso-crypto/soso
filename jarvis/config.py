"""Configuration de Jarvis : ~/.jarvis/config.json (ou $JARVIS_HOME)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def data_dir() -> Path:
    path = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Config:
    user_name: str = "Monsieur"
    model: str = "claude-opus-5-5"
    # low = réponses rapides, medium = équilibré, high = tâches complexes
    effort: str = "medium"
    language: str = "fr-FR"
    wake_word: str = "jarvis"
    # Si True, les commandes shell / écritures de fichiers ne demandent plus confirmation
    auto_approve: bool = False
    # Recherche web côté serveur Claude
    web_search: bool = True
    telegram_token: str = ""
    telegram_allowed_ids: list[int] = field(default_factory=list)
    tts: bool = True

    @classmethod
    def load(cls) -> "Config":
        path = data_dir() / "config.json"
        if not path.exists():
            cfg = cls()
            cfg.save()
            return cfg
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        # Les variables d'environnement priment (pratique pour les secrets)
        cfg.telegram_token = os.environ.get("JARVIS_TELEGRAM_TOKEN", cfg.telegram_token)
        return cfg

    def save(self) -> None:
        path = data_dir() / "config.json"
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
