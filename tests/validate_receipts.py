"""Real-receipt accuracy, latency, and memory validation harness.

Run MANUALLY on the Mac mini with a live Ollama model.
This file is NOT a pytest test — it contains no test_ functions and is
intentionally excluded from the pytest CI suite.

Usage
-----
    uv run python tests/validate_receipts.py --help
    uv run python tests/validate_receipts.py
    uv run python tests/validate_receipts.py --extractor vlm --model qwen3-vl:4b

Ground-truth CSV columns (required):
    filename, amount, currency, date, merchant, category

Pass/Fail bars
--------------
    Amount   >= 95%  (strict: exact minor-unit match — the hard gate)
    Date     >= 90%
    Merchant >= 70%  (lenient: normalised substring match)
    Category >= 60%  (case-insensitive exact match against the hint)

Escalation rule: if Amount accuracy < 95%, print "ESCALATE — set EXTRACTOR=vlm".
"""
import argparse
import asyncio
import csv
import platform
import resource
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

# Run as a standalone script (`uv run python tests/validate_receipts.py`), so the
# project root must be on sys.path for the lazy `bot.*` / `app.*` imports to resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Pass/Fail bars (gate thresholds)
# ---------------------------------------------------------------------------

BAR_AMOUNT_PCT: int = 95
BAR_DATE_PCT: int = 90
BAR_MERCHANT_PCT: int = 70
BAR_CATEGORY_PCT: int = 60

# ---------------------------------------------------------------------------
# Default categories — mirrors app/seed.py DEFAULT_CATEGORIES names
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES: list[str] = [
    "Food & Dining",
    "Groceries",
    "Transport",
    "Housing/Rent",
    "Utilities",
    "Shopping",
    "Health",
    "Entertainment",
    "Travel",
    "Other",
]

# ---------------------------------------------------------------------------
# RSS scale: macOS ru_maxrss is bytes; Linux is kilobytes
# ---------------------------------------------------------------------------

_RSS_TO_MB: float = (
    1.0 / (1024 * 1024) if platform.system() == "Darwin" else 1.0 / 1024
)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _normalise(s: str) -> str:
    """Lowercase, unicode-normalise, strip punctuation for lenient merchant match."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    return " ".join(s.split())


def score_amount(
    extracted_str: str | None,
    extracted_currency: str,
    gt_amount: str,
    gt_currency: str,
) -> bool:
    """Strict gate: exact match in minor units AND same currency."""
    from app.services.money import parse_to_minor_units

    if not extracted_str:
        return False
    if extracted_currency.strip().upper() != gt_currency.strip().upper():
        return False
    try:
        ext_minor = parse_to_minor_units(extracted_str, extracted_currency.strip().upper())
        gt_minor = parse_to_minor_units(gt_amount, gt_currency.strip().upper())
        return ext_minor == gt_minor
    except (ValueError, KeyError):
        return False


def score_date(extracted_date: date | None, gt_date_str: str) -> bool:
    """Exact date match. Ground truth is authored as strict ISO YYYY-MM-DD, so parse
    it ISO-first — NEVER force DATE_ORDER=DMY on an ISO string, which silently swaps
    month/day (2026-06-04 -> 2026-04-06) or drops it (2026-04-19 -> None)."""
    if extracted_date is None:
        return False
    gt_date_str = (gt_date_str or "").strip()
    if not gt_date_str:
        return False
    try:
        gt = date.fromisoformat(gt_date_str)
    except ValueError:
        import dateparser  # type: ignore[import-untyped]

        parsed = dateparser.parse(gt_date_str, settings={"DATE_ORDER": "DMY"})
        if parsed is None:
            return False
        gt = parsed.date()
    return extracted_date == gt


def score_merchant(extracted_merchant: str | None, gt_merchant: str) -> bool:
    """Lenient: normalised ground-truth is a substring of normalised extracted (or vice versa)."""
    if not extracted_merchant or not gt_merchant:
        return False
    ext_norm = _normalise(extracted_merchant)
    gt_norm = _normalise(gt_merchant)
    return bool(gt_norm) and (gt_norm in ext_norm or ext_norm in gt_norm)


def score_category(extracted_hint: str, gt_category: str) -> bool:
    """Case-insensitive exact match on the category hint."""
    return extracted_hint.strip().lower() == gt_category.strip().lower()


# ---------------------------------------------------------------------------
# Extractor factory — LAZY (only called when actually scoring, not on --help)
# ---------------------------------------------------------------------------


def _build_extractor(extractor_name: str, model: str) -> object:
    """Construct the real extractor. Never called from --help path."""
    from bot.hermes_extractor import HermesExtractor, VLMExtractor
    from bot.config import OLLAMA_BASE_URL

    if extractor_name == "hermes":
        return HermesExtractor(OLLAMA_BASE_URL, model, DEFAULT_CATEGORIES)
    if extractor_name == "vlm":
        return VLMExtractor(OLLAMA_BASE_URL, model, DEFAULT_CATEGORIES)
    raise ValueError(
        f"Unknown extractor {extractor_name!r}. Valid options: 'hermes', 'vlm'."
    )


# ---------------------------------------------------------------------------
# Latency helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Return the pct-th percentile value from a sorted list."""
    if not sorted_vals:
        return 0.0
    idx = min(int(len(sorted_vals) * pct / 100), len(sorted_vals) - 1)
    return sorted_vals[idx]


# ---------------------------------------------------------------------------
# Harness — runs the real extractor over all receipts and prints the report
# ---------------------------------------------------------------------------


def run_harness(
    receipts_dir: Path,
    ground_truth_path: Path,
    model: str,
    extractor_name: str,
) -> None:
    """Execute the full accuracy/latency/memory gate and print the report."""

    # --- Load ground truth ---
    if not ground_truth_path.exists():
        print(
            f"ERROR: Ground-truth CSV not found: {ground_truth_path}", file=sys.stderr
        )
        sys.exit(1)

    rows: list[dict[str, str]] = []
    with open(ground_truth_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        print("ERROR: ground_truth.csv is empty.", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== Validation Harness — {extractor_name.upper()} / {model} ===")
    print(f"Receipts dir : {receipts_dir}")
    print(f"Ground truth : {ground_truth_path}")
    print(f"Receipts     : {len(rows)}")
    print()

    # --- Lazy extractor construction (skipped entirely on --help) ---
    extractor = _build_extractor(extractor_name, model)

    # --- RSS snapshot before first receipt ---
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    per_receipt: list[dict] = []

    for row in rows:
        filename = row.get("filename", "").strip()
        if not filename:
            continue

        image_path = receipts_dir / filename
        if not image_path.exists():
            print(f"  SKIP  {filename} (file not found)")
            continue

        gt_amount = row.get("amount", "").strip()
        gt_currency = row.get("currency", "SGD").strip()
        gt_date_str = row.get("date", "").strip()
        gt_merchant = row.get("merchant", "").strip()
        gt_category = row.get("category", "").strip()

        # Run extraction — one asyncio.run() per receipt (standalone script)
        t0 = time.perf_counter()
        result = asyncio.run(extractor.extract("", str(image_path)))
        latency = time.perf_counter() - t0

        amt_ok = score_amount(result.amount_str, result.currency, gt_amount, gt_currency)
        date_ok = score_date(result.expense_date, gt_date_str)
        merch_ok = score_merchant(result.merchant, gt_merchant)
        cat_ok = score_category(result.category_hint, gt_category)

        tag = "OK  " if amt_ok else "FAIL"
        print(
            f"  [{tag}] {filename:<30s}  "
            f"amt={result.amount_str!r:>10s} (gt={gt_amount!r:>10s})  "
            f"date={result.expense_date}  "
            f"{latency:.2f}s"
        )

        per_receipt.append(
            {
                "filename": filename,
                "latency": latency,
                "amount": amt_ok,
                "date": date_ok,
                "merchant": merch_ok,
                "category": cat_ok,
            }
        )

    # --- RSS snapshot after last receipt ---
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    if not per_receipt:
        print("\nERROR: No receipt images were processed.", file=sys.stderr)
        sys.exit(1)

    n = len(per_receipt)

    # Per-field accuracy percentages
    pct_amount = 100.0 * sum(r["amount"] for r in per_receipt) / n
    pct_date = 100.0 * sum(r["date"] for r in per_receipt) / n
    pct_merchant = 100.0 * sum(r["merchant"] for r in per_receipt) / n
    pct_category = 100.0 * sum(r["category"] for r in per_receipt) / n

    # Latency
    latencies = sorted(r["latency"] for r in per_receipt)
    mean_latency = sum(latencies) / n
    p95_latency = _percentile(latencies, 95)

    # Memory (RSS) delta in MB
    rss_before_mb = rss_before * _RSS_TO_MB
    rss_after_mb = rss_after * _RSS_TO_MB
    rss_delta_mb = rss_after_mb - rss_before_mb
    rss_ok = rss_delta_mb <= 50  # flag only large growth (> 50 MB)

    # -------------------------------------------------------------------
    # Print validation report
    # -------------------------------------------------------------------
    SEP = "=" * 64
    print()
    print(SEP)
    print("  VALIDATION REPORT")
    print(SEP)
    print(f"  Receipts processed : {n}")
    print()
    print("  Per-field accuracy:")
    print(
        f"    Amount accuracy   : {pct_amount:5.1f}%  "
        f"(bar >= {BAR_AMOUNT_PCT}%)   "
        f"{'PASS' if pct_amount >= BAR_AMOUNT_PCT else 'FAIL'}"
    )
    print(
        f"    Date accuracy     : {pct_date:5.1f}%  "
        f"(bar >= {BAR_DATE_PCT}%)   "
        f"{'PASS' if pct_date >= BAR_DATE_PCT else 'FAIL'}"
    )
    print(
        f"    Merchant accuracy : {pct_merchant:5.1f}%  "
        f"(bar >= {BAR_MERCHANT_PCT}%)   "
        f"{'PASS' if pct_merchant >= BAR_MERCHANT_PCT else 'FAIL'}"
    )
    print(
        f"    Category accuracy : {pct_category:5.1f}%  "
        f"(bar >= {BAR_CATEGORY_PCT}%)   "
        f"{'PASS' if pct_category >= BAR_CATEGORY_PCT else 'FAIL'}"
    )
    print()
    print("  Latency:")
    print(f"    Mean              : {mean_latency:.2f}s")
    print(f"    p95               : {p95_latency:.2f}s")
    print()
    print("  Memory (RSS — Python harness process):")
    print(f"    RSS before        : {rss_before_mb:.1f} MB")
    print(f"    RSS after         : {rss_after_mb:.1f} MB")
    rss_note = "OK (no significant growth)" if rss_ok else "WARNING: significant resident-RAM growth"
    print(f"    RSS delta         : {rss_delta_mb:+.1f} MB  [{rss_note}]")
    print()

    # Overall verdict
    all_fields_pass = (
        pct_amount >= BAR_AMOUNT_PCT
        and pct_date >= BAR_DATE_PCT
        and pct_merchant >= BAR_MERCHANT_PCT
        and pct_category >= BAR_CATEGORY_PCT
    )
    escalate = pct_amount < BAR_AMOUNT_PCT

    print(SEP)
    if all_fields_pass:
        print("  OVERALL VERDICT   : PASS")
        print("  DECISION          : Ship OCR->Hermes as the baseline extractor.")
        print("  ESCALATE FLAG     : NO")
    else:
        print("  OVERALL VERDICT   : FAIL")
        if escalate:
            print("  DECISION          : ESCALATE — amount accuracy < 95%.")
            print(
                "                      Pull qwen3-vl:4b and re-run with --extractor vlm."
            )
            print(
                "                      Set EXTRACTOR=vlm in .env once VLM accuracy is confirmed."
            )
            print("  ESCALATE FLAG     : YES")
        else:
            print(
                "  DECISION          : FAIL — non-amount fields below bar; "
                "investigate extraction quality."
            )
            print("  ESCALATE FLAG     : NO (amount accuracy meets the hard gate)")
    print(SEP)
    print()

    # Exit with non-zero if gate failed (useful for shell scripting)
    if not all_fields_pass:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the validation harness.

    --help exits immediately (argparse sys.exit(0)) — the extractor is NEVER
    constructed, so this works with no Ollama model running.
    """
    parser = argparse.ArgumentParser(
        prog="validate_receipts",
        description=(
            "Real-receipt accuracy, latency, and memory validation harness.\n\n"
            "Runs the REAL OCR+Hermes (or VLM) extractor over a folder of\n"
            "household receipt images and scores per-field accuracy against a\n"
            "ground-truth CSV. Run manually on the Mac mini — NEVER from CI.\n\n"
            "Ground-truth CSV columns:\n"
            "  filename, amount, currency, date, merchant, category\n\n"
            "Pass/Fail bars:\n"
            f"  Amount   >= {BAR_AMOUNT_PCT}%  (strict, minor-unit exact match)\n"
            f"  Date     >= {BAR_DATE_PCT}%\n"
            f"  Merchant >= {BAR_MERCHANT_PCT}%  (lenient substring)\n"
            f"  Category >= {BAR_CATEGORY_PCT}%"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--receipts-dir",
        default="validation/receipts",
        help="Folder containing receipt images (default: validation/receipts)",
    )
    parser.add_argument(
        "--ground-truth",
        default="validation/ground_truth.csv",
        help="Ground-truth CSV path (default: validation/ground_truth.csv)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model name (default: OLLAMA_MODEL env var / hermes3:8b)",
    )
    parser.add_argument(
        "--extractor",
        choices=["hermes", "vlm"],
        default="hermes",
        help="Extractor to use: hermes (default) or vlm",
    )

    args = parser.parse_args()

    # Resolve model lazily — bot.config is only imported when we're actually running
    if args.model:
        model = args.model
    else:
        from bot.config import OLLAMA_MODEL  # type: ignore[import-untyped]

        model = OLLAMA_MODEL

    run_harness(
        receipts_dir=Path(args.receipts_dir),
        ground_truth_path=Path(args.ground_truth),
        model=model,
        extractor_name=args.extractor,
    )


if __name__ == "__main__":
    main()
