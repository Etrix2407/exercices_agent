"""Adaptateur pour l'API Claude (SDK anthropic)."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from agent.llm_providers.base import (
    LLMConfigError,
    LLMError,
    LLMQuotaError,
    ToolError,
    ToolSpec,
)

DEFAULT_MODEL = "claude-opus-5-5"
# Modèles qui acceptent le repli automatique côté serveur en cas de refus.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Génère les réponses avec un modèle Claude."""

    def __init__(self, api_key: str, model: str | None = None, temperature: float | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model or DEFAULT_MODEL
        if temperature is not None:
            # Les modèles Claude actuels refusent les paramètres d'échantillonnage (erreur 400).
            logger.warning("Température ignorée : non prise en charge par %s.", self.model)

    def generate(self, system: str, user: str) -> str:
        """Envoie la question au modèle et renvoie le texte de la réponse."""
        response = self._create(system, [{"role": "user", "content": user}])
        return self._final_text(response)

    def run_agent(self, system: str, user: str, tools: list[ToolSpec], max_steps: int = 25) -> str:
        """Fait tourner une boucle d'appels d'outils jusqu'à la réponse finale du modèle."""
        tools_by_name = {tool.name: tool for tool in tools}
        tool_params = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        for step in range(1, max_steps + 1):
            response = self._create(system, messages, tools=tool_params)
            if response.stop_reason != "tool_use":
                return self._final_text(response)
            logger.debug("Étape %d : le modèle demande des outils.", step)
            # Les blocs sont renvoyés tels quels (les blocs de réflexion doivent être retransmis).
            messages.append({"role": "assistant", "content": response.content})
            results = [_run_tool(block, tools_by_name) for block in response.content if block.type == "tool_use"]
            # Tous les résultats partent dans un seul message utilisateur.
            messages.append({"role": "user", "content": results})
        raise LLMError(f"Nombre maximal d'étapes atteint (max_steps={max_steps}) sans réponse finale du modèle.")

    def _create(self, system: str, messages: list[dict[str, Any]], **extra: Any) -> Any:
        """Appelle l'API Messages avec les options communes et convertit les erreurs en LLMError."""
        fallback_options = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if self.model in FALLBACK_MODELS else {}
        try:
            return self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                # Le prompt système est identique pour chaque appel : on le met en cache.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                **fallback_options,
                **extra,
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as error:
            raise LLMConfigError(
                f"Configuration refusée par Anthropic ({error.status_code}) : {error.message}. "
                "Vérifier ANTHROPIC_API_KEY et LLM_MODEL."
            ) from error
        except anthropic.RateLimitError as error:
            # Le SDK a déjà réessayé : la limite persiste, inutile de continuer le lot.
            raise LLMQuotaError(f"Limite d'utilisation Anthropic atteinte : {error.message}") from error
        except anthropic.APIStatusError as error:
            raise LLMError(f"Anthropic a renvoyé l'erreur {error.status_code} : {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise LLMError(f"Connexion à Anthropic impossible : {error}") from error

    @staticmethod
    def _final_text(response: Any) -> str:
        """Extrait le texte de la réponse finale, ou lève LLMError en cas de refus ou de réponse vide."""
        if response.stop_reason == "refusal":
            raise LLMError("Le modèle a refusé de répondre.")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise LLMError("Réponse vide du modèle.")
        return text


def _run_tool(block: Any, tools_by_name: dict[str, ToolSpec]) -> dict[str, Any]:
    """Exécute un appel d'outil et renvoie le bloc tool_result correspondant."""
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id}
    tool = tools_by_name.get(block.name)
    if tool is None:
        return result | {"content": f"Outil inconnu : « {block.name} ».", "is_error": True}
    try:
        return result | {"content": tool.handler(dict(block.input))}
    except ToolError as error:
        logger.debug("L'outil %s a renvoyé une erreur : %s", block.name, error)
        return result | {"content": str(error), "is_error": True}
