"""Accès à Claude : client et paramètres communs."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import anthropic

from .config import get_secret

FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


def client() -> anthropic.Anthropic:
    key = get_secret("anthropic")
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def image_block(path: str | Path) -> dict:
    path = Path(path)
    media = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    if media not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        media = "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def text_of(response) -> str:
    return " ".join(b.text for b in response.content if b.type == "text" and b.text.strip())


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def validate(schema: dict, args: dict) -> str | None:
    """Vérifie une entrée d'outil (nécessaire avec eager_input_streaming, où l'API ne valide plus)."""
    if not isinstance(args, dict):
        return "entrée non valide"
    for key in schema.get("required", []):
        if key not in args:
            return f"paramètre manquant « {key} »"
    types = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
    for key, value in args.items():
        spec = schema["properties"].get(key)
        if spec is None:
            return f"paramètre inconnu « {key} »"
        expected = types.get(spec.get("type"))
        if expected and not isinstance(value, expected):
            return f"« {key} » doit être de type {spec['type']}"
        if "enum" in spec and value not in spec["enum"]:
            return f"« {key} » doit valoir l'une de ces valeurs : {', '.join(spec['enum'])}"
    return None
