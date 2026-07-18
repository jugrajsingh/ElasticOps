from config.settings import AnalyzerSettings, get_settings


def _bytes_to_gb(num_bytes: int) -> float:
    return num_bytes / (1024**3)


class IndexAnalyzer:
    """Analyzes index health and detects optimization opportunities.

    Ported from scripts/index-analyzer.py — pure computation, no IO.
    """

    def __init__(self, indices: list[dict], shards: list[dict], cfg: AnalyzerSettings | None = None):
        self._cfg: AnalyzerSettings = cfg if cfg is not None else get_settings().analyzer
        self._index_map = self._build_index_map(indices, shards)

    def _build_index_map(self, indices: list[dict], shards: list[dict]) -> dict:
        idx_map: dict[str, dict] = {}
        for row in indices:
            name = row.get("index", "")
            if not name:
                continue
            idx_map[name] = {
                "name": name,
                "health": row.get("health", ""),
                "status": row.get("status", ""),
                "pri_count": row.get("pri", 0),
                "rep_count": row.get("rep", 0),
                "doc_count": row.get("docs_count", 0),
                "docs_deleted": row.get("docs_deleted", 0),
                "store_bytes": row.get("store_size", 0),
                "pri_store_bytes": row.get("pri_store_size", 0),
                "shards": [],
            }

        for row in shards:
            idx_name = row.get("index", "")
            if idx_name not in idx_map:
                continue
            idx_map[idx_name]["shards"].append(
                {
                    "shard_num": row.get("shard", 0),
                    "prirep": row.get("prirep", ""),
                    "state": row.get("state", ""),
                    "docs": row.get("docs", 0),
                    "store_bytes": row.get("store", 0),
                    "node": row.get("node", ""),
                    "segment_count": row.get("segments_count", 0),
                }
            )

        return idx_map

    def _analyze_index(self, idx: dict) -> dict:
        pri_shards = [s for s in idx["shards"] if s["prirep"] == "p"]
        pri_store = idx["pri_store_bytes"]
        pri_count = idx["pri_count"]
        rep_count = idx["rep_count"]
        doc_count = idx["doc_count"]
        docs_deleted = int(idx.get("docs_deleted", 0) or 0)
        total_docs = doc_count + docs_deleted
        deleted_ratio = (docs_deleted / total_docs) if total_docs > 0 else 0.0
        pri_size_gb = _bytes_to_gb(pri_store)

        pri_shard_sizes = sorted([s["store_bytes"] for s in pri_shards], reverse=True)
        avg_shard_gb = _bytes_to_gb(sum(pri_shard_sizes) / len(pri_shard_sizes)) if pri_shard_sizes else 0
        max_shard_gb = _bytes_to_gb(max(pri_shard_sizes)) if pri_shard_sizes else 0

        pri_seg_counts = [s["segment_count"] for s in pri_shards]
        max_segments = max(pri_seg_counts) if pri_seg_counts else 0

        # Shard size coefficient of variation
        if len(pri_shard_sizes) > 1 and sum(pri_shard_sizes) > 0:
            mean = sum(pri_shard_sizes) / len(pri_shard_sizes)
            variance = sum((s - mean) ** 2 for s in pri_shard_sizes) / len(pri_shard_sizes)
            shard_size_cv = (variance**0.5) / mean if mean > 0 else 0
        else:
            shard_size_cv = 0

        opportunities: list[dict] = []

        # Over-sharded detection
        if pri_size_gb < self._cfg.tiny_index_max_gb and pri_count > self._cfg.ideal_max_shards_for_tiny_index:
            wasted = (pri_count - 1) * (1 + rep_count)
            opportunities.append(
                {
                    "type": "over-sharded",
                    "severity": "high" if pri_count >= 5 else "medium",
                    "detail": f"{pri_count} shards for {pri_size_gb:.2f}GB, should be 1. Wasting {wasted} shards.",
                    "wasted_shards": wasted,
                    "target_shards": 1,
                }
            )
        elif avg_shard_gb < self._cfg.ideal_shard_min_gb and pri_count > 1:
            ideal_pri = max(1, int(pri_size_gb / self._cfg.ideal_shard_max_gb) + 1)
            if ideal_pri < pri_count:
                wasted = (pri_count - ideal_pri) * (1 + rep_count)
                opportunities.append(
                    {
                        "type": "over-sharded",
                        "severity": "medium",
                        "detail": f"Avg shard {avg_shard_gb:.1f}GB, could reduce {pri_count} to {ideal_pri} shards.",
                        "wasted_shards": wasted,
                        "target_shards": ideal_pri,
                    }
                )

        # Under-sharded detection
        if max_shard_gb > self._cfg.ideal_shard_max_gb:
            ideal_pri = max(pri_count, int(pri_size_gb / self._cfg.ideal_shard_max_gb) + 1)
            if ideal_pri > pri_count:
                opportunities.append(
                    {
                        "type": "under-sharded",
                        "severity": "medium" if max_shard_gb > 100 else "low",
                        "detail": f"Max shard {max_shard_gb:.1f}GB, consider {pri_count} to {ideal_pri} shards.",
                        "wasted_shards": 0,
                        "target_shards": ideal_pri,
                    }
                )

        # Segment fragmentation
        if max_segments > self._cfg.ideal_max_segments_per_shard and idx["status"] == "open":
            opportunities.append(
                {
                    "type": "segment-fragmentation",
                    "severity": "medium" if max_segments > 30 else "low",
                    "detail": f"Max {max_segments} segments/shard. Force merge to 1 segment.",
                    "wasted_shards": 0,
                    "target_shards": pri_count,
                }
            )

        # Deleted-docs accumulation
        if deleted_ratio >= 0.20 and idx["status"] == "open":
            opportunities.append(
                {
                    "type": "deleted-docs",
                    "severity": "medium" if deleted_ratio >= 0.4 else "low",
                    "detail": f"{deleted_ratio * 100:.0f}% deleted docs ({docs_deleted}). Expunge to reclaim space.",
                    "wasted_shards": 0,
                    "target_shards": pri_count,
                }
            )

        # Shard imbalance
        if shard_size_cv > 0.3 and pri_count > 1:
            opportunities.append(
                {
                    "type": "shard-imbalance",
                    "severity": "low",
                    "detail": f"Shard size CV={shard_size_cv:.2f}. Shards are unevenly distributed.",
                    "wasted_shards": 0,
                    "target_shards": pri_count,
                }
            )

        return {
            "name": idx["name"],
            "health": idx["health"],
            "status": idx["status"],
            "pri_count": pri_count,
            "rep_count": rep_count,
            "doc_count": doc_count,
            "pri_store_bytes": pri_store,
            "store_bytes": idx["store_bytes"],
            "avg_shard_size_gb": round(avg_shard_gb, 2),
            "max_shard_size_gb": round(max_shard_gb, 2),
            "max_segments_per_shard": max_segments,
            "shard_size_cv": round(shard_size_cv, 3),
            "opportunities": opportunities,
            "opportunity_count": len(opportunities),
            "wasted_shards": sum(o.get("wasted_shards", 0) for o in opportunities),
        }

    def analyze_all(self, problems_only: bool = False) -> list[dict]:
        results = []
        for name, idx in self._index_map.items():
            if name.startswith("."):
                continue
            analysis = self._analyze_index(idx)
            if problems_only and not analysis["opportunities"]:
                continue
            results.append(analysis)
        return results
