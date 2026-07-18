"""Tier-aware node-role helpers — the single backend source of truth for role classification.

Mirrors the (already-fixed) frontend ``isDataNode`` (ShardMap.tsx) and ``formatRole`` (Nodes.tsx).

The bug this fixes: Elasticsearch's ``node.role`` is a string of single-letter role codes (e.g.
``"dim"``, ``"his"``, ``"m"``), while a coordinating-only node reports the literal ``"coord"`` (or
``"-"``). A naive ``"d" in role`` check wrongly counts ``"coord"`` as a data node (it contains a
``d``) and drops real hot/warm/cold data nodes whose role string lacks a literal ``"d"`` (e.g.
``"his"`` = hot + ingest + search). Shards only live on data nodes, so this classification drives
the shard-map / pivot node columns and the overview role counts.
"""

# Data-tier role letters: (d)ata, (h)ot, (w)arm, (c)old, (s)earch/frozen.
DATA_TIER_LETTERS = ("d", "h", "w", "c", "s")

# Sentinels that mark a coordinating-only node (carries no shards despite "coord" containing a "d").
_COORD_ROLES = ("coord", "-", "")


def is_data_node(role: str) -> bool:
    """Return True when the node carries shards (has any data-tier role letter).

    Coordinating-only nodes (``coord``/``-``/``""``) are never data nodes even though ``"coord"``
    contains a ``"d"``.
    """
    if role in _COORD_ROLES:
        return False
    return any(letter in role for letter in DATA_TIER_LETTERS)


def node_tier(role: str) -> str:
    """Return a single human-facing tier label for a node role.

    One of: ``master``, ``hot``, ``warm``, ``cold``, ``data``, ``coord``. Matches the frontend
    ``formatRole``: coordinating sentinels → ``coord``; a lone ``"m"`` → ``master``; otherwise the
    first data tier present (hot > warm > cold) or generic ``data``.
    """
    if role in _COORD_ROLES:
        return "coord"
    if role == "m":
        return "master"
    if "h" in role:
        return "hot"
    if "w" in role:
        return "warm"
    if "c" in role:
        return "cold"
    if "d" in role or "s" in role:
        return "data"
    return role


def role_counts(nodes: list[dict]) -> dict[str, int]:
    """Tier-aware tally of nodes by category from parsed node dicts.

    Returns counts for ``master``, ``data``, ``coord``, ``ingest`` and ``other``. A node is counted
    as ``data`` when :func:`is_data_node` is True; as ``master`` for a master-only role; as ``coord``
    for coordinating sentinels; as ``ingest`` for an ingest-only role; ``other`` otherwise. Each node
    is counted exactly once (data classification takes precedence so e.g. ``"his"`` is data, not
    ingest).
    """
    counts = {"master": 0, "data": 0, "coord": 0, "ingest": 0, "other": 0}
    for node in nodes:
        role = node.get("role", "")
        if role in _COORD_ROLES:
            counts["coord"] += 1
        elif is_data_node(role):
            counts["data"] += 1
        elif "m" in role:
            counts["master"] += 1
        elif "i" in role:
            counts["ingest"] += 1
        else:
            counts["other"] += 1
    return counts
