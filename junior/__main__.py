"""Jarvis Junior — l'instit vocal des devoirs.

    python -m junior app        l'application des enfants (par défaut)
    python -m junior daemon     le service Telegram (photos de devoirs, rapports, consignes)
    python -m junior setup      configuration (clés, parents, codes, voix)
    python -m junior install    crée l'app avec son icône sur le bureau + démarrage auto du service
    python -m junior uninstall  retire l'app et le service
"""

from __future__ import annotations

import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "app"
    if cmd == "app":
        from .app import main as run
        run()
    elif cmd == "daemon":
        from .daemon import main as run
        run()
    elif cmd == "setup":
        from .setup_wizard import run
        run()
    elif cmd == "install":
        from .macos import build_app, desktop_alias, install_daemon
        app = build_app()
        desktop_alias(app)
        print(f"✓ Application : {app} (raccourci sur le bureau)")
        print(f"✓ Service de fond : {install_daemon()}")
    elif cmd == "uninstall":
        from .macos import uninstall
        uninstall()
        print("✓ Application et service retirés (vos données restent dans ~/Library/Application Support/JarvisJunior).")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
