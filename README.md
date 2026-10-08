# J.A.R.V.I.S. — votre assistant personnel propulsé par Claude

Jarvis tourne **sur votre ordinateur** et **agit** dessus à votre place : il lance des commandes,
ouvre des applications, gère vos fichiers, prend des captures d'écran pour voir ce que vous voyez,
retient vos préférences, programme des rappels et cherche sur le web. Vous lui parlez **au clavier**,
**à la voix** (« Jarvis, … ») ou **depuis votre téléphone** via Telegram.

```
vous › Jarvis, trouve la facture EDF la plus récente dans mes documents et ouvre-la
jarvis › Je l'ai trouvée : ~/Documents/Factures/edf-2026-09.pdf. Elle est ouverte, Monsieur.

vous › rappelle-moi d'appeler le garage demain à 9h
jarvis › Rappel programmé pour le 09/10/2026 à 09:00.

vous › qu'est-ce qui cloche sur mon écran ?
jarvis › (capture d'écran) Votre terminal affiche « permission denied » : le script n'est pas exécutable…
```

## Architecture

```
 Clavier ─┐                       ┌─ run_shell (avec confirmation)
 Voix ────┼─► jarvis/brain.py ◄──►├─ open (apps, URLs, fichiers)
 Telegram ┘   boucle agentique    ├─ fichiers : list / read / write / find
              Claude (API)        ├─ screenshot (vision), clipboard, notify, system_info
                                  ├─ mémoire long terme (remember / forget)
 jarvis/scheduler.py ─ rappels ──►├─ rappels (add / list / cancel)
                                  └─ recherche web (côté serveur Claude)
```

| Fichier | Rôle |
|---|---|
| `jarvis/brain.py` | Boucle agentique : envoie la demande à Claude, exécute les outils demandés, renvoie les résultats, jusqu'à la réponse finale |
| `jarvis/tools.py` | Tous les outils locaux (ajoutez les vôtres ici) |
| `jarvis/voice.py` | Micro + synthèse vocale + mot d'éveil |
| `jarvis/telegram.py` | Bot Telegram pour piloter le PC depuis le téléphone |
| `jarvis/scheduler.py` | Déclenchement des rappels en tâche de fond |
| `jarvis/store.py` | Mémoire et rappels persistés dans `~/.jarvis/` |

## Installation

Prérequis : Python 3.10+ et une clé API Claude (https://console.anthropic.com → *API Keys*).

```bash
git clone <ce dépôt> jarvis && cd jarvis
python -m venv .venv
# Windows : .venv\Scripts\activate     macOS/Linux : source .venv/bin/activate
pip install -e ".[desktop]"          # + ".[all]" pour la voix
```

Définissez votre clé :

```bash
# macOS / Linux (ajoutez la ligne à ~/.zshrc ou ~/.bashrc)
export ANTHROPIC_API_KEY="sk-ant-..."
# Windows (PowerShell, permanent)
setx ANTHROPIC_API_KEY "sk-ant-..."
```

Pour la voix : sous macOS `brew install portaudio` avant `pip install -e ".[all]"` ;
sous Linux `sudo apt install portaudio19-dev espeak-ng`.

## Utilisation

```bash
jarvis                 # conversation au clavier
jarvis voice           # mode vocal : « Jarvis, ouvre Spotify »
jarvis voice --always  # sans mot d'éveil
jarvis telegram        # pilotage depuis le téléphone
jarvis ask "combien de place reste-t-il sur mon disque ?"
jarvis config          # où se trouve le fichier de configuration
```

Commandes pendant une conversation : `/reset` (nouvelle conversation), `/aide`, `/quitter`.

## Depuis votre téléphone (Telegram)

1. Sur Telegram, parlez à **@BotFather** → `/newbot` → récupérez le **token**.
2. Mettez-le dans `~/.jarvis/config.json` (`"telegram_token"`) ou dans la variable `JARVIS_TELEGRAM_TOKEN`.
3. Lancez `jarvis telegram`, envoyez un message à votre bot : il vous répond avec **votre id**.
4. Ajoutez cet id dans `"telegram_allowed_ids": [123456789]` et relancez.

Votre ordinateur doit rester allumé : c'est lui qui exécute les ordres. Les actions sensibles vous
sont soumises sur Telegram (« oui » / « non ») avant exécution. Les rappels arrivent aussi sur le téléphone.

## Configuration (`~/.jarvis/config.json`)

| Clé | Défaut | Effet |
|---|---|---|
| `user_name` | `"Monsieur"` | Comment Jarvis vous appelle |
| `model` | `"claude-opus-5-5"` | Modèle Claude utilisé |
| `effort` | `"medium"` | `low` = plus rapide et moins cher, `high` = tâches complexes |
| `language` | `"fr-FR"` | Langue de la reconnaissance vocale |
| `wake_word` | `"jarvis"` | Mot d'éveil en mode vocal |
| `auto_approve` | `false` | `true` = plus de confirmation pour le shell et l'écriture de fichiers (déconseillé) |
| `web_search` | `true` | Recherche web |
| `telegram_token`, `telegram_allowed_ids` | — | Voir ci-dessus |
| `tts` | `true` | Réponses lues à voix haute en mode vocal |

## Sécurité

- Jarvis a les mêmes droits que votre compte utilisateur. Les commandes shell et les écritures de
  fichiers demandent **toujours** votre accord, sauf si vous activez `auto_approve`.
- Le bot Telegram ignore tout utilisateur absent de `telegram_allowed_ids`.
- La mémoire et les rappels restent en local dans `~/.jarvis/` ; seuls vos messages et les
  résultats d'outils sont envoyés à l'API Claude.

## Lancer Jarvis au démarrage

- **Windows** : `Win+R` → `shell:startup`, créez un raccourci vers `pythonw -m jarvis telegram`.
- **macOS** : Réglages → Général → Ouverture → ajoutez un script `jarvis telegram`, ou un `launchd` plist.
- **Linux** : un service `systemd --user` avec `ExecStart=/chemin/.venv/bin/jarvis telegram`.

## Ajouter un outil

Dans `jarvis/tools.py`, à l'intérieur de `_register_all` :

```python
@self.add("meteo_locale", "Donne la température de la sonde du salon.", _obj({}))
def meteo_locale() -> str:
    return lire_ma_sonde()
```

Claude découvre l'outil automatiquement et l'utilise quand c'est pertinent. Passez
`dangerous=True` pour exiger une confirmation.

## Tests

```bash
pip install -e ".[dev]" && pytest
```
