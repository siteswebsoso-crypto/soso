"""Lecture des devoirs à partir d'une photo (cahier de textes, Pronote, ENT…)."""

from __future__ import annotations

import json
from datetime import date

from .config import Config
from .data import WEEKDAYS, Store
from .llm import FALLBACK, image_block

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Matière, ex : Mathématiques, Français, Anglais"},
        "task": {"type": "string", "description": "Consigne précise, avec pages et numéros d'exercices"},
        "due": {"type": "string", "description": "Date de rendu AAAA-MM-JJ, ou chaîne vide si inconnue"},
        "minutes": {"type": "integer", "description": "Durée estimée pour un élève de ce niveau"},
        "kind": {"type": "string", "enum": ["exercice", "leçon", "récitation", "lecture", "rédaction",
                                             "révision contrôle", "autre"]},
    },
    "required": ["subject", "task", "due", "minutes", "kind"],
    "additionalProperties": False,
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "child": {"type": "string", "description": "Identifiant de l'enfant concerné, ou 'inconnu'"},
        "confidence": {"type": "string", "enum": ["sûr", "probable", "incertain"]},
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "remarks": {"type": "string", "description": "Ce qui est illisible ou ambigu, sinon chaîne vide"},
    },
    "required": ["child", "confidence", "items", "remarks"],
    "additionalProperties": False,
}


def extract_homework(client, cfg: Config, image_paths: list[str], caption: str = "",
                     today: date | None = None) -> dict:
    """Analyse une ou plusieurs photos et renvoie {child, confidence, items, remarks}."""
    today = today or date.today()
    children = "\n".join(f"- id « {c.id} » : {c.name}, classe de {c.level}" for c in cfg.children)
    prompt = f"""Voici une ou plusieurs photos des devoirs d'un enfant (cahier de textes, agenda, \
Pronote, ENT, fiche de la maîtresse…). Nous sommes le {WEEKDAYS[today.weekday()]} {today:%d/%m/%Y}.

Enfants de la famille :
{children}

Légende écrite par le parent : « {caption or 'aucune'} »

1. Détermine l'enfant concerné : d'abord d'après la légende ; sinon d'après le niveau des devoirs \
(programme de CM2 ou de collège, nom de professeur, format Pronote…). Si tu ne peux pas trancher, \
mets « inconnu ».
2. Liste chaque devoir séparément, avec la consigne exacte (pages, numéros d'exercices, titre de la \
poésie…). Convertis les dates relatives (« pour jeudi ») en dates AAAA-MM-JJ à venir.
3. Estime une durée réaliste pour un enfant de ce niveau qui travaille sérieusement.
4. Ignore ce qui est déjà barré ou coché comme fait."""
    content = [image_block(p) for p in image_paths] + [{"type": "text", "text": prompt}]
    response = client.beta.messages.create(
        model=cfg.model, max_tokens=8000, messages=[{"role": "user", "content": content}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        **FALLBACK,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude n'a pas pu analyser cette image.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def save_extraction(store: Store, cfg: Config, result: dict, photo: str | None) -> list[dict]:
    child = cfg.child(result["child"])
    if not child:
        return []
    return [store.add_homework(child.id, i["subject"], i["task"], _date_or_none(i["due"]), i["minutes"],
                               i["kind"], photo)
            for i in result["items"]]


def _date_or_none(value: str | None) -> str | None:
    try:
        return date.fromisoformat(value).isoformat() if value else None
    except ValueError:
        return None
