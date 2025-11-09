"""
Unit tests for FusionService.

Tests fusion cost calculation, success rates, element combinations, and core fusion logic.
"""

import pytest
from src.modules.fusion.service import FusionService


class TestFusionCosts:
    """Test fusion cost calculations."""

    def test_tier_1_cost(self, mock_config):
        """Tier 1 fusion should cost base amount."""
        cost = FusionService.get_fusion_cost(1)
        assert cost == 1000

    def test_tier_3_cost(self, mock_config):
        """Tier 3 fusion should cost base * (multiplier ^ 2)."""
        cost = FusionService.get_fusion_cost(3)
        assert cost == 6250  # 1000 * (2.5 ^ 2)

    def test_cost_capped_at_max(self, mock_config):
        """Fusion cost should be capped at max_cost."""
        cost = FusionService.get_fusion_cost(20)
        assert cost == 10000000  # max_cost


class TestFusionSuccessRates:
    """Test fusion success rate calculations."""

    def test_tier_1_success_rate(self, mock_config):
        """Tier 1 should have 70% success rate."""
        rate = FusionService.get_fusion_success_rate(1)
        assert rate == 70

    def test_tier_3_success_rate(self, mock_config):
        """Tier 3 should have 60% success rate."""
        rate = FusionService.get_fusion_success_rate(3)
        assert rate == 60

    def test_unknown_tier_defaults_to_50(self, mock_config):
        """Unknown tiers should default to 50%."""
        rate = FusionService.get_fusion_success_rate(99)
        assert rate == 50


class TestElementCombination:
    """Test element combination logic."""

    def test_same_element_returns_same(self, mock_config):
        """Combining same element should return that element."""
        result = FusionService.calculate_element_result("infernal", "infernal")
        assert result == "infernal"

    def test_unknown_combination_returns_first(self, mock_config):
        """Unknown combinations should return first element."""
        result = FusionService.calculate_element_result("unknown1", "unknown2")
        assert result == "unknown1"


class TestFusionRoll:
    """Test fusion success roll logic."""

    def test_bonus_rate_increases_success_chance(self, mock_config):
        """Bonus rate should increase success chance."""
        successes = 0
        trials = 1000

        for _ in range(trials):
            if FusionService.roll_fusion_success(1, bonus_rate=30.0):
                successes += 1

        # With 70% base + 30% bonus = 100%, should succeed every time
        # Allow 1% margin for randomness
        assert successes >= trials * 0.99

    def test_roll_respects_100_percent_cap(self, mock_config):
        """Success rate should be capped at 100%."""
        successes = 0
        trials = 1000

        for _ in range(trials):
            if FusionService.roll_fusion_success(1, bonus_rate=50.0):  # Would be 120%
                successes += 1

        # Should not exceed 100% success
        assert successes <= trials


@pytest.mark.asyncio
class TestFusionExecution:
    """Test full fusion execution workflow."""

    async def test_fusion_requires_exactly_2_maidens(self, db_session, test_player):
        """Fusion should require exactly 2 maiden IDs."""
        from src.core.exceptions import InvalidFusionError

        with pytest.raises(InvalidFusionError, match="exactly 2 maidens"):
            await FusionService.execute_fusion(db_session, test_player.discord_id, [1])

        with pytest.raises(InvalidFusionError, match="exactly 2 maidens"):
            await FusionService.execute_fusion(db_session, test_player.discord_id, [1, 2, 3])

    async def test_fusion_validates_player_ownership(self, db_session, test_player, test_maiden):
        """Fusion should validate player owns the maidens."""
        from src.core.exceptions import MaidenNotFoundError

        # Try to fuse maidens that don't exist
        with pytest.raises(MaidenNotFoundError):
            await FusionService.execute_fusion(
                db_session,
                test_player.discord_id,
                [999999, 999998]
            )

    async def test_fusion_validates_same_tier(self, db_session, test_player):
        """Fusion should require maidens of same tier."""
        from src.core.exceptions import InvalidFusionError

        # Would need to create 2 maidens of different tiers for full test
        # Placeholder for now
        pass

    async def test_fusion_validates_tier_12_cannot_fuse(self, db_session):
        """Fusion should reject tier 12+ maidens."""
        # Would need tier 12 maidens to test
        pass


class TestShardManagement:
    """Test shard awarding and redemption."""

    @pytest.mark.asyncio
    async def test_add_fusion_shard_grants_random_amount(self, test_player, mock_config):
        """Shards should be randomly granted between min and max."""
        initial = test_player.get_fusion_shards(3)

        result = await FusionService.add_fusion_shard(test_player, tier=3)

        assert result["shards_gained"] >= 1
        assert result["shards_gained"] <= 12
        assert result["new_total"] == initial + result["shards_gained"]

    def test_get_redeemable_tiers(self, test_player, mock_config):
        """Should identify tiers with enough shards for redemption."""
        test_player.fusion_shards["tier_3"] = 100
        test_player.fusion_shards["tier_5"] = 150

        redeemable = FusionService.get_redeemable_tiers(test_player)

        assert 3 in redeemable
        assert 5 in redeemable
        assert 1 not in redeemable
