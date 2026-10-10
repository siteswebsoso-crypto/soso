"""Assistant de configuration (à lancer une fois) : clé Claude, espace parents, codes, voix."""

from __future__ import annotations

import getpass
import platform
import subprocess
import time

from .cloud import Cloud, CloudError
from .config import Config, app_dir, get_secret, set_secret
from .data import Store

AVATARS = ["🦁", "🚀", "🦊", "🐼", "🐯", "🦄", "🐸", "⚽", "🎮", "🐉", "🦖", "🌟"]


def ask(prompt: str, default: str = "") -> str:
    value = input(f"{prompt}{f' [{default}]' if default else ''} : ").strip()
    return value or default


def ask_pin(label: str) -> str:
    while True:
        pin = getpass.getpass(f"{label} (4 chiffres, invisible à la saisie) : ").strip()
        if len(pin) == 4 and pin.isdigit() and getpass.getpass("Confirmez : ").strip() == pin:
            return pin
        print("  Le code doit faire 4 chiffres et être identique deux fois.")


def step_api_key() -> None:
    print("\n① Clé API Claude — https://console.anthropic.com → API Keys")
    if get_secret("anthropic"):
        if ask("Une clé est déjà enregistrée. La remplacer ? (o/N)", "n").lower() != "o":
            return
    key = getpass.getpass("Collez la clé (sk-ant-…) : ").strip()
    if key:
        set_secret("anthropic", key)
        print("  ✓ Clé enregistrée dans le Trousseau.")


def step_cloud(cfg: Config) -> None:
    print("\n② Espace parents (site Netlify)")
    print("  Il doit déjà être en ligne (voir JARVIS_JUNIOR.md, « Mettre en ligne l'espace parents »).")
    url = ask("  Adresse du site (ex : https://jarvis-famille.netlify.app)", cfg.cloud_url).strip().rstrip("/")
    if not url:
        print("  (ignoré : les rapports resteront sur le Mac)")
        return
    if not url.startswith("http"):
        url = "https://" + url
    cfg.cloud_url = url
    cloud = Cloud(cfg, Store(app_dir()))
    for _ in range(3):
        password = getpass.getpass("  Mot de passe familial (celui choisi sur Netlify) : ").strip()
        try:
            cloud.login(password)
            cloud.sync()
            print("  ✓ Le Mac est relié à l'espace parents.")
            return
        except CloudError as exc:
            print(f"  ✗ {exc}")
    print("  Connexion impossible pour l'instant : relancez « python -m junior setup » plus tard.")


def step_children(cfg: Config) -> None:
    print("\n③ Les enfants")
    for child in cfg.children:
        print(f"\n  {child.name} ({child.grade})")
        child.grade = ask("  Classe", child.grade)
        print("  Avatars : " + "  ".join(f"{i + 1}:{a}" for i, a in enumerate(AVATARS)))
        choice = ask("  Numéro de l'avatar", str(AVATARS.index(child.avatar) + 1 if child.avatar in AVATARS else 1))
        if choice.isdigit() and 1 <= int(choice) <= len(AVATARS):
            child.avatar = AVATARS[int(choice) - 1]
        child.set_pin(ask_pin(f"  Code secret de {child.name}"))
    print("\n④ Code parent (pour l'espace parents dans l'application)")
    cfg.set_parent_pin(ask_pin("  Code parent"))


def step_voice(cfg: Config) -> None:
    if platform.system() != "Darwin":
        return
    from .audio import best_voice, french_voices
    print("\n⑤ Voix de Jarvis")
    voices = french_voices()
    if not any(m in v for v in voices for m in ("Premium", "Enhanced", "Amélioré")):
        print("  Conseil : pour une voix beaucoup plus naturelle, installez une voix « Premium » :")
        print("  Réglages Système → Accessibilité → Contenu énoncé → Voix du système → Gérer les voix…")
        print("  → Français → cochez « Audrey (Premium) » ou « Thomas (Premium) ». Puis relancez ce réglage.")
    print("  Voix françaises installées : " + (", ".join(voices) or "aucune"))
    cfg.voice = ask("  Voix à utiliser", best_voice(cfg.voice))
    subprocess.run(["say", "-v", cfg.voice, "Bonjour ! Je suis Jarvis, et je vais t'aider à faire tes devoirs."])


def run() -> None:
    print("=== Configuration de Jarvis Junior ===")
    cfg = Config.load()
    step_api_key()
    step_children(cfg)
    cfg.save()
    step_cloud(cfg)
    step_voice(cfg)
    cfg.save()
    print("\n✓ Configuration terminée.")
