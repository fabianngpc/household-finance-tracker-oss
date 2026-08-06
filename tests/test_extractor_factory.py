"""Tests for the build_extractor config-driven factory and EXTRACTOR default.

No model construction beyond __init__; no real Ollama or Vision calls.
"""
import pytest

from bot.extractor import Extractor


CATEGORIES = ["Food", "Transport", "Other"]


# ---------------------------------------------------------------------------
# build_extractor: name → correct class
# ---------------------------------------------------------------------------


def test_stub_name_returns_stub_extractor():
    from bot.extractor import StubExtractor
    from bot.hermes_extractor import build_extractor

    extractor = build_extractor("stub", CATEGORIES)

    assert isinstance(extractor, StubExtractor)
    assert isinstance(extractor, Extractor)


def test_hermes_name_returns_hermes_extractor():
    from bot.hermes_extractor import HermesExtractor, build_extractor

    extractor = build_extractor("hermes", CATEGORIES)

    assert isinstance(extractor, HermesExtractor)
    assert isinstance(extractor, Extractor)


def test_vlm_name_returns_vlm_extractor():
    from bot.hermes_extractor import VLMExtractor, build_extractor

    extractor = build_extractor("vlm", CATEGORIES)

    assert isinstance(extractor, VLMExtractor)
    assert isinstance(extractor, Extractor)


def test_unknown_name_raises_value_error():
    from bot.hermes_extractor import build_extractor

    with pytest.raises(ValueError):
        build_extractor("unknown_model_xyz", CATEGORIES)


def test_empty_name_raises_value_error():
    from bot.hermes_extractor import build_extractor

    with pytest.raises(ValueError):
        build_extractor("", CATEGORIES)


# ---------------------------------------------------------------------------
# EXTRACTOR default is "hermes" (not "vlm")
# ---------------------------------------------------------------------------


def test_default_extractor_config_is_hermes():
    """EXTRACTOR env var defaults to 'hermes' (Ollama path, not stub or VLM)."""
    from bot.config import EXTRACTOR

    assert EXTRACTOR == "hermes"


def test_vlm_is_not_the_default_extractor():
    """VLMExtractor is the escalation contingency, never selected by default."""
    from bot.config import EXTRACTOR

    assert EXTRACTOR != "vlm"


# ---------------------------------------------------------------------------
# Config vars are present with expected defaults
# ---------------------------------------------------------------------------


def test_ollama_base_url_defaults_to_localhost():
    from bot.config import OLLAMA_BASE_URL

    assert OLLAMA_BASE_URL == "http://localhost:11434"


def test_ollama_model_defaults_to_hermes():
    from bot.config import OLLAMA_MODEL

    assert OLLAMA_MODEL == "hermes3:8b"


def test_vlm_model_defaults_to_qwen():
    from bot.config import VLM_MODEL

    assert VLM_MODEL == "qwen3-vl:4b"
