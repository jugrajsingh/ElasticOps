from backend.services.role_logic import is_data_node, node_tier, role_counts


class TestIsDataNode:
    def test_should_be_true_when_role_has_data_tier_letters(self):
        assert is_data_node("his") is True

    def test_should_be_true_for_plain_data_role(self):
        assert is_data_node("d") is True
        assert is_data_node("dim") is True

    def test_should_be_false_for_coordinating_role(self):
        assert is_data_node("coord") is False

    def test_should_be_false_for_master_only_role(self):
        assert is_data_node("m") is False

    def test_should_be_false_for_sentinel_roles(self):
        assert is_data_node("-") is False
        assert is_data_node("") is False


class TestNodeTier:
    def test_should_map_hot(self):
        assert node_tier("his") == "hot"

    def test_should_map_master(self):
        assert node_tier("m") == "master"

    def test_should_map_warm(self):
        assert node_tier("wis") == "warm"

    def test_should_map_cold(self):
        assert node_tier("cis") == "cold"

    def test_should_map_coord(self):
        assert node_tier("coord") == "coord"
        assert node_tier("-") == "coord"
        assert node_tier("") == "coord"

    def test_should_map_generic_data(self):
        assert node_tier("dim") == "data"


class TestRoleCounts:
    def test_should_count_tier_aware_mixed_cluster(self):
        nodes = [{"role": "m"}] * 3 + [{"role": "coord"}] * 3 + [{"role": "his"}] * 26
        counts = role_counts(nodes)
        assert counts == {"master": 3, "data": 26, "coord": 3, "ingest": 0, "other": 0}

    def test_should_not_count_coordinator_as_data(self):
        counts = role_counts([{"role": "coord"}])
        assert counts["coord"] == 1
        assert counts["data"] == 0

    def test_should_count_ingest_only_node(self):
        counts = role_counts([{"role": "i"}])
        assert counts == {"master": 0, "data": 0, "coord": 0, "ingest": 1, "other": 0}
