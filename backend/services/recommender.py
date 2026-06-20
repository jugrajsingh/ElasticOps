from datetime import UTC, datetime


def _bytes_to_gb(num_bytes: int) -> float:
    return num_bytes / (1024**3)


class RecommendationEngine:
    """Classifies analysis opportunities into tiered, actionable jobs."""

    @staticmethod
    def classify(opp: dict, analysis: dict) -> tuple[str | None, int | None]:
        opp_type = opp["type"]
        year = analysis.get("year")
        pri_size_gb = _bytes_to_gb(analysis["pri_store_bytes"])
        current_year = datetime.now(UTC).year

        if opp_type in ("segment-fragmentation", "deleted-docs"):
            if year and year < current_year:
                return "force_merge", 1
            return "force_merge", 2

        if opp_type == "over-sharded":
            if pri_size_gb < 0.5:
                return "reduce_shards", 3
            return "reduce_shards", 4

        if opp_type == "under-sharded":
            return "reduce_shards", 4

        return None, None

    @staticmethod
    def generate_jobs(analysis_results: list[dict]) -> list[dict]:
        jobs: list[dict] = []
        for a in analysis_results:
            for opp in a.get("opportunities", []):
                job_type, tier = RecommendationEngine.classify(opp, a)
                if job_type is None:
                    continue
                jobs.append(
                    {
                        "index_name": a["name"],
                        "job_type": job_type,
                        "tier": tier,
                        "severity": opp["severity"],
                        "detail": opp.get("detail", ""),
                        "current_shards": a["pri_count"],
                        "target_shards": opp.get("target_shards", a["pri_count"]),
                        "current_replicas": a.get("rep_count", 0),
                        "pri_store_bytes": a["pri_store_bytes"],
                        "doc_count": a.get("doc_count", 0),
                        "estimated_savings_shards": opp.get("wasted_shards", 0),
                    }
                )
        return jobs
