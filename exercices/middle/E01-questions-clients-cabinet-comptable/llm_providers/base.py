"""Interface commune à tous les fournisseurs de modèles."""

from __future__ import annotations

from typing import Protocol


class LLMError(Exception):
    """Erreur d'appel au modèle (configuration, réseau, refus, réponse vide)."""


class LLMBatchError(LLMError):
    """Erreur qui touchera toutes les questions suivantes : le lot doit s'arrêter tout de suite."""


class LLMQuotaError(LLMBatchError):
    """Quota de l'API épuisé malgré les réessais."""


class LLMConfigError(LLMBatchError):
    """Configuration refusée par l'API : modèle introuvable, clé invalide ou sans droits."""


class LLMProvider(Protocol):
    """Fournisseur capable de générer un texte à partir d'un prompt système et d'un message."""

    model: str

    def generate(self, system: str, user: str) -> str:
        """Renvoie la réponse texte du modèle, ou lève LLMError."""
        ...
