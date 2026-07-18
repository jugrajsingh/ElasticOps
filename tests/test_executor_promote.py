"""Tests for the promote_index executor (alias swap + opt-in source delete)."""

from types import SimpleNamespace

import pytest

from backend.services.executor import execute_promote_index


class FakeES:
    def __init__(self) -> None:
        self.aliases: list[dict] | None = None
        self.deleted: str | None = None

    async def update_aliases(self, actions):
        self.aliases = actions

    async def delete_index(self, index):
        self.deleted = index


@pytest.mark.asyncio
async def test_should_swap_alias_without_deleting_source_by_default():
    es = FakeES()
    job = SimpleNamespace(
        index_name="logs-2024",
        target_index="logs-2024-shrink-1",
        node_name="logs",  # carries the alias name
        from_node=None,  # not "delete" -> keep source
        detail="",
    )
    await execute_promote_index(es, job)
    assert es.aliases is not None
    assert {"remove": {"index": "logs-2024", "alias": "logs"}} in es.aliases
    assert {"add": {"index": "logs-2024-shrink-1", "alias": "logs"}} in es.aliases
    assert es.deleted is None
    assert "retained" in job.detail.lower()


@pytest.mark.asyncio
async def test_should_delete_source_when_flagged():
    es = FakeES()
    job = SimpleNamespace(
        index_name="logs-2024",
        target_index="logs-2024-shrink-1",
        node_name="logs",
        from_node="delete",  # opt-in delete of the old source
        detail="",
    )
    await execute_promote_index(es, job)
    assert es.deleted == "logs-2024"
    assert "deleted" in job.detail.lower()
