"""Pure-function tests for backend.services.drain.preflight.

No DB, no cluster, no fixtures — just dicts in, tuple out.
"""

from backend.services.drain import preflight


def _node(name: str, role: str = "d", total: str = "100", used: str = "10") -> dict:
    return {"name": name, "node.role": role, "disk.total": total, "disk.used": used}


def _shard(node: str, store: str = "5") -> dict:
    return {"node": node, "store": store}


class TestPreflight:
    # ── guard: need >=2 other data nodes ──────────────────────────────────────

    def test_should_refuse_when_no_other_data_node(self):
        nodes = [_node("es01")]
        shards = [_shard("es01")]
        ok, reason = preflight("es01", nodes, shards)
        assert ok is False
        assert "node" in reason.lower()

    def test_should_refuse_when_only_one_other_data_node(self):
        nodes = [_node("es01"), _node("es02")]
        shards = [_shard("es01")]
        ok, reason = preflight("es01", nodes, shards)
        assert ok is False
        assert "node" in reason.lower()

    def test_should_allow_when_two_other_data_nodes_and_capacity_sufficient(self):
        nodes = [_node(n) for n in ("es01", "es02", "es03")]
        shards = [_shard("es01")]
        ok, _reason = preflight("es01", nodes, shards)
        assert ok is True

    # ── disk capacity guard ───────────────────────────────────────────────────

    def test_should_refuse_when_shards_exceed_free_disk(self):
        # es01 has 200 bytes of shards; es02+es03 each have 90 free → 180 total < 200
        nodes = [
            _node("es01", total="300", used="50"),
            _node("es02", total="100", used="10"),  # 90 free
            _node("es03", total="100", used="10"),  # 90 free
        ]
        shards = [_shard("es01", store="200")]
        ok, reason = preflight("es01", nodes, shards)
        assert ok is False
        assert "free" in reason.lower() or "disk" in reason.lower() or "200" in reason

    def test_should_allow_when_free_disk_exactly_equals_shard_size(self):
        # es02+es03 each have 90 free = 180 total; es01 has exactly 180 bytes of shards
        nodes = [
            _node("es01", total="300", used="50"),
            _node("es02", total="100", used="10"),
            _node("es03", total="100", used="10"),
        ]
        shards = [_shard("es01", store="180")]
        ok, _reason = preflight("es01", nodes, shards)
        assert ok is True

    def test_should_allow_when_free_disk_exceeds_shard_size(self):
        nodes = [_node(n) for n in ("es01", "es02", "es03")]  # 90 free each on es02+es03
        shards = [_shard("es01", store="5")]
        ok, _reason = preflight("es01", nodes, shards)
        assert ok is True

    # ── tier-aware role check: coordinating nodes must not count ──────────────

    def test_should_not_count_coord_node_as_data_target(self):
        """A coordinating-only node (role 'coord') must NOT be counted as an available
        data-node relocation target — even though 'coord' contains the letter 'd'.
        With only 1 real data node besides es01, the drain must be refused."""
        nodes = [
            _node("es01", role="d"),
            _node("es02", role="d"),  # only 1 other real data node
            {"name": "coord1", "node.role": "coord", "disk.total": "1000", "disk.used": "0"},
            {"name": "coord2", "node.role": "coord", "disk.total": "1000", "disk.used": "0"},
        ]
        shards = [_shard("es01")]
        ok, reason = preflight("es01", nodes, shards)
        assert ok is False
        assert "node" in reason.lower()

    def test_should_not_count_coord_via_role_key_either(self):
        """Nodes may report role via 'role' key instead of 'node.role' — still must not count."""
        nodes = [
            {"name": "es01", "role": "d", "disk.total": "100", "disk.used": "10"},
            {"name": "es02", "role": "d", "disk.total": "100", "disk.used": "10"},
            {"name": "coord1", "role": "coord", "disk.total": "1000", "disk.used": "0"},
        ]
        shards = [_shard("es01")]
        ok, reason = preflight("es01", nodes, shards)
        assert ok is False
        assert "node" in reason.lower()

    # ── tier roles (hot/warm) should count as data nodes ─────────────────────

    def test_should_count_hot_tier_nodes_as_data_targets(self):
        """Tier roles like 'his' (hot+ingest+search) must count as valid data targets."""
        nodes = [
            _node("es01", role="his"),
            _node("es02", role="his"),
            _node("es03", role="his"),
        ]
        shards = [_shard("es01", store="5")]
        ok, _reason = preflight("es01", nodes, shards)
        assert ok is True

    # ── edge: no shards on the node being drained ────────────────────────────

    def test_should_allow_drain_when_node_has_no_shards(self):
        nodes = [_node(n) for n in ("es01", "es02", "es03")]
        shards = [_shard("es02", store="50")]  # shards only on es02, not es01
        ok, _reason = preflight("es01", nodes, shards)
        assert ok is True

    # ── edge: master-only node must not count as data target ─────────────────

    def test_should_not_count_master_only_node_as_data_target(self):
        nodes = [
            _node("es01", role="d"),
            _node("es02", role="d"),
            {"name": "master1", "node.role": "m", "disk.total": "500", "disk.used": "0"},
        ]
        shards = [_shard("es01")]
        ok, reason = preflight("es01", nodes, shards)
        assert ok is False
        assert "node" in reason.lower()
