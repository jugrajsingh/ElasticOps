import pytest

from backend.services.es_client import ESClient


@pytest.mark.asyncio
async def test_reroute_posts_move_command(monkeypatch):
    calls = {}

    async def fake_request(_self, method, path, **kw):
        calls.update(method=method, path=path, json=kw.get("json"))
        return {"acknowledged": True}

    monkeypatch.setattr(ESClient, "request", fake_request)
    es = ESClient(base_url="http://es.example.com", username="", password="")
    out = await es.reroute([{"move": {"index": "i", "shard": 0, "from_node": "a", "to_node": "b"}}])
    assert calls["method"] == "POST"
    assert calls["path"] == "/_cluster/reroute"
    assert calls["json"]["commands"][0]["move"]["to_node"] == "b"
    assert out["acknowledged"] is True


@pytest.mark.asyncio
async def test_get_task_fetches_correct_path(monkeypatch):
    calls = {}

    async def fake_request(_self, method, path, **_kw):
        calls.update(method=method, path=path)
        return {"completed": True, "task": {"status": {}}}

    monkeypatch.setattr(ESClient, "request", fake_request)
    es = ESClient(base_url="http://es.example.com", username="", password="")
    out = await es.get_task("nodeA:12345")
    assert calls["method"] == "GET"
    assert calls["path"] == "/_tasks/nodeA:12345"
    assert out["completed"] is True


@pytest.mark.asyncio
async def test_forcemerge_async_uses_wait_for_completion_false(monkeypatch):
    calls = {}

    async def fake_request(_self, method, path, **kw):
        calls.update(method=method, path=path, params=kw.get("params"))
        return {"task": "nodeA:99"}

    monkeypatch.setattr(ESClient, "request", fake_request)
    es = ESClient(base_url="http://es.example.com", username="", password="")
    out = await es.forcemerge_async("my-index")
    assert calls["method"] == "POST"
    assert calls["path"] == "/my-index/_forcemerge"
    assert calls["params"]["wait_for_completion"] == "false"
    assert calls["params"]["max_num_segments"] == "1"
    assert out["task"] == "nodeA:99"


@pytest.mark.asyncio
async def test_forcemerge_async_only_expunge_deletes(monkeypatch):
    calls = {}

    async def fake_request(_self, _method, _path, **kw):
        calls.update(params=kw.get("params"))
        return {"task": "nodeA:100"}

    monkeypatch.setattr(ESClient, "request", fake_request)
    es = ESClient(base_url="http://es.example.com", username="", password="")
    await es.forcemerge_async("my-index", only_expunge_deletes=True)
    assert calls["params"]["only_expunge_deletes"] == "true"
    assert "max_num_segments" not in calls["params"]


@pytest.mark.asyncio
async def test_cat_shards_on_node_filters_by_node(monkeypatch):
    shards = [
        {"index": "a", "shard": "0", "node": "node1"},
        {"index": "b", "shard": "0", "node": "node2"},
        {"index": "c", "shard": "1", "node": "node1"},
    ]

    async def fake_cat_shards_detailed(_self):
        return shards

    monkeypatch.setattr(ESClient, "cat_shards_detailed", fake_cat_shards_detailed)
    es = ESClient(base_url="http://es.example.com", username="", password="")
    result = await es.cat_shards_on_node("node1")
    assert len(result) == 2
    assert all(r["node"] == "node1" for r in result)


@pytest.mark.asyncio
async def test_cat_shards_on_node_returns_empty_for_unknown_node(monkeypatch):
    async def fake_cat_shards_detailed(_self):
        return [{"index": "a", "shard": "0", "node": "node1"}]

    monkeypatch.setattr(ESClient, "cat_shards_detailed", fake_cat_shards_detailed)
    es = ESClient(base_url="http://es.example.com", username="", password="")
    result = await es.cat_shards_on_node("ghost-node")
    assert result == []
