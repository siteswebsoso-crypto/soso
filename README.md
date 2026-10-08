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

vous › Jarvis, crée le site de la boulangerie Dupont à Lyon 3 avec la recette site SEO
jarvis › Je vais lancer en autonomie le projet « Site Boulangerie Dupont » (recette : site-vitrine-seo). Je lance ?
vous › oui, mais ajoute une page pour les gâteaux sur commande
jarvis › C'est parti. Je vous préviens quand il est prêt.
   … 20 minutes plus tard …
jarvis › Monsieur, le projet Site Boulangerie Dupont est terminé : 7 pages, Lighthouse 98, dans ~/JarvisProjets/…

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
| `jarvis/playbooks.py` | Recettes : vos instructions réutilisables (`~/.jarvis/playbooks/*.md`) |
| `jarvis/projects.py` | Projets autonomes en arrière-plan (moteur Claude Code ou agent intégré) |
| `jarvis/channels.py` | Questions/validations des projets par la voix, le clavier ou Telegram |
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
jarvis recette site-seo consignes.md   # importer une recette (fichier ou URL)
jarvis config          # où se trouvent la configuration et les recettes
```

Commandes pendant une conversation : `/reset` (nouvelle conversation), `/recettes`, `/projets`, `/aide`, `/quitter`.

## Tout à la voix : ordres, consignes, validations

`jarvis voice` puis parlez naturellement :

- **Réveil** : « Jarvis, … ». Après sa réponse, Jarvis écoute encore quelques secondes : vous pouvez
  enchaîner sans répéter « Jarvis ». « Merci Jarvis » ou « c'est tout » clôt l'échange.
- **Validation** : avant toute action sensible (commande, écriture de fichier, lancement d'un projet),
  Jarvis annonce ce qu'il va faire et attend votre réponse :
  - « oui » / « vas-y » → il exécute ;
  - « oui, mais ajoute un blog » → il exécute en tenant compte de la précision ;
  - « non, mets plutôt du bleu » → il annule, corrige selon votre remarque et repropose.
- **Questions des projets** : un projet en cours peut vous poser une question (« Je mets en ligne ? ») ;
  répondez directement, sans « Jarvis ».

## Recettes : vos instructions réutilisables

Une recette est un fichier Markdown qui décrit **comment** faire un type de tâche (exemple fourni :
`site-vitrine-seo`, un site vitrine full SEO). Quand vous dites « Jarvis, crée un site pour… », il
retrouve la bonne recette, l'applique et la transmet à l'agent qui fait le travail.

Créer ou compléter une recette :

- **À la voix** : « Jarvis, crée une recette *post LinkedIn* : ton professionnel, 3 hashtags, une
  question à la fin » ou « Jarvis, ajoute à la recette site SEO : toujours une page FAQ ».
- **Depuis un fichier ou un lien public** : `jarvis recette site-seo mes-consignes.md`
  (ou une URL : Google Docs partagé « tous les utilisateurs disposant du lien », GitHub, page web).
- **À la main** : éditez `~/.jarvis/playbooks/*.md` (`jarvis config` affiche le chemin).

> **Vos consignes sont dans une conversation ou un artefact claude.ai ?** Jarvis passe par l'API
> Claude, qui n'a pas accès à votre historique claude.ai (vos conversations et artefacts y sont
> privés). Copiez le contenu dans une recette (fichier `.md`), ou partagez-le par un lien public
> et importez-le avec `jarvis recette <nom> <lien>`. Une fois importées, les consignes servent à
> chaque projet.

## Projets autonomes

Pour une grosse tâche, Jarvis :

1. lit les recettes concernées et rassemble les infos (ce que vous avez dit, sa mémoire,
   recherche web sur l'entreprise) ;
2. vous annonce le projet et attend votre **validation vocale** ;
3. crée `~/JarvisProjets/<nom-du-projet>/` avec un cahier des charges `JARVIS_BRIEF.md`
   (votre demande et les recettes complètes) ;
4. lance un agent **en arrière-plan** qui réalise tout, vérifie son travail et vous prévient à la fin
   (voix, notification, Telegram). Vous pouvez continuer à utiliser Jarvis pendant ce temps.

« Jarvis, où en est le site Dupont ? » → avancement. « Jarvis, arrête le projet Dupont » → arrêt.

**Deux moteurs** (`worker_engine` dans la config, `auto` par défaut) :

| Moteur | Quand | Détails |
|---|---|---|
| `claude-code` | Si la commande `claude` est installée (`npm install -g @anthropic-ai/claude-code`) | Le meilleur pour coder des sites et des applications. Lancé en mode non interactif dans le dossier du projet. Par défaut il peut modifier les fichiers et lancer les commandes de développement courantes (npm, git, python…) ; `claude_code_permission_mode` permet d'élargir |
| `builtin` | Sinon | Agent Claude intégré : terminal et fichiers **confinés au dossier du projet**, recherche et lecture web, questions à l'utilisateur |

Par sécurité, la mise en ligne, les achats et les envois restent soumis à votre validation (c'est écrit dans
les règles de l'agent et dans la recette d'exemple).

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
| `follow_up_seconds` | `8` | Durée d'écoute de la suite après une réponse vocale (0 = toujours redire « Jarvis ») |
| `projects_dir` | `"~/JarvisProjets"` | Où sont créés les projets |
| `worker_engine` | `"auto"` | `auto`, `claude-code` ou `builtin` |
| `worker_effort` | `"high"` | Niveau de réflexion de l'agent de projet |
| `worker_max_steps` | `150` | Nombre max d'étapes du moteur intégré |
| `claude_code_permission_mode` | `"acceptEdits"` | `acceptEdits` (commandes de dev courantes), `auto` ou `bypassPermissions` (tout autorisé, à vos risques) |

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
