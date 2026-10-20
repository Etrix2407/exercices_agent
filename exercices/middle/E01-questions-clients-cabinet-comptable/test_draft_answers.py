"""Tests du script de brouillons et du choix du fournisseur (sans appel réseau)."""

from __future__ import annotations

from pathlib import Path

import pytest

from draft_answers import UNKNOWN, draft_answers, load_questions, summarize_draft
from llm_providers import LLMError, get_provider
from llm_providers.anthropic_provider import AnthropicProvider
from llm_providers.gemini_provider import GeminiProvider

HEADER = "identifiant,nom,numero_dossier,question\n"


class FakeProvider:
    """Fournisseur factice : renvoie un brouillon fixe, ou échoue sur un identifiant donné."""

    model = "factice"

    def __init__(self, failing_id: str | None = None) -> None:
        self.failing_id = failing_id

    def generate(self, system: str, user: str) -> str:
        if self.failing_id and user.startswith(self.failing_id):
            raise LLMError("panne | simulée\nsur deux lignes")
        return "**Étiquette :** traitable\n**Section citée :** § 2.1 (Déclaration de TVA trimestrielle)"


def write_csv(tmp_path: Path, content: str) -> Path:
    csv_path = tmp_path / "questions.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


def test_get_provider_prefers_anthropic_when_both_keys_exist():
    provider = get_provider({"ANTHROPIC_API_KEY": "a", "API_KEY_GEMINI": "g"})
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_uses_requested_provider_and_model():
    env = {"ANTHROPIC_API_KEY": "a", "API_KEY_GEMINI": "g", "LLM_PROVIDER": "Gemini", "LLM_MODEL": "gemini-x"}
    provider = get_provider(env)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-x"


def test_get_provider_fails_without_key_for_requested_provider():
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        get_provider({"LLM_PROVIDER": "anthropic", "API_KEY_GEMINI": "g"})


def test_load_questions_rejects_unsafe_identifier(tmp_path):
    csv_path = write_csv(tmp_path, HEADER + '../Q01,Nom,DA-1,"Question ?"\n')
    with pytest.raises(ValueError, match="Identifiants invalides"):
        load_questions(csv_path)


def test_summarize_draft_without_label():
    summary = summarize_draft("Q01", "texte libre sans format")
    assert summary.label == UNKNOWN


def test_draft_answers_continues_after_a_failure(tmp_path):
    csv_path = write_csv(tmp_path, HEADER + 'Q01,A,DA-1,"Q ?"\nQ02,B,DA-2,"Q ?"\n')
    output_dir = tmp_path / "drafts"
    output_dir.mkdir()
    (output_dir / "Q01.md").write_text("brouillon d'une exécution précédente", encoding="utf-8")

    summaries = draft_answers(csv_path, output_dir, FakeProvider(failing_id="Q01"))

    assert [item.label for item in summaries] == ["erreur", "traitable"]
    assert summaries[1].section == "§ 2.1 (Déclaration de TVA trimestrielle)"
    assert not (output_dir / "Q01.md").exists()
    assert (output_dir / "Q02.md").exists()
    recap = (output_dir / "recap.md").read_text(encoding="utf-8")
    assert "| Q01 | erreur | panne \\| simulée sur deux lignes |" in recap


def test_exercise_settings_override_env():
    env = {"ANTHROPIC_API_KEY": "a", "API_KEY_GEMINI": "g", "LLM_PROVIDER": "anthropic", "LLM_MODEL": "autre"}
    provider = get_provider(env, provider="gemini", model="gemini-test", temperature=0.2)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-test" and provider.temperature == 0.2
