"""Tests du filtre des machines libres."""

from agent.machine_filter import usable_machines

END = "2026-10-24"


def machine(reference: str, **overrides) -> dict:
    base = {
        "reference_machine": reference,
        "statut_declare": "disponible",
        "date_dernier_retour": "2026-09-01",
        "controle_retour_fait": "oui",
        "prochaine_echeance_controle": "2027-01-01",
    }
    return base | overrides


def test_filter_keeps_ready_machines_and_explains_exclusions() -> None:
    free = [
        machine("OK-1"),
        machine("NEUVE", date_dernier_retour=None, controle_retour_fait=None),
        machine("MAINT", statut_declare="en maintenance"),
        machine("SANS-CTRL", controle_retour_fait="non"),
        machine("ECHUE", prochaine_echeance_controle="2026-10-10"),
    ]
    usable, excluded = usable_machines(free, END)
    assert [m["reference_machine"] for m in usable] == ["OK-1", "NEUVE"]
    reasons = {item["reference_machine"]: item["raison"] for item in excluded}
    assert set(reasons) == {"MAINT", "SANS-CTRL", "ECHUE"}
    assert "échu" in reasons["ECHUE"]
