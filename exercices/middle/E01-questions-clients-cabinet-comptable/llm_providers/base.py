"""Interface commune à tous les fournisseurs de modèles."""

from __future__ import annotations

from typing import Protocol


class LLMError(Exception):
    """Erreur d'appel au modèle (configuration, réseau, refus, réponse vide)."""


class LLMProvider(Protocol):
    """Fournisseur capable de générer un texte à partir d'un prompt système et d'un message."""

    model: str

    def generate(self, system: str, user: str) -> str:
        """Renvoie la réponse texte du modèle, ou lève LLMError."""
        ...
