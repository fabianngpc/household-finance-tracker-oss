"""Smoke tests: health endpoint and seeded category assertions."""


def test_health(client):
    """GET /health returns 200 with {"ok": True}."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_seeded_categories_count(seeded_categories):
    """A seeded user has exactly 10 categories."""
    assert len(seeded_categories) == 10


def test_seeded_categories_has_protected_other(seeded_categories):
    """Exactly one category is protected and its name is 'Other'."""
    protected = [c for c in seeded_categories if c.is_protected]
    assert len(protected) == 1
    assert protected[0].name == "Other"
