"""Deterministic test fakes for CI — no real model calls.

Usage:
    from tests.fakes import FakeExtractor, make_result

    result = make_result(amount_str="5.00", merchant="Coffee")
    extractor = FakeExtractor(result)
    out = await extractor.extract("some text")  # always returns result
"""
from datetime import date

from bot.extractor import Extractor, ExtractionResult


def make_result(**overrides) -> ExtractionResult:
    """Build an ExtractionResult with sensible defaults; override any field."""
    defaults = dict(
        amount_str="12.50",
        currency="SGD",
        merchant="Test",
        expense_date=date.today(),
        category_hint="Other",
        confidence=1.0,
        confidence_amount=0.9,
        confidence_category=0.0,
    )
    defaults.update(overrides)
    return ExtractionResult(**defaults)


class FakeExtractor(Extractor):
    """Async Extractor that always returns a preset ExtractionResult.

    Used in gating/worker/photo tests so the real Ollama model is never
    called in CI.
    """

    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    async def extract(self, text: str, image_path: str | None = None) -> ExtractionResult:
        return self._result
