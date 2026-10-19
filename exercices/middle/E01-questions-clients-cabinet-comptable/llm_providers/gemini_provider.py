"""Adaptateur pour l'API Gemini (SDK google-genai)."""

from __future__ import annotations

from google import genai
from google.genai import errors, types

from llm_providers.base import LLMError

# Alias qui pointe toujours vers le dernier modèle Flash disponible.
DEFAULT_MODEL = "gemini-flash-latest"
# Le SDK ne réessaie pas par défaut : on réessaie sur saturation (429, 503) et erreurs serveur.
RETRY_OPTIONS = types.HttpRetryOptions(attempts=4, http_status_codes=[429, 500, 502, 503, 504])


class GeminiProvider:
    """Génère les réponses avec un modèle Gemini."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(retry_options=RETRY_OPTIONS))
        self.model = model or DEFAULT_MODEL

    def generate(self, system: str, user: str) -> str:
        """Envoie la question au modèle et renvoie le texte de la réponse."""
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(system_instruction=system),
            )
        except errors.APIError as error:
            raise LLMError(f"Gemini a renvoyé l'erreur {error.code} : {error.message}") from error

        text = (response.text or "").strip()
        if not text:
            raise LLMError("Réponse vide du modèle (bloquée ou interrompue).")
        return text
