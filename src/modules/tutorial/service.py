from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime

from src.database.models.core.player import Player
from src.modules.resource.service import ResourceService  # ✅ added
from src.core.logging.logger import get_logger

logger = get_logger(__name__)

# Ordered, tangible tutorial steps.
# Each step: key, title, trigger (EventBus topic), reward (lumees/auric coin), congrats text.
TUTORIAL_STEPS = [
    {
        "key": "tos_agreed",
        "title": "Accepted Terms of Service",
        "trigger": "tos_agreed",
        "reward": {"lumees": 0, "auric_coin": 0},
        "congrats": "Thanks for agreeing to our **Terms of Service**. Welcome aboard!"
    },
    {
        "key": "first_drop",
        "title": "First DROP",
        "trigger": "drop_completed",
        "reward": {"lumees": 250, "auric_coin": 1},
        "congrats": "DROP grants **AuricCoin** used for summoning maidens."
    },
    {
        "key": "first_summon",
        "title": "First Summon",
        "trigger": "summons_completed",
        "reward": {"lumees": 0, "auric_coin": 1},
        "congrats": "Summoning adds new maidens to your collection."
    },
    {
        "key": "first_fusion",
        "title": "First Fusion",
        "trigger": "fusion_completed",
        "reward": {"lumees": 500, "auric_coin": 0},
        "congrats": "Fusion upgrades tiers — save duplicates to progress faster."
    },
    {
        "key": "view_collection",
        "title": "Viewed Collection",
        "trigger": "collection_viewed",
        "reward": {"lumees": 0, "auric_coin": 1},
        "congrats": "Use filters to plan your fusions and leaders."
    },
    {
        "key": "set_leader",
        "title": "Set a Leader",
        "trigger": "leader_set",
        "reward": {"lumees": 0, "auric_coin": 1},
        "congrats": "Leaders grant passive element-based bonuses."
    },
]

TRIGGER_INDEX: Dict[str, Dict[str, Any]] = {s["trigger"]: s for s in TUTORIAL_STEPS}
KEY_INDEX: Dict[str, Dict[str, Any]] = {s["key"]: s for s in TUTORIAL_STEPS}


class TutorialService:
    @staticmethod
    def _ensure_state(player: Player) -> None:
        """Ensure player has tutorial tracking structure initialized."""
        if "tutorial" not in player.stats:
            player.stats["tutorial"] = {"completed": {}}

    @staticmethod
    def is_completed(player: Player, step_key: str) -> bool:
        """Check if tutorial step already completed."""
        TutorialService._ensure_state(player)
        return bool(player.stats["tutorial"]["completed"].get(step_key))

    # ✅ Updated version with ResourceService integration
    @staticmethod
    async def complete_step(
        session,
        player: Player,
        step_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        Idempotently complete tutorial step with ResourceService integration.
        Tutorial rewards are small fixed bonuses with NO leader/class modifiers.
        """
        TutorialService._ensure_state(player)

        step = KEY_INDEX.get(step_key)
        if not step:
            logger.warning(f"Unknown tutorial step: {step_key}")
            return None

        if TutorialService.is_completed(player, step_key):
            return None

        player.stats["tutorial"]["completed"][step_key] = datetime.utcnow().isoformat()

        reward = step.get("reward") or {}
        reward_resources = {}
        if reward.get("lumees", 0) > 0:
            reward_resources["lumees"] = reward["lumees"]
        if reward.get("auric_coin", 0) > 0:
            reward_resources["auric_coin"] = reward["auric_coin"]

        # ✅ Unified resource grant through ResourceService (no modifiers)
        if reward_resources:
            await ResourceService.grant_resources(
                session=session,
                player=player,
                resources=reward_resources,
                source="tutorial_completion",
                apply_modifiers=False,
                context={"step_key": step_key}
            )

        logger.info(f"Tutorial step '{step_key}' completed for player {player.discord_id}")

        return {
            "title": step["title"],
            "congrats": step["congrats"],
            "reward": {
                "lumees": reward.get("lumees", 0),
                "auric_coin": reward.get("auric_coin", 0)
            },
        }


