"""Point d'entrée : `jarvis` (clavier), `jarvis voice` (voix), `jarvis telegram` (téléphone)."""

from __future__ import annotations

import argparse
import sys

import anthropic

from .brain import Jarvis
from .config import Config, data_dir
from .scheduler import ReminderScheduler
from .store import Store
from .tools import desktop_notify

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝   propulsé par Claude
"""

CYAN, DIM, YELLOW, RESET = "\033[36m", "\033[2m", "\033[33m", "\033[0m"


def console_approver(description: str) -> bool:
    answer = input(f"{YELLOW}⚠️  {description}\n   Autoriser ? [o/N] {RESET}").strip().lower()
    return answer in {"o", "oui", "y", "yes"}


def safe_ask(jarvis: Jarvis, text: str) -> str:
    try:
        return jarvis.ask(text)
    except anthropic.AuthenticationError:
        return "Clé API invalide : définissez ANTHROPIC_API_KEY (https://console.anthropic.com)."
    except anthropic.RateLimitError:
        return "Limite de débit atteinte, réessayez dans un instant."
    except anthropic.APIConnectionError:
        return "Impossible de joindre les serveurs de Claude. Vérifiez la connexion."
    except anthropic.APIStatusError as exc:
        return f"Erreur de l'API ({exc.status_code}) : {exc.message}"


def handle_command(jarvis: Jarvis, text: str) -> str | None:
    cmd = text.strip().lower()
    if cmd in {"/reset", "/nouveau"}:
        jarvis.reset()
        return "Nouvelle conversation. Je vous écoute."
    if cmd in {"/aide", "/help"}:
        return ("Commandes : /reset (nouvelle conversation), /aide, /quitter. "
                "Sinon, demandez simplement ce que vous voulez.")
    return None


def run_chat(cfg: Config, store: Store) -> None:
    print(CYAN + BANNER + RESET)
    jarvis = Jarvis(cfg, store, console_approver, on_text=lambda t: print(f"{DIM}{t}{RESET}"))
    ReminderScheduler(store, lambda m: (print(f"\n🔔 {CYAN}Rappel : {m}{RESET}"),
                                        desktop_notify("Rappel Jarvis", m))).start()
    print(f"À votre service, {cfg.user_name}. (/aide pour les commandes)\n")
    while True:
        try:
            text = input(f"{CYAN}vous ›{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAu revoir.")
            return
        if not text:
            continue
        if text.lower() in {"/quitter", "/exit", "exit", "quit"}:
            print("Au revoir.")
            return
        reply = handle_command(jarvis, text) or safe_ask(jarvis, text)
        print(f"{CYAN}jarvis ›{RESET} {reply}\n")


def run_voice(cfg: Config, store: Store, always_listen: bool) -> None:
    from .voice import Voice, strip_wake_word

    voice = Voice(cfg.language, cfg.tts)

    def approve(description: str) -> bool:
        voice.say("Je dois confirmer une action.")
        print(f"{YELLOW}⚠️  {description}{RESET}")
        voice.say("Dites oui pour autoriser.")
        heard = (voice.listen(timeout=8) or "").lower()
        print(f"{DIM}(entendu : {heard}){RESET}")
        return any(w in heard.split() for w in ("oui", "ok", "vas-y", "autorise", "confirme"))

    jarvis = Jarvis(cfg, store, approve, on_text=lambda t: print(f"{DIM}{t}{RESET}"))
    ReminderScheduler(store, lambda m: (desktop_notify("Rappel Jarvis", m),
                                        voice.say(f"{cfg.user_name}, un rappel : {m}"))).start()
    print(CYAN + BANNER + RESET)
    hint = "parlez" if always_listen else f"dites « {cfg.wake_word.capitalize()}, … »"
    print(f"Mode vocal actif — {hint}. Ctrl+C pour quitter.\n")
    voice.say(f"Bonjour {cfg.user_name}. Je suis en ligne.")

    while True:
        try:
            heard = voice.listen()
        except KeyboardInterrupt:
            print("\nAu revoir.")
            return
        if not heard:
            continue
        command = heard if always_listen else strip_wake_word(heard, cfg.wake_word)
        if command is None:
            continue
        if not command:  # « Jarvis » tout seul : on attend la suite
            voice.say("Oui ?")
            command = voice.listen(timeout=6)
            if not command:
                continue
        print(f"{CYAN}vous ›{RESET} {command}")
        reply = safe_ask(jarvis, command)
        print(f"{CYAN}jarvis ›{RESET} {reply}\n")
        voice.say(reply)


def run_telegram(cfg: Config, store: Store) -> None:
    from .telegram import TelegramBot

    bot = TelegramBot(cfg.telegram_token, cfg.telegram_allowed_ids)
    jarvis = Jarvis(cfg, store, bot.approver())
    ReminderScheduler(store, lambda m: (bot.broadcast(f"🔔 Rappel : {m}"),
                                        desktop_notify("Rappel Jarvis", m))).start()
    if not cfg.telegram_allowed_ids:
        print("⚠️  telegram_allowed_ids est vide : envoyez un message au bot pour connaître votre id, "
              "puis ajoutez-le dans la config.")
    print("Bot Telegram actif. Ctrl+C pour arrêter.")
    try:
        for chat_id, text in bot.updates():
            bot.last_chat = chat_id
            print(f"[telegram] {text}")
            if text.strip().lower() == "/start":
                bot.send(chat_id, f"À votre service, {cfg.user_name}. Que puis-je faire ?")
                continue
            bot._api("sendChatAction", chat_id=chat_id, action="typing")
            reply = handle_command(jarvis, text) or safe_ask(jarvis, text)
            bot.send(chat_id, reply)
    except KeyboardInterrupt:
        print("Arrêt du bot.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Assistant personnel propulsé par Claude")
    sub = parser.add_subparsers(dest="mode")
    sub.add_parser("chat", help="conversation au clavier (défaut)")
    v = sub.add_parser("voice", help="mode vocal avec mot d'éveil")
    v.add_argument("--always", action="store_true", help="pas de mot d'éveil : tout est une commande")
    sub.add_parser("telegram", help="pilotage depuis le téléphone via Telegram")
    sub.add_parser("ask", help="une seule question, ex : jarvis ask \"quelle heure est-il\"").add_argument("text", nargs="+")
    sub.add_parser("config", help="affiche l'emplacement de la configuration")
    args = parser.parse_args(argv)

    cfg = Config.load()
    store = Store(data_dir())

    if args.mode == "config":
        print(f"Configuration : {data_dir() / 'config.json'}")
        return
    if args.mode == "voice":
        run_voice(cfg, store, args.always)
    elif args.mode == "telegram":
        run_telegram(cfg, store)
    elif args.mode == "ask":
        jarvis = Jarvis(cfg, store, console_approver if sys.stdin.isatty() else (lambda _: False))
        print(safe_ask(jarvis, " ".join(args.text)))
    else:
        run_chat(cfg, store)


if __name__ == "__main__":
    main()
