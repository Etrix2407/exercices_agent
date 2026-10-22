"""Tests de l'agent devis : relance unique quand le brouillon manque, avec un faux fournisseur (sans réseau)."""

from __future__ import annotations

from agent import quote_agent
from agent.mcp_bridge import Trace

SANS_BROUILLON = '{"statut": "precisions_requises", "machine": null, "resume": "x"}'
HORS_PERIMETRE = '{"statut": "hors_perimetre", "machine": null, "resume": "x"}'


class FakeKit:
    """Faux kit : seul l'envoi de brouillon est attendu."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        assert name == "brouillon_mail", name
        return {"id": "b001", "statut": "brouillon", "dossier": "outbox"}


class FakeProvider:
    """Faux fournisseur : chaque appel joue un script (réponse, éventuel brouillon à créer)."""

    model = "fake"

    def __init__(self, scripts: list) -> None:
        self.scripts = scripts
        self.users: list[str] = []

    def run_agent(self, system: str, user: str, tools, max_steps: int = 25) -> str:
        self.users.append(user)
        script = self.scripts[len(self.users) - 1]
        if script == "brouillon":
            handler = next(spec.handler for spec in tools if spec.name == "draft_reply")
            handler({"to": "a@b.example", "subject": "s", "body": "b", "in_reply_to": "demande_08"})
            return SANS_BROUILLON
        return SANS_BROUILLON if script is None else script


def test_relance_unique_si_brouillon_obligatoire_manquant():
    kit = FakeKit()
    trace = Trace()
    provider = FakeProvider([None, "brouillon"])

    answer = quote_agent.run_quote_agent(provider, kit, "demande_08", trace)

    assert len(provider.users) == 2
    assert "Rappel" in provider.users[1]
    assert trace.drafts == ["b001"]
    assert answer == SANS_BROUILLON


def test_pas_de_relance_si_brouillon_deja_cree_ou_hors_perimetre():
    kit = FakeKit()
    trace = Trace()
    provider = FakeProvider(["brouillon"])
    quote_agent.run_quote_agent(provider, kit, "demande_08", trace)
    assert len(provider.users) == 1
    assert trace.drafts == ["b001"]

    kit = FakeKit()
    trace = Trace()
    provider = FakeProvider([HORS_PERIMETRE])
    quote_agent.run_quote_agent(provider, kit, "demande_08", trace)
    assert len(provider.users) == 1
    assert trace.drafts == []
