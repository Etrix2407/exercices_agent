"""Adaptateur pour l'API Gemini (SDK google-genai)."""

from __future__ import annotations

import logging

from google import genai
from google.genai import errors, types

from llm_providers.base import LLMError, ToolError, ToolSpec

DEFAULT_MODEL = "gemini-3.5-flash"
# Le SDK ne réessaie pas par défaut : on réessaie sur saturation (429, 503) et erreurs serveur.
# Le quota gratuit est compté par minute : les attentes (4, 8, 16, 32, 60, 60 s) couvrent une fenêtre entière.
RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=7, initial_delay=4.0, max_delay=60.0, http_status_codes=[429, 500, 502, 503, 504]
)

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Génère les réponses avec un modèle Gemini."""

    def __init__(self, api_key: str, model: str | None = None, temperature: float | None = None) -> None:
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(retry_options=RETRY_OPTIONS))
        self.model = model or DEFAULT_MODEL
        # None : valeur par défaut du modèle.
        self.temperature = temperature

    def generate(self, system: str, user: str) -> str:
        """Envoie la question au modèle et renvoie le texte de la réponse."""
        config = types.GenerateContentConfig(system_instruction=system, temperature=self.temperature)
        response = self._generate(user, config)
        return _final_text(response)

    def run_agent(self, system: str, user: str, tools: list[ToolSpec], max_steps: int = 25) -> str:
        """Fait tourner une boucle d'appels d'outils jusqu'à la réponse finale du modèle."""
        tools_by_name = {tool.name: tool for tool in tools}
        config = _agent_config(system, tools, self.temperature)
        contents: list[types.Content] = [types.Content(role="user", parts=[types.Part.from_text(text=user)])]
        for step in range(1, max_steps + 1):
            response = self._generate(contents, config)
            calls = response.function_calls
            if not calls:
                return _final_text(response)
            logger.debug("Étape %d : le modèle demande %d outil(s).", step, len(calls))
            model_turn = response.candidates[0].content if response.candidates else None
            if model_turn is None:
                raise LLMError("Réponse du modèle sans contenu (bloquée ou filtrée).")
            contents.append(model_turn)
            parts = [_run_tool(call, tools_by_name) for call in calls]
            # Toutes les réponses d'outils partent dans un seul message utilisateur.
            contents.append(types.Content(role="user", parts=parts))
        raise LLMError(f"Nombre maximal d'étapes atteint (max_steps={max_steps}) sans réponse finale du modèle.")

    def _generate(
        self, contents: str | list[types.Content], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        """Appelle generate_content et convertit les erreurs d'API en LLMError."""
        try:
            return self._client.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.APIError as error:
            raise LLMError(f"Gemini a renvoyé l'erreur {error.code} : {error.message}") from error


def _agent_config(system: str, tools: list[ToolSpec], temperature: float | None) -> types.GenerateContentConfig:
    """Construit la configuration avec les déclarations d'outils, appel automatique désactivé."""
    declarations = [
        types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
        for t in tools
    ]
    return types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def _final_text(response: types.GenerateContentResponse) -> str:
    """Extrait le texte de la réponse, ou lève LLMError si elle est vide."""
    text = (response.text or "").strip()
    if not text:
        raise LLMError("Réponse vide du modèle (bloquée ou interrompue).")
    return text


def _run_tool(call: types.FunctionCall, tools_by_name: dict[str, ToolSpec]) -> types.Part:
    """Exécute un appel de fonction et renvoie la partie function_response correspondante."""
    tool = tools_by_name.get(call.name or "")
    if tool is None:
        payload = {"error": f"Outil inconnu : « {call.name} »."}
    else:
        try:
            payload = {"result": tool.handler(dict(call.args or {}))}
        except ToolError as error:
            logger.debug("L'outil %s a renvoyé une erreur : %s", call.name, error)
            payload = {"error": str(error)}
    # Part.from_function_response n'accepte pas d'identifiant : on construit la réponse directement.
    return types.Part(function_response=types.FunctionResponse(id=call.id, name=call.name, response=payload))
