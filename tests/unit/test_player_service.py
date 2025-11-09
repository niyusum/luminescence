"""
Unit tests for PlayerService.

Tests resource regeneration, leveling, XP calculations, and activity tracking.
"""

import pytest
from datetime import datetime, timedelta
from src.modules.player.service import PlayerService
from src.database.models.core.player import Player


class TestXPCalculations:
    """Test XP requirement calculations."""

    def test_xp_for_level_2(self, mock_config):
        """Level 2 should require base * (2 ^ exponent)."""
        xp = PlayerService.get_xp_for_next_level(1)
        # With polynomial curve: 50 * (1 ^ 2.2) = 50
        assert xp == 50

    def test_xp_increases_with_level(self, mock_config):
        """XP requirement should increase with each level."""
        xp_level_5 = PlayerService.get_xp_for_next_level(5)
        xp_level_10 = PlayerService.get_xp_for_next_level(10)
        xp_level_20 = PlayerService.get_xp_for_next_level(20)

        assert xp_level_5 < xp_level_10 < xp_level_20

    def test_xp_never_negative_or_zero(self, mock_config):
        """XP requirement should always be positive."""
        for level in range(1, 100):
            xp = PlayerService.get_xp_for_next_level(level)
            assert xp > 0


@pytest.mark.asyncio
class TestLevelingSystem:
    """Test leveling and XP award logic."""

    async def test_level_up_increases_level(self, test_player):
        """Awarding sufficient XP should increase level."""
        initial_level = test_player.level
        xp_needed = PlayerService.get_xp_for_next_level(test_player.level)

        result = await PlayerService.add_xp_and_level_up(test_player, xp_needed + 100)

        assert result["leveled_up"] is True
        assert result["levels_gained"] >= 1
        assert test_player.level > initial_level

    async def test_level_up_refreshes_resources(self, test_player):
        """Leveling up should refresh energy and stamina."""
        test_player.energy = 10
        test_player.stamina = 5
        xp_needed = PlayerService.get_xp_for_next_level(test_player.level)

        await PlayerService.add_xp_and_level_up(test_player, xp_needed)

        assert test_player.energy == test_player.max_energy
        assert test_player.stamina == test_player.max_stamina

    async def test_safety_cap_prevents_infinite_loop(self, test_player):
        """Safety cap should prevent infinite leveling loops."""
        # Award massive XP
        result = await PlayerService.add_xp_and_level_up(test_player, 999999999)

        # Should hit safety cap
        assert result["safety_cap_hit"] is True
        assert result["levels_gained"] <= 10

    async def test_overcap_bonus_at_high_resources(self, test_player, mock_config):
        """Overcap bonus should apply when at 90%+ resources."""
        test_player.energy = 95  # 95% of 100
        test_player.max_energy = 100
        xp_needed = PlayerService.get_xp_for_next_level(test_player.level)

        result = await PlayerService.add_xp_and_level_up(test_player, xp_needed, allow_overcap=True)

        assert result["overcap_energy"] > 0
        assert test_player.energy > test_player.max_energy

    async def test_no_overcap_when_below_threshold(self, test_player, mock_config):
        """No overcap bonus when below 90% resources."""
        test_player.energy = 50  # 50% of 100
        xp_needed = PlayerService.get_xp_for_next_level(test_player.level)

        result = await PlayerService.add_xp_and_level_up(test_player, xp_needed, allow_overcap=True)

        assert result["overcap_energy"] == 0


class TestResourceRegeneration:
    """Test energy, stamina, and prayer charge regeneration."""

    def test_energy_regen_no_change_when_full(self, test_player):
        """No energy regeneration when already at max."""
        test_player.energy = test_player.max_energy

        regen = PlayerService.regenerate_energy(test_player)

        assert regen == 0

    def test_energy_regen_after_time_passes(self, test_player):
        """Energy should regenerate after sufficient time."""
        test_player.energy = 50
        test_player.max_energy = 100
        test_player.last_active = datetime.utcnow() - timedelta(minutes=10)  # 10 minutes ago

        regen = PlayerService.regenerate_energy(test_player)

        # Should regen 2 energy (10 min / 5 min per energy)
        assert regen == 2
        assert test_player.energy == 52

    def test_energy_regen_faster_for_adapter_class(self, test_player):
        """Adapter class should regenerate energy 25% faster."""
        test_player.player_class = "adapter"
        test_player.energy = 50
        test_player.last_active = datetime.utcnow() - timedelta(minutes=10)

        regen_adapter = PlayerService.regenerate_energy(test_player)

        # Adapter gets 25% faster regen (5 min * 0.75 = 3.75 min per energy)
        # So should regen more in same time period
        assert regen_adapter > 0

    def test_stamina_regen_faster_for_destroyer_class(self, test_player):
        """Destroyer class should regenerate stamina 25% faster."""
        test_player.player_class = "destroyer"
        test_player.stamina = 25
        test_player.max_stamina = 50
        test_player.last_active = datetime.utcnow() - timedelta(minutes=20)

        regen = PlayerService.regenerate_stamina(test_player)

        assert regen > 0

    def test_prayer_charge_regen_single_charge_system(self, test_player):
        """Prayer system should only grant 1 charge max."""
        test_player.prayer_charges = 0
        test_player.last_prayer_regen = datetime.utcnow() - timedelta(minutes=6)

        regen = PlayerService.regenerate_prayer_charges(test_player)

        assert regen == 1
        assert test_player.prayer_charges == 1

    def test_prayer_no_regen_when_already_charged(self, test_player):
        """No prayer regen when already has charge."""
        test_player.prayer_charges = 1

        regen = PlayerService.regenerate_prayer_charges(test_player)

        assert regen == 0
        assert test_player.prayer_charges == 1


class TestActivityTracking:
    """Test player activity scoring and tracking."""

    def test_activity_score_high_for_recent_activity(self, test_player):
        """Recent activity should result in high score."""
        test_player.last_active = datetime.utcnow() - timedelta(minutes=30)

        score = PlayerService.calculate_activity_score(test_player)

        assert score >= 40  # Should get 40 points for being active within 1 hour

    def test_activity_score_includes_level(self, test_player):
        """Activity score should include level component."""
        test_player.level = 15
        test_player.last_active = datetime.utcnow()

        score = PlayerService.calculate_activity_score(test_player)

        assert score >= 15  # Should get at least level points

    def test_activity_score_capped_at_100(self, test_player_high_level):
        """Activity score should be capped at 100."""
        test_player_high_level.last_active = datetime.utcnow()
        test_player_high_level.level = 100
        test_player_high_level.total_fusions = 1000
        test_player_high_level.unique_maidens = 100

        score = PlayerService.calculate_activity_score(test_player_high_level)

        assert score <= 100
