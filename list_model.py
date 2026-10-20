"""Liste les modèles Gemini disponibles pour la clé du fichier exercices/.env.

Usage (depuis la racine du dépôt) : exercices\\avance\\.venv\\Scripts\\python list_model.py
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors

# Le .env partagé par tous les exercices, retrouvé à partir de l'emplacement du script.
ENV_PATH = Path(__file__).resolve().parent / "exercices" / ".env"


def list_generation_models(api_key: str) -> list[str]:
    """Renvoie les noms des modèles capables de générer du texte (generateContent)."""
    client = genai.Client(api_key=api_key)
    return [model.name for model in client.models.list() if "generateContent" in (model.supported_actions or [])]


def main() -> None:
    """Point d'entrée du script."""
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(f"GEMINI_API_KEY absente : la renseigner dans {ENV_PATH}.")
    try:
        names = list_generation_models(api_key)
    except errors.APIError as error:
        raise SystemExit(f"Gemini a renvoyé l'erreur {error.code} : {error.message}") from error
    print("\n".join(names))


if __name__ == "__main__":
    main()
