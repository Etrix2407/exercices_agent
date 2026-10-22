"""Agent retour : analyse un compte rendu de retour d'atelier et prépare un dossier de preuve.

Il compare le compte rendu aux bons de livraison et de reprise du contrat, propose une imputation
(client, usure normale, dommage préexistant) et n'écrit que des brouillons : jamais de facture,
jamais de contact client. Les forfaits de retour viennent de la grille, en code.
"""

from __future__ import annotations

from pathlib import Path

from agent import pricing
from agent.llm_providers import LLMProvider, get_provider
from agent.llm_providers.base import ToolError, ToolSpec
from agent.mcp_bridge import (
    KitCaller,
    Trace,
    logged_spec,
    require_sources,
    require_str,
    to_text,
    wrap_data,
)

# Modèle de l'agent retour (le .env est partagé par tous les exercices).
# None : choix automatique selon les clés du .env / modèle et effort par défaut.
LLM_PROVIDER = "anthropic"
LLM_MODEL = "claude-haiku-5-5"
# Effort de raisonnement : low, medium, high, xhigh, max (traduit pour Gemini) ; ignoré par claude-haiku-4-5.
LLM_EFFORT = "medium"
# Longueur maximale d'une réponse du modèle (réflexion comprise chez Gemini) ; None : défaut du fournisseur.
LLM_MAX_TOKENS = 8000

AGENT_NAME = "retour"
PROMPT_PATH = Path(__file__).resolve().parent / "prompt_retour.md"
MAX_STEPS = 15


class ReturnTools:
    """Outils de l'agent retour pour un compte rendu ; appels et brouillons notés dans trace."""

    def __init__(self, kit: KitCaller, trace: Trace) -> None:
        self.kit = kit
        self.trace = trace

    def read_document(self, args: dict) -> str:
        reference = require_str(args, "reference")
        return wrap_data(reference, self.kit.call("lire_document", {"reference": reference}))

    def read_contract(self, args: dict) -> str:
        contract_id = require_str(args, "contract_id")
        return to_text(self.kit.call("contrat", {"contrat_id": contract_id}))

    def find_documents(self, args: dict) -> str:
        contract_id = require_str(args, "contract_id")
        return to_text(self.kit.call("rechercher_documents", {"contrat_id": contract_id}))

    def grid_fee(self, args: dict) -> str:
        try:
            return to_text(pricing.return_fee(require_str(args, "code")))
        except ValueError as error:
            raise ToolError(str(error)) from error

    def _draft(self, draft_type: str, args: dict) -> str:
        arguments = {
            "type_brouillon": draft_type,
            "cible": require_str(args, "target"),
            "contenu": require_str(args, "content"),
            "justification": require_str(args, "justification"),
            "sources": require_sources(args),
        }
        result = self.kit.call("creer_brouillon", arguments)
        self.trace.drafts.append(f"{draft_type}#{result['id']}")
        return to_text(result)

    def create_evidence_file(self, args: dict) -> str:
        return self._draft("dossier_litige", args)

    def ask_technician(self, args: dict) -> str:
        return self._draft("alerte", args)

    def specs(self) -> list[ToolSpec]:
        reference = {"type": "string", "description": "Ex. CR-2026-1044, BL-2026-0287."}
        contract = {"type": "string", "description": "Ex. LOC-2026-0121."}
        draft = {
            "target": {"type": "string", "description": "Contrat ou machine concerné."},
            "content": {"type": "string", "description": "Constat, imputation proposée, montants de la grille."},
            "justification": {"type": "string", "description": "Pourquoi, en citant les pièces."},
            "sources": {"type": "array", "items": {"type": "string"},
                        "description": "Références existantes (CR-…, BL-…, LOC-…, F-…)."},
        }
        draft_required = ["target", "content", "justification", "sources"]
        tools = [
            ("read_document", "Texte intégral d'un document (compte rendu, bon de livraison ou de reprise).",
             {"reference": reference}, ["reference"], self.read_document),
            ("read_contract", "Contrat avec machine, factures et documents rattachés.",
             {"contract_id": contract}, ["contract_id"], self.read_contract),
            ("find_documents", "Documents (bons, comptes rendus) rattachés à un contrat, avec extrait.",
             {"contract_id": contract}, ["contract_id"], self.find_documents),
            ("grid_fee", "Forfait de retour lu dans la grille : NET (nettoyage lourd) ou CAR (carburant).",
             {"code": {"type": "string", "enum": list(pricing.RETURN_FEE_CODES)}}, ["code"], self.grid_fee),
            ("create_evidence_file",
             "Crée un dossier de preuve en brouillon (validation humaine, aucune facturation).",
             draft, draft_required, self.create_evidence_file),
            ("ask_technician",
             "Crée une alerte en brouillon pour demander un complément à l'atelier (photo, chiffrage).",
             draft, draft_required, self.ask_technician),
        ]
        return [
            logged_spec(AGENT_NAME, self.trace, name, description,
                        {"type": "object", "properties": properties, "required": required}, handler)
            for name, description, properties, required, handler in tools
        ]


def make_provider() -> LLMProvider:
    """Fournisseur de l'agent retour, selon les réglages en tête de ce module."""
    return get_provider(
        provider=LLM_PROVIDER, model=LLM_MODEL, effort=LLM_EFFORT, max_tokens=LLM_MAX_TOKENS
    )


def run_return_agent(provider: LLMProvider, kit: KitCaller, report_ref: str, trace: Trace) -> str:
    """Traite un compte rendu ; renvoie la réponse finale du modèle (appels et brouillons notés dans trace)."""
    tools = ReturnTools(kit, trace)
    system = PROMPT_PATH.read_text(encoding="utf-8")
    return provider.run_agent(system, f"Compte rendu à traiter : {report_ref}", tools.specs(), max_steps=MAX_STEPS)
