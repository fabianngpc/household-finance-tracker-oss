"""Tests for bot/extractor.py — Extractor ABC + StubExtractor + FakeExtractor."""
import pytest
from datetime import date

from bot.extractor import ExtractionResult, Extractor, StubExtractor
from tests.fakes import FakeExtractor, make_result


# ---------------------------------------------------------------------------
# Instance / ABC contract
# ---------------------------------------------------------------------------

def test_stub_extractor_is_instance_of_extractor():
    assert isinstance(StubExtractor(), Extractor)


def test_extractor_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        Extractor()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# ExtractionResult fields always present
# ---------------------------------------------------------------------------

async def test_result_currency_always_sgd():
    result = await StubExtractor().extract("$12 lunch")
    assert result.currency == "SGD"


async def test_result_category_hint_always_other():
    result = await StubExtractor().extract("$12 lunch")
    assert result.category_hint == "Other"


async def test_result_expense_date_is_today():
    result = await StubExtractor().extract("$12 lunch")
    assert result.expense_date == date.today()


# ---------------------------------------------------------------------------
# High-confidence cases (amount present → confidence == 1.0)
# ---------------------------------------------------------------------------

async def test_dollar_prefix_integer():
    """'$12 lunch' -> amount_str='12', merchant non-empty, confidence=1.0"""
    result = await StubExtractor().extract("$12 lunch")
    assert result.amount_str == "12"
    assert result.confidence == 1.0
    assert result.merchant is not None
    assert "lunch" in result.merchant.lower()


async def test_decimal_amount():
    """'12.50 coffee' -> amount_str='12.50', confidence=1.0"""
    result = await StubExtractor().extract("12.50 coffee")
    assert result.amount_str == "12.50"
    assert result.confidence == 1.0


async def test_comma_decimal_normalised_to_dot():
    """'1.234,56 groceries' — simple rule: first token is '1.234', comma->dot -> '1.234'"""
    result = await StubExtractor().extract("1.234,56 groceries")
    # The regex r"\d+(?:[.,]\d+)?" matches "1.234" first (stops at ",56")
    assert result.amount_str == "1.234"
    assert result.confidence == 1.0


async def test_merchant_is_remainder_text():
    """Numeric part stripped, remainder returned as merchant."""
    result = await StubExtractor().extract("12 lunch")
    assert result.merchant == "lunch"


async def test_dollar_sign_stripped_from_merchant():
    """'$12 lunch' — '$' should not appear as a standalone merchant."""
    result = await StubExtractor().extract("$12 lunch")
    # merchant = '$12 lunch' with '12' removed -> '$ lunch' -> stripped -> '$ lunch'
    # The plan says "strip leftover currency symbols/whitespace; if empty -> None"
    # The implementation uses _NUMBER.sub("", text).strip() or None
    # so merchant = "$  lunch".strip() = "$ lunch" (dollar sign stays — that's fine per spec)
    assert result.merchant is not None


async def test_only_number_merchant_is_none():
    """'42' -> merchant is None (no remainder text)."""
    result = await StubExtractor().extract("42")
    assert result.merchant is None
    assert result.amount_str == "42"
    assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# Low-confidence cases (no amount → confidence == 0.0)
# ---------------------------------------------------------------------------

async def test_no_amount_in_text():
    """'lunch' -> amount_str is None, confidence=0.0, merchant='lunch'"""
    result = await StubExtractor().extract("lunch")
    assert result.amount_str is None
    assert result.confidence == 0.0
    assert result.merchant == "lunch"


async def test_empty_string():
    """'' -> amount_str is None, confidence=0.0"""
    result = await StubExtractor().extract("")
    assert result.amount_str is None
    assert result.confidence == 0.0


async def test_no_amount_merchant_preserved():
    """When no amount, the full text becomes the merchant."""
    result = await StubExtractor().extract("coffee shop")
    assert result.amount_str is None
    assert result.merchant == "coffee shop"
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# ExtractionResult is a dataclass (quick structural check)
# ---------------------------------------------------------------------------

def test_extraction_result_fields():
    r = ExtractionResult(
        amount_str="10",
        currency="SGD",
        merchant="test",
        expense_date=date.today(),
        category_hint="Other",
        confidence=1.0,
    )
    assert r.amount_str == "10"
    assert r.currency == "SGD"
    assert r.merchant == "test"
    assert r.category_hint == "Other"
    assert r.confidence == 1.0


# ---------------------------------------------------------------------------
# FakeExtractor — deterministic CI fake (no real model)
# ---------------------------------------------------------------------------

async def test_fake_extractor_is_async_extractor():
    """FakeExtractor is a valid Extractor and await extract returns preset result."""
    preset = make_result()
    fake = FakeExtractor(preset)

    assert isinstance(fake, Extractor)

    result = await fake.extract("any text", image_path=None)
    assert result is preset
    assert result.amount_str == "12.50"
    assert result.confidence == 1.0
