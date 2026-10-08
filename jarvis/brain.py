"""Le cerveau de Jarvis : boucle agentique Claude + exécution des outils."""

from __future__ import annotations

import platform
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

import anthropic

from .config import Config
from .store import Store
from .tools import Toolbox

MAX_STEPS = 25

# Reçoit la description de l'action, renvoie (approuvé, remarque éventuelle de l'utilisateur)
Approver = Callable[[str], "tuple[bool, str]"]
TextSink = Callable[[str], None]


def build_system_prompt(cfg: Config, store: Store, playbooks=None) -> str:
    recipes = playbooks.summary() if playbooks is not None else "(désactivées)"
    memories = "\n".join(f"- [{m['id']}] {m['fact']}" for m in store.memories.all()) or "(rien pour l'instant)"
    return f"""Tu es J.A.R.V.I.S., l'assistant personnel de {cfg.user_name}. Tu tournes directement \
sur son ordinateur ({platform.system()} {platform.release()}, dossier perso : {Path.home()}) et tu \
peux agir dessus grâce à tes outils : terminal, fichiers, applications, navigateur, presse-papiers, \
captures d'écran, notifications, mémoire long terme, rappels et recherche web.

Style : réponds en français, avec la courtoisie posée et l'humour discret d'un majordome britannique \
de haute technologie. Sois bref : tes réponses peuvent être lues à voix haute, donc pas de tableaux \
ni de longs blocs de code sauf si on te les demande.

Façon de travailler :
- Quand on te demande de faire quelque chose, fais-le avec tes outils plutôt que d'expliquer comment le faire.
- Enchaîne plusieurs outils si nécessaire, puis rends compte du résultat en une ou deux phrases.
- Les commandes shell et écritures de fichiers sont soumises à l'approbation de l'utilisateur ; s'il \
refuse, n'insiste pas et propose une alternative.
- Évite toute action destructrice (suppression massive, formatage, envoi d'argent…) sans demande explicite.
- Quand tu apprends une information durable sur l'utilisateur (préférences, proches, habitudes), \
mémorise-la avec `remember`.
- Chaque message de l'utilisateur commence par la date et l'heure locales entre crochets ; \
utilise-les pour les rappels et les questions de temps.
- L'utilisateur te parle souvent à la voix : la transcription peut contenir des fautes ou des noms \
mal reconnus ; interprète intelligemment et, en cas de doute réel, demande une précision courte.

Grosses tâches (site internet, application, dossier, étude…) :
1. Repère les recettes pertinentes (les instructions que l'utilisateur a préparées pour ce type de \
tâche) et lis-les avec `read_playbook`. Si l'utilisateur en nomme une (« utilise la recette site SEO »), \
utilise-la.
2. Rassemble les infos nécessaires : ce qu'il t'a dit, ta mémoire, une recherche web sur l'entreprise. \
Ne pose une question que si une info indispensable manque vraiment.
3. Appelle `start_project` avec un cahier des charges complet : l'utilisateur valide ou corrige à la voix.
4. Ensuite tout se fait en autonomie ; donne l'avancement avec `project_status` quand on te le demande.
Quand l'utilisateur te dicte des consignes à garder pour la suite (« retiens pour les sites : … »), \
enregistre-les dans une recette avec `save_playbook`.

Recettes disponibles :
{recipes}

Ce que tu sais déjà de {cfg.user_name} :
{memories}"""


class Jarvis:
    def __init__(self, cfg: Config, store: Store, approver: Approver, on_text: TextSink | None = None,
                 playbooks=None, projects=None):
        self.cfg = cfg
        self.store = store
        self.playbooks = playbooks
        self.toolbox = Toolbox(store, playbooks, projects)
        self.approver = approver
        self.on_text = on_text
        self.client = anthropic.Anthropic()
        self.messages: list[dict] = []
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Nouvelle conversation (recharge aussi la mémoire dans le prompt système)."""
        self.messages = []
        self.system = build_system_prompt(self.cfg, self.store, self.playbooks)
        self.tools = self.toolbox.definitions()
        if self.cfg.web_search:
            self.tools.append({"type": "web_search_20260209", "name": "web_search"})

    # ------------------------------------------------------------------ API
    def ask(self, text: str) -> str:
        """Envoie une demande et laisse Claude agir jusqu'à ce qu'il ait fini. Renvoie la réponse finale."""
        with self._lock:
            stamp = datetime.now().strftime("%A %d/%m/%Y %H:%M")
            self._append_user([{"type": "text", "text": f"[{stamp}] {text}"}])

            for _ in range(MAX_STEPS):
                response = self._call()
                # On renvoie toujours le contenu complet (blocs de réflexion compris), sans le modifier.
                self.messages.append({"role": "assistant", "content": response.content})
                texts = [b.text for b in response.content if b.type == "text" and b.text.strip()]

                if response.stop_reason == "pause_turn":
                    continue  # outil serveur (recherche web) en cours : on relance tel quel
                if response.stop_reason == "tool_use":
                    if texts and self.on_text:
                        self.on_text(" ".join(texts))
                    self._append_user(self._run_tools(response.content))
                    continue
                if response.stop_reason == "refusal":
                    return "Je crains de ne pas pouvoir donner suite à cette demande."
                if response.stop_reason == "max_tokens":
                    return " ".join(texts) + " … (réponse tronquée)"
                return " ".join(texts) or "C'est fait."

            return "J'ai atteint ma limite d'étapes pour cette demande ; dites-moi si je dois continuer."

    def _call(self):
        return self.client.beta.messages.create(
            model=self.cfg.model,
            max_tokens=16000,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self.cfg.effort},
            cache_control={"type": "ephemeral"},
            # En cas de refus d'un classifieur, l'API rejoue la requête sur un modèle de repli.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def _append_user(self, blocks: list[dict]) -> None:
        # L'historique reste en ajout seul : on fusionne seulement si le dernier message est déjà « user ».
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"].extend(blocks)
        else:
            self.messages.append({"role": "user", "content": blocks})

    def _run_tools(self, content) -> list[dict]:
        results = []
        for block in content:
            if block.type != "tool_use":
                continue
            args = block.input if isinstance(block.input, dict) else {}
            tool = self.toolbox.tools.get(block.name)
            remark = ""
            try:
                if tool and tool.dangerous and not self.cfg.auto_approve:
                    approved, remark = self.approver(self.toolbox.describe_call(block.name, args))
                    if not approved:
                        msg = "L'utilisateur a refusé cette action."
                        if remark:
                            msg += f" Il a dit : « {remark} ». Tiens-en compte (corrige puis repropose si besoin)."
                        results.append(_result(block.id, msg, error=True))
                        continue
                if remark and block.name == "start_project":
                    args = {**args, "brief": f"{args.get('brief', '')}\n\nPrécision donnée à la validation : {remark}"}
                output = self.toolbox.run(block.name, args)
                output = output if isinstance(output, list) else str(output)
                if remark and isinstance(output, str):
                    output += f"\n(Remarque de l'utilisateur en validant : « {remark} »)"
                results.append(_result(block.id, output))
            except Exception as exc:  # noqa: BLE001 - l'erreur est renvoyée à Claude
                results.append(_result(block.id, f"Erreur : {type(exc).__name__}: {exc}", error=True))
        return results


def _result(tool_use_id: str, content, error: bool = False) -> dict:
    result = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if error:
        result["is_error"] = True
    return result
