"""Point d'entrée : `jarvis` (clavier), `jarvis voice` (voix), `jarvis telegram` (téléphone)."""

from __future__ import annotations

import argparse
import sys
import threading

import anthropic

from .brain import Jarvis
from .channels import Channel, parse_confirmation
from .config import Config, data_dir
from .playbooks import PlaybookLibrary
from .projects import ProjectManager
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


class App:
    """Assemble mémoire, recettes, projets, rappels et cerveau autour d'un canal de communication."""

    def __init__(self, cfg: Config, channel: Channel, approver, on_text=None):
        root = data_dir()
        self.cfg = cfg
        self.channel = channel
        self.store = Store(root)
        self.playbooks = PlaybookLibrary(root / "playbooks")
        self.projects = ProjectManager(cfg, root, self.playbooks, channel)
        self.jarvis = Jarvis(cfg, self.store, approver, on_text, self.playbooks, self.projects)
        ReminderScheduler(self.store, self._remind).start()
        self._busy = threading.Lock()

    def _remind(self, message: str) -> None:
        desktop_notify("Rappel Jarvis", message)
        self.channel.say(f"🔔 Rappel : {message}")

    def handle(self, text: str) -> str | None:
        """Traite une entrée utilisateur. None = c'était la réponse à une question d'un projet."""
        if self.channel.deliver(text):
            return None
        cmd = text.strip().lower()
        if cmd in {"/reset", "/nouveau"}:
            self.jarvis.reset()
            return "Nouvelle conversation. Je vous écoute."
        if cmd in {"/aide", "/help"}:
            return ("Commandes : /reset (nouvelle conversation), /recettes, /projets, /quitter. "
                    "Sinon, demandez simplement ce que vous voulez.")
        if cmd == "/recettes":
            return self.playbooks.summary()
        if cmd == "/projets":
            return "\n".join(p.status_text(last=2) for p in self.projects.all()) or "Aucun projet."
        with self._busy:
            return safe_ask(self.jarvis, text)


def safe_ask(jarvis: Jarvis, text: str) -> str:
    try:
        return jarvis.ask(text)
    except anthropic.AuthenticationError:
        return "Clé API invalide : définissez ANTHROPIC_API_KEY (https://console.anthropic.com)."
    except TypeError as exc:
        if "authentication" not in str(exc):
            raise
        return "Aucune clé API : définissez ANTHROPIC_API_KEY (https://console.anthropic.com)."
    except anthropic.RateLimitError:
        return "Limite de débit atteinte, réessayez dans un instant."
    except anthropic.APIConnectionError:
        return "Impossible de joindre les serveurs de Claude. Vérifiez la connexion."
    except anthropic.APIStatusError as exc:
        return f"Erreur de l'API ({exc.status_code}) : {exc.message}"


# ---------------------------------------------------------------------- clavier

def run_chat(cfg: Config) -> None:
    def console_approver(description: str) -> tuple[bool, str]:
        answer = input(f"{YELLOW}⚠️  {description}\n   Autoriser ? (oui / non / « non, mais … ») {RESET}")
        return parse_confirmation(answer)

    channel = Channel(lambda t: print(f"\n{CYAN}jarvis ›{RESET} {t}\n{CYAN}vous ›{RESET} ", end="", flush=True))
    app = App(cfg, channel, console_approver, on_text=lambda t: print(f"{DIM}{t}{RESET}"))
    print(CYAN + BANNER + RESET)
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
        reply = app.handle(text)
        if reply:
            print(f"{CYAN}jarvis ›{RESET} {reply}\n")


# ---------------------------------------------------------------------- voix

def run_voice(cfg: Config, always_listen: bool) -> None:
    from .voice import Voice, is_dismissal, strip_wake_word

    voice = Voice(cfg.language, cfg.tts)

    def show_and_say(text: str) -> None:
        print(f"{CYAN}jarvis ›{RESET} {text}")
        voice.say(text, wait=False)

    def approve(description: str) -> tuple[bool, str]:
        print(f"{YELLOW}⚠️  {description}{RESET}")
        voice.say(f"Je vais : {description}. Je lance ?")
        for _ in range(2):
            heard = voice.listen(timeout=10)
            print(f"{DIM}(entendu : {heard}){RESET}")
            if heard:
                return parse_confirmation(heard)
            voice.say("Je n'ai pas entendu. Oui ou non ?")
        return False, ""

    channel = Channel(show_and_say)
    app = App(cfg, channel, approve, on_text=lambda t: (print(f"{DIM}{t}{RESET}"), voice.say(t)))
    print(CYAN + BANNER + RESET)
    hint = "parlez" if always_listen else f"dites « {cfg.wake_word.capitalize()}, … »"
    print(f"Mode vocal actif — {hint}. Ctrl+C pour quitter.\n")
    voice.say(f"Bonjour {cfg.user_name}. Je suis en ligne.")

    def converse(command: str) -> None:
        """Traite une commande puis écoute la suite sans mot d'éveil (conversation naturelle)."""
        while command:
            if is_dismissal(command):
                voice.say("Très bien.")
                return
            print(f"{CYAN}vous ›{RESET} {command}")
            reply = app.handle(command)
            if reply is None:  # c'était une réponse à une question de projet
                voice.say("Bien noté, je transmets.")
                return
            print(f"{CYAN}jarvis ›{RESET} {reply}\n")
            voice.say(reply)
            command = voice.listen(timeout=cfg.follow_up_seconds) if cfg.follow_up_seconds else None

    while True:
        try:
            heard = voice.listen(timeout=5)
            if not heard:
                continue
            if channel.pending:  # un projet attend une réponse : pas besoin du mot d'éveil
                print(f"{CYAN}vous ›{RESET} {heard}")
                channel.deliver(heard)
                voice.say("Bien noté.")
                continue
            command = heard if always_listen else strip_wake_word(heard, cfg.wake_word)
            if command is None:
                continue
            if not command:  # « Jarvis » tout seul : on attend la suite
                voice.say("Oui ?")
                command = voice.listen(timeout=8)
            if command:
                converse(command)
        except KeyboardInterrupt:
            print("\nAu revoir.")
            return


# ---------------------------------------------------------------------- Telegram

def run_telegram(cfg: Config) -> None:
    from .telegram import TelegramBot

    bot = TelegramBot(cfg.telegram_token, cfg.telegram_allowed_ids)
    channel = Channel(bot.broadcast)
    app = App(cfg, channel, bot.approver())
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
            reply = app.handle(text)
            bot.send(chat_id, reply or "Bien noté, je transmets au projet.")
    except KeyboardInterrupt:
        print("Arrêt du bot.")


# ---------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Assistant personnel propulsé par Claude")
    sub = parser.add_subparsers(dest="mode")
    sub.add_parser("chat", help="conversation au clavier (défaut)")
    v = sub.add_parser("voice", help="mode vocal avec mot d'éveil")
    v.add_argument("--always", action="store_true", help="pas de mot d'éveil : tout est une commande")
    sub.add_parser("telegram", help="pilotage depuis le téléphone via Telegram")
    sub.add_parser("ask", help="une seule demande, ex : jarvis ask \"quelle heure est-il\"").add_argument("text", nargs="+")
    pb = sub.add_parser("recette", help="importer une recette : jarvis recette site-seo fichier.md|URL")
    pb.add_argument("name")
    pb.add_argument("source")
    sub.add_parser("config", help="affiche l'emplacement de la configuration")
    args = parser.parse_args(argv)

    cfg = Config.load()

    if args.mode == "config":
        print(f"Configuration : {data_dir() / 'config.json'}\nRecettes : {data_dir() / 'playbooks'}")
    elif args.mode == "recette":
        saved = PlaybookLibrary(data_dir() / "playbooks").import_from(args.name, args.source)
        print(f"Recette « {saved} » enregistrée dans {data_dir() / 'playbooks'}.")
    elif args.mode == "voice":
        run_voice(cfg, args.always)
    elif args.mode == "telegram":
        run_telegram(cfg)
    elif args.mode == "ask":
        interactive = sys.stdin.isatty()
        approver = (lambda d: parse_confirmation(input(f"⚠️  {d}\nAutoriser ? "))) if interactive \
            else (lambda _: (False, ""))
        app = App(cfg, Channel(print), approver)
        print(app.handle(" ".join(args.text)))
        for project in list(app.projects.running.values()):  # ne pas tuer un projet lancé
            print(f"Projet « {project.data['name']} » en cours… (Ctrl+C pour le laisser en plan)")
            while project.data["id"] in app.projects.running:
                threading.Event().wait(2)
    else:
        run_chat(cfg)


if __name__ == "__main__":
    main()
