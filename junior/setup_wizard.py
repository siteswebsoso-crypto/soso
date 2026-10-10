"""Assistant de configuration (à lancer une fois) : clés, parents Telegram, codes, voix."""

from __future__ import annotations

import getpass
import platform
import subprocess
import time

from .config import Config, get_secret, set_secret
from .telegram_api import Telegram

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


def step_telegram(cfg: Config) -> None:
    print("\n② Bot Telegram des parents")
    print("  Sur Telegram, ouvrez @BotFather → /newbot → choisissez un nom (ex : Jarvis Junior Maison).")
    token = get_secret("telegram")
    if token and ask("Un bot est déjà configuré. Le changer ? (o/N)", "n").lower() != "o":
        pass
    else:
        token = getpass.getpass("  Collez le token donné par BotFather : ").strip()
        if not token:
            print("  (ignoré : pas de Telegram)")
            return
        set_secret("telegram", token)
    tg = Telegram(token)
    print("\n  Maintenant, CHAQUE PARENT ouvre le bot sur son téléphone et lui envoie « /start ».")
    print("  J'attends 2 minutes (Entrée ou Ctrl+C pour arrêter plus tôt)…")
    offset, found = 0, {}
    deadline = time.time() + 120
    try:
        while time.time() < deadline and len(found) < 2:
            for upd in tg.updates(offset, timeout=10):
                offset = upd["update_id"] + 1
                user = (upd.get("message") or {}).get("from")
                if user and user["id"] not in found:
                    found[user["id"]] = user.get("first_name", "Parent")
                    print(f"  → reçu : {found[user['id']]} (id {user['id']})")
    except KeyboardInterrupt:
        pass
    if offset:
        tg.updates(offset, timeout=0)  # marque ces messages comme lus
    for uid, name in found.items():
        if ask(f"  Autoriser {name} comme parent ? (O/n)", "o").lower() != "n":
            if uid not in cfg.parent_ids:
                cfg.parent_ids.append(uid)
            cfg.parent_names[str(uid)] = ask(f"  Comment l'appeler dans les rapports", name)
            tg.send(uid, "✅ Vous êtes enregistré comme parent sur Jarvis Junior. "
                         "Envoyez-moi une photo des devoirs quand vous voulez !")
    print(f"  Parents enregistrés : {', '.join(cfg.parent_names.values()) or 'aucun'}")


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
    step_telegram(cfg)
    step_children(cfg)
    step_voice(cfg)
    cfg.save()
    print("\n✓ Configuration terminée.")
