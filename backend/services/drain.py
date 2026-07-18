"""Drain pre-flight safety check — pure function, no I/O.

Decides whether it is safe to drain a node (remove all its shards and exclude it
from allocation) before any ES API calls are made.

Two safety invariants:
1. **Quorum**: at least 2 *other* data nodes must exist to relocate shards to.
2. **Disk**: the total free disk on those other data nodes must be >= the bytes
   currently stored on the node being drained.

Both checks use :func:`backend.services.role_logic.is_data_node` — the tier-aware
helper that correctly classifies ``coord``/``-``/``""`` as non-data even though
``"coord"`` contains the letter ``"d"``, and correctly counts tier roles like
``"his"`` (hot+ingest+search) as data nodes.
"""

from backend.services.role_logic import is_data_node


def preflight(node_name: str, nodes: list[dict], shards: list[dict]) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for draining *node_name*.

    Args:
        node_name: Name of the node to drain (matches ``nodes[*]["name"]``).
        nodes: List of node dicts from ``cat_nodes_detailed()``; each dict must
            contain ``name``, one of ``node.role`` / ``role``, ``disk.total``,
            and ``disk.used`` (all values may be strings or ints).
        shards: List of shard dicts from ``cat_shards_detailed()``; each dict
            must contain ``node`` and ``store`` (bytes, may be string or int).

    Returns:
        ``(True, "ok")`` when the drain is safe.
        ``(False, <human-readable reason>)`` when a safety invariant is violated.
    """
    others = [
        n for n in nodes if n.get("name") != node_name and is_data_node(n.get("node.role") or n.get("role") or "")
    ]

    if len(others) < 2:
        return (
            False,
            f"Cannot drain '{node_name}': need >=2 other data nodes to relocate to, found {len(others)}.",
        )

    on_node = sum(int(s.get("store") or 0) for s in shards if s.get("node") == node_name)
    free_elsewhere = sum(int(n.get("disk.total") or 0) - int(n.get("disk.used") or 0) for n in others)

    if on_node > free_elsewhere:
        return (
            False,
            f"Cannot drain '{node_name}': needs {on_node}B but only {free_elsewhere}B free on other data nodes.",
        )

    return True, "ok"
