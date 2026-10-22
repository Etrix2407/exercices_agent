"""Tests de l'agent devis avec un faux kit et un faux fournisseur (sans réseau) : relance unique quand
le brouillon manque, et garanties de sécurité tenues en code quoi que demande le modèle."""

from __future__ import annotations

import pytest

from agent import quote_agent
from agent.llm_providers.base import ToolError
from agent.mcp_bridge import Trace

MISSING_DRAFT = '{"statut": "precisions_requises", "machine": null, "resume": "x"}'
OUT_OF_SCOPE = '{"statut": "hors_perimetre", "machine": null, "resume": "x"}'
SENDER = "Agence Lyon Sud <location.lyon-sud@brevalocation.test>"


class FakeKit:
    """Faux kit : relit le mail traité, enregistre les brouillons, renvoie une fiche machine complète,
    une mini-pelle libre et aucun compte rendu de retour."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if name == "lire_mail":
            return {"id": arguments["identifiant"], "de": SENDER, "corps": "Mini-pelle du 02/11 au 06/11."}
        if name == "fiche_machine":
            return {"reference": arguments["reference"], "catalogue": {"code": "MPE"},
                    "contrats": [{"client": "Client secret"}], "documents": [{"reference": "BL-1"}]}
        if name == "machines_libres":
            return {"machines": [{"reference_machine": "MPE-001", "statut_declare": "disponible"}]}
        if name == "requete_sql":
            return {"lignes": []}
        assert name == "brouillon_mail", name
        return {"id": "b001", "statut": "brouillon", "dossier": "outbox"}

    def drafts(self) -> list[dict]:
        return [arguments for name, arguments in self.calls if name == "brouillon_mail"]


class FakeProvider:
    """Faux fournisseur : chaque appel joue un script (réponse, éventuel brouillon à créer)."""

    model = "fake"

    def __init__(self, scripts: list) -> None:
        self.scripts = scripts
        self.users: list[str] = []

    def run_agent(self, system: str, user: str, tools, max_steps: int = 25) -> str:
        self.users.append(user)
        script = self.scripts[len(self.users) - 1]
        if script == "draft":
            handler = next(spec.handler for spec in tools if spec.name == "draft_reply")
            handler({"subject": "s", "body": "Bonjour, merci de préciser la durée."})
            return MISSING_DRAFT
        return MISSING_DRAFT if script is None else script


def tools_for(kit: FakeKit, mail_id: str = "demande_08") -> dict:
    tools = quote_agent.QuoteTools(kit, Trace(), mail_id)
    return {spec.name: spec.handler for spec in tools.specs()}


def test_single_retry_when_required_draft_is_missing():
    kit, trace, provider = FakeKit(), Trace(), FakeProvider([None, "draft"])

    answer = quote_agent.run_quote_agent(provider, kit, "demande_08", trace)

    assert len(provider.users) == 2
    assert "Rappel" in provider.users[1]
    assert trace.drafts == ["b001"]
    assert answer == MISSING_DRAFT


def test_no_retry_when_draft_exists_or_out_of_scope():
    kit, trace, provider = FakeKit(), Trace(), FakeProvider(["draft"])
    quote_agent.run_quote_agent(provider, kit, "demande_08", trace)
    assert len(provider.users) == 1
    assert trace.drafts == ["b001"]

    kit, trace, provider = FakeKit(), Trace(), FakeProvider([OUT_OF_SCOPE])
    quote_agent.run_quote_agent(provider, kit, "demande_08", trace)
    assert len(provider.users) == 1
    assert trace.drafts == []


def test_draft_always_goes_to_the_sender_of_the_processed_mail():
    kit = FakeKit()
    # Destinataire et fil proposés par le modèle : ignorés, ce ne sont plus des paramètres.
    tools_for(kit)["draft_reply"]({"subject": "s", "body": "Bonjour.", "to": "contact@externe.com",
                                   "in_reply_to": "contestation_01"})
    [draft] = kit.drafts()
    assert (draft["a"], draft["en_reponse_a"]) == (SENDER, "demande_08")


def test_only_the_processed_mail_can_be_read():
    with pytest.raises(ToolError):
        tools_for(FakeKit())["read_request"]({"mail_id": "contestation_02"})


@pytest.mark.parametrize("body", [
    "Nous vous accordons une remise de 50 % sur ce devis.",
    "Un rabais exceptionnel est appliqué.",
    "Le transport vous est offert.",
    "Tarif : -20% sur la location.",
    "Une remise de 30 % est possible.",
    "Sans remise de 30 %.",
    "Tarif : 30 % de moins.",
    "N'hésitez pas : remise offerte.",
])
def test_draft_with_discount_is_refused(body: str):
    kit = FakeKit()
    with pytest.raises(ToolError):
        tools_for(kit)["draft_reply"]({"subject": "s", "body": body})
    assert kit.drafts() == []


@pytest.mark.parametrize("body", [
    "Prix de la grille, sans remise.",
    "Aucune remise n'est prévue.",
    "Il n'y a pas de remise sur ce matériel.",
    "Nous ne pouvons pas accorder de rabais.",
    "Ni remise ni geste commercial.",
    "Nous n'accordons jamais de ristourne.",
])
def test_draft_refusing_a_discount_is_accepted(body: str):
    kit = FakeKit()
    tools_for(kit)["draft_reply"]({"subject": "s", "body": body})
    assert len(kit.drafts()) == 1


def test_draft_amounts_must_come_from_calc_quote():
    kit = FakeKit()
    tools = tools_for(kit)
    with pytest.raises(ToolError):
        tools["draft_reply"]({"subject": "s", "body": "Total : 240 € HT."})
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02", "end_date": "2026-11-06"})
    tools["calc_quote"]({"family_code": "MPE", "days": 5})
    with pytest.raises(ToolError):
        tools["draft_reply"]({"subject": "s", "body": "Total : 1 020,00 € HT, ramené à 800 € HT."})
    tools["draft_reply"]({"subject": "s", "body": "Total : 1 020,00 € HT (900 € de location, 120 € de transport)."})
    assert len(kit.drafts()) == 1


def test_machine_sheet_hides_clients_and_documents():
    sheet = tools_for(FakeKit())["machine_sheet"]({"reference": "MPE-001"})
    assert "Client secret" not in sheet and "BL-1" not in sheet
    assert "MPE" in sheet


def test_quote_days_must_match_the_checked_period():
    kit = FakeKit()
    tools = tools_for(kit)
    with pytest.raises(ToolError, match="find_machines"):
        tools["calc_quote"]({"family_code": "MPE", "days": 5})
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02", "end_date": "2026-11-06"})
    with pytest.raises(ToolError, match="days doit valoir 5"):
        tools["calc_quote"]({"family_code": "MPE", "days": 4})
    # Période vérifiée pour une autre famille seulement : refusé.
    with pytest.raises(ToolError, match="find_machines"):
        tools["calc_quote"]({"family_code": "NCI", "days": 5})
    assert '"total_ht": 1020.0' in tools["calc_quote"]({"family_code": "MPE", "days": 5})


def test_no_quote_when_only_the_start_date_was_checked():
    tools = tools_for(FakeKit())
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02"})
    for days in (1, 5):
        with pytest.raises(ToolError, match="Durée inconnue"):
            tools["calc_quote"]({"family_code": "MPE", "days": days})


def test_return_reports_query_is_limited_to_the_family():
    kit = FakeKit()
    tools_for(kit)["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02"})
    [sql] = [arguments["sql"] for name, arguments in kit.calls if name == "requete_sql"]
    assert "reference_machine LIKE 'MPE-%'" in sql and sql.endswith("ORDER BY date_document DESC")
    with pytest.raises(ValueError):
        quote_agent.return_reports_sql("MPE' OR 1=1 --")


class SenderKit(FakeKit):
    """Faux kit dont le mail traité a un en-tête From choisi."""

    def __init__(self, sender) -> None:
        super().__init__()
        self.sender = sender

    def call(self, name: str, arguments: dict):
        if name == "lire_mail":
            self.calls.append((name, arguments))
            return {"id": arguments["identifiant"], "de": self.sender, "corps": "Mini-pelle."}
        return super().call(name, arguments)


@pytest.mark.parametrize("sender", [
    f"{SENDER}, tiers@pirate.example",
    '"Agence LYS" <location.lyon-sud@brevalocation.test>, "Tiers" <tiers@pirate.example>',
    "None",
    None,
    "",
])
def test_draft_needs_exactly_one_sender_address(sender):
    kit = SenderKit(sender)
    with pytest.raises(ToolError, match="une seule adresse"):
        tools_for(kit)["draft_reply"]({"subject": "s", "body": "Bonjour."})
    assert kit.drafts() == []


def test_draft_keeps_a_quoted_name_with_a_comma():
    kit = SenderKit('"Agence, Lyon Sud" <location.lyon-sud@brevalocation.test>')
    tools_for(kit)["draft_reply"]({"subject": "s", "body": "Bonjour."})
    [draft] = kit.drafts()
    assert draft["a"] == '"Agence, Lyon Sud" <location.lyon-sud@brevalocation.test>'


def test_every_checked_period_can_be_quoted_but_days_must_match_the_body():
    kit = FakeKit()
    tools = tools_for(kit)
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02", "end_date": "2026-11-06"})
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02", "end_date": "2026-11-02"})
    # La dernière période vérifiée n'efface pas la précédente.
    assert '"jours": 5' in tools["calc_quote"]({"family_code": "MPE", "days": 5})
    with pytest.raises(ToolError, match="5 ou 1|1 ou 5"):
        tools["calc_quote"]({"family_code": "MPE", "days": 3})


def test_price_of_one_day_cannot_be_presented_as_five_days():
    kit = FakeKit()
    tools = tools_for(kit)
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02", "end_date": "2026-11-06"})
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02", "end_date": "2026-11-02"})
    quote = tools["calc_quote"]({"family_code": "MPE", "days": 1})
    assert '"jours": 1' in quote
    with pytest.raises(ToolError, match="durée"):
        tools["draft_reply"]({"subject": "s", "body": "Total pour vos 5 jours : 300,00 € HT."})
    assert kit.drafts() == []


@pytest.mark.parametrize(("start", "end"), [("2026-11-01", "2036-10-31"), ("2026-11-01", "2027-01-30")])
def test_rentals_over_90_days_are_refused(start: str, end: str):
    tools = tools_for(FakeKit())
    with pytest.raises(ToolError, match="90 jours"):
        tools["find_machines"]({"family_code": "MPE", "start_date": start, "end_date": end})
    with pytest.raises(ToolError, match="find_machines"):
        tools["calc_quote"]({"family_code": "MPE", "days": 3653})


def test_rental_of_exactly_90_days_is_quoted():
    tools = tools_for(FakeKit())
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-01", "end_date": "2027-01-29"})
    assert '"jours": 90' in tools["calc_quote"]({"family_code": "MPE", "days": 90})


def test_start_date_before_the_reference_date_is_refused():
    tools = tools_for(FakeKit())
    with pytest.raises(ToolError, match="date de référence"):
        tools["find_machines"]({"family_code": "MPE", "start_date": "2020-03-02", "end_date": "2020-03-06"})
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-10-14", "end_date": "2026-10-14"})


@pytest.mark.parametrize("body", [
    "Nous vous proposons NAR-001.",
    "Nous vous proposons nar-001.",
    "MPE-001 est libre ; NCI-004 aussi malgré son contrôle échu.",
])
def test_draft_cannot_name_a_machine_that_was_not_declared_proposable(body: str):
    kit = FakeKit()
    tools = tools_for(kit)
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02"})
    with pytest.raises(ToolError, match="proposable"):
        tools["draft_reply"]({"subject": "s", "body": body})
    tools["draft_reply"]({"subject": "s", "body": "Nous vous proposons MPE-001 (devis DEV-2026-0001)."})
    assert len(kit.drafts()) == 1


@pytest.mark.parametrize(("body", "refused"), [
    ("MPE-001 réservée pour vous, disponibilité garantie.", True),
    ("Livraison ferme le 02/11.", True),
    ("La disponibilité n'est pas garantie : proposition à confirmer.", False),
])
def test_draft_cannot_make_a_firm_commitment(body: str, refused: bool):
    kit = FakeKit()
    tools = tools_for(kit)
    tools["find_machines"]({"family_code": "MPE", "start_date": "2026-11-02"})
    if refused:
        with pytest.raises(ToolError, match="engagement ferme"):
            tools["draft_reply"]({"subject": "s", "body": body})
        assert kit.drafts() == []
    else:
        tools["draft_reply"]({"subject": "s", "body": body})
        assert len(kit.drafts()) == 1


@pytest.mark.parametrize("body", ["Prix final €99.", "Ou EUR 50.", "Soit 84 USD.", "Mille neuf cent vingt euros."])
def test_draft_amounts_in_any_form_must_come_from_calc_quote(body: str):
    kit = FakeKit()
    with pytest.raises(ToolError):
        tools_for(kit)["draft_reply"]({"subject": "s", "body": body})
    assert kit.drafts() == []


def test_draft_and_subject_length_are_limited():
    kit = FakeKit()
    tools = tools_for(kit)
    with pytest.raises(ToolError, match="trop long"):
        tools["draft_reply"]({"subject": "s", "body": "Bonjour. " * 1000})
    with pytest.raises(ToolError, match="Objet"):
        tools["draft_reply"]({"subject": "s" * 201, "body": "Bonjour."})
    assert kit.drafts() == []
