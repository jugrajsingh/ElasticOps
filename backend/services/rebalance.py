"""Shard-imbalance rebalance advisory.

Pure, advisory-only computation: given parsed node + shard rows, suggest a small set of relocate
moves that even out the shard COUNT across data nodes. Each suggestion is executable as-is via the
existing ``relocate_shard`` job; nothing here mutates the cluster.
"""

from backend.services.role_logic import is_data_node


def _role(node: dict[str, str]) -> str:
    return node.get("node.role") or node.get("role") or ""


def suggest_moves(
    nodes: list[dict[str, str]], shards: list[dict[str, str]], *, max_moves: int = 5
) -> list[dict[str, object]]:
    """Suggest relocate moves to even shard COUNT across data nodes (greedy, capped).

    Advisory only — each move is executable via the existing ``relocate_shard`` job. Greedily moves a
    shard off the heaviest data node onto the lightest until the count gap is <= 1 or ``max_moves`` is
    reached. Returns a list of ``{index, shard, from_node, to_node, size_bytes}`` dicts.
    """
    data_nodes = [n["name"] for n in nodes if is_data_node(_role(n))]
    if len(data_nodes) < 2:
        return []
    started = [s for s in shards if s.get("state") == "STARTED" and s.get("node") in data_nodes]
    # Shards still available to move off their current node (placed shards are removed as we go so a
    # suggestion never moves the same shard twice or oscillates a shard back to where it came from).
    available: dict[str, list[dict[str, str]]] = {n: [] for n in data_nodes}
    for s in started:
        available[s["node"]].append(s)
    # Projected post-move counts; the destination grows but its shards are never re-picked.
    counts = {n: len(available[n]) for n in data_nodes}
    # Nodes that have RECEIVED a shard are frozen as destinations only — never picked as a source —
    # so a planned move is never undone on a later iteration (no oscillation at small gaps).
    frozen: set[str] = set()
    moves: list[dict[str, object]] = []
    for _ in range(max_moves):
        sources = [n for n in data_nodes if n not in frozen and available[n]]
        if not sources:
            break
        hi = max(sources, key=lambda n: counts[n])
        lo = min(counts, key=lambda n: counts[n])
        if counts[hi] <= counts[lo]:
            break
        shard = available[hi].pop()
        counts[hi] -= 1
        counts[lo] += 1
        frozen.add(lo)
        moves.append(
            {
                "index": shard["index"],
                "shard": int(shard["shard"]),
                "from_node": hi,
                "to_node": lo,
                "size_bytes": int(shard.get("store") or 0),
            }
        )
    return moves
