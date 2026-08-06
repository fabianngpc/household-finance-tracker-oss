"""Hermes LLM extractor + VLM escalation path.

HermesExtractor:
  - Text path: send raw text directly to Ollama /api/chat with grammar-constrained
    JSON schema output.
  - Photo path: apple_vision_ocr(image_path) → OCR text → Hermes.
  - Blank OCR → returns an 'unreadable' ExtractionResult WITHOUT calling Ollama.

VLMExtractor (contingency, NOT the default):
  - Sends a base64-encoded image to qwen3-vl:4b with keep_alive=0 so the model
    is freed from GPU RAM immediately after each inference.
  - Raises ValueError when no image_path provided.

Validation-override confidence (Pattern 6):
  - Amount parseable by parse_to_minor_units → confidence_amount max(model, 0.9)
  - Unparseable amount → amount_str=None, confidence_amount=0.0 (never hallucinate)
  - Date parseable by dateparser (DATE_ORDER=DMY) → that date, conf max(model, 0.9)
  - Unknown date → date.today(), confidence_date=0.0
  - Category in user's list → conf max(model, 0.7)
  - Unknown category → "Other", confidence_category=0.0

Note: extract() is `async def` throughout to avoid asyncio.run() inside the
running event loop of the async worker (research anti-pattern).

IMPORTANT: Must NOT import the FastAPI app entrypoint (would initialize middleware).
"""
import base64
from datetime import date, datetime, time

import httpx
from pydantic import BaseModel, Field

from bot.extractor import Extractor, ExtractionResult
from bot.ocr import apple_vision_ocr


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are an expense extraction assistant for a personal finance app.
Extract the following from the user's message:
- amount_str: the monetary amount as a string (e.g. "42.50"). null if not present.
- currency: 3-letter ISO code. Default to "SGD" if not specified.
- merchant: store or person paid. null if not present.
- expense_date: the expense date. If the message states an explicit calendar date, output it as STRICT ISO 8601 YYYY-MM-DD (e.g. 2025-01-31) — NEVER MM/DD/YYYY or DD/MM/YYYY. If the message uses a relative word ("today", "yesterday", "this morning", "last Friday"), output that word VERBATIM — do NOT calculate the date yourself. If no date is mentioned, output "today". (Today is {today}.)
- category_hint: one of [{categories}]. Default to "Other" if unsure.
- confidence_amount: 0.0-1.0. How confident are you the amount is correct?
- confidence_date: 0.0-1.0. How confident are you the date is correct?
- confidence_merchant: 0.0-1.0. How confident are you the merchant is correct?
- confidence_category: 0.0-1.0. How confident are you the category is correct?

Rules:
- NEVER invent an amount. If the text doesn't contain one, set amount_str to null and confidence_amount to 0.0.
- Set confidence values honestly. 0.9+ = very sure. 0.5-0.9 = somewhat sure. <0.5 = guessing.
"""

# Appended only when the input is OCR text from a photographed receipt. Receipt OCR
# is a wall of numbers (line items, quantities, subtotal, tax, service charge); the
# generic prompt above makes the model grab the first item or the pre-tax subtotal.
RECEIPT_GUIDANCE = """
The user's message is the raw OCR text of a PHOTOGRAPHED RECEIPT, so apply these rules:
- amount_str: return the GRAND TOTAL — the final amount the customer paid, AFTER
  subtotal, tax/GST/VAT, service charge, and discounts. Prefer the bottom-most line
  labelled "Total", "Grand Total", "Amount Due", "Total Payable", or the amount
  charged to the payment method (NETS/VISA/Mastercard/cash). NEVER return an
  individual line item or the pre-tax subtotal. Ignore loyalty/membership "Balance"
  or "Points" lines — those are not the amount paid.
- Output amount_str EXACTLY as printed on the receipt, keeping its own separators
  (e.g. "288.400", "7,403.33", "S$90.76" -> "90.76"). Do NOT reformat or strip
  digits — the app normalises thousands separators itself.
- currency: read it from the receipt. "Rp"/"IDR"/"Rupiah" -> IDR; "฿"/"Baht"/"THB" -> THB;
  "RM"/"MYR" -> MYR; "S$"/"SGD" or a Singapore address -> SGD; a bare "$" -> SGD.
- merchant: the business name, usually at the very TOP of the receipt — not a menu
  item, cashier, or server name.
- expense_date: the receipt's transaction/print date (often near the top or after
  "Date"/"Printed"), output as strict ISO YYYY-MM-DD.
"""


def _build_system(
    categories: list[str], today: date, is_receipt: bool = False
) -> str:
    """Render the system prompt with today's date and user category list.

    When ``is_receipt`` is set the OCR-receipt guidance (grand-total selection,
    locale-aware thousands separators, currency-symbol detection) is appended.
    """
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        categories=", ".join(categories),
    )
    if is_receipt:
        prompt += RECEIPT_GUIDANCE
    return prompt


# ---------------------------------------------------------------------------
# Pydantic schema for grammar-constrained Ollama output
# ---------------------------------------------------------------------------


class _RawExtraction(BaseModel):
    """Schema sent to Ollama as `format` for grammar-constrained JSON decoding."""

    amount_str: str | None = None
    currency: str = "SGD"
    merchant: str | None = None
    expense_date: str = Field(
        default="",
        description="Date in strict ISO 8601 format YYYY-MM-DD, e.g. 2025-01-31. Never MM/DD/YYYY or DD/MM/YYYY.",
    )
    category_hint: str = "Other"
    confidence_amount: float = 0.0
    confidence_date: float = 0.0
    confidence_merchant: float = 0.0
    confidence_category: float = 0.0


# ---------------------------------------------------------------------------
# Validation-override confidence (Pattern 6)
# ---------------------------------------------------------------------------


def _normalize_receipt_amount(amount_str: str, currency: str) -> str:
    """Normalise a receipt amount into a plain decimal string, interpreting
    '.'/','/space thousands separators via the currency's minor-unit digit count.

    Receipts print amounts locale-dependently; the model returns them verbatim
    (e.g. "288.400", "7,403.33", "1.234,56") and we resolve them here rather than
    asking the model to reformat (which corrupts real decimals like 90.76 -> 9076).

    Examples:
        "288.400" IDR(0) -> "288400"     "Rp 52.000" IDR -> "52000"
        "7,403.33" THB(2) -> "7403.33"   "1.234,56" EUR(2) -> "1234.56"
        "90.76" SGD(2) -> "90.76"        "168,000" IDR(0) -> "168000"

    Only applied to the OCR/receipt path — typed text ("1.5" meaning 1.50) is
    parsed directly by parse_to_minor_units and must NOT pass through here.
    """
    from app.services.money import CURRENCY_DECIMALS

    s = "".join(c for c in amount_str if c.isdigit() or c in "., ").replace(" ", "")
    if not s:
        return amount_str  # nothing numeric — let downstream reject it

    decimals = CURRENCY_DECIMALS.get(currency.strip().upper(), 2)
    if decimals == 0:
        return s.replace(".", "").replace(",", "")  # no minor unit → all seps are thousands

    seps = [i for i, c in enumerate(s) if c in ".,"]
    if not seps:
        return s
    last = seps[-1]
    frac = s[last + 1:]
    if len(frac) == decimals:  # rightmost group is the fractional part → decimal point
        integer = s[:last].replace(".", "").replace(",", "")
        return f"{integer}.{frac}"
    return s.replace(".", "").replace(",", "")  # else every separator is a thousands sep


def _to_extraction_result(
    raw: _RawExtraction, user_categories: list[str], is_receipt: bool = False
) -> ExtractionResult:
    """Apply rule-based validation overrides to the model's self-reported confidence.

    Imports are local to avoid circular imports and to keep bot/ free of app.main.
    """
    import dateparser
    from app.services.money import parse_to_minor_units

    # --- Amount validation ---
    conf_amount = raw.confidence_amount
    amount_str = raw.amount_str
    if amount_str:
        if is_receipt:
            amount_str = _normalize_receipt_amount(amount_str, raw.currency)
        try:
            parse_to_minor_units(amount_str, raw.currency)
            conf_amount = max(conf_amount, 0.9)  # parseable → HIGH
        except (ValueError, KeyError):
            amount_str = None
            conf_amount = 0.0  # hallucinated unparseable value → FORCE low

    # --- Date validation ---
    # Two-stage, deterministic resolution:
    #   1. Strict ISO (YYYY-MM-DD) → parsed verbatim, unambiguous.
    #   2. Everything else (relative words like "yesterday", or free-form dates
    #      like "12/06/2025") → dateparser, with RELATIVE_BASE pinned to today so
    #      relative-date arithmetic is done in code, NOT by the LLM (models slip
    #      on date math — e.g. computing the wrong YEAR for "yesterday").
    conf_date = raw.confidence_date
    raw_date = (raw.expense_date or "").strip()
    expense_date = None
    try:
        expense_date = date.fromisoformat(raw_date)
    except ValueError:
        base = datetime.combine(date.today(), time())
        parsed_dt = dateparser.parse(
            raw_date,
            settings={
                "DATE_ORDER": "DMY",
                "RELATIVE_BASE": base,
                "PREFER_DATES_FROM": "past",
            },
        )
        if parsed_dt:
            expense_date = parsed_dt.date()
    if expense_date is not None:
        conf_date = max(conf_date, 0.9)
    else:
        expense_date = date.today()  # safe fallback; do NOT hallucinate
        conf_date = 0.0

    # --- Category validation ---
    conf_category = raw.confidence_category
    hint = raw.category_hint
    if hint not in user_categories:
        hint = "Other"
        conf_category = 0.0  # unknown category → unsure
    else:
        conf_category = max(conf_category, 0.7)  # known → at least MEDIUM

    return ExtractionResult(
        amount_str=amount_str,
        currency=raw.currency,
        merchant=raw.merchant or None,
        expense_date=expense_date,
        category_hint=hint,
        confidence=conf_amount,  # backward compat
        confidence_amount=conf_amount,
        confidence_date=conf_date,
        confidence_merchant=raw.confidence_merchant,
        confidence_category=conf_category,
    )


def _unreadable_result() -> ExtractionResult:
    """Return an all-low-confidence result for images that couldn't be read.

    Used when OCR returns blank text — Ollama is never called so there is no
    hallucination risk.  The worker treats amount_str=None / confidence_amount=0.0
    as a signal to prompt the user for the amount.
    """
    return ExtractionResult(
        amount_str=None,
        currency="SGD",
        merchant=None,
        expense_date=date.today(),
        category_hint="Other",
        confidence=0.0,
        confidence_amount=0.0,
        confidence_date=0.0,
        confidence_merchant=0.0,
        confidence_category=0.0,
    )


# ---------------------------------------------------------------------------
# HermesExtractor — default extractor (text + OCR→Hermes)
# ---------------------------------------------------------------------------


class HermesExtractor(Extractor):
    """Calls Ollama /api/chat with grammar-constrained JSON schema output.

    Text path: sends raw text directly to Hermes.
    Photo path: OCR via apple_vision_ocr → text → Hermes.
    Blank OCR → _unreadable_result() (Ollama never called).
    """

    def __init__(self, base_url: str, model: str, categories: list[str]) -> None:
        self._url = f"{base_url}/api/chat"
        self._model = model
        self._categories = categories

    async def extract(
        self, text: str, image_path: str | None = None
    ) -> ExtractionResult:
        """Structure text (or OCR'd photo) into an ExtractionResult.

        Args:
            text: Raw text from a Telegram text message.
            image_path: Local path to a receipt image. When provided, OCR is
                applied first; text is ignored.

        Returns:
            ExtractionResult with validation-override confidence fields.
        """
        is_receipt = bool(image_path)
        if image_path:
            ocr_text = apple_vision_ocr(image_path)
            if not ocr_text.strip():
                return _unreadable_result()
            prompt = ocr_text
        else:
            prompt = text

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": _build_system(
                        self._categories, date.today(), is_receipt=is_receipt
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": _RawExtraction.model_json_schema(),
            "options": {"temperature": 0},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()

        raw = _RawExtraction.model_validate_json(resp.json()["message"]["content"])
        return _to_extraction_result(raw, self._categories, is_receipt=is_receipt)


# ---------------------------------------------------------------------------
# VLMExtractor — escalation contingency (NOT the default)
# ---------------------------------------------------------------------------


class VLMExtractor(Extractor):
    """qwen3-vl:4b loaded on-demand; freed from GPU RAM via keep_alive=0.

    Only instantiated when EXTRACTOR=vlm in .env.  Requires an image_path —
    raises ValueError for text-only calls.
    """

    def __init__(self, base_url: str, model: str, categories: list[str]) -> None:
        self._url = f"{base_url}/api/chat"
        self._model = model
        self._categories = categories

    async def extract(
        self, text: str, image_path: str | None = None
    ) -> ExtractionResult:
        """Extract expense details from a receipt image via the VLM.

        Args:
            text: Ignored (VLM reads the image directly).
            image_path: Required. Local path to the receipt image.

        Raises:
            ValueError: When image_path is None or empty.
        """
        if not image_path:
            raise ValueError(
                "VLMExtractor requires an image_path — text-only input is not supported"
            )

        from bot.ocr import preprocess_image

        preprocessed = preprocess_image(image_path, max_dim=1024)
        with open(preprocessed, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Extract amount, merchant, date, and category from this receipt. "
                        "Return JSON matching the schema exactly."
                    ),
                    "images": [b64],
                }
            ],
            "stream": False,
            "format": _RawExtraction.model_json_schema(),
            "options": {"temperature": 0},
            "keep_alive": 0,  # free qwen3-vl from GPU RAM immediately after inference
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self._url, json=payload)
        resp.raise_for_status()

        raw = _RawExtraction.model_validate_json(resp.json()["message"]["content"])
        return _to_extraction_result(raw, self._categories, is_receipt=True)


# ---------------------------------------------------------------------------
# Extractor factory — config-driven swap point (AI-01)
# ---------------------------------------------------------------------------


def build_extractor(name: str, categories: list[str]) -> Extractor:
    """Construct the configured extractor by name.

    Supported names:
      - "stub"   → StubExtractor (deterministic, no model)
      - "hermes" → HermesExtractor (default; text + OCR→Hermes via Ollama)
      - "vlm"    → VLMExtractor (escalation; qwen3-vl:4b, keep_alive=0)

    Args:
        name: Extractor name from EXTRACTOR env var / config.
        categories: User's category names for hint resolution.

    Raises:
        ValueError: For unknown extractor names.
    """
    from bot.config import OLLAMA_BASE_URL, OLLAMA_MODEL, VLM_MODEL
    from bot.extractor import StubExtractor

    if name == "stub":
        return StubExtractor()
    if name == "hermes":
        return HermesExtractor(OLLAMA_BASE_URL, OLLAMA_MODEL, categories)
    if name == "vlm":
        return VLMExtractor(OLLAMA_BASE_URL, VLM_MODEL, categories)
    raise ValueError(
        f"Unknown extractor {name!r}. Valid options: 'stub', 'hermes', 'vlm'."
    )
