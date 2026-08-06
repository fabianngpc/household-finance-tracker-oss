"""Tests for bot/ocr.py — Apple Vision OCR via ocrmac + Pillow downscale.

All tests mock the ocrmac OCR class so no real Vision framework calls happen in CI.
Tests use Pillow to create a tiny in-memory test image written to a temp file.
"""
import os
import tempfile

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_temp_image(suffix: str = ".jpg") -> str:
    """Create a tiny 10x10 white test image and return its path."""
    img = Image.new("RGB", (10, 10), color=(255, 255, 255))
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    img.save(tmp.name, format="JPEG")
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# apple_vision_ocr — normal path (ocrmac mocked)
# ---------------------------------------------------------------------------


def test_apple_vision_ocr_joins_recognized_lines(mocker):
    """Recognized lines (confidence > 0.1) are joined by newlines."""
    mocker.patch(
        "ocrmac.ocrmac.OCR",
        return_value=mocker.MagicMock(
            recognize=mocker.MagicMock(
                return_value=[
                    ("Total: $42.00", 0.98, [0, 0, 0.5, 0.1]),
                    ("COOP", 0.92, [0, 0.2, 0.3, 0.1]),
                ]
            )
        ),
    )

    from bot.ocr import apple_vision_ocr

    tmp = _make_temp_image()
    try:
        result = apple_vision_ocr(tmp)
    finally:
        os.unlink(tmp)

    assert result == "Total: $42.00\nCOOP"


def test_apple_vision_ocr_filters_low_confidence(mocker):
    """Annotations with confidence ≤ 0.1 are excluded from the result."""
    mocker.patch(
        "ocrmac.ocrmac.OCR",
        return_value=mocker.MagicMock(
            recognize=mocker.MagicMock(
                return_value=[
                    ("Good line", 0.95, [0, 0, 0.5, 0.1]),
                    ("Low confidence", 0.05, [0, 0.2, 0.5, 0.1]),
                    ("Boundary exactly", 0.10, [0, 0.3, 0.5, 0.1]),
                ]
            )
        ),
    )

    from bot.ocr import apple_vision_ocr

    tmp = _make_temp_image()
    try:
        result = apple_vision_ocr(tmp)
    finally:
        os.unlink(tmp)

    assert "Good line" in result
    assert "Low confidence" not in result
    assert "Boundary exactly" not in result


def test_apple_vision_ocr_empty_annotations_returns_empty_string(mocker):
    """Empty annotations list returns '' without raising an exception."""
    mocker.patch(
        "ocrmac.ocrmac.OCR",
        return_value=mocker.MagicMock(
            recognize=mocker.MagicMock(return_value=[])
        ),
    )

    from bot.ocr import apple_vision_ocr

    tmp = _make_temp_image()
    try:
        result = apple_vision_ocr(tmp)
    finally:
        os.unlink(tmp)

    assert result == ""


# ---------------------------------------------------------------------------
# apple_vision_ocr — import guard: raises RuntimeError when ocrmac unavailable
# ---------------------------------------------------------------------------


def test_apple_vision_ocr_raises_runtime_error_when_ocrmac_unavailable(mocker):
    """RuntimeError (not ImportError) raised when ocrmac cannot be imported."""
    # Simulate ocrmac being absent by making the import raise ImportError
    import sys
    import importlib

    mocker.patch.dict("sys.modules", {"ocrmac": None, "ocrmac.ocrmac": None})

    # Reload the module so the lazy import inside apple_vision_ocr is re-evaluated
    import bot.ocr as ocr_mod
    importlib.reload(ocr_mod)

    tmp = _make_temp_image()
    try:
        with pytest.raises(RuntimeError, match="ocrmac not installed"):
            ocr_mod.apple_vision_ocr(tmp)
    finally:
        os.unlink(tmp)
        # Restore by reloading without the patch
        importlib.reload(ocr_mod)


# ---------------------------------------------------------------------------
# preprocess_image — downscale behaviour
# ---------------------------------------------------------------------------


def test_preprocess_image_returns_a_png_path():
    """preprocess_image saves a temp PNG and returns a path ending in .png."""
    from bot.ocr import preprocess_image

    img = Image.new("RGB", (100, 100), color=(128, 128, 128))
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.save(tmp.name, format="JPEG")
    tmp.close()

    try:
        out_path = preprocess_image(tmp.name)
        assert out_path.endswith(".png")
        assert os.path.isfile(out_path)
        os.unlink(out_path)
    finally:
        os.unlink(tmp.name)


def test_preprocess_image_downscales_large_image():
    """Images larger than max_dim are downscaled on their longest side."""
    from bot.ocr import preprocess_image

    big = Image.new("RGB", (3200, 1600), color=(0, 0, 0))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    big.save(tmp.name, format="PNG")
    tmp.close()

    try:
        out_path = preprocess_image(tmp.name, max_dim=1600)
        out_img = Image.open(out_path)
        assert max(out_img.size) <= 1600
        os.unlink(out_path)
    finally:
        os.unlink(tmp.name)
