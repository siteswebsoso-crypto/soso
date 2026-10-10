"""Service d'arrière-plan : synchronise le Mac avec l'espace parents (Netlify).

Lancé automatiquement à l'ouverture de session (LaunchAgent), il fonctionne même quand
l'application des enfants est fermée.
"""

from __future__ import annotations

from .cloud import Cloud
from .config import Config, app_dir
from .data import Store
from .llm import client as make_client


def main() -> None:
    cfg = Config.load()
    cloud = Cloud(cfg, Store(app_dir()))
    if not cloud.configured:
        print("Espace parents non configuré : lancez « python -m junior setup ».")
        return
    cloud.run_forever(make_client)
