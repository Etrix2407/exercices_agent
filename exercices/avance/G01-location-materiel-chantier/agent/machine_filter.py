"""Filtre en code des machines renvoyées par machines_libres (le kit ne les interprète pas)."""

from __future__ import annotations

AVAILABLE_STATUS = "disponible"


def exclusion_reason(machine: dict, end_date: str) -> str | None:
    """Raison d'écarter une machine sur la période, ou None si elle peut être proposée."""
    if machine.get("statut_declare") != AVAILABLE_STATUS:
        return f"statut déclaré « {machine.get('statut_declare')} »"
    # Machine déjà revenue de location : le contrôle de retour doit avoir été fait.
    if machine.get("date_dernier_retour") and machine.get("controle_retour_fait") != "oui":
        return "contrôle de retour non fait"
    deadline = machine.get("prochaine_echeance_controle")
    if deadline and deadline < end_date:
        return f"contrôle réglementaire échu le {deadline}"
    return None


def usable_machines(free: list[dict], end_date: str) -> tuple[list[dict], list[dict]]:
    """Sépare les machines proposables et les machines écartées (avec la raison)."""
    usable, excluded = [], []
    for machine in free:
        reason = exclusion_reason(machine, end_date)
        if reason is None:
            usable.append(machine)
        else:
            excluded.append({"reference_machine": machine.get("reference_machine"), "raison": reason})
    return usable, excluded
