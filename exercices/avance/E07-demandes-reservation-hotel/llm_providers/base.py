"""Interface commune à tous les fournisseurs de modèles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(Exception):
    """Erreur d'appel au modèle (configuration, réseau, refus, réponse vide, boucle trop longue)."""


class ToolError(Exception):
    """Erreur « métier » d'un outil : son message est renvoyé au modèle comme résultat en erreur."""


@dataclass(frozen=True)
class ToolSpec:
    """Outil mis à disposition de l'agent, décrit indépendamment du fournisseur."""

    name: str
    description: str
    # Schéma JSON des arguments : {"type": "object", "properties": {...}, "required": [...]}.
    parameters: dict[str, Any]
    # Reçoit les arguments décodés et renvoie toujours un texte ; lève ToolError en cas d'erreur métier.
    handler: Callable[[dict[str, Any]], str]


class LLMProvider(Protocol):
    """Fournisseur capable de générer un texte, avec ou sans outils."""

    model: str

    def generate(self, system: str, user: str) -> str:
        """Renvoie la réponse texte du modèle, ou lève LLMError."""
        ...

    def run_agent(self, system: str, user: str, tools: list[ToolSpec], max_steps: int = 25) -> str:
        """Fait tourner la boucle d'outils jusqu'à la réponse finale texte.

        Lève LLMError si max_steps est dépassé, en cas de refus ou d'erreur d'API.
        """
        ...
