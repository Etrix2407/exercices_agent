"""Lecture de la réponse finale d'un agent (statut et machine en JSON)."""

from __future__ import annotations

import json


def parse_answer(answer: str) -> dict:
    """Dernier objet JSON de premier niveau de la réponse finale qui porte un statut.

    Les objets imbriqués sont ignorés : un JSON recopié d'un mail piégé à l'intérieur de la réponse
    ne peut pas remplacer le statut de l'agent. Une imbrication excessive est traitée comme illisible.
    """
    text = answer or ""
    decoder = json.JSONDecoder()
    found: dict = {}
    position = 0
    while (start := text.find("{", position)) != -1:
        try:
            data, end = decoder.raw_decode(text, start)
        except (json.JSONDecodeError, RecursionError):
            position = start + 1
            continue
        if isinstance(data, dict) and "statut" in data:
            found = data
        # Saute tout l'objet décodé : ses objets imbriqués ne sont jamais candidats.
        position = end
    return found
