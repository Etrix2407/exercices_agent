"""Tests du chiffrage en code d'après la grille du kit."""

import pytest

from agent.pricing import calc_quote, return_fee


def test_quote_is_days_times_daily_rate_plus_transport() -> None:
    quote = calc_quote("NCI", 5)
    assert (quote["location_ht"], quote["transport_ht"], quote["total_ht"]) == (750.0, 120.0, 870.0)


@pytest.mark.parametrize(("family", "days"), [("XXX", 3), ("TRA", 3), ("NCI", 0), ("NCI", -2), ("NCI", True)])
def test_invalid_quote_is_refused(family: str, days: int) -> None:
    with pytest.raises(ValueError):
        calc_quote(family, days)


def test_return_fee_reads_grid_and_refuses_other_codes() -> None:
    assert return_fee("NET")["tarif_ht_eur"] == 150.0
    with pytest.raises(ValueError):
        return_fee("MPE")
