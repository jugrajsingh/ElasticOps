"""DB access for cluster snapshots: one row per (cluster_id, kind), upsert + read."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.snapshot import ClusterSnapshot


async def upsert_snapshot(
    db: AsyncSession,
    cluster_id: int,
    kind: str,
    payload: dict | list,
    item_count: int,
    duration_ms: int,
) -> ClusterSnapshot:
    """Insert or update the single snapshot row for (cluster_id, kind).

    The ``UniqueConstraint(cluster_id, kind)`` makes "one latest row" structural; this updates the
    existing row in place when present, else inserts a new one. ``fetched_at`` is refreshed to now.
    """
    existing = await get_latest(db, cluster_id, kind)
    if existing is not None:
        existing.payload = payload
        existing.item_count = item_count
        existing.duration_ms = duration_ms
        existing.fetched_at = _now()
        snapshot = existing
    else:
        snapshot = ClusterSnapshot(
            cluster_id=cluster_id,
            kind=kind,
            payload=payload,
            item_count=item_count,
            duration_ms=duration_ms,
            fetched_at=_now(),
        )
        db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_latest(db: AsyncSession, cluster_id: int, kind: str) -> ClusterSnapshot | None:
    """Return the snapshot row for (cluster_id, kind), or None if absent."""
    result = await db.execute(
        select(ClusterSnapshot).where(
            ClusterSnapshot.cluster_id == cluster_id,
            ClusterSnapshot.kind == kind,
        )
    )
    return result.scalar_one_or_none()


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(tzinfo=None)
