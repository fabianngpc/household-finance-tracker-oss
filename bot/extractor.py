"""Extractor interface and StubExtractor for the Telegram capture pipeline.

A real model (e.g. HermesExtractor) can be dropped in by subclassing Extractor
without touching the pipeline — the worker always calls await extractor.extract(text).
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class ExtractionResult:
    amount_str: str | None      # None -> low confidence -> confirm flow
    currency: str               # default "SGD"
    merchant: str | None
    expense_date: date
    category_hint: str          # "Other" for the stub
    confidence: float           # 1.0 if amount found else 0.0
    # Per-field confidence (with defaults for backward compat)
    confidence_amount: float | None = None   # None -> derive from confidence
    confidence_date: float = 1.0
    confidence_merchant: float = 1.0
    confidence_category: float = 0.0


class Extractor(ABC):
    @abstractmethod
    async def extract(self, text: str, image_path: str | None = None) -> ExtractionResult: ...


class StubExtractor(Extractor):
    """Deterministic stub: first number -> amount, rest -> merchant, date = today.

    Confidence rule:
      - amount found  -> confidence = 1.0  -> pipeline auto-logs
      - no amount     -> confidence = 0.0  -> pipeline enters confirm flow
    """

    _NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

    async def extract(self, text: str, image_path: str | None = None) -> ExtractionResult:
        match = self._NUMBER.search(text)
        amount_str = match.group().replace(",", ".") if match else None
        merchant = self._NUMBER.sub("", text).strip() or None
        return ExtractionResult(
            amount_str=amount_str,
            currency="SGD",
            merchant=merchant,
            expense_date=date.today(),
            category_hint="Other",
            confidence=1.0 if amount_str else 0.0,
        )
