import asyncio
import contextlib


def largest_factor_le(current: int, target: int) -> int:
    """Largest divisor of `current` that is >= 1, < current, and <= target."""
    upper = min(target, current - 1)
    for n in range(upper, 0, -1):
        if current % n == 0:
            return n
    return 1


def pick_target_node(nodes: list[dict]) -> str:
    """Choose a data node with the most free disk to hold all shards during shrink."""
    def is_data(n: dict) -> bool:
        return "d" in (n.get("node.role") or n.get("role") or "")

    def free(n: dict) -> int:
        return int(n.get("disk.total") or 0) - int(n.get("disk.used") or 0)

    candidates = [n for n in nodes if is_data(n)] or nodes
    if not candidates:
        raise ValueError("No nodes available to host the shrink target")  # noqa: TRY003
    return max(candidates, key=free)["name"]


async def wait_until_green(es, index: str, *, attempts: int = 150, delay: float = 2.0) -> dict:
    for _ in range(attempts):
        health = None
        with contextlib.suppress(Exception):
            health = await es.index_health(index)
        if health and health.get("status") == "green" and health.get("relocating_shards", 0) == 0:
            return health
        if delay:
            await asyncio.sleep(delay)
    raise TimeoutError(f"Index '{index}' did not reach green state in time")  # noqa: TRY003


async def execute_force_merge(es, job) -> None:
    await es.post(f"/{job.index_name}/_forcemerge", params={"max_num_segments": "1"})


async def execute_reduce_shards(es, job, *, delay: float = 2.0) -> None:
    """Reduce primary shard count via the ES _shrink workflow.

    Creates `<index>-shrink-<n>`; the source index is left intact (non-destructive).
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
    target_index = f"{source}-shrink-{target}"
    node = pick_target_node(await es.cat_nodes_detailed())

    try:
        await es.set_index_settings(
            source,
            {"index.blocks.write": True, "index.routing.allocation.require._name": node},
        )
        await wait_until_green(es, source, delay=delay)
        await es.shrink_index(
            source,
            target_index,
            {
                "index.number_of_shards": target,
                "index.number_of_replicas": job.current_replicas,
                "index.blocks.write": None,
                "index.routing.allocation.require._name": None,
            },
        )
        await wait_until_green(es, target_index, delay=delay)
    finally:
        # The write-block + single-node pin is only scaffolding for the shrink;
        # always restore the source to a writable, unpinned state (success OR failure).
        with contextlib.suppress(Exception):
            await es.set_index_settings(
                source,
                {"index.blocks.write": None, "index.routing.allocation.require._name": None},
            )

    job.target_shards = target
    job.task_id = target_index
    job.detail = (
        f"Shrunk '{source}' ({current}->{target} shards) into '{target_index}'. "
        "Original index retained; verify, then swap/delete manually."
    )
