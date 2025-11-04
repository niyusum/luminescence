import discord
from discord.ext import commands

from src.core.infra.database_service import DatabaseService
from src.core.infra.transaction_logger import TransactionLogger
from src.features.player.service import PlayerService
from src.features.tutorial.service import TutorialService, TRIGGER_INDEX
from src.core.event.event_bus import EventBus
from src.core.logging.logger import get_logger
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class TutorialCog(commands.Cog):
    """
    Reacts to gameplay events and announces tangible tutorial completions.
    Sends a public embed, followed by a plain text reward line.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Subscribe to all tutorial triggers
        for topic in TRIGGER_INDEX.keys():
            EventBus.subscribe(topic, self._handle_event)

    async def _handle_event(self, payload: dict):
        """
        Expected payload:
        {
          "__topic__": str (required),
          "player_id": int,
          "channel_id": Optional[int],
          ...other fields...
        }
        """
        try:
            player_id = payload.get("player_id")
            channel_id = payload.get("channel_id")
            topic = payload.get("__topic__")

            # Validate required fields
            if not topic:
                logger.warning(
                    "Tutorial event missing required __topic__ field",
                    extra={"payload": payload}
                )
                return

            if not player_id:
                logger.warning(
                    "Tutorial event missing player_id",
                    extra={"payload": payload, "topic": topic}
                )
                return

            if not channel_id:
                logger.warning(
                    "Tutorial event missing channel_id",
                    extra={"payload": payload, "topic": topic, "player_id": player_id}
                )
                return

            # Lookup step from topic
            step = TRIGGER_INDEX.get(topic)
            if not step:
                logger.warning(
                    f"Tutorial event topic '{topic}' not found in TRIGGER_INDEX",
                    extra={"payload": payload, "topic": topic, "player_id": player_id}
                )
                return

            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(session, player_id, lock=True)
                if not player:
                    logger.warning(
                        f"Tutorial event player not found",
                        extra={"player_id": player_id, "topic": topic, "channel_id": channel_id}
                    )
                    return

                done = await TutorialService.complete_step(session, player, step["key"])
                if not done:
                    # Step already completed or invalid - this is expected behavior, no warning needed
                    return

                # Log transaction for tutorial step completion
                await TransactionLogger.log_transaction(
                    player_id=player_id,
                    transaction_type="tutorial_step_complete",
                    details={
                        "step_key": step["key"],
                        "step_title": done["title"],
                        "rikis_rewarded": done["reward"].get("rikis", 0),
                        "grace_rewarded": done["reward"].get("grace", 0),
                        "trigger": topic,
                    },
                    context=f"tutorial_step:{step['key']}",
                )

            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                logger.warning(
                    f"Tutorial event channel not found",
                    extra={"channel_id": channel_id, "player_id": player_id, "topic": topic}
                )
                return

            # Public congrats embed
            embed = EmbedBuilder.success(
                title=f"🎉 Tutorial Complete: {done['title']}",
                description=done["congrats"],
                footer="Keep going — complete all steps for starter boosts!"
            )
            await channel.send(embed=embed)

            # Plain text reward message (no embed)
            rikis = done["reward"].get("rikis", 0)
            grace = done["reward"].get("grace", 0)
            if rikis or grace:
                parts = []
                if rikis:
                    parts.append(f"+{rikis} rikis")
                if grace:
                    parts.append(f"+{grace} grace")
                await channel.send(f"You received {' and '.join(parts)} as a tutorial reward!")

        except Exception as e:
            logger.error(f"Tutorial event handling failed: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TutorialCog(bot))

