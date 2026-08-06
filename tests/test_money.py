"""
Unit tests for app/services/money.py — integer minor-unit money pipeline.

Covers:
- parse_to_minor_units: SGD/EUR/MYR (2 decimal), JPY (0 decimal), rounding,
  invalid input (zero, negative, non-numeric)
- format_from_minor_units: SGD 2-decimal formatting, JPY no-decimal formatting
"""

import pytest

from app.services.money import parse_to_minor_units, format_from_minor_units, CURRENCY_DECIMALS


class TestCurrencyDecimals:
    def test_sgd_has_2_decimals(self):
        assert CURRENCY_DECIMALS["SGD"] == 2

    def test_usd_has_2_decimals(self):
        assert CURRENCY_DECIMALS["USD"] == 2

    def test_myr_has_2_decimals(self):
        assert CURRENCY_DECIMALS["MYR"] == 2

    def test_eur_has_2_decimals(self):
        assert CURRENCY_DECIMALS["EUR"] == 2

    def test_jpy_has_0_decimals(self):
        assert CURRENCY_DECIMALS["JPY"] == 0

    def test_idr_has_0_decimals(self):
        """Indonesian rupiah has no minor unit — Rp 288400 stays 288400."""
        assert CURRENCY_DECIMALS["IDR"] == 0

    def test_thb_has_2_decimals(self):
        """Thai baht has 2 decimal places (satang)."""
        assert CURRENCY_DECIMALS["THB"] == 2


class TestParseToMinorUnits:
    def test_sgd_two_decimals(self):
        assert parse_to_minor_units("12.50", "SGD") == 1250

    def test_eur_two_decimals(self):
        assert parse_to_minor_units("9.99", "EUR") == 999

    def test_jpy_no_decimals(self):
        """JPY has 0 minor-unit places — 1500 yen stays 1500, NOT 150000."""
        assert parse_to_minor_units("1500", "JPY") == 1500

    def test_myr_two_decimals(self):
        assert parse_to_minor_units("5.5", "MYR") == 550

    def test_idr_no_decimals(self):
        """IDR has 0 minor-unit places — Rp 288400 stays 288400, NOT 28840000."""
        assert parse_to_minor_units("288400", "IDR") == 288400

    def test_thb_two_decimals(self):
        assert parse_to_minor_units("7403.33", "THB") == 740333

    def test_usd_whole_number(self):
        assert parse_to_minor_units("10", "USD") == 1000

    def test_rounding_half_up(self):
        """1.005 SGD should round to 101 cents (ROUND_HALF_UP), not 100 (float)."""
        assert parse_to_minor_units("1.005", "SGD") == 101

    def test_zero_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_to_minor_units("0", "SGD")

    def test_negative_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_to_minor_units("-3", "SGD")

    def test_non_numeric_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_to_minor_units("abc", "SGD")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_to_minor_units("", "SGD")

    def test_jpy_small_amount(self):
        assert parse_to_minor_units("100", "JPY") == 100


class TestFormatFromMinorUnits:
    def test_sgd_formats_with_2_decimals(self):
        assert format_from_minor_units(1250, "SGD") == "12.50"

    def test_jpy_formats_as_integer(self):
        """JPY has no decimal places — 1500 minor units is ¥1500."""
        assert format_from_minor_units(1500, "JPY") == "1500"

    def test_usd_formats_with_2_decimals(self):
        assert format_from_minor_units(999, "USD") == "9.99"

    def test_myr_formats_with_2_decimals(self):
        assert format_from_minor_units(550, "MYR") == "5.50"

    def test_eur_formats_with_2_decimals(self):
        assert format_from_minor_units(100, "EUR") == "1.00"
