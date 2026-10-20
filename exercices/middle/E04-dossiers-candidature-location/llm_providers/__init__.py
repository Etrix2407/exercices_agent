"""Choix du fournisseur de modèle selon les variables d'environnement.

- LLM_PROVIDER : « anthropic » ou « gemini ». Sans valeur, le premier fournisseur dont la clé est présente.
- LLM_MODEL : modèle à utiliser. Sans valeur, le modèle par défaut du fournisseur.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from llm_providers.anthropic_provider import AnthropicProvider
from llm_providers.base import LLMError, LLMProvider
from llm_providers.gemini_provider import GeminiProvider

# Nom du fournisseur -> (variable de la clé, classe). L'ordre fixe la priorité du choix automatique.
PROVIDERS: dict[str, tuple[str, type[AnthropicProvider | GeminiProvider]]] = {
    "anthropic": ("ANTHROPIC_API_KEY", AnthropicProvider),
    "gemini": ("API_KEY_GEMINI", GeminiProvider),
}

__all__ = ["LLMError", "LLMProvider", "get_provider"]


def get_provider(env: Mapping[str, str] | None = None) -> LLMProvider:
    """Instancie le fournisseur demandé, ou le premier dont la clé est disponible."""
    env = os.environ if env is None else env
    requested = env.get("LLM_PROVIDER", "").strip().lower()
    if requested and requested not in PROVIDERS:
        raise LLMError(f"LLM_PROVIDER inconnu : « {requested} ». Valeurs possibles : {', '.join(PROVIDERS)}.")

    candidates = [requested] if requested else list(PROVIDERS)
    for name in candidates:
        key_variable, provider_class = PROVIDERS[name]
        api_key = env.get(key_variable, "").strip()
        if api_key:
            return provider_class(api_key=api_key, model=env.get("LLM_MODEL", "").strip() or None)

    expected = ", ".join(PROVIDERS[name][0] for name in candidates)
    raise LLMError(f"Aucune clé d'API trouvée. Renseigner {expected} dans le fichier .env.")
