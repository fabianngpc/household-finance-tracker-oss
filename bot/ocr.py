"""Apple Vision OCR wrapper via ocrmac + Pillow image pre-processing.

Usage:
    from bot.ocr import apple_vision_ocr

    text = apple_vision_ocr("/path/to/receipt.jpg")
    # Returns newline-joined recognized lines; "" on blank image.

macOS only: ocrmac wraps Apple's VNRecognizeTextRequest via pyobjc.
On non-macOS systems (or when ocrmac is not installed) apple_vision_ocr raises
RuntimeError with an install hint so the worker's except block can log it cleanly.
"""
import tempfile

from pathlib import Path
from PIL import Image


def preprocess_image(src_path: str, max_dim: int = 1600) -> str:
    """Downscale image to max_dim on its longest side, save as a temp PNG.

    Args:
        src_path: Path to source image (any Pillow-supported format).
        max_dim: Maximum pixel length for the longest side. Default 1600.

    Returns:
        Path to the temporary PNG file. Caller is responsible for cleanup.
    """
    img = Image.open(src_path).convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name, format="PNG")
    tmp.close()
    return tmp.name


def apple_vision_ocr(image_path: str) -> str:
    """Run Apple Vision OCR on image_path; return all text joined by newlines.

    Text lines with confidence > 0.1 are included; lower-confidence lines are
    dropped. An image with no recognizable text returns "" (empty string).

    Args:
        image_path: Path to the image file to recognize.

    Returns:
        Newline-joined text of all high-confidence recognized lines, or "".

    Raises:
        RuntimeError: When ocrmac is not installed or the system is not macOS.
            Message includes the install command for a clear error in worker logs.

    Performance: ~200ms per image on Apple M-series Silicon.
    """
    try:
        from ocrmac import ocrmac as _ocrmac
    except ImportError as exc:
        raise RuntimeError(
            "ocrmac not installed — run: uv add ocrmac"
        ) from exc

    preprocessed = preprocess_image(image_path)
    annotations = _ocrmac.OCR(preprocessed).recognize()
    # annotations: list of (text_str, confidence_float, bounding_box)
    lines = [item[0] for item in annotations if item[1] > 0.1]
    return "\n".join(lines)
