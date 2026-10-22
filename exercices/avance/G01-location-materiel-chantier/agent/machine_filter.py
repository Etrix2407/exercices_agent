"""Filtre en code des machines renvoyées par machines_libres (le kit ne les interprète pas)."""

from __future__ import annotations

import re

AVAILABLE_STATUS = "disponible"
# Mentions d'un compte rendu de retour qui retirent la machine de la location.
OUT_OF_SERVICE = re.compile(r"hors (service|location)", re.IGNORECASE)


def out_of_service_machines(reports: list[dict]) -> dict[str, str]:
    """Machines dont le dernier compte rendu de retour les dit hors service : {machine: référence du CR}.

    reports : lignes {reference, reference_machine, date_document, texte} des comptes rendus de retour.
    """
    latest: dict[str, dict] = {}
    for report in sorted(reports, key=lambda item: item.get("date_document") or ""):
        latest[report["reference_machine"]] = report
    return {
        machine: report["reference"]
        for machine, report in latest.items()
        if OUT_OF_SERVICE.search(report.get("texte") or "")
    }


def exclusion_reason(machine: dict, end_date: str, out_of_service: dict[str, str]) -> str | None:
    """Raison d'écarter une machine sur la période, ou None si elle peut être proposée."""
    if machine.get("statut_declare") != AVAILABLE_STATUS:
        return f"statut déclaré « {machine.get('statut_declare')} »"
    # Machine déjà revenue de location : le contrôle de retour doit avoir été fait.
    if machine.get("date_dernier_retour") and machine.get("controle_retour_fait") != "oui":
        return "contrôle de retour non fait"
    deadline = machine.get("prochaine_echeance_controle")
    if deadline and deadline < end_date:
        return f"contrôle réglementaire échu le {deadline}"
    # Le statut déclaré peut être faux : le compte rendu d'atelier fait foi.
    report = out_of_service.get(machine.get("reference_machine"))
    if report:
        return f"hors service selon {report}"
    return None


def usable_machines(
    free: list[dict], end_date: str, out_of_service: dict[str, str] | None = None
) -> tuple[list[dict], list[dict]]:
    """Sépare les machines proposables et les machines écartées (avec la raison)."""
    usable, excluded = [], []
    for machine in free:
        reason = exclusion_reason(machine, end_date, out_of_service or {})
        if reason is None:
            usable.append(machine)
        else:
            excluded.append({"reference_machine": machine.get("reference_machine"), "raison": reason})
    return usable, excluded
