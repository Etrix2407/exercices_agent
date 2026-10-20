"""Tests de l'orchestrateur check_applications.py, sans réseau ni modèle réel."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from check_applications import (
    ApplicationResult,
    check_applications,
    list_candidate_dirs,
    parse_agent_output,
)
from llm_providers import LLMError
from llm_providers.base import LLMQuotaError

GRID = {"date_reference_controle": "2026-10-14", "pieces_candidat": []}


class FakeProvider:
    """Fournisseur factice : renvoie une réponse préparée par dossier et écrit la relance si demandé."""

    model = "factice"

    def __init__(
        self,
        output_dir: Path,
        answers: dict[str, str | Exception],
        write_relance: set[str],
        relance_text: str = "Bonjour,\n",
    ) -> None:
        self.output_dir = output_dir
        self.answers = answers
        self.write_relance = write_relance
        self.relance_text = relance_text

    def generate(self, system: str, user: str) -> str:
        raise NotImplementedError

    def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
        folder = user.split(":", 1)[1].strip()
        answer = self.answers[folder]
        if isinstance(answer, Exception):
            raise answer
        if folder in self.write_relance:
            (self.output_dir / f"relance_{folder}.txt").write_text(self.relance_text, encoding="utf-8")
        return answer


def answer(statut: str, **fields: object) -> str:
    """Construit une réponse finale JSON d'agent."""
    data = {
        "statut": statut,
        "candidat": "",
        "pieces_manquantes": [],
        "incoherences": [],
        "relance_fichier": "",
        "points_a_verifier": [],
        "sources": [],
    }
    data.update(fields)
    return json.dumps(data, ensure_ascii=False)


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Crée une grille et trois dossiers de candidats minimaux."""
    candidates = tmp_path / "candidats"
    for folder in ("alice-test", "bruno-test", "carla-test"):
        (candidates / folder).mkdir(parents=True)
        (candidates / folder / "identite.txt").write_text("Nom : X\n", encoding="utf-8")
    grid = tmp_path / "grille.json"
    grid.write_text(json.dumps(GRID), encoding="utf-8")
    return candidates, grid, tmp_path / "output"


def run(
    workspace: tuple[Path, Path, Path],
    answers: dict,
    write_relance: set[str] = frozenset(),
    only=None,
    relance_text: str = "Bonjour,\n",
):
    """Lance l'orchestrateur avec le fournisseur factice et sans outils réels."""
    candidates, grid, output = workspace
    output.mkdir(parents=True, exist_ok=True)
    provider = FakeProvider(output, answers, set(write_relance), relance_text)
    return check_applications(candidates, grid, output, provider, only=only, tools_factory=lambda *_: [])


def test_parse_tolerates_json_fences() -> None:
    text = "\n```json\n" + answer("complet", candidat="Alice Test") + "\n```\n"
    result = parse_agent_output("alice-test", text)
    assert result == ApplicationResult(folder="alice-test", statut="complet", candidat="Alice Test")


def test_invalid_json_gives_error_and_batch_continues(workspace) -> None:
    answers = {"alice-test": "pas du JSON", "bruno-test": answer("complet"), "carla-test": answer("statut_bidon")}
    results = run(workspace, answers)
    assert [item.statut for item in results] == ["erreur", "complet", "erreur"]
    assert "aucun objet JSON" in results[0].points_a_verifier[0]
    assert "statut inconnu" in results[2].points_a_verifier[0]


def test_llm_error_gives_error_status(workspace) -> None:
    results = run(workspace, {"alice-test": LLMError("quota dépassé")}, only="alice-test")
    assert results[0].statut == "erreur"
    assert results[0].points_a_verifier == ["quota dépassé"]


def test_relance_checks_and_stale_file_removed(workspace) -> None:
    _, _, output = workspace
    output.mkdir(parents=True)
    # Relance d'une exécution précédente : elle doit être supprimée avant le passage de l'agent.
    (output / "relance_bruno-test.txt").write_text("ancienne", encoding="utf-8")
    answers = {
        "alice-test": answer("incomplet", relance_fichier="relance_alice-test.txt"),
        "bruno-test": answer("incomplet", relance_fichier="relance_bruno-test.txt"),
        "carla-test": answer("complet"),
    }
    results = run(workspace, answers, write_relance={"alice-test", "carla-test"})
    alice, bruno, carla = results
    assert alice.relance_fichier == "relance_alice-test.txt" and alice.points_a_verifier == []
    assert not (output / "relance_bruno-test.txt").exists()
    assert bruno.relance_fichier == "" and "relance non écrite" in bruno.points_a_verifier[0]
    # Relance contraire au statut « complet » : signalée et retirée du dossier de sortie.
    assert "pas incomplet" in carla.points_a_verifier[0]
    assert carla.relance_fichier == ""
    assert not (output / "relance_carla-test.txt").exists()


def test_synthesis_escapes_cells_and_labels_status(workspace) -> None:
    answers = {
        "alice-test": answer("a_verifier", candidat="Alice Test", incoherences=["nom « A|B »\nsur le bulletin"]),
        "bruno-test": answer(
            "incomplet",
            candidat="Bruno Test",
            pieces_manquantes=[{"piece": "Avis d'imposition", "motif": "manquante"}],
        ),
        "carla-test": answer("complet", candidat="Carla Test"),
    }
    run(workspace, answers, write_relance={"bruno-test"})
    output = workspace[2]
    synthesis = (output / "synthese.md").read_text(encoding="utf-8")
    assert "Modèle : `factice`" in synthesis and "2026-10-14" in synthesis
    assert "| alice-test | Alice Test | à vérifier | — | nom « A\\|B » sur le bulletin | — |" in synthesis
    assert "| bruno-test | Bruno Test | incomplet | Avis d'imposition (manquante) | — | relance_bruno-test.txt |" in (
        synthesis
    )
    saved = json.loads((output / "resultats.json").read_text(encoding="utf-8"))
    assert [item["statut"] for item in saved] == ["a_verifier", "incomplet", "complet"]


def test_unknown_only_folder_raises(workspace) -> None:
    with pytest.raises(ValueError, match="Dossier inconnu"):
        list_candidate_dirs(workspace[0], "zoe-test")


def test_owner_draft_only_for_complete_dossier(workspace) -> None:
    _, grid_path, output = workspace
    grid = {
        "date_reference_controle": "2026-10-14",
        "logement": {"reference": "LOG-TEST", "adresse_fictive": "Rue Test 1"},
        "pieces_candidat": [
            {"id": "identite", "court": "Pièce d'identité", "motifs": ["identite*"]},
            {"id": "revenus", "court": "Justificatifs de revenus", "motifs": ["bulletin_*"]},
        ],
        "garant": {
            "pieces_garant": [{"id": "g", "court": "Garant : pièce d'identité", "motifs": ["garant/identite*"]}]
        },
    }
    grid_path.write_text(json.dumps(grid), encoding="utf-8")
    output.mkdir(parents=True)
    # Brouillon d'une exécution précédente : il doit disparaître si le dossier n'est plus complet.
    (output / "transmission_bruno-test.txt").write_text("ancien", encoding="utf-8")
    sources = ["identite_carte.pdf", "bulletin_2026-09.pdf", "bulletin_2026-08.pdf", "garant/identite.txt"]
    for source in sources:
        (workspace[0] / "alice-test" / source).parent.mkdir(exist_ok=True)
        (workspace[0] / "alice-test" / source).write_text("pièce", encoding="utf-8")
    answers = {
        "alice-test": answer("complet", candidat="Alice Test", sources=sources),
        "bruno-test": answer("a_verifier", candidat="Bruno Test"),
    }
    alice = run(workspace, answers, only="alice-test")[0]
    bruno = run(workspace, answers, only="bruno-test")[0]

    draft = (output / "transmission_alice-test.txt").read_text(encoding="utf-8")
    assert alice.transmission_fichier == "transmission_alice-test.txt"
    assert "Bonjour [à compléter]," in draft
    assert "logement LOG-TEST (Rue Test 1)" in draft and "14/10/2026" in draft
    assert "- Pièce d'identité : identite_carte.pdf" in draft
    assert "- Justificatifs de revenus : bulletin_2026-08.pdf, bulletin_2026-09.pdf" in draft
    assert "- Garant : pièce d'identité : garant/identite.txt" in draft
    assert bruno.transmission_fichier == ""
    assert not (output / "transmission_bruno-test.txt").exists()


def test_owner_draft_skipped_when_points_to_check(workspace) -> None:
    output = workspace[2]
    points = ["identite.pdf : PDF sans texte extractible (document scanné ?)"]
    answers = {"alice-test": answer("complet", candidat="Alice Test", points_a_verifier=points)}
    alice = run(workspace, answers, only="alice-test")[0]
    # « complet » avec un point à vérifier est ramené à « à vérifier » : aucune transmission au propriétaire.
    assert alice.statut == "a_verifier"
    assert alice.transmission_fichier == ""
    assert not (output / "transmission_alice-test.txt").exists()
    assert alice.points_a_verifier[0] == points[0] and "ramené" in alice.points_a_verifier[1]


def test_quota_error_stops_batch_and_still_writes_synthesis(workspace) -> None:
    _, _, output = workspace
    output.mkdir(parents=True)
    # Brouillon d'une exécution précédente pour un dossier qui ne sera pas traité : il doit disparaître.
    (output / "relance_carla-test.txt").write_text("ancienne", encoding="utf-8")
    answers = {"alice-test": answer("complet"), "bruno-test": LLMQuotaError("quota du jour épuisé")}
    results = run(workspace, answers)
    assert [item.statut for item in results] == ["complet", "erreur", "non_traite"]
    assert results[1].points_a_verifier == ["quota du jour épuisé"]
    assert "lot arrêté" in results[2].points_a_verifier[0]
    assert not (output / "relance_carla-test.txt").exists()
    synthesis = (output / "synthese.md").read_text(encoding="utf-8")
    assert "| carla-test | — | non traité |" in synthesis
    assert not list(output.glob("*.tmp"))


def test_unexpected_exception_only_fails_current_folder(workspace, caplog: pytest.LogCaptureFixture) -> None:
    answers = {"alice-test": RuntimeError("bogue"), "bruno-test": answer("complet"), "carla-test": answer("complet")}
    results = run(workspace, answers)
    assert [item.statut for item in results] == ["erreur", "complet", "complet"]
    assert "RuntimeError" in results[0].points_a_verifier[0]
    assert "erreur inattendue" in caplog.text


def test_synthesis_written_after_each_folder(workspace) -> None:
    output = workspace[2]
    seen: list[str] = []

    class SpyProvider(FakeProvider):
        def run_agent(self, system: str, user: str, tools: list, max_steps: int = 25) -> str:
            seen.append((output / "synthese.md").read_text(encoding="utf-8"))
            return super().run_agent(system, user, tools, max_steps)

    output.mkdir(parents=True)
    answers = {name: answer("complet") for name in ("alice-test", "bruno-test", "carla-test")}
    check_applications(
        workspace[0], workspace[1], output, SpyProvider(output, answers, set()), tools_factory=lambda *_: []
    )
    assert "Lot en cours : 0/3" in seen[0]
    assert "Lot en cours : 2/3" in seen[2] and "| bruno-test |" in seen[2]
    assert "Lot en cours" not in (output / "synthese.md").read_text(encoding="utf-8")


def test_unknown_sources_and_long_relance_are_flagged(workspace) -> None:
    answers = {
        "alice-test": answer("complet", sources=["identite.txt", "bulletin_invente.pdf"]),
        "bruno-test": answer("incomplet", sources=["identite.txt"]),
    }
    alice = run(workspace, answers, only="alice-test")[0]
    bruno = run(workspace, answers, write_relance={"bruno-test"}, only="bruno-test", relance_text="mot " * 121)[0]
    assert alice.points_a_verifier[0] == "sources absentes du dossier : bulletin_invente.pdf"
    assert alice.transmission_fichier == ""
    assert bruno.points_a_verifier == ["relance trop longue : 121 mots (limite 120)"]
    assert bruno.relance_fichier == "relance_bruno-test.txt"


def test_default_batch_only_has_the_eight_statement_folders() -> None:
    from check_applications import CANDIDATES_DIR

    names = [path.name for path in list_candidate_dirs(CANDIDATES_DIR)]
    assert len(names) == 8 and not {"leroy", "marchal", "pieges"} & set(names)


def test_complete_with_points_to_check_becomes_to_verify() -> None:
    from check_applications import ApplicationResult, enforce_complete_status

    result = ApplicationResult(folder="x", statut="complet", points_a_verifier=["bulletin.pdf illisible"])
    enforce_complete_status(result)
    assert result.statut == "a_verifier" and "ramené" in result.points_a_verifier[-1]


# --- Filet de sécurité : pièce présente déclarée manquante -------------------------------------------------------

SAFETY_GRID = {
    "pieces_candidat": [
        {"court": "Pièce d'identité", "motifs": ["identite*"], "nombre_min": 1},
        {"court": "Avis d'imposition", "motifs": ["avis_imposition*"], "nombre_min": 1},
        {"court": "Justificatifs de revenus", "motifs": ["bulletin_*"], "nombre_min": 3},
    ]
}


@pytest.fixture
def safety_folder(tmp_path: Path) -> tuple[Path, Path]:
    candidate = tmp_path / "jane"
    candidate.mkdir()
    for name in ("identite.txt", "avis_imposition_2025.txt", "bulletin_1.txt", "bulletin_2.txt"):
        (candidate / name).write_text("x", encoding="utf-8")
    grid = tmp_path / "grille.json"
    grid.write_text(json.dumps(SAFETY_GRID), encoding="utf-8")
    return candidate, grid


@pytest.mark.parametrize(
    ("incoherences", "expected_status"),
    [([], "complet"), (["avis_imposition_2025.txt au nom de « Jane Do »"], "a_verifier")],
)
def test_present_piece_declared_missing_is_dropped(safety_folder, incoherences, expected_status) -> None:
    from check_applications import drop_pieces_found_by_code

    result = ApplicationResult(
        folder="jane",
        statut="incomplet",
        pieces_manquantes=[{"piece": "Avis d'imposition", "motif": "manquante (nom non concordant)"}],
        incoherences=incoherences,
    )
    drop_pieces_found_by_code(result, *safety_folder, safety_folder[0].parent / "sorties")
    assert result.pieces_manquantes == [] and result.statut == expected_status


@pytest.mark.parametrize(
    "piece",
    [
        {"piece": "Avis d'imposition", "motif": "périmée (émise le 01/01/2024)"},
        {"piece": "Pièce d'identité", "motif": "périmée (expirée le 01/01/2026)"},
        {"piece": "Justificatifs de revenus", "motif": "1 sur 3 manquante"},
        {"piece": "Avis d'imposition", "motif": "trop ancien (émis le 01/01/2024)"},
        {"piece": "Avis d'imposition", "motif": ""},
        {"piece": "Avis d'imposition"},
    ],
)
def test_outdated_or_really_missing_piece_is_kept(safety_folder, piece) -> None:
    from check_applications import drop_pieces_found_by_code

    result = ApplicationResult(folder="jane", statut="incomplet", pieces_manquantes=[piece])
    drop_pieces_found_by_code(result, *safety_folder, safety_folder[0].parent / "sorties")
    assert result.pieces_manquantes == [piece] and result.statut == "incomplet"


def test_dossier_made_complete_by_safety_net_has_no_point_and_no_relance(safety_folder) -> None:
    from check_applications import (
        check_relance,
        drop_pieces_found_by_code,
        enforce_complete_status,
    )

    output_dir = safety_folder[0].parent / "sorties"
    output_dir.mkdir()
    (output_dir / "relance_jane.txt").write_text("Bonjour,", encoding="utf-8")
    result = ApplicationResult(
        folder="jane", statut="incomplet", pieces_manquantes=[{"piece": "Avis d'imposition", "motif": "manquante"}]
    )
    drop_pieces_found_by_code(result, *safety_folder, output_dir)
    check_relance(result, output_dir)
    enforce_complete_status(result)
    assert result.statut == "complet" and result.points_a_verifier == []
    assert not (output_dir / "relance_jane.txt").exists()
