"""Invariant #12 — Alembic revision chain resolves to exactly one head.

Guards against the confirmed-broken down_revision string mismatch (migration 003
pointed at "002" while migration 002's actual revision id is "002_telegram_phase2",
causing a KeyError when Alembic tried to walk the chain).
"""

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script_directory() -> ScriptDirectory:
    config = Config("alembic.ini")
    return ScriptDirectory.from_config(config)


class TestAlembicChain:
    def test_single_head(self):
        sd = _script_directory()
        heads = sd.get_heads()
        assert len(heads) == 1

    def test_head_is_005_phase5_budgets_recurring(self):
        sd = _script_directory()
        heads = sd.get_heads()
        assert heads[0] == "005_phase5_budgets_recurring"

    def test_every_revision_resolves_without_error(self):
        sd = _script_directory()
        # walk_revisions raises if any down_revision can't be resolved —
        # this is the exact failure mode of the original bug.
        revisions = list(sd.walk_revisions())
        assert len(revisions) >= 5
