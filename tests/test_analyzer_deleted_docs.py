"""Tests for deleted-docs opportunity detection in IndexAnalyzer.

The analyzer consumes the PARSED (underscore-keyed) index shape produced by ``_parse_index`` —
i.e. ``docs_count`` / ``docs_deleted`` / ``store_size`` / ``pri_store_size`` — not the raw dotted
``_cat`` keys. The fixture below matches that parsed shape.
"""

from backend.services.analyzer import IndexAnalyzer


def _idx(docs_count, docs_deleted, store=10_000_000_000):
    return {
        "index": "i",
        "health": "green",
        "status": "open",
        "pri": 2,
        "rep": 1,
        "docs_count": docs_count,
        "docs_deleted": docs_deleted,
        "store_size": store,
        "pri_store_size": store,
    }


def test_should_emit_deleted_docs_when_ratio_high():
    a = IndexAnalyzer([_idx(1000, 400)], shards=[]).analyze_all()
    opp_types = {o["type"] for o in a[0]["opportunities"]}
    assert "deleted-docs" in opp_types


def test_should_not_emit_deleted_docs_when_ratio_low():
    a = IndexAnalyzer([_idx(1000, 10)], shards=[]).analyze_all()
    opp_types = {o["type"] for o in a[0]["opportunities"]}
    assert "deleted-docs" not in opp_types
