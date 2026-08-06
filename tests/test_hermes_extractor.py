"""Tests for bot/hermes_extractor.py — HermesExtractor + VLMExtractor.

All tests mock httpx.AsyncClient.post and bot.hermes_extractor.apple_vision_ocr
so no real Ollama or Vision framework calls happen in CI.
"""
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CATEGORIES = ["Food", "Transport", "Groceries", "Other"]


def _raw_json(
    amount_str="12.50",
    currency="SGD",
    merchant="Lunch",
    expense_date="2025-06-12",
    category_hint="Food",
    confidence_amount=0.95,
    confidence_date=0.9,
    confidence_merchant=0.8,
    confidence_category=0.85,
) -> str:
    return json.dumps(
        {
            "amount_str": amount_str,
            "currency": currency,
            "merchant": merchant,
            "expense_date": expense_date,
            "category_hint": category_hint,
            "confidence_amount": confidence_amount,
            "confidence_date": confidence_date,
            "confidence_merchant": confidence_merchant,
            "confidence_category": confidence_category,
        }
    )


def _patch_httpx(mocker, raw_json_str: str) -> MagicMock:
    """Patch httpx.AsyncClient so POST returns a mock response with raw_json_str."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": raw_json_str}}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# HermesExtractor: ABC contract
# ---------------------------------------------------------------------------


def test_hermes_extractor_is_extractor():
    """HermesExtractor subclasses the Extractor ABC."""
    from bot.extractor import Extractor
    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    assert isinstance(extractor, Extractor)


# ---------------------------------------------------------------------------
# HermesExtractor: text path
# ---------------------------------------------------------------------------


async def test_hermes_text_path_returns_parsed_fields(mocker):
    """Text path POSTs to Ollama and returns a parsed ExtractionResult."""
    _patch_httpx(mocker, _raw_json())

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("Lunch $12.50")

    assert result.amount_str == "12.50"
    assert result.currency == "SGD"
    assert result.merchant == "Lunch"
    # Parseable amount triggers validation override → confidence_amount >= 0.9
    assert result.confidence_amount >= 0.9


async def test_hermes_text_path_calls_ollama_api(mocker):
    """Text path issues exactly one POST to /api/chat."""
    mock_client = _patch_httpx(mocker, _raw_json())

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    await extractor.extract("test message")

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "/api/chat" in call_args[0][0]


# ---------------------------------------------------------------------------
# HermesExtractor: photo / OCR path
# ---------------------------------------------------------------------------


async def test_hermes_photo_path_calls_apple_vision_ocr(mocker):
    """Photo path calls apple_vision_ocr with the provided image_path."""
    _patch_httpx(mocker, _raw_json())
    mock_ocr = mocker.patch(
        "bot.hermes_extractor.apple_vision_ocr", return_value="Receipt OCR text"
    )

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    await extractor.extract("", image_path="receipt.jpg")

    mock_ocr.assert_called_once_with("receipt.jpg")


async def test_hermes_photo_path_uses_receipt_grand_total_prompt(mocker):
    """Photo path augments the system prompt with receipt/grand-total guidance.

    Receipt OCR text is full of line items and subtotals; without explicit
    guidance the model grabs the first item or the pre-tax subtotal instead of
    the final total. The receipt-mode system prompt must steer it to the total.
    """
    mock_client = _patch_httpx(mocker, _raw_json())
    mocker.patch(
        "bot.hermes_extractor.apple_vision_ocr", return_value="Some receipt text"
    )

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    await extractor.extract("", image_path="receipt.jpg")

    system_content = mock_client.post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "GRAND TOTAL" in system_content.upper()


async def test_hermes_text_path_omits_receipt_prompt(mocker):
    """Plain text path does NOT carry receipt grand-total guidance."""
    mock_client = _patch_httpx(mocker, _raw_json())

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    await extractor.extract("Lunch $12")

    system_content = mock_client.post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "GRAND TOTAL" not in system_content.upper()


@pytest.mark.parametrize(
    "raw_amount,currency,expected",
    [
        ("288.400", "IDR", "288400"),   # IDR 0-dp, '.' thousands sep
        ("52.000", "IDR", "52000"),
        ("168,000", "IDR", "168000"),   # IDR 0-dp, ',' thousands sep
        ("7,403.33", "THB", "7403.33"), # THB 2-dp, ',' thousands + '.' decimal
        ("1.234,56", "EUR", "1234.56"), # European format
        ("90.76", "SGD", "90.76"),      # plain 2-dp decimal, untouched
        ("424.45", "SGD", "424.45"),
        ("S$ 314.14", "SGD", "314.14"), # currency symbol stripped
        ("12", "SGD", "12"),            # no separators
    ],
)
def test_normalize_receipt_amount(raw_amount, currency, expected):
    """Locale-aware receipt amount normalisation keyed on the currency's decimals."""
    from bot.hermes_extractor import _normalize_receipt_amount

    assert _normalize_receipt_amount(raw_amount, currency) == expected


async def test_hermes_receipt_amount_locale_normalised(mocker):
    """Photo path normalises '288.400' IDR to 288400 minor units (not 288)."""
    _patch_httpx(mocker, _raw_json(amount_str="288.400", currency="IDR"))
    mocker.patch(
        "bot.hermes_extractor.apple_vision_ocr", return_value="Rp 288.400 total"
    )

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("", image_path="receipt.jpg")

    assert result.amount_str == "288400"


async def test_hermes_text_amount_not_locale_normalised(mocker):
    """Typed text '1.5' means 1.50 — must NOT be mangled to '15' by receipt logic."""
    _patch_httpx(mocker, _raw_json(amount_str="1.5", currency="SGD"))

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("coffee 1.5")

    assert result.amount_str == "1.5"


# ---------------------------------------------------------------------------
# HermesExtractor: validation overrides
# ---------------------------------------------------------------------------


async def test_hermes_unparseable_amount_forces_none_and_zero_confidence(mocker):
    """An amount that parse_to_minor_units rejects → amount_str=None, confidence_amount=0.0."""
    _patch_httpx(mocker, _raw_json(amount_str="12.5x"))  # invalid decimal

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("text with bad amount")

    assert result.amount_str is None
    assert result.confidence_amount == 0.0


async def test_hermes_unknown_category_hint_becomes_other_with_zero_confidence(mocker):
    """Unknown category hint → category_hint='Other', confidence_category=0.0."""
    _patch_httpx(mocker, _raw_json(category_hint="NonExistentCategory"))

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("Some text")

    assert result.category_hint == "Other"
    assert result.confidence_category == 0.0


async def test_hermes_known_category_gets_boosted_confidence(mocker):
    """Known category hint → confidence_category elevated to at least 0.7."""
    _patch_httpx(mocker, _raw_json(category_hint="Groceries", confidence_category=0.3))

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("Groceries")

    assert result.category_hint == "Groceries"
    assert result.confidence_category >= 0.7


async def test_hermes_date_dmy_parses_12_june(mocker):
    """Date '12/06/2025' with DATE_ORDER=DMY parses as June 12, 2025."""
    _patch_httpx(mocker, _raw_json(expense_date="12/06/2025"))

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("Lunch")

    assert result.expense_date == date(2025, 6, 12)


async def test_hermes_iso_date_parsed_exactly_not_dmy_flipped(mocker):
    """A strict ISO YYYY-MM-DD date is honoured verbatim — never month/day flipped.

    Regression: Hermes emits ISO dates; parsing must read them unambiguously.
    '2026-07-06' must be July 6, not June 7.
    """
    _patch_httpx(mocker, _raw_json(expense_date="2026-07-06"))

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("Lunch today")

    assert result.expense_date == date(2026, 7, 6)
    assert result.confidence_date >= 0.9


async def test_hermes_relative_yesterday_resolved_in_code(mocker):
    """A relative word 'yesterday' is resolved deterministically to today-1.

    Regression: the model must NOT do date arithmetic (it slips on the year);
    parsing pins RELATIVE_BASE to today so 'yesterday' == today - 1 day, always
    the correct year.
    """
    from datetime import timedelta

    _patch_httpx(mocker, _raw_json(expense_date="yesterday"))

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("Coffee yesterday")

    assert result.expense_date == date.today() - timedelta(days=1)
    assert result.confidence_date >= 0.9


async def test_hermes_unparseable_date_falls_back_to_today(mocker):
    """An unparseable date string → expense_date=date.today(), confidence_date=0.0."""
    _patch_httpx(mocker, _raw_json(expense_date="not-a-date-at-all-xyz"))

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("Some text")

    assert result.expense_date == date.today()
    assert result.confidence_date == 0.0


# ---------------------------------------------------------------------------
# HermesExtractor: blank OCR → unreadable result without Ollama call
# ---------------------------------------------------------------------------


async def test_hermes_blank_ocr_returns_unreadable_without_httpx_call(mocker):
    """Blank OCR text returns an unreadable ExtractionResult; Ollama is NOT called."""
    mock_client = _patch_httpx(mocker, "{}")
    mocker.patch(
        "bot.hermes_extractor.apple_vision_ocr", return_value="   "  # whitespace-only
    )

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("", image_path="blurry.jpg")

    assert result.amount_str is None
    assert result.confidence_amount == 0.0
    # Ollama was not called
    mock_client.post.assert_not_called()


async def test_hermes_empty_ocr_string_is_unreadable(mocker):
    """Empty string OCR (not just whitespace) is also treated as unreadable."""
    mock_client = _patch_httpx(mocker, "{}")
    mocker.patch("bot.hermes_extractor.apple_vision_ocr", return_value="")

    from bot.hermes_extractor import HermesExtractor

    extractor = HermesExtractor("http://localhost:11434", "hermes3:8b", CATEGORIES)
    result = await extractor.extract("", image_path="blank.jpg")

    assert result.amount_str is None
    assert result.confidence_amount == 0.0
    mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# VLMExtractor: ABC contract + error guard
# ---------------------------------------------------------------------------


def test_vlm_extractor_is_extractor():
    """VLMExtractor subclasses the Extractor ABC."""
    from bot.extractor import Extractor
    from bot.hermes_extractor import VLMExtractor

    extractor = VLMExtractor("http://localhost:11434", "qwen3-vl:4b", CATEGORIES)
    assert isinstance(extractor, Extractor)


async def test_vlm_extractor_raises_value_error_without_image_path():
    """VLMExtractor.extract raises ValueError when image_path is None."""
    from bot.hermes_extractor import VLMExtractor

    extractor = VLMExtractor("http://localhost:11434", "qwen3-vl:4b", CATEGORIES)
    with pytest.raises(ValueError):
        await extractor.extract("text only — no image")
