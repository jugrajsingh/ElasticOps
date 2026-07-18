"""Tests for the shard-imbalance rebalance advisory (pure suggest_moves)."""

from backend.services.rebalance import suggest_moves


def _node(name):
    return {"name": name, "node.role": "d", "disk.total": "100", "disk.used": "10"}


def _shard(index, sh, node, store):
    return {
        "index": index,
        "shard": str(sh),
        "prirep": "p",
        "state": "STARTED",
        "node": node,
        "store": str(store),
    }


def test_should_suggest_move_from_overloaded_to_underloaded():
    nodes = [_node("a"), _node("b")]
    shards = [_shard("i", 0, "a", 100), _shard("i", 1, "a", 100), _shard("i", 2, "b", 100)]
    moves = suggest_moves(nodes, shards, max_moves=5)
    assert len(moves) >= 1
    assert moves[0]["from_node"] == "a"
    assert moves[0]["to_node"] == "b"


def test_should_suggest_no_moves_when_balanced():
    nodes = [_node("a"), _node("b")]
    shards = [_shard("i", 0, "a", 100), _shard("i", 1, "b", 100)]
    assert suggest_moves(nodes, shards) == []
