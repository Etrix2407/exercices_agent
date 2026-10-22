"""Lecture de la réponse finale d'un agent (statut et machine en JSON)."""

from __future__ import annotations

import json


def parse_answer(answer: str) -> dict:
    """Dernier objet JSON de la réponse finale du modèle (imbrications et accolades dans les textes comprises)."""
    text = answer or ""
    decoder = json.JSONDecoder()
    for start in reversed([position for position, char in enumerate(text) if char == "{"]):
        try:
            data, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "statut" in data:
            return data
    return {}
