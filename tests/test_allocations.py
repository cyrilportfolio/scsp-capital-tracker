"""Allocation rule and the cents it must not lose."""

from __future__ import annotations


from src import allocations, capital_calls, config


def test_shares_sum_to_one(fund):
    assert abs(float(allocations.shares(fund.investors).sum()) - 1.0) < 1e-12


def test_shares_follow_commitments(fund):
    part = allocations.shares(fund.investors)
    commitments = fund.investors.set_index("code")["engagement"]
    biggest = commitments.idxmax()
    assert part.idxmax() == biggest
    assert abs(part[biggest] - commitments[biggest] / commitments.sum()) < 1e-12


def test_an_amount_that_does_not_divide_is_still_fully_allocated(small_investors):
    """One euro between three equal partners: 0.34 + 0.33 + 0.33."""
    split = allocations.allocate(1.0, small_investors)
    assert round(float(split.sum()), 2) == 1.0
    assert sorted(round(v, 2) for v in split.values) == [0.33, 0.33, 0.34]


def test_allocation_never_leaves_a_residue(small_investors):
    for amount in (0.01, 1.0, 99.99, 12_345.67, 1_000_000.0, 7_777_777.77):
        split = allocations.allocate(amount, small_investors)
        assert round(float(split.sum()), 2) == round(amount, 2), amount


def test_a_negative_amount_is_allocated_too(small_investors):
    split = allocations.allocate(-1.0, small_investors)
    assert round(float(split.sum()), 2) == -1.0


def test_zero_allocates_to_zero(small_investors):
    split = allocations.allocate(0.0, small_investors)
    assert float(split.sum()) == 0.0


def test_every_call_is_fully_shared_between_partners(fund, pipeline):
    calls = pipeline["calls"]
    per_call = calls.groupby("appel").agg(
        reparti=("montant", "sum"), total=("montant_appel_total", "first"))
    ecart = (per_call["reparti"] - per_call["total"]).abs().max()
    assert ecart <= 0.005


def test_commitment_status_never_goes_negative(pipeline):
    assert (pipeline["status"]["non_appele"] >= -config.TOLERANCE).all()


def test_called_capital_matches_the_bank_account(fund, pipeline):
    from_bank = fund.cashflows.loc[
        fund.cashflows["type"] == config.CAPITAL_CALL, "montant"].sum()
    from_partners = pipeline["calls"]["montant"].sum()
    assert round(float(from_partners - from_bank), 2) == 0.0


def test_call_notice_lists_every_partner(fund, pipeline):
    reference = pipeline["calls"]["appel"].iloc[0]
    notice = capital_calls.call_notice(pipeline["calls"], fund.investors, reference)
    assert len(notice) == len(fund.investors)
    assert (notice["date_limite_paiement"] > notice["date"]).all()
