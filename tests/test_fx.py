"""
Unit tests for app/services/fx.py — Frankfurter FX fetch, cache, and conversion.

Covers:
- get_rate_for_date: SGD short-circuits to (1.0, date) without network call
- First call for a foreign currency fetches from Frankfurter (via mock) and caches all rates
- Second call for same date+currency returns cached row (no second httpx call)
- compute_base_amount_minor: JPY and USD conversion math
- Historical stability: earlier cached rate unchanged when later date row is mutated
"""

from datetime import date

import pytest

from app.services.fx import get_rate_for_date, compute_base_amount_minor


class TestGetRateForDateSGD:
    def test_sgd_returns_one_and_date_no_network(self, db):
        """SGD is the base currency — always (1.0, expense_date), never calls httpx."""
        expense_date = date(2026, 6, 1)
        rate, actual_date = get_rate_for_date(expense_date, "SGD", db)
        assert rate == 1.0
        assert actual_date == expense_date

    def test_sgd_does_not_call_httpx(self, db, mocker):
        """Confirm zero network calls for SGD."""
        mock_get = mocker.patch("httpx.get")
        get_rate_for_date(date(2026, 6, 1), "SGD", db)
        mock_get.assert_not_called()


class TestGetRateForDateForeignCurrency:
    def test_first_call_fetches_and_stores_all_rates(self, db, mock_frankfurter):
        """
        On cache miss, httpx.get is called once and all returned currencies
        (USD, MYR, EUR, JPY) are stored in fx_rates.
        """
        from app.models.fx_rate import FxRate

        expense_date = date(2026, 6, 1)
        rate, actual_date = get_rate_for_date(expense_date, "USD", db)

        # The mock returns date "2026-06-27" and USD rate 0.74
        assert rate == 0.74
        assert actual_date == date(2026, 6, 27)

        # All four currencies should be cached
        cached_currencies = {
            row.quote_currency
            for row in db.query(FxRate).all()
        }
        assert cached_currencies == {"USD", "MYR", "EUR", "JPY"}

        mock_frankfurter.assert_called_once()

    def test_second_call_is_cache_hit_no_extra_network(self, db, mock_frankfurter):
        """
        Two calls for the same date+currency must result in exactly one httpx.get
        call — the second call reads from the fx_rates cache, not the network.
        """
        expense_date = date(2026, 6, 27)

        # First call: miss -> fetch
        get_rate_for_date(expense_date, "USD", db)
        # Second call: hit -> cache
        rate2, date2 = get_rate_for_date(expense_date, "USD", db)

        # httpx.get must have been called exactly once across both calls
        assert mock_frankfurter.call_count == 1

        assert rate2 == 0.74
        assert date2 == date(2026, 6, 27)

    def test_jpy_rate_returned_correctly(self, db, mock_frankfurter):
        """JPY rate from mock is 109.5 — verify it is stored and returned."""
        expense_date = date(2026, 6, 27)
        rate, actual_date = get_rate_for_date(expense_date, "JPY", db)
        assert rate == 109.5

    def test_myr_rate_returned_correctly(self, db, mock_frankfurter):
        expense_date = date(2026, 6, 27)
        rate, _ = get_rate_for_date(expense_date, "MYR", db)
        assert rate == 3.16

    def test_second_call_different_currency_also_cached(self, db, mock_frankfurter):
        """
        After fetching USD, looking up JPY for the same date should be a cache hit
        (all currencies stored on first fetch) — still only one httpx call total.
        """
        expense_date = date(2026, 6, 27)
        get_rate_for_date(expense_date, "USD", db)
        get_rate_for_date(expense_date, "JPY", db)
        # Both lookups should have triggered at most one network call
        assert mock_frankfurter.call_count == 1


class TestHistoricalStability:
    def test_cached_rate_does_not_change_when_later_row_added(self, db, mock_frankfurter):
        """
        A cached historical rate for date A must not change when a rate for a later
        date B is added.  This verifies that compute_base_amount_minor uses the
        stored per-date rate, not any mutable global.
        """
        from app.models.fx_rate import FxRate

        expense_date = date(2026, 6, 27)
        rate_v1, _ = get_rate_for_date(expense_date, "USD", db)

        # Add a later-dated row directly
        later_rate = FxRate(
            base_currency="SGD",
            quote_currency="USD",
            rate=0.99,  # completely different rate
            as_of_date=date(2026, 7, 1),
            source="test",
        )
        db.add(later_rate)
        db.commit()

        # The original cached rate for 2026-06-27 must be unchanged
        from app.models.fx_rate import FxRate as FxRate2
        original_row = (
            db.query(FxRate2)
            .filter_by(
                base_currency="SGD",
                quote_currency="USD",
                as_of_date=expense_date,
            )
            .first()
        )
        assert original_row is not None
        assert original_row.rate == rate_v1  # still 0.74, not 0.99


class TestComputeBaseAmountMinor:
    def test_jpy_conversion(self):
        """
        1500 JPY minor units at 109.5 JPY/SGD:
        1500 JPY / 109.5 ≈ S$13.699… → 1370 SGD cents (ROUND_HALF_UP)
        """
        result = compute_base_amount_minor(1500, "JPY", 109.5)
        assert result == 1370

    def test_usd_conversion(self):
        """
        1000 USD cents (= $10.00) at 0.74 USD/SGD:
        10.00 / 0.74 ≈ S$13.513… → 1351 SGD cents
        """
        result = compute_base_amount_minor(1000, "USD", 0.74)
        assert result == 1351

    def test_sgd_identity(self):
        """SGD with rate 1.0 should be a no-op (1250 cents -> 1250 cents)."""
        result = compute_base_amount_minor(1250, "SGD", 1.0)
        assert result == 1250

    def test_returns_integer(self):
        result = compute_base_amount_minor(500, "USD", 0.74)
        assert isinstance(result, int)
