#!/bin/bash
# Installation de Jarvis Junior sur Mac (puce Apple).
#   1. Ouvrez le Terminal, allez dans le dossier du projet, puis lancez :  ./install_mac.sh
set -euo pipefail

APP_HOME="$HOME/Library/Application Support/JarvisJunior"
VENV="$APP_HOME/venv"
cd "$(dirname "$0")"

echo "=== Installation de Jarvis Junior ==="

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Ce script est prévu pour macOS."; exit 1
fi

# Python 3.11+ (Homebrew recommandé)
PY=""
for candidate in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$(command -v "$candidate")"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "Python 3.11 ou plus est nécessaire."
  echo "Installez Homebrew (https://brew.sh) puis :  brew install python@3.12"
  exit 1
fi
echo "✓ Python : $PY"

mkdir -p "$APP_HOME"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
echo "… installation des composants (quelques minutes la première fois)"
"$VENV/bin/pip" install ".[junior]"
echo "✓ Composants installés"

echo "… téléchargement du modèle de reconnaissance vocale (≈ 1,5 Go, une seule fois)"
"$VENV/bin/python" - <<'EOF' || echo "  (le modèle sera téléchargé au premier lancement)"
from huggingface_hub import snapshot_download
from junior.config import Config
snapshot_download(Config.load().whisper_model)
EOF

"$VENV/bin/python" -m junior setup
"$VENV/bin/python" -m junior install

echo
echo "🎉 C'est prêt ! L'icône « Jarvis Junior » est sur le bureau."
echo "   Au premier lancement, autorisez l'accès au micro."
echo "   Sur vos téléphones : ouvrez l'adresse de l'espace parents et ajoutez-le à l'écran d'accueil."
