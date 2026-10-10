"""Intégration macOS : application « Jarvis Junior.app » avec icône, raccourci sur le bureau,
et service de fond (LaunchAgent) qui démarre à l'ouverture de session."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import app_dir

APP_NAME = "Jarvis Junior"
BUNDLE_ID = "fr.jarvis.junior"
AGENT_LABEL = "fr.jarvis.junior.daemon"
ICON = Path(__file__).parent / "assets" / "icon.png"


def build_icns(dest: Path) -> None:
    """Convertit icon.png en .icns avec les outils intégrés à macOS (sips, iconutil)."""
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(px), str(px), str(ICON), "--out", str(iconset / name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


def build_app(apps_dir: Path | None = None, python: str | None = None) -> Path:
    apps_dir = apps_dir or Path.home() / "Applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    app = apps_dir / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    python = python or sys.executable

    with (app / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump({
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleVersion": "1.0",
            "CFBundleShortVersionString": "1.0",
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": "JarvisJunior",
            "CFBundleIconFile": "icon",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "Jarvis Junior écoute l'enfant pour l'aider à faire ses devoirs.",
            "NSCameraUsageDescription": "Jarvis Junior peut regarder le cahier pour vérifier les exercices.",
            "LSApplicationCategoryType": "public.app-category.education",
        }, f)

    launcher = app / "Contents" / "MacOS" / "JarvisJunior"
    log = app_dir() / "app.log"
    launcher.write_text(f'#!/bin/bash\nexec "{python}" -m junior app >>"{log}" 2>&1\n')
    launcher.chmod(0o755)
    build_icns(app / "Contents" / "Resources" / "icon.icns")
    return app


def desktop_alias(app: Path) -> None:
    """Crée un raccourci (alias Finder) sur le bureau."""
    script = (f'tell application "Finder" to make alias file to (POSIX file "{app}") '
              f'at (path to desktop folder)')
    alias = Path.home() / "Desktop" / APP_NAME
    if alias.exists() or alias.is_symlink():
        alias.unlink()
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def install_daemon(python: str | None = None) -> Path:
    """Installe et démarre la synchronisation avec l'espace parents (relancée automatiquement, même après redémarrage)."""
    python = python or sys.executable
    plist = Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    with plist.open("wb") as f:
        plistlib.dump({
            "Label": AGENT_LABEL,
            "ProgramArguments": [python, "-m", "junior", "daemon"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 30,
            "StandardOutPath": str(app_dir() / "daemon.log"),
            "StandardErrorPath": str(app_dir() / "daemon.log"),
        }, f)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    return plist


def uninstall() -> None:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
    plist.unlink(missing_ok=True)
    for p in (Path.home() / "Applications" / f"{APP_NAME}.app",):
        if p.exists():
            shutil.rmtree(p)
    alias = Path.home() / "Desktop" / APP_NAME
    if alias.exists():
        alias.unlink()
