"""Agent devis : propose une machine libre et contrôlée pour une demande d'agence, sans rien réserver.

Le prix n'est calculé qu'en code (pricing.calc_quote) et seulement si la durée est connue.
La seule écriture possible est un brouillon de mail dans boite/outbox/.
"""

from __future__ import annotations

from pathlib import Path

from agent import pricing
from agent.llm_providers import LLMProvider, get_provider
from agent.llm_providers.base import ToolError, ToolSpec
from agent.machine_filter import usable_machines
from agent.mcp_bridge import KitCaller, logged_spec, require_str, to_text, wrap_data

# Modèle de l'agent devis (le .env est partagé par tous les exercices).
# None : choix automatique selon les clés du .env / modèle et température par défaut.
LLM_PROVIDER = "gemini"
LLM_MODEL = "gemini-3.5-flash"
LLM_TEMPERATURE = None

AGENT_NAME = "devis"
PROMPT_PATH = Path(__file__).resolve().parent / "prompt_devis.md"
AGENCIES = ("LYS", "GRE", "MRS", "TLS", "BDX")
MAX_STEPS = 15


def rental_families() -> dict[str, str]:
    """Familles louables de la grille : {code: libellé}."""
    return {code: line["libelle"] for code, line in pricing.load_grid().items() if line["type_ligne"] == "location"}


class QuoteTools:
    """Outils de l'agent devis pour un événement ; ajoute chaque brouillon créé à drafts."""

    def __init__(self, kit: KitCaller, drafts: list[str]) -> None:
        self.kit = kit
        self.families = rental_families()
        self.drafts = drafts

    def read_request(self, args: dict) -> str:
        mail_id = require_str(args, "mail_id")
        return wrap_data(mail_id, self.kit.call("lire_mail", {"identifiant": mail_id}))

    def find_machines(self, args: dict) -> str:
        code = require_str(args, "family_code")
        if code not in self.families:
            raise ToolError(f"Famille inconnue : {code}. Codes : {', '.join(self.families)}.")
        start, end = require_str(args, "start_date"), require_str(args, "end_date")
        if end < start:
            raise ToolError("end_date doit être postérieure ou égale à start_date.")
        arguments = {"famille": self.families[code], "date_debut": start, "date_fin": end}
        if args.get("agency"):
            arguments["agence"] = args["agency"]
        free = self.kit.call("machines_libres", arguments)["machines"]
        usable, excluded = usable_machines(free, end)
        return to_text({"proposables": usable, "ecartees": excluded})

    def machine_sheet(self, args: dict) -> str:
        reference = require_str(args, "reference")
        return wrap_data(reference, self.kit.call("fiche_machine", {"reference": reference}))

    def calc_quote(self, args: dict) -> str:
        days = args.get("days")
        # Certains fournisseurs renvoient les entiers JSON en flottants (5.0).
        if isinstance(days, float) and days.is_integer():
            days = int(days)
        try:
            return to_text(pricing.calc_quote(require_str(args, "family_code"), days))
        except ValueError as error:
            raise ToolError(str(error)) from error

    def draft_reply(self, args: dict) -> str:
        arguments = {
            "a": require_str(args, "to"),
            "sujet": require_str(args, "subject"),
            "corps": require_str(args, "body"),
            "service": "planification",
            "en_reponse_a": require_str(args, "in_reply_to"),
        }
        result = self.kit.call("brouillon_mail", arguments)
        self.drafts.append(result["id"])
        return to_text(result)

    def specs(self) -> list[ToolSpec]:
        date = {"type": "string", "description": "AAAA-MM-JJ"}
        family = {"type": "string", "enum": list(self.families), "description": "Code famille de la grille."}
        tools = [
            ("read_request", "Lit le mail de demande d'une agence.",
             {"mail_id": {"type": "string", "description": "Ex. demande_08."}}, ["mail_id"], self.read_request),
            ("find_machines",
             ("Machines libres sur la période, déjà filtrées (statut, contrôle de retour, contrôle réglementaire). "
              "Sans agence : toutes les agences."),
             {"family_code": family, "start_date": date, "end_date": date,
              "agency": {"type": "string", "enum": list(AGENCIES)}},
             ["family_code", "start_date", "end_date"], self.find_machines),
            ("machine_sheet", "Fiche d'une machine : catalogue, contrôle, contrats et documents.",
             {"reference": {"type": "string", "description": "Ex. NCI-004."}}, ["reference"], self.machine_sheet),
            ("calc_quote", "Calcule le devis HT d'après la grille (seule source de prix). Durée connue uniquement.",
             {"family_code": family, "days": {"type": "integer", "minimum": 1}},
             ["family_code", "days"], self.calc_quote),
            ("draft_reply", "Prépare un brouillon de réponse à l'agence (jamais envoyé).",
             {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
              "in_reply_to": {"type": "string", "description": "Identifiant du mail auquel on répond (ex. demande_08), pas son Message-ID."}},
             ["to", "subject", "body", "in_reply_to"], self.draft_reply),
        ]
        return [
            logged_spec(AGENT_NAME, name, description,
                        {"type": "object", "properties": properties, "required": required}, handler)
            for name, description, properties, required, handler in tools
        ]


def make_provider() -> LLMProvider:
    """Fournisseur de l'agent devis, selon les réglages en tête de ce module."""
    return get_provider(provider=LLM_PROVIDER, model=LLM_MODEL, temperature=LLM_TEMPERATURE)


def run_quote_agent(provider: LLMProvider, kit: KitCaller, mail_id: str, drafts: list[str]) -> str:
    """Traite une demande ; renvoie la réponse finale du modèle (brouillons créés ajoutés à drafts)."""
    tools = QuoteTools(kit, drafts)
    system = PROMPT_PATH.read_text(encoding="utf-8")
    return provider.run_agent(system, f"Demande à traiter : {mail_id}", tools.specs(), max_steps=MAX_STEPS)
