"""Adaptateur pour l'API Gemini (SDK google-genai)."""

from __future__ import annotations

import logging
import time

import httpx
from google import genai
from google.genai import errors, types

try:
    import httpx2
except ImportError:  # anciennes versions du SDK : httpx seulement
    httpx2 = None

from llm_providers.base import LLMConfigError, LLMError, LLMQuotaError

DEFAULT_MODEL = "gemini-3.5-flash"
# Aucun nouvel essai silencieux du SDK : c'est _generate qui décide, avec un message visible.
RETRY_OPTIONS = types.HttpRetryOptions(attempts=1)
# Erreurs serveur passagères : nouvel essai après ces attentes (en secondes), puis abandon.
TRANSIENT_STATUS = (500, 502, 503, 504)
SERVER_RETRY_DELAYS_S = (5, 15, 30)
# Au-delà de ce délai demandé par Google (quota du jour, par exemple), attendre ne sert à rien : on s'arrête.
MAX_QUOTA_WAIT_S = 90
# Nombre de nouveaux essais après un quota par minute atteint.
MAX_QUOTA_RETRIES = 3
# Attente quand Google renvoie un 429 sans indiquer de délai (capacité saturée), en secondes.
DEFAULT_QUOTA_WAIT_S = 30
# Le palier gratuit répond parfois en plus d'une minute et demie : 5 minutes avant d'abandonner (sans relancer).
REQUEST_TIMEOUT_MS = 300_000
# Erreurs réseau du client HTTP utilisé par le SDK (httpx, ou httpx2 selon les versions).
TIMEOUT_ERRORS: tuple[type[Exception], ...] = (httpx.TimeoutException,)
CONNECT_ERRORS: tuple[type[Exception], ...] = (httpx.ConnectError,)
if httpx2 is not None:
    TIMEOUT_ERRORS += (httpx2.TimeoutException,)
    CONNECT_ERRORS += (httpx2.ConnectError,)

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Génère les réponses avec un modèle Gemini."""

    def __init__(self, api_key: str, model: str | None = None, temperature: float | None = None) -> None:
        http_options = types.HttpOptions(retry_options=RETRY_OPTIONS, timeout=REQUEST_TIMEOUT_MS)
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self.model = model or DEFAULT_MODEL
        # None : valeur par défaut du modèle.
        self.temperature = temperature

    def generate(self, system: str, user: str) -> str:
        """Envoie la question au modèle et renvoie le texte de la réponse."""
        config = types.GenerateContentConfig(system_instruction=system, temperature=self.temperature)
        response = self._generate(user, config)
        return _final_text(response)

    def _generate(self, contents: str, config: types.GenerateContentConfig) -> types.GenerateContentResponse:
        """Appelle generate_content avec des nouveaux essais visibles et bornés.

        Quota par minute ou erreur serveur passagère : attente annoncée puis nouvel essai. Quota du jour,
        délai dépassé ou autre erreur : arrêt immédiat avec un message clair.
        """
        quota_retries = server_retries = 0
        while True:
            started = time.monotonic()
            try:
                response = self._client.models.generate_content(model=self.model, contents=contents, config=config)
            except TIMEOUT_ERRORS as error:
                raise LLMError(
                    f"Gemini n'a pas répondu en {REQUEST_TIMEOUT_MS // 1000} s : modèle saturé, réessayer plus tard."
                ) from error
            except CONNECT_ERRORS as error:
                raise LLMError(f"Connexion à Gemini impossible : {error}") from error
            except errors.APIError as error:
                if error.code in TRANSIENT_STATUS and server_retries < len(SERVER_RETRY_DELAYS_S):
                    wait = SERVER_RETRY_DELAYS_S[server_retries]
                    server_retries += 1
                    logger.warning("Gemini indisponible (%d) : nouvel essai dans %d s…", error.code, wait)
                    time.sleep(wait)
                    continue
                if error.code != 429:
                    raise _classify(error) from error
                announced = _retry_delay(error)
                # Sans délai annoncé (saturation passagère), on attend un délai fixe au lieu d'arrêter le lot.
                delay = DEFAULT_QUOTA_WAIT_S if announced is None else announced
                too_long = _is_daily_quota(error) or delay > MAX_QUOTA_WAIT_S
                if too_long or quota_retries == MAX_QUOTA_RETRIES:
                    raise _quota_error(error, announced) from error
                quota_retries += 1
                logger.warning("Quota ou capacité Gemini atteint : nouvel essai dans %d s…", round(delay))
                time.sleep(delay + 1)
                continue
            logger.info("Réponse du modèle en %d s.", round(time.monotonic() - started))
            return response


def _error_details(error: errors.APIError) -> list[dict]:
    """Détails structurés renvoyés par Google avec l'erreur (RetryInfo, QuotaFailure…)."""
    details = error.details if isinstance(error.details, dict) else {}
    items = details.get("error", {}).get("details", [])
    return [item for item in items if isinstance(item, dict)]


def _retry_delay(error: errors.APIError) -> float | None:
    """Délai d'attente demandé par Google (champ RetryInfo.retryDelay, par exemple « 71541s »), en secondes."""
    for item in _error_details(error):
        delay = str(item.get("retryDelay", ""))
        if delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                return None
    return None


def _is_daily_quota(error: errors.APIError) -> bool:
    """Vrai si le quota dépassé est un quota journalier (quotaId « …PerDay… »)."""
    return any(
        "PerDay" in str(violation.get("quotaId", ""))
        for item in _error_details(error)
        for violation in item.get("violations", [])
        if isinstance(violation, dict)
    )


def _quota_error(error: errors.APIError, delay: float | None) -> LLMQuotaError:
    """Erreur de quota avec le délai annoncé par Google, lisible par un humain."""
    kind = "quota du jour" if _is_daily_quota(error) else "quota"
    wait = f" : nouvel essai possible dans {delay / 3600:.1f} h" if delay and delay >= 3600 else ""
    return LLMQuotaError(f"Gemini : {kind} épuisé pour le modèle{wait}. Changer LLM_MODEL ou réessayer plus tard.")


def _classify(error: errors.APIError) -> LLMError:
    """Traduit une erreur Gemini hors quota : une erreur de configuration (clé, modèle) arrête tout le lot."""
    message = f"Gemini a renvoyé l'erreur {error.code} : {error.message}"
    # Gemini signale une clé invalide par un 400 « API key not valid ».
    if error.code in (401, 403, 404) or (error.code == 400 and "api key" in str(error.message).lower()):
        return LLMConfigError(f"{message}. Vérifier GEMINI_API_KEY et LLM_MODEL.")
    return LLMError(message)


def _final_text(response: types.GenerateContentResponse) -> str:
    """Extrait le texte de la réponse, ou lève LLMError si elle est vide."""
    text = (response.text or "").strip()
    if not text:
        raise LLMError("Réponse vide du modèle (bloquée ou interrompue).")
    return text
