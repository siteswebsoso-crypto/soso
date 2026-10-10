"""Rapport de fin de séance, envoyé aux deux parents."""

from __future__ import annotations

from .config import Child, Config, get_secret
from .data import DONE, PARTIAL, Store, now_iso
from .telegram_api import Telegram


def build_report(child: Child, minutes: int, homework: list[dict], summary: str,
                 difficulties: list[str], to_review: list[str], finished: bool) -> str:
    done = [h for h in homework if h["status"] == DONE]
    partial = [h for h in homework if h["status"] == PARTIAL]
    todo = [h for h in homework if h["status"] not in (DONE, PARTIAL)]
    if finished and not todo and not partial:
        head = f"✅ {child.name} a terminé ses devoirs ({minutes} min)."
    elif finished:
        head = f"🟡 {child.name} a fini sa séance ({minutes} min), mais tout n'est pas terminé."
    else:
        head = f"⏸️ {child.name} a arrêté la séance en cours de route ({minutes} min)."
    lines = [head, ""]
    for h in done:
        lines.append(f"✔︎ {h['subject']} — {h['task']}" + (f" : {h['comment']}" if h["comment"] else ""))
    for h in partial:
        lines.append(f"◐ {h['subject']} — {h['task']} (en partie" + (f" : {h['comment']}" if h["comment"] else "") + ")")
    for h in todo:
        lines.append(f"✗ {h['subject']} — {h['task']} (pas fait)")
    if summary:
        lines += ["", f"📝 {summary}"]
    if difficulties:
        lines += ["", "⚠️ Difficultés :"] + [f"• {d}" for d in difficulties]
    if to_review:
        lines += ["", "🔁 À renforcer :"] + [f"• {r}" for r in to_review]
    return "\n".join(lines)


def send_report(cfg: Config, store: Store, child: Child, text: str) -> int:
    """Enregistre le rapport et l'envoie aux parents. Renvoie le nombre de parents prévenus."""
    store.reports.add({"child": child.id, "date": now_iso(), "text": text})
    token = get_secret("telegram")
    if not token or not cfg.parent_ids:
        return 0
    tg = Telegram(token)
    sent = 0
    for chat_id in cfg.parent_ids:
        try:
            tg.send(chat_id, f"📚 Rapport de devoirs — {child.name}\n\n{text}")
            sent += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[rapport] envoi à {chat_id} impossible : {exc}")
    return sent
