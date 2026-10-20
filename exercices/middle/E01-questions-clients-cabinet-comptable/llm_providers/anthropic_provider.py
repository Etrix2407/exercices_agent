"""Adaptateur pour l'API Claude (SDK anthropic)."""

from __future__ import annotations

import logging

import anthropic

from llm_providers.base import LLMConfigError, LLMError, LLMQuotaError

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
        fallback_options = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if self.model in FALLBACK_MODELS else {}
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                # Le prompt système et la FAQ sont identiques pour chaque question : on les met en cache.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                **fallback_options,
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

        if response.stop_reason == "refusal":
            raise LLMError("Le modèle a refusé de répondre.")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise LLMError("Réponse vide du modèle.")
        return text
