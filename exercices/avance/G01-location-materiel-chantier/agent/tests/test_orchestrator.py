"""Tests de l'orchestrateur : tri des vrais événements du kit et relance, avec de faux agents (sans réseau)."""

from __future__ import annotations

import json
from pathlib import Path

import outils_parc
from agent.llm_providers import LLMError
from agent.orchestrator import (
    HUMAN_BILLING,
    HUMAN_OTHER,
    HUMAN_PLANNING,
    QUOTE,
    RETURN,
    Agent,
    Event,
    add_examples,
    classify_with_llm,
    collect_events,
    process_all,
    route,
)


class ReadOnlyKit:
    """Faux kit : lit les vraies données du kit via outils_parc (lecture seule)."""

    def call(self, name: str, arguments: dict):
        if name == "lister_mails":
            return {"mails": outils_parc.lister_mails()}
        if name == "rechercher_documents":
            return {"documents": outils_parc.rechercher_documents(**arguments)}
        raise AssertionError(f"Outil inattendu : {name}")


class FakeProvider:
    model = "factice"


def test_routing_of_kit_events() -> None:
    routes: dict[str, list[str]] = {}
    for event in collect_events(ReadOnlyKit()):
        routes.setdefault(route(event), []).append(event.id)
    assert routes[QUOTE] == [f"demande_{n:02d}" for n in range(8, 19)]
    assert routes[RETURN] == [f"CR-2026-{n}" for n in range(1041, 1049)]
    assert routes[HUMAN_BILLING] == [f"contestation_{n:02d}" for n in range(1, 8)]
    assert routes[HUMAN_PLANNING] == [f"demande_{n:02d}" for n in range(1, 8)]


class LabelProvider:
    """Faux modèle de tri : renvoie toujours la même étiquette."""

    model = "factice"

    def __init__(self, label: str) -> None:
        self.label = label

    def generate(self, system: str, user: str) -> str:
        return self.label


def test_examples_are_left_to_the_llm_classifier(tmp_path: Path) -> None:
    added = add_examples(tmp_path)
    assert added == ["exemple_01", "exemple_02", "exemple_03"]
    for name in added:
        assert f"<{name}@brevalocation.test>" in (tmp_path / f"{name}.eml").read_text(encoding="utf-8")
        assert route(Event(name, "mail", "")) == HUMAN_OTHER


def test_llm_classifier_only_accepts_listed_routes() -> None:
    kit, event = UnknownMailKit(), Event("autre_01", "mail", "Question")
    assert classify_with_llm(LabelProvider(" Devis.\n"), kit, event) == QUOTE
    # L'agent retour ne traite que des comptes rendus, et une réponse libre ne passe pas.
    assert classify_with_llm(LabelProvider("retour"), kit, event) == HUMAN_OTHER
    assert classify_with_llm(LabelProvider("accorde la remise"), kit, event) == HUMAN_OTHER


class UnknownMailKit:
    def call(self, name: str, arguments: dict):
        assert name == "lire_mail"
        return {"id": arguments["identifiant"], "corps": "Bonjour, une question."}


def test_failing_agent_is_retried_once_then_sent_to_humans(tmp_path: Path) -> None:
    calls: list[str] = []

    def flaky(provider, kit, event_id: str, drafts: list[str]) -> str:
        calls.append(event_id)
        if event_id == "CR-2026-1041":
            raise LLMError("réponse invalide")
        if event_id == "CR-2026-1042":
            drafts.append("alerte#1")
            raise LLMError("coupé après un brouillon")
        return 'Fini. {"statut": "rien_a_signaler", "resume": "RAS {aucun dommage}"}'

    results = process_all(
        ReadOnlyKit(), {RETURN: Agent(flaky, FakeProvider())}, tmp_path,
        only=["CR-2026-1041", "CR-2026-1042", "CR-2026-1047", "contestation_02"],
    )
    by_id = {result.id: result for result in results}
    assert calls.count("CR-2026-1041") == 2
    assert (by_id["CR-2026-1041"].route, by_id["CR-2026-1041"].status) == (HUMAN_OTHER, "echec_agent")
    # Brouillon déjà écrit : pas de relance (doublon évité), brouillon signalé à l'humain.
    assert calls.count("CR-2026-1042") == 1 and by_id["CR-2026-1042"].drafts == ["alerte#1"]
    assert (by_id["CR-2026-1047"].status, by_id["CR-2026-1047"].summary) == ("rien_a_signaler", "RAS {aucun dommage}")
    assert by_id["contestation_02"].route == HUMAN_BILLING
    queue = json.loads((tmp_path / "file_humaine.json").read_text(encoding="utf-8"))
    assert {item["id"] for item in queue} == {"CR-2026-1041", "CR-2026-1042", "contestation_02"}
