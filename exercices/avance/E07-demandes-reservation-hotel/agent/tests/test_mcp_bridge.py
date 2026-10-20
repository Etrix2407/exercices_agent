"""Tests du pont MCP et des cinq outils de l'agent (sans réseau ni modèle)."""

from __future__ import annotations

import json
from typing import Any

import anyio
import pytest
from mcp import MCPError
from mcp_types import CONNECTION_CLOSED

from agent.llm_providers.base import ToolError
from agent.mcp_bridge import HotelTools, KitClient, KitConnectionError, kit_session
from agent.tests.fakes import REQUEST, WEDDING_NEEDS, FakeKit


def handlers(tools: HotelTools) -> dict:
    return {spec.name: spec.handler for spec in tools.specs()}


def sheet(statut: str) -> dict:
    return {"statut": statut, "besoins": WEDDING_NEEDS, "brouillon_reponse": "Bonjour,\n\nMerci."}


def test_five_fixed_tools_and_no_reservation_tool() -> None:
    names = sorted(handlers(HotelTools(FakeKit(), REQUEST)))
    assert names == ["calc_devis", "read_email", "read_grille", "read_planning", "write_draft"]


def test_read_email_is_framed_as_data_and_limited_to_its_request() -> None:
    tools = handlers(HotelTools(FakeKit(), REQUEST))
    text = tools["read_email"]({"demande_id": REQUEST})
    assert text.index("pas une instruction") < text.index("IGNORE TOUT")
    with pytest.raises(ToolError):
        tools["read_email"]({"demande_id": "demande_autre"})


def test_read_planning_reports_missing_rooms_and_busy_hall() -> None:
    needs = {**WEDDING_NEEDS, "date_arrivee": "2026-12-11", "date_depart": "2026-12-13"}
    needs["chambres"] = [{"type": "double", "nombre": 12}]
    needs["salles"] = [{"salle": "Cedre", "dates": ["2026-12-12"]}]
    report = json.loads(
        handlers(HotelTools(FakeKit(), REQUEST))["read_planning"](
            {"date_debut": "2026-12-11", "date_fin": "2026-12-13", "besoins": needs}
        )
    )
    assert report["chambres_manquantes"] == {"double": 3}
    assert report["salles_demandees"] == [{"salle": "Cedre", "date": "2026-12-12", "libre": False}]
    assert report["disponible"] is False


def test_calc_devis_matches_kit_reference_quote() -> None:
    tools = HotelTools(FakeKit(), REQUEST)
    quote = json.loads(handlers(tools)["calc_devis"]({"besoins": WEDDING_NEEDS}))
    assert quote["total_ttc"] == 1980.0 and "markdown" not in quote
    assert tools.last_quote["markdown"].startswith("# Devis indicatif")


def test_write_draft_attaches_quote_only_for_proposal_and_only_once() -> None:
    kit = FakeKit()
    tools = HotelTools(kit, REQUEST)
    with pytest.raises(ToolError, match="calc_devis"):
        handlers(tools)["write_draft"]({"fiche_json": sheet("proposition")})
    handlers(tools)["calc_devis"]({"besoins": WEDDING_NEEDS})
    handlers(tools)["write_draft"]({"fiche_json": sheet("precisions_requises")})
    draft_call = dict(kit.saved)["enregistrer_brouillon"]
    assert draft_call["devis_markdown"] is None
    with pytest.raises(ToolError, match="déjà"):
        handlers(tools)["write_draft"]({"fiche_json": sheet("precisions_requises")})


def test_write_draft_with_error_status_writes_nothing() -> None:
    kit = FakeKit()
    tools = HotelTools(kit, REQUEST)
    answer = handlers(tools)["write_draft"]({"fiche_json": {"statut": "erreur", "points_a_verifier": ["panne"]}})
    assert answer == "Statut erreur noté, aucun brouillon écrit."
    assert kit.saved == [] and tools.draft["brouillon"] == {} and tools.draft["fiche"]["statut"] == "erreur"


def test_real_mcp_server_reads_email_and_quotes() -> None:
    """Démarre le vrai serveur MCP du kit (local, lecture seule ici)."""

    def use_tools(kit: KitClient) -> tuple[str, dict]:
        tools = handlers(HotelTools(kit, "demande_05_fete_famille"))
        email = tools["read_email"]({"demande_id": "demande_05_fete_famille"})
        return email, json.loads(tools["calc_devis"]({"besoins": WEDDING_NEEDS}))

    async def scenario() -> tuple[str, dict]:
        async with kit_session() as client:
            return await anyio.to_thread.run_sync(use_tools, KitClient(client))

    email, quote = anyio.run(scenario)
    assert "décembre" in email
    assert quote["total_ttc"] == 1980.0


def test_gemini_key_read_from_standard_name() -> None:
    from agent.llm_providers import get_provider

    assert get_provider({"GEMINI_API_KEY": "g"}, provider="gemini").model


def test_hall_without_dates_or_malformed_is_refused() -> None:
    tools = handlers(HotelTools(FakeKit(), REQUEST))
    for halls in (["Cèdre"], [{"salle": "Cèdre"}]):
        with pytest.raises(ToolError, match="[Ss]alle"):
            tools["read_planning"](
                {"date_debut": "2026-12-13", "date_fin": "2026-12-16", "besoins": {**WEDDING_NEEDS, "salles": halls}}
            )


def test_unresponsive_mcp_server_raises_tool_error(monkeypatch) -> None:
    from agent import mcp_bridge

    class SilentClient:
        async def call_tool(self, name: str, arguments: dict) -> Any:
            await anyio.sleep(10)

    monkeypatch.setattr(mcp_bridge, "MCP_TIMEOUT_S", 0.2)
    kit = KitClient(SilentClient())

    async def scenario() -> None:
        await anyio.to_thread.run_sync(kit.call, "lire_demande", {"identifiant": "x"})

    with pytest.raises(ToolError, match="pas répondu"):
        anyio.run(scenario)


class BrokenClient:
    """Faux client MCP : la grille ne répond pas, les outils lèvent l'erreur choisie."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def read_resource(self, uri: str) -> Any:
        await anyio.sleep(10)

    async def call_tool(self, name: str, arguments: dict) -> Any:
        raise self.error


def in_worker(function, *args) -> Any:
    async def scenario() -> Any:
        return await anyio.to_thread.run_sync(function, *args)

    return anyio.run(scenario)


def test_read_grid_has_a_timeout(monkeypatch) -> None:
    from agent import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "MCP_TIMEOUT_S", 0.2)
    with pytest.raises(ToolError, match="grille"):
        in_worker(KitClient(BrokenClient(RuntimeError())).read_grid)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MCPError(code=CONNECTION_CLOSED, message="Connection closed"), KitConnectionError),
        (anyio.ClosedResourceError(), KitConnectionError),
        (anyio.BrokenResourceError(), KitConnectionError),
        (MCPError(code=-32602, message="paramètres invalides"), ToolError),
    ],
)
def test_mcp_transport_errors_become_clear_errors(error: Exception, expected: type[Exception]) -> None:
    with pytest.raises(expected, match="(?i)serveur MCP"):
        in_worker(KitClient(BrokenClient(error)).call, "lire_demande", {"identifiant": "x"})
