"""Tests for bot/config.py — parse_allowed_ids and environment loading."""
from bot.config import parse_allowed_ids


def test_parse_allowed_ids_basic():
    assert parse_allowed_ids("111, 222") == [111, 222]


def test_parse_allowed_ids_empty():
    assert parse_allowed_ids("") == []


def test_parse_allowed_ids_trailing_comma():
    assert parse_allowed_ids("111,") == [111]


def test_parse_allowed_ids_single():
    assert parse_allowed_ids("42") == [42]


def test_parse_allowed_ids_no_spaces():
    assert parse_allowed_ids("100,200,300") == [100, 200, 300]


def test_parse_allowed_ids_whitespace_only_entries_ignored():
    assert parse_allowed_ids("111, , 222") == [111, 222]
