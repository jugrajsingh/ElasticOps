from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from backend.services import role_logic

if TYPE_CHECKING:
    from backend.models.job import Job
    from backend.services.es_client import ESClient

_EXCLUDE_KEY = "cluster.routing.allocation.exclude._name"

ProgressCb = Callable[[str], Awaitable[None]]


def largest_factor_le(current: int, target: int) -> int:
    """Largest divisor of `current` that is >= 1, < current, and <= target."""
    upper = min(target, current - 1)
    for n in range(upper, 0, -1):
        if current % n == 0:
            return n
    return 1


def smallest_multiple_ge(current: int, target_min: int) -> int:
    """Smallest multiple of ``current`` that is >= ``target_min`` (ES _split requires a multiple)."""
    if target_min <= current:
        return current
    times = -(-target_min // current)  # ceil division
    return current * times


def pick_target_node(nodes: list[dict]) -> str:
    """Choose a data node with the most free disk to hold all shards during shrink."""

    def is_data(n: dict) -> bool:
        return role_logic.is_data_node(n.get("node.role") or n.get("role") or "")

    def free(n: dict) -> int:
        return int(n.get("disk.total") or 0) - int(n.get("disk.used") or 0)

    candidates = [n for n in nodes if is_data(n)] or nodes
    if not candidates:
        raise ValueError("No nodes available to host the shrink target")  # noqa: TRY003
    return max(candidates, key=free)["name"]


async def wait_until_green(es: ESClient, index: str, *, attempts: int = 150, delay: float = 2.0) -> dict:
    for _ in range(attempts):
        health = None
        with contextlib.suppress(Exception):
            health = await es.index_health(index)
        if health and health.get("status") == "green" and health.get("relocating_shards", 0) == 0:
            return health
        if delay:
            await asyncio.sleep(delay)
    raise TimeoutError(f"Index '{index}' did not reach green state in time")  # noqa: TRY003


async def wait_until_primaries_on_node(
    es: ESClient, index: str, node: str, *, attempts: int = 150, delay: float = 2.0
) -> None:
    """Block until every PRIMARY shard of ``index`` is STARTED on ``node`` (shrink pre-flight).

    ES ``_shrink`` requires a copy of every shard colocated on one node. We assert this against the
    actual shard table (``_cat/shards``), NOT cluster health: immediately after a ``require._name``
    change, ``_cluster/health`` can still report ``relocating_shards == 0`` before the reroute it just
    triggered surfaces, so a health check races the relocation and the shrink fires while shards are
    still scattered (ES then returns 500). Replicas are intentionally ignored — a replica cannot share
    its primary's node, so pinning every copy to one node leaves replicas unassigned and the index
    never reaches green; only primary colocation matters for the shrink.
    """
    for _ in range(attempts):
        rows: list[dict] = []
        with contextlib.suppress(Exception):
            rows = await es.cat_shards_detailed()
        primaries = [r for r in rows if r.get("index") == index and r.get("prirep") == "p"]
        if primaries and all(r.get("state") == "STARTED" and r.get("node") == node for r in primaries):
            return
        if delay:
            await asyncio.sleep(delay)
    raise TimeoutError(f"Primaries of '{index}' did not colocate on '{node}' in time")  # noqa: TRY003


def _forcemerge_failure(status: dict) -> str | None:
    """Return a failure reason from a COMPLETED force-merge task, or ``None`` if it succeeded.

    ES surfaces a failed force-merge two ways: a top-level ``error`` when the task itself errors,
    or per-shard failures under ``response._shards`` (a ``failed`` count with an optional
    ``failures`` list) when some shards could not merge. A synchronous POST would have masked
    both behind a swallowed read timeout; polling the task lets us report them.
    """
    error = status.get("error")
    if error:
        return (error.get("reason") if isinstance(error, dict) else str(error)) or "task error"
    shards = (status.get("response") or {}).get("_shards") or {}
    if shards.get("failed"):
        failures = shards.get("failures") or []
        if failures:
            first = failures[0]
            reason = first.get("reason") if isinstance(first, dict) else str(first)
            return f"{shards['failed']} shard(s) failed: {reason}"
        return f"{shards['failed']} shard(s) failed"
    return None


async def _run_forcemerge_task(
    es: ESClient,
    job: Job,
    *,
    only_expunge_deletes: bool,
    on_progress: ProgressCb | None,
    attempts: int,
    delay: float,
) -> None:
    """Submit a force-merge via the ES Tasks API (``wait_for_completion=false``) and poll to done.

    Mirrors :func:`execute_reindex`: submits without blocking so a long merge never hits the client
    read timeout, records the task id on the job, polls until the task reports completion, then
    raises :class:`RuntimeError` on a task-level failure or :class:`TimeoutError` if it never
    finishes within ``attempts``.
    """
    action = "expunge deletes" if only_expunge_deletes else "force merge"
    resp = await es.forcemerge_async(job.index_name, only_expunge_deletes=only_expunge_deletes)
    task_id = resp.get("task")
    if task_id is None:
        raise RuntimeError(f"{action} of '{job.index_name}' did not return a task id")  # noqa: TRY003
    job.task_id = task_id
    for _ in range(attempts):
        status = None
        with contextlib.suppress(Exception):
            status = await es.get_task(task_id)
        if status is None:
            if delay:
                await asyncio.sleep(delay)
            continue
        if on_progress:
            await on_progress(f"{action}: '{job.index_name}'...")
        if status.get("completed"):
            failure = _forcemerge_failure(status)
            if failure is not None:
                raise RuntimeError(f"{action} of '{job.index_name}' failed: {failure}")  # noqa: TRY003
            return
        if delay:
            await asyncio.sleep(delay)
    raise TimeoutError(f"{action} of '{job.index_name}' did not complete in time")  # noqa: TRY003


async def execute_force_merge(
    es: ESClient, job: Job, *, on_progress: ProgressCb | None = None, attempts: int = 10000, delay: float = 5.0
) -> None:
    """Force-merge ``job.index_name`` down to a single segment via the ES Tasks API (async, polled).

    Submits with ``wait_for_completion=false`` so a merge that runs for minutes/hours never exceeds
    the httpx read timeout (which previously marked the job failed while ES kept merging), then
    polls the task to completion.
    """
    await _run_forcemerge_task(
        es, job, only_expunge_deletes=False, on_progress=on_progress, attempts=attempts, delay=delay
    )
    job.detail = f"Force-merged '{job.index_name}' to a single segment."


async def execute_expunge_deletes(
    es: ESClient, job: Job, *, on_progress: ProgressCb | None = None, attempts: int = 10000, delay: float = 5.0
) -> None:
    """Force-merge expunging only deleted docs (reclaims space without a full segment rewrite).

    Runs asynchronously via the ES Tasks API (see :func:`execute_force_merge`) so a large index
    does not exceed the client read timeout.
    """
    await _run_forcemerge_task(
        es, job, only_expunge_deletes=True, on_progress=on_progress, attempts=attempts, delay=delay
    )
    job.detail = f"Expunged deleted docs from '{job.index_name}'."


async def _copy_started_on(es: ESClient, index: str, shard: int, node: str) -> bool:
    """True if any copy (primary or replica) of (index, shard) is STARTED on `node`.

    Shards expose ``shard`` as a string (e.g. "0") and have two rows when replicated, so we
    match on index+shard loosely (string compare) and treat "done" as ANY matching copy being
    STARTED on the target node — we don't disambiguate primary vs replica.
    """
    for row in await es.cat_shards_detailed():
        if (
            row.get("index") == index
            and str(row.get("shard")) == str(shard)
            and row.get("node") == node
            and row.get("state") == "STARTED"
        ):
            return True
    return False


async def execute_relocate_shard(
    es: ESClient, job: Job, *, on_progress: ProgressCb | None = None, attempts: int = 150, delay: float = 2.0
) -> None:
    """Move one shard copy of `job.index_name` from `from_node` to `to_node` via _cluster/reroute.

    Idempotent: if a copy of (index, shard) is already STARTED on ``to_node``, returns without
    rerouting. Otherwise issues the move command and polls until a copy is STARTED on ``to_node``,
    raising :class:`TimeoutError` if it does not settle within ``attempts``.
    """
    index, shard = job.index_name, job.shard_number
    if await _copy_started_on(es, index, shard, job.to_node):
        job.detail = f"Shard {index}[{shard}] already STARTED on {job.to_node}; no relocation needed."
        return

    await es.reroute([{"move": {"index": index, "shard": shard, "from_node": job.from_node, "to_node": job.to_node}}])

    for _ in range(attempts):
        if on_progress:
            await on_progress(f"Relocating shard {index}[{shard}] to {job.to_node}...")
        if await _copy_started_on(es, index, shard, job.to_node):
            job.detail = f"Relocated shard {index}[{shard}] from {job.from_node} to {job.to_node}."
            return
        if delay:
            await asyncio.sleep(delay)

    raise TimeoutError(f"Shard {index}[{shard}] did not relocate to {job.to_node} in time")  # noqa: TRY003


async def _index_exists(es: ESClient, index: str) -> bool:
    """True if ``index`` exists (an ``index_health`` lookup succeeds)."""
    try:
        await es.index_health(index)
    except Exception:  # noqa: BLE001 — any failure (404 included) means "not present for our purposes"
        return False
    return True


async def _capture_index_metadata(es: ESClient, index: str) -> dict | None:
    """Best-effort capture of ``index``'s mappings, aliases, and analysis settings.

    Re-applied when the in-place resize recreates ``source`` so the resize no longer silently drops
    field mappings, aliases, and custom analyzers (a bare ``create_index`` with only shard/replica
    counts would lose them). Returns ``None`` when the definition can't be read (e.g. a minimal test
    double without ``get_index``); the caller then recreates with shard/replica counts only, as before.
    """
    getter = getattr(es, "get_index", None)
    if getter is None:
        return None
    try:
        defn = await getter(index)
    except Exception:  # noqa: BLE001 — best-effort; the resize still completes without preserved metadata
        return None
    settings_index = (defn.get("settings") or {}).get("index") or {}
    return {
        "mappings": defn.get("mappings") or {},
        "aliases": defn.get("aliases") or {},
        "analysis": settings_index.get("analysis"),
    }


async def _resize_in_place(
    es: ESClient,
    source: str,
    target_shards: int,
    replicas: int,
    *,
    op: str,
    on_progress: ProgressCb | None = None,
    delay: float = 2.0,
) -> None:
    """Replace ``source``'s shard count IN PLACE via a verified temp-copy + reindex-back.

    ``op`` is ``"split"`` or ``"shrink"``. The source keeps its name with ``target_shards``
    primaries and NO suffixed copy survives. The sequence is crash-safe: the source is NEVER
    deleted without a verified equal-doc-count replacement living in the temp index.

    Steps:
      1. Resume guard — recover a half-finished prior attempt by inspecting which of source/temp
         exist.
      2. Write-block source, create the temp with the new shard count, wait green.
      3. Verify ``count(temp) == count(source)`` (abort, source intact, if not).
      4. Delete source.
      5. Recreate source with ``target_shards`` and reindex temp -> source (polled).
      6. Verify ``count(source) == count(temp)`` (raise, keeping temp, if not).
      7. Delete temp.
    """
    temp = f"{source}__resize"

    async def progress(msg: str) -> None:
        if on_progress:
            await on_progress(msg)

    source_exists = await _index_exists(es, source)
    temp_exists = await _index_exists(es, temp)

    # 1. RESUME GUARD.
    if not source_exists and temp_exists:
        # A prior attempt already deleted source after a verified copy; resume at the reindex-back.
        await _reindex_temp_into_source(es, source, temp, target_shards, replicas, progress, delay)
        return
    if not source_exists and not temp_exists:
        raise ValueError(f"Cannot {op} '{source}': neither source nor temp '{temp}' exists")  # noqa: TRY003
    # source exists — clear any stale temp from an aborted earlier run before re-copying.
    if temp_exists:
        await es.delete_index(temp)

    # 2. Create resized copy.
    await progress(f"{op}: creating resized copy")
    try:
        if op == "shrink":
            # ES _shrink REQUIRES every source shard to live on ONE node, write-blocked first. Pin
            # the source to a single data node and wait for its shards to migrate there (green).
            node = pick_target_node(await es.cat_nodes_detailed())
            await progress(f"shrink: colocating shards on {node}")
            await es.set_index_settings(
                source,
                {"index.blocks.write": True, "index.routing.allocation.require._name": node},
            )
            # Gate on the SHARD TABLE, not cluster health: _shrink needs every primary STARTED on
            # `node`, and health reports relocating==0 spuriously right after the pin (the reroute it
            # triggered hasn't surfaced), which would let the shrink fire mid-relocation and 500.
            await wait_until_primaries_on_node(es, source, node, delay=delay)
            copy_settings = {
                "index.number_of_shards": target_shards,
                "index.number_of_replicas": replicas,
                "index.blocks.write": None,
                # Clear the colocation pin on the temp so its shards can spread normally.
                "index.routing.allocation.require._name": None,
            }
        else:
            await es.set_index_settings(source, {"index.blocks.write": True})
            await wait_until_green(es, source, delay=delay)
            copy_settings = {
                "index.number_of_shards": target_shards,
                "index.number_of_replicas": replicas,
                "index.blocks.write": None,
            }
        copy = es.split_index if op == "split" else es.shrink_index
        await copy(source, temp, copy_settings)
        await wait_until_green(es, temp, delay=delay)
    finally:
        # The write block (and, for shrink, the node pin) are only scaffolding for the copy; restore
        # source to writable/unpinned — but only if source still exists (deleted later in happy path).
        if await _index_exists(es, source):
            with contextlib.suppress(Exception):
                await es.set_index_settings(
                    source,
                    {"index.blocks.write": None, "index.routing.allocation.require._name": None},
                )

    # 3. VERIFY the copy before destroying anything.
    await progress("verifying copy")
    if await es.count(temp) != await es.count(source):
        await es.delete_index(temp)
        raise ValueError(  # noqa: TRY003
            f"{op} copy of '{source}' has a mismatched doc count; aborted (source intact)"
        )

    # 4. Capture the source's mappings/aliases/analysis (so the recreate preserves them), then
    # delete source (its data is now safely mirrored in the verified temp).
    preserved = await _capture_index_metadata(es, source)
    await progress("replacing original (reindex back)")
    await es.delete_index(source)

    # 5–7. Recreate source, reindex temp -> source, verify, drop temp.
    await _reindex_temp_into_source(es, source, temp, target_shards, replicas, progress, delay, preserved=preserved)


async def _reindex_temp_into_source(
    es: ESClient,
    source: str,
    temp: str,
    target_shards: int,
    replicas: int,
    progress: ProgressCb,
    delay: float,
    *,
    preserved: dict | None = None,
) -> None:
    """Recreate ``source`` with ``target_shards``, reindex ``temp`` -> ``source``, verify, drop temp.

    Assumes ``source`` has already been deleted and ``temp`` holds the verified data. ``preserved``
    carries the source's mappings/aliases/analysis so the recreate keeps them; on the resume path
    (source already gone before capture) it is ``None`` and we fall back to the temp's own definition.
    Safe to call on resume: it only deletes ``temp`` after a final equal-doc-count check against ``source``.
    """
    if not await _index_exists(es, source):
        meta = preserved if preserved is not None else await _capture_index_metadata(es, temp)
        if meta:
            index_settings: dict = {"number_of_shards": target_shards, "number_of_replicas": replicas}
            if meta.get("analysis"):
                index_settings["analysis"] = meta["analysis"]
            await es.create_index(
                source,
                {"index": index_settings},
                mappings=(meta.get("mappings") or None),
                aliases=(meta.get("aliases") or None),
            )
        else:
            await es.create_index(
                source,
                {"index.number_of_shards": target_shards, "index.number_of_replicas": replicas},
            )
    resp = await es.reindex_async(temp, source)
    task_id = resp["task"]
    while True:
        status = await es.get_task(task_id)
        await progress("reindexing...")
        if status.get("completed"):
            break
        if delay:
            await asyncio.sleep(delay)
    await wait_until_green(es, source, delay=delay)

    # 6. VERIFY the replacement; keep temp on mismatch so the data is recoverable.
    await progress("verifying replacement")
    if await es.count(source) != await es.count(temp):
        raise ValueError(  # noqa: TRY003
            f"Replacement of '{source}' has a mismatched doc count; temp '{temp}' retained"
        )

    # 7. Drop the now-redundant temp.
    await es.delete_index(temp)


async def execute_reduce_shards(
    es: ESClient, job: Job, *, on_progress: ProgressCb | None = None, delay: float = 2.0
) -> None:
    """Reduce primary shard count IN PLACE via the ES _shrink workflow.

    Shrinks ``job.index_name`` into a temp copy, then reindexes it back so the original keeps its
    name with the new shard count; no ``-shrink-<n>`` copy survives. The source is never deleted
    without a verified equal-doc-count replacement (see :func:`_resize_in_place`).
    """
    current = job.current_shards
    if current <= 1 or job.target_shards >= current:
        raise ValueError(  # noqa: TRY003
            f"Cannot reduce '{job.index_name}': current={current}, target={job.target_shards}"
        )
    target = largest_factor_le(current, job.target_shards)
    if target >= current or target < 1:
        raise ValueError(f"No valid shrink factor for current={current}, target={job.target_shards}")  # noqa: TRY003

    source = job.index_name
    await _resize_in_place(es, source, target, job.current_replicas, op="shrink", on_progress=on_progress, delay=delay)

    job.target_shards = target
    job.task_id = None
    job.detail = f"Shrunk '{source}' {current}->{target} shards in place (no temp index retained)."


async def execute_split_shards(
    es: ESClient, job: Job, *, on_progress: ProgressCb | None = None, delay: float = 2.0
) -> None:
    """Increase primary shard count IN PLACE via the ES _split workflow.

    ES _split requires the target shard count to be a multiple of the source's; we round the
    requested ``target_shards`` up to the smallest valid multiple, split into a temp copy, then
    reindex it back so the original keeps its name with the new shard count — no ``-split-<n>`` copy
    survives. The source is never deleted without a verified replacement (see
    :func:`_resize_in_place`).
    """
    current = job.current_shards
    target = smallest_multiple_ge(current, job.target_shards)
    if target <= current:
        raise ValueError(  # noqa: TRY003
            f"Cannot split '{job.index_name}': current={current}, target={job.target_shards}"
        )

    source = job.index_name
    await _resize_in_place(es, source, target, job.current_replicas, op="split", on_progress=on_progress, delay=delay)

    job.target_shards = target
    job.task_id = None
    job.detail = f"Split '{source}' {current}->{target} shards in place (no temp index retained)."


async def execute_promote_index(es: ESClient, job: Job, *, on_progress: ProgressCb | None = None) -> None:  # noqa: ARG001
    """Atomically point ``job.node_name`` (the alias) at ``job.target_index``, off ``job.index_name``.

    The alias name is carried in ``job.node_name`` and the new index in ``job.target_index``. When
    ``job.from_node == "delete"`` the old source index is also deleted (guarded, opt-in); otherwise
    the source is retained for verification.
    """
    alias = job.node_name
    actions = [
        {"remove": {"index": job.index_name, "alias": alias}},
        {"add": {"index": job.target_index, "alias": alias}},
    ]
    await es.update_aliases(actions)
    if job.from_node == "delete":
        await es.delete_index(job.index_name)
        job.detail = f"Promoted alias '{alias}' to '{job.target_index}'; deleted source '{job.index_name}'."
    else:
        job.detail = f"Promoted alias '{alias}' to '{job.target_index}'; source retained."


async def execute_reindex(
    es: ESClient,
    job: Job,
    *,
    on_progress: ProgressCb | None = None,
    attempts: int = 10000,
    delay: float = 5.0,
) -> None:
    """Reindex ``job.index_name`` -> ``job.target_index`` via the ES Tasks API (async, polled).

    Non-destructive: creates the destination index, leaving the source intact. Starts the reindex
    with ``wait_for_completion=false`` and polls the returned task until it reports completion,
    raising :class:`TimeoutError` if it does not finish within ``attempts``.
    """
    resp = await es.reindex_async(job.index_name, job.target_index)
    task_id = resp.get("task")
    if task_id is None:
        raise RuntimeError(f"Reindex '{job.index_name}' did not return a task id")  # noqa: TRY003
    job.task_id = task_id
    for _ in range(attempts):
        status = None
        with contextlib.suppress(Exception):
            status = await es.get_task(task_id)
        if status is None:
            if delay:
                await asyncio.sleep(delay)
            continue
        if on_progress:
            await on_progress("reindexing...")
        if status.get("completed"):
            job.detail = f"Reindexed '{job.index_name}' -> '{job.target_index}'."
            return
        if delay:
            await asyncio.sleep(delay)
    raise TimeoutError(f"Reindex '{job.index_name}' did not complete in time")  # noqa: TRY003


def _exclude_set(settings: dict) -> set[str]:
    """Read the allocation-exclude node set from FLAT cluster settings.

    ``cluster_settings_full`` requests ``flat_settings=true``, so the exclude value lives directly
    under the flat key as a comma-joined string in ``transient`` and/or ``persistent``. Transient
    takes precedence over persistent (it overrides at runtime); we union them so a node excluded
    persistently is never silently dropped.
    """
    transient = settings.get("transient") or {}
    persistent = settings.get("persistent") or {}
    raw = f"{transient.get(_EXCLUDE_KEY, '')},{persistent.get(_EXCLUDE_KEY, '')}"
    return {name for name in raw.split(",") if name}


async def execute_drain_node(
    es: ESClient, job: Job, *, on_progress: ProgressCb | None = None, attempts: int = 10000, delay: float = 5.0
) -> None:
    """Gracefully drain ``job.node_name`` by adding it to the allocation-exclude set, then poll.

    ADDS the node to the existing exclude set (never clobbers nodes already excluded), writes the
    transient setting, and polls ``cat_shards_on_node`` until no shards remain on the node —
    reporting ``"shards left: N"`` each iteration. Raises :class:`TimeoutError` if the node never
    drains within ``attempts``. Undo with :func:`undrain_node`.
    """
    current = _exclude_set(await es.cluster_settings_full())
    current.add(job.node_name)
    await es.put_cluster_settings({"transient": {_EXCLUDE_KEY: ",".join(sorted(current))}})

    for _ in range(attempts):
        left = len(await es.cat_shards_on_node(job.node_name))
        if on_progress:
            await on_progress(f"shards left: {left}")
        if left == 0:
            job.detail = f"Node '{job.node_name}' drained; safe to stop/remove. Undrain to restore."
            return
        if delay:
            await asyncio.sleep(delay)

    raise TimeoutError(f"Node '{job.node_name}' did not drain in time")  # noqa: TRY003


async def undrain_node(es: ESClient, node: str) -> None:
    """REMOVE ``node`` from the allocation-exclude set, restoring it as an allocation target.

    Writes the remaining set back as a comma-joined string, or ``None`` when the set becomes empty
    so the transient setting is cleared entirely.
    """
    current = _exclude_set(await es.cluster_settings_full())
    current.discard(node)
    value = ",".join(sorted(current)) or None
    await es.put_cluster_settings({"transient": {_EXCLUDE_KEY: value}})
