"""Tests de l'orchestrateur : tri des vrais événements du kit et relance, avec de faux agents (sans réseau)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

import outils_parc
from agent.llm_providers import LLMError
from agent.llm_providers.base import ToolError
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
        if name == "lire_mail":
            return outils_parc.lire_mail(**arguments)
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


@pytest.mark.parametrize("name", ["demande_99.eml", "contestation_99.eml", "exemple_01.eml"])
def test_examples_cannot_overwrite_or_imitate_kit_mails(tmp_path: Path, name: str) -> None:
    inbox, examples = tmp_path / "inbox", tmp_path / "exemples"
    inbox.mkdir()
    examples.mkdir()
    (inbox / "exemple_01.eml").write_text("original", encoding="utf-8")
    (examples / name).write_text("Subject: piège\n\nBonjour.", encoding="utf-8")
    with pytest.raises(ValueError):
        add_examples(inbox, examples)
    assert sorted(path.name for path in inbox.iterdir()) == ["exemple_01.eml"]
    assert (inbox / "exemple_01.eml").read_text(encoding="utf-8") == "original"


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

    def flaky(provider, kit, event_id: str, trace) -> str:
        calls.append(event_id)
        if event_id == "CR-2026-1041":
            raise LLMError("réponse invalide")
        if event_id == "CR-2026-1042":
            trace.drafts.append("alerte#1")
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


class MixedMailKit:
    """Faux kit : un mail reconnu par les règles (devis) et un mail que seul le modèle peut trier."""

    def call(self, name: str, arguments: dict):
        if name == "lister_mails":
            return {"mails": [{"id": "autre_01", "sujet": "Question"},
                              {"id": "demande_08", "sujet": "Affectation DEV-2026-0001"}]}
        if name == "rechercher_documents":
            return {"documents": []}
        assert name == "lire_mail", name
        return {"id": arguments["identifiant"], "corps": "Bonjour, il me faudrait une mini-pelle."}


def test_mail_routed_to_an_agent_by_the_model_is_flagged(tmp_path: Path) -> None:
    def quote(provider, kit, event_id: str, trace) -> str:
        return '{"statut": "precisions_requises", "machine": null, "resume": "durée à préciser"}'

    results = process_all(
        MixedMailKit(), {QUOTE: Agent(quote, FakeProvider())}, tmp_path, classifier=LabelProvider("devis"),
    )
    by_id = {result.id: result for result in results}
    assert by_id["autre_01"].route == QUOTE
    assert by_id["autre_01"].details["classe_par_modele"] is True
    assert by_id["autre_01"].summary == "(classé par le modèle) durée à préciser"
    assert "classe_par_modele" not in by_id["demande_08"].details
    assert by_id["demande_08"].summary == "durée à préciser"


class FailingKit:
    def call(self, name: str, arguments: dict):
        raise ToolError("Mail introuvable.")


def test_kit_tool_error_during_classification_goes_to_humans() -> None:
    classifier = LabelProvider("devis")
    assert classify_with_llm(classifier, FailingKit(), Event("autre_01", "mail", "Question")) == HUMAN_OTHER


class BrokenMailKit:
    """Faux kit : lister_mails échoue à cause d'un mail à la date invalide, que lire_mail ne lit pas non plus."""

    MAILS: ClassVar[dict[str, dict]] = {
        "demande_08": {"de": "Agence <a@brevalocation.test>", "sujet": "Affectation DEV-2026-0001", "corps": "A"},
        "autre_01": {"de": "Client <c@exemple.test>", "sujet": "Question", "corps": "B"},
    }

    def call(self, name: str, arguments: dict):
        if name == "lister_mails":
            raise ToolError('Invalid date value or format "pas une date"')
        if name == "rechercher_documents":
            return {"documents": []}
        assert name == "lire_mail", name
        mail_id = arguments["identifiant"]
        if mail_id not in self.MAILS:
            raise ToolError('Invalid date value or format "pas une date"')
        return {"id": mail_id, **self.MAILS[mail_id]}


def test_unreadable_mail_goes_to_humans_without_stopping_the_batch(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name in ("demande_08", "autre_01", "casse_01"):
        (inbox / f"{name}.eml").write_text("x", encoding="utf-8")
    events = {event.id: event for event in collect_events(BrokenMailKit(), inbox)}
    assert events["demande_08"].subject == "Affectation DEV-2026-0001" and not events["demande_08"].issue
    assert events["casse_01"].issue == "illisible" and "pas une date" in events["casse_01"].reason

    def quote(provider, kit, event_id: str, trace) -> str:
        return '{"statut": "precisions_requises", "machine": null, "resume": "ok"}'

    results = process_all(BrokenMailKit(), {QUOTE: Agent(quote, FakeProvider())}, tmp_path / "out", inbox=inbox)
    by_id = {result.id: result for result in results}
    assert (by_id["demande_08"].route, by_id["demande_08"].status) == (QUOTE, "precisions_requises")
    assert (by_id["casse_01"].route, by_id["casse_01"].status) == (HUMAN_OTHER, "illisible")


class DuplicateMailKit:
    """Faux kit : deux mails au même expéditeur et au même corps (espaces mis à part), un troisième différent."""

    def call(self, name: str, arguments: dict):
        if name == "lister_mails":
            return {"mails": [{"id": f"demande_{n}", "sujet": "Affectation DEV-2026-0001"} for n in (8, 9, 10)]}
        if name == "rechercher_documents":
            return {"documents": []}
        assert name == "lire_mail", name
        mail_id = arguments["identifiant"]
        sender = "Agence <A@brevalocation.test>" if mail_id != "demande_9" else "a@brevalocation.test"
        body = "Mini-pelle  du 02/11\nau 06/11." if mail_id != "demande_10" else "Autre demande."
        return {"id": mail_id, "de": sender, "corps": body}


def test_second_identical_mail_goes_to_humans_as_duplicate(tmp_path: Path) -> None:
    calls: list[str] = []

    def quote(provider, kit, event_id: str, trace) -> str:
        calls.append(event_id)
        return '{"statut": "precisions_requises", "machine": null, "resume": "ok"}'

    results = process_all(DuplicateMailKit(), {QUOTE: Agent(quote, FakeProvider())}, tmp_path)
    by_id = {result.id: result for result in results}
    assert calls == ["demande_10", "demande_8"]
    assert (by_id["demande_9"].route, by_id["demande_9"].status) == (HUMAN_OTHER, "doublon")
    assert "doublon de demande_8" in by_id["demande_9"].summary
    queue = json.loads((tmp_path / "file_humaine.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in queue] == ["demande_9"]
