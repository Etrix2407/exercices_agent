"""Agent devis : propose une machine libre et contrôlée pour une demande d'agence, sans rien réserver.

Le prix n'est calculé qu'en code (pricing.calc_quote) et seulement si la durée est connue.
La seule écriture possible est un brouillon de mail dans boite/outbox/.
"""

from __future__ import annotations

import re
from datetime import date
from email.utils import formataddr, getaddresses
from pathlib import Path

from agent import pricing, text_checks
from agent.answers import parse_answer
from agent.llm_providers import LLMProvider, get_provider
from agent.llm_providers.base import ToolError, ToolSpec
from agent.machine_filter import out_of_service_machines, usable_machines
from agent.mcp_bridge import (
    KitCaller,
    Trace,
    logged_spec,
    require_str,
    to_text,
    wrap_data,
)

# Modèle de l'agent devis (le .env est partagé par tous les exercices).
# None : choix automatique selon les clés du .env / modèle et effort par défaut.
LLM_PROVIDER = "anthropic"
LLM_MODEL = "claude-haiku-5-5"
# Effort de raisonnement : low, medium, high, xhigh, max (traduit pour Gemini) ;
# ignoré par les modèles qui ne le prennent pas en charge (ex. claude-haiku-4-5).
LLM_EFFORT = "medium"
# Longueur maximale d'une réponse du modèle (réflexion comprise chez Gemini) ; None : défaut du fournisseur.
LLM_MAX_TOKENS = 8000

AGENT_NAME = "devis"
PROMPT_PATH = Path(__file__).resolve().parent / "prompt_devis.md"
AGENCIES = ("LYS", "GRE", "MRS", "TLS", "BDX")
MAX_STEPS = 15
# Statuts qui exigent un brouillon ; sans brouillon, l'agent est relancé une seule fois.
DRAFT_STATUSES = ("precisions_requises", "proposition")
DRAFT_REMINDER = (
    "\n\nRappel : ta réponse précédente avait le statut « {statut} » sans brouillon. "
    "Pour ce statut, le brouillon est obligatoire : appelle draft_reply avant de répondre."
)
# Champs de la fiche machine qui révèlent clients et chantiers : retirés avant de la montrer au modèle.
PRIVATE_SHEET_KEYS = ("contrats", "documents")
QUOTE_AMOUNT_KEYS = ("tarif_jour_ht", "location_ht", "transport_ht", "total_ht")
# requete_sql coupe à 200 lignes : seuls les comptes rendus de la famille, les plus récents d'abord.
RETURN_REPORTS_SQL = (
    "SELECT reference, reference_machine, date_document, texte FROM documents "
    "WHERE type = 'compte_rendu_retour' AND reference_machine LIKE '{code}-%' ORDER BY date_document DESC"
)
FAMILY_CODE = re.compile(r"[A-Z]{3}")
# Référence de machine citée dans un brouillon (NCI-004) : seulement celles déclarées proposables par le code.
MACHINE_REFERENCE = re.compile(r"\b[A-Z]{3}-\d{3}\b", re.IGNORECASE)
# Nombre de jours cité dans un brouillon (« vos 5 jours ») : doit correspondre à un devis calculé.
DAYS_MENTION = re.compile(r"\b(\d+)\s*jours?\b")
# Date de référence du kit : aucune location ne commence avant.
REFERENCE_DATE = date(2026, 10, 14)
# Au-delà, la location est hors périmètre (renvoyée au chargé d'affaires).
MAX_RENTAL_DAYS = 90
MAX_SUBJECT_CHARS = 200


def return_reports_sql(family_code: str) -> str:
    """Requête des comptes rendus de retour d'une famille, construite en code à partir d'un code validé."""
    if not FAMILY_CODE.fullmatch(family_code):
        raise ValueError(f"Code famille invalide : {family_code!r}.")
    return RETURN_REPORTS_SQL.format(code=family_code)


def parse_date(args: dict, key: str) -> date:
    """Date AAAA-MM-JJ d'un argument d'outil."""
    try:
        return date.fromisoformat(args[key])
    except (TypeError, ValueError) as error:
        raise ToolError(f"'{key}' doit être une date AAAA-MM-JJ.") from error


def single_recipient(sender: object) -> str:
    """Adresse unique de l'expéditeur, au format « Nom <adresse> » ; ToolError s'il n'y en a pas une et une seule."""
    found = [(name, address) for name, address in getaddresses([str(sender or "")]) if "@" in address]
    if len(found) != 1:
        raise ToolError(
            f"Brouillon refusé : l'expéditeur du mail doit avoir une seule adresse, {len(found)} trouvée(s). "
            "Ne réponds pas : la demande passe à un humain."
        )
    return formataddr(found[0])


def rental_families() -> dict[str, str]:
    """Familles louables de la grille : {code: libellé}."""
    return {code: line["libelle"] for code, line in pricing.load_grid().items() if line["type_ligne"] == "location"}


class QuoteTools:
    """Outils de l'agent devis pour un seul mail ; appels, brouillons et machines proposables notés dans trace.

    Garanties en code, quoi que dise le modèle : seul le mail traité est lisible, la réponse part à son
    expéditeur, et le brouillon ne cite ni remise ni montant autre que ceux calculés par calc_quote.
    """

    def __init__(self, kit: KitCaller, trace: Trace, mail_id: str) -> None:
        self.kit = kit
        self.families = rental_families()
        self.trace = trace
        self.mail_id = mail_id
        # Montants calculés par le code (calc_quote) : les seuls que le brouillon peut citer.
        self.quoted_amounts: set[float] = set()
        # Périodes vérifiées par find_machines pour chaque famille : (début, fin ou None si inconnue).
        self.checked_periods: dict[str, set[tuple[date, date | None]]] = {}
        # Nombres de jours chiffrés par calc_quote : les seuls qu'un brouillon chiffré peut citer.
        self.quoted_days: set[int] = set()

    def read_request(self, args: dict) -> str:
        mail_id = require_str(args, "mail_id")
        if mail_id != self.mail_id:
            raise ToolError(f"Seul le mail « {self.mail_id} » peut être lu pour cette demande.")
        return wrap_data(mail_id, self.kit.call("lire_mail", {"identifiant": mail_id}))

    def find_machines(self, args: dict) -> str:
        code = require_str(args, "family_code")
        if code not in self.families:
            raise ToolError(f"Famille inconnue : {code}. Codes : {', '.join(self.families)}.")
        start = parse_date(args, "start_date")
        # Durée inconnue : disponibilité vérifiée sur la seule date de début.
        end = parse_date(args, "end_date") if args.get("end_date") else None
        if end is not None and end < start:
            raise ToolError("end_date doit être postérieure ou égale à start_date.")
        if start < REFERENCE_DATE:
            raise ToolError(f"start_date antérieure à la date de référence {REFERENCE_DATE} : rien à chiffrer.")
        if end is not None and (end - start).days + 1 > MAX_RENTAL_DAYS:
            raise ToolError(
                f"Location de plus de {MAX_RENTAL_DAYS} jours : hors périmètre, renvoyée au chargé d'affaires."
            )
        last_day = (end or start).isoformat()
        arguments = {"famille": self.families[code], "date_debut": start.isoformat(), "date_fin": last_day}
        if args.get("agency"):
            arguments["agence"] = args["agency"]
        free = self.kit.call("machines_libres", arguments)["machines"]
        reports = self.kit.call("requete_sql", {"sql": return_reports_sql(code)})["lignes"]
        usable, excluded = usable_machines(free, last_day, out_of_service_machines(reports))
        # Périodes retenues pour calc_quote : le nombre de jours chiffré doit correspondre à l'une d'elles.
        self.checked_periods.setdefault(code, set()).add((start, end))
        self.trace.proposable.update(machine["reference_machine"] for machine in usable)
        return to_text({"proposables": usable, "ecartees": excluded})

    def machine_sheet(self, args: dict) -> str:
        reference = require_str(args, "reference")
        sheet = self.kit.call("fiche_machine", {"reference": reference})
        # Les contrats et documents (clients, chantiers) ne servent pas au devis : jamais montrés au modèle.
        public = {key: value for key, value in sheet.items() if key not in PRIVATE_SHEET_KEYS}
        return wrap_data(reference, public)

    def calc_quote(self, args: dict) -> str:
        days = args.get("days")
        # Certains fournisseurs renvoient les entiers JSON en flottants (5.0).
        if isinstance(days, float) and days.is_integer():
            days = int(days)
        code = require_str(args, "family_code")
        periods = self.checked_periods.get(code)
        if not periods:
            raise ToolError(f"Vérifier d'abord la disponibilité avec find_machines pour la famille {code}.")
        lengths = sorted({(end - start).days + 1 for start, end in periods if end is not None})
        if not lengths:
            raise ToolError(
                "Durée inconnue : find_machines a été appelé sans end_date. Si la demande donne une date "
                "de fin, rappelle find_machines avec end_date puis calc_quote ; sinon ne chiffre pas et "
                "demande la durée dans le brouillon."
            )
        if isinstance(days, int) and days > MAX_RENTAL_DAYS:
            raise ToolError(f"Plus de {MAX_RENTAL_DAYS} jours : hors périmètre, renvoyée au chargé d'affaires.")
        if days not in lengths:
            raise ToolError(
                f"days doit valoir {' ou '.join(map(str, lengths))} : nombre de jours (bornes incluses) "
                "d'une période vérifiée par find_machines."
            )
        try:
            quote = pricing.calc_quote(code, days)
        except ValueError as error:
            raise ToolError(str(error)) from error
        self.quoted_amounts.update(quote[key] for key in QUOTE_AMOUNT_KEYS)
        self.quoted_days.add(days)
        return to_text(quote)

    def check_body(self, body: str) -> None:
        """Refuse (ToolError) un corps trop long, avec remise, montant ou durée non calculés, machine non
        proposable ou engagement ferme."""
        too_long = text_checks.length_problem(body)
        if too_long:
            raise ToolError(f"Brouillon refusé : trop long ({too_long}).")
        problem = text_checks.discount_problem(body)
        if problem:
            raise ToolError(f"Brouillon refusé ({problem}) : aucune remise ni pourcentage, prix de la grille seulement.")
        problem = text_checks.amount_problem(body, self.quoted_amounts)
        if problem:
            raise ToolError(
                f"Brouillon refusé : {problem}. Ne cite que les montants en euros renvoyés par calc_quote, "
                "écrits en chiffres, ou aucun montant."
            )
        if text_checks.amounts(body):
            mentioned = {int(value) for value in DAYS_MENTION.findall(text_checks.plain(body))}
            days = sorted(mentioned - self.quoted_days)
            if days:
                raise ToolError(
                    f"Brouillon refusé : durée de {days} jour(s) citée avec un prix, mais calc_quote n'a chiffré "
                    f"que {sorted(self.quoted_days) or 'aucune durée'}."
                )
        cited = {reference.upper() for reference in MACHINE_REFERENCE.findall(text_checks.normalize(body))}
        unknown = sorted(cited - self.trace.proposable)
        if unknown:
            raise ToolError(
                f"Brouillon refusé : machine(s) {', '.join(unknown)} non déclarée(s) proposable(s) par find_machines."
            )
        problem = text_checks.commitment_problem(body)
        if problem:
            raise ToolError(
                f"Brouillon refusé ({problem}) : rien n'est réservé ni garanti, la proposition reste à confirmer."
            )

    def draft_reply(self, args: dict) -> str:
        body = require_str(args, "body")
        subject = require_str(args, "subject")
        if len(subject) > MAX_SUBJECT_CHARS:
            raise ToolError(f"Objet refusé : {MAX_SUBJECT_CHARS} caractères au plus.")
        self.check_body(body)
        # Destinataire et fil imposés par le code : la réponse ne part qu'à l'expéditeur du mail traité,
        # à une seule adresse (un en-tête From à plusieurs adresses ne peut pas ajouter de destinataire).
        mail = self.kit.call("lire_mail", {"identifiant": self.mail_id})
        arguments = {
            "a": single_recipient(mail.get("de")),
            "sujet": subject,
            "corps": body,
            "service": "planification",
            "en_reponse_a": self.mail_id,
        }
        result = self.kit.call("brouillon_mail", arguments)
        self.trace.drafts.append(result["id"])
        return to_text(result)

    def specs(self) -> list[ToolSpec]:
        date = {"type": "string", "description": "AAAA-MM-JJ"}
        family = {"type": "string", "enum": list(self.families), "description": "Code famille de la grille."}
        tools = [
            ("read_request", "Lit le mail de demande d'une agence.",
             {"mail_id": {"type": "string", "description": "Ex. demande_08."}}, ["mail_id"], self.read_request),
            ("find_machines",
             ("Machines libres sur la période, déjà filtrées (statut, contrôle de retour, contrôle réglementaire, "
              "hors service selon l'atelier). "
              "Sans agence : toutes les agences. Sans end_date : la seule date de début."),
             {"family_code": family, "start_date": date, "end_date": date,
              "agency": {"type": "string", "enum": list(AGENCIES)}},
             ["family_code", "start_date"], self.find_machines),
            ("machine_sheet", "Fiche d'une machine : catalogue et contrôle réglementaire.",
             {"reference": {"type": "string", "description": "Ex. NCI-004."}}, ["reference"], self.machine_sheet),
            ("calc_quote",
             ("Calcule le devis HT d'après la grille (seule source de prix). Durée connue uniquement : "
              "après find_machines, days = nombre de jours de la période vérifiée, bornes incluses."),
             {"family_code": family, "days": {"type": "integer", "minimum": 1, "maximum": MAX_RENTAL_DAYS}},
             ["family_code", "days"], self.calc_quote),
            ("draft_reply",
             ("Prépare un brouillon de réponse à l'expéditeur du mail traité (jamais envoyé). "
              "Refusé s'il cite une remise, un pourcentage, un montant non calculé par calc_quote, une machine "
             "non proposable ou un engagement ferme (disponibilité garantie, réservation)."),
             {"subject": {"type": "string"}, "body": {"type": "string"}},
             ["subject", "body"], self.draft_reply),
        ]
        return [
            logged_spec(AGENT_NAME, self.trace, name, description,
                        {"type": "object", "properties": properties, "required": required}, handler)
            for name, description, properties, required, handler in tools
        ]


def make_provider() -> LLMProvider:
    """Fournisseur de l'agent devis, selon les réglages en tête de ce module."""
    return get_provider(
        provider=LLM_PROVIDER, model=LLM_MODEL, effort=LLM_EFFORT, max_tokens=LLM_MAX_TOKENS
    )


def run_quote_agent(provider: LLMProvider, kit: KitCaller, mail_id: str, trace: Trace) -> str:
    """Traite une demande ; renvoie la réponse finale du modèle (appels et brouillons notés dans trace)."""
    tools = QuoteTools(kit, trace, mail_id)
    system = PROMPT_PATH.read_text(encoding="utf-8")
    user = f"Demande à traiter : {mail_id}"
    specs = tools.specs()
    answer = provider.run_agent(system, user, specs, max_steps=MAX_STEPS)
    status = parse_answer(answer).get("statut")
    if status in DRAFT_STATUSES and not trace.drafts:
        # Relance unique : le brouillon est obligatoire pour ce statut.
        user += DRAFT_REMINDER.format(statut=status)
        return provider.run_agent(system, user, specs, max_steps=MAX_STEPS)
    return answer
