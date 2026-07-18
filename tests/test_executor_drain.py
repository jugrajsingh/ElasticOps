"""Tests for the graceful node drain + undrain executor.

No real cluster, no DB. A FakeES holds an in-memory cluster-settings dict (FLAT keys, as
``cluster_settings_full`` returns with ``flat_settings=true``) and serves a SHRINKING list of
shards so the drain poll completes. ``delay=0`` keeps every test instant.
"""

from types import SimpleNamespace

import pytest

from backend.services.executor import (
    _EXCLUDE_KEY,
    _exclude_set,
    execute_drain_node,
    undrain_node,
)


class FakeES:
    """Scripted ES double: in-memory transient settings + a shrinking shard list.

    ``shard_counts`` is a list of per-call lengths returned by ``cat_shards_on_node`` (e.g.
    ``[2, 1, 0]`` drains in three polls). ``transient`` mirrors the FLAT-key shape that
    ``cluster_settings_full`` returns; ``persistent`` is always empty here.
    """

    def __init__(self, shard_counts: list[int], *, transient: dict | None = None) -> None:
        self.shard_counts = list(shard_counts)
        self._call = 0
        self.transient: dict = dict(transient or {})
        self.put_bodies: list[dict] = []

    async def cluster_settings_full(self) -> dict:
        return {"transient": dict(self.transient), "persistent": {}}

    async def put_cluster_settings(self, body: dict) -> dict:
        self.put_bodies.append(body)
        for key, value in body.get("transient", {}).items():
            if value is None:
                self.transient.pop(key, None)
            else:
                self.transient[key] = value
        return {"acknowledged": True}

    async def cat_shards_on_node(self, node: str) -> list[dict]:  # noqa: ARG002
        count = self.shard_counts[min(self._call, len(self.shard_counts) - 1)]
        self._call += 1
        return [{"node": node} for _ in range(count)]


def _job(node_name: str = "es01") -> SimpleNamespace:
    return SimpleNamespace(node_name=node_name, detail="")


# ── _exclude_set ──────────────────────────────────────────────────────────────


def test_exclude_set_reads_flat_transient_key():
    settings = {"transient": {_EXCLUDE_KEY: "a,b"}, "persistent": {}}
    assert _exclude_set(settings) == {"a", "b"}


def test_exclude_set_reads_persistent_when_transient_absent():
    settings = {"transient": {}, "persistent": {_EXCLUDE_KEY: "x"}}
    assert _exclude_set(settings) == {"x"}


def test_exclude_set_empty_when_unset():
    assert _exclude_set({"transient": {}, "persistent": {}}) == set()


# ── execute_drain_node ────────────────────────────────────────────────────────


async def test_drain_adds_node_polls_to_zero_and_sets_detail():
    es = FakeES(shard_counts=[2, 1, 0])
    job = _job("es01")
    messages: list[str] = []

    async def on_progress(text: str) -> None:
        messages.append(text)

    await execute_drain_node(es, job, on_progress=on_progress, delay=0)

    # Exclusion was written with the drained node present.
    assert es.transient[_EXCLUDE_KEY] == "es01"
    # Progress walked the shard count down to zero.
    assert messages == ["shards left: 2", "shards left: 1", "shards left: 0"]
    # Detail names the node and is set only after draining completed.
    assert "es01" in job.detail


async def test_drain_appends_to_existing_exclusion_without_clobbering():
    es = FakeES(shard_counts=[1, 0], transient={_EXCLUDE_KEY: "old-node"})
    job = _job("es01")

    await execute_drain_node(es, job, delay=0)

    # Both the previously-excluded node and the new one are present, sorted.
    assert es.transient[_EXCLUDE_KEY] == "es01,old-node"


async def test_drain_is_idempotent_when_node_already_excluded():
    es = FakeES(shard_counts=[0], transient={_EXCLUDE_KEY: "es01"})
    job = _job("es01")

    await execute_drain_node(es, job, delay=0)

    assert es.transient[_EXCLUDE_KEY] == "es01"


async def test_drain_times_out_when_shards_never_clear():
    es = FakeES(shard_counts=[3])  # never reaches zero
    job = _job("es01")

    with pytest.raises(TimeoutError):
        await execute_drain_node(es, job, attempts=3, delay=0)


# ── undrain_node ──────────────────────────────────────────────────────────────


async def test_undrain_removes_node_and_keeps_others():
    es = FakeES(shard_counts=[0], transient={_EXCLUDE_KEY: "es01,es02"})

    await undrain_node(es, "es01")

    assert es.transient[_EXCLUDE_KEY] == "es02"
    assert es.put_bodies[-1]["transient"][_EXCLUDE_KEY] == "es02"


async def test_undrain_clears_setting_to_none_when_node_was_only_one():
    es = FakeES(shard_counts=[0], transient={_EXCLUDE_KEY: "es01"})

    await undrain_node(es, "es01")

    # Writing None clears the setting entirely.
    assert es.put_bodies[-1]["transient"][_EXCLUDE_KEY] is None
    assert _EXCLUDE_KEY not in es.transient


async def test_undrain_clears_to_none_when_node_absent():
    es = FakeES(shard_counts=[0], transient={})

    await undrain_node(es, "es01")

    assert es.put_bodies[-1]["transient"][_EXCLUDE_KEY] is None
