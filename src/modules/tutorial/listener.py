import asyncio
from src.core.event import event_bus
from src.modules.tutorial.service import TutorialService
from src.core.database.service import DatabaseService
from src.core.logging.logger import get_logger

logger = get_logger(__name__)

async def _handle_tutorial_event(event_name: str, data):
    """Handle tutorial step completion and reward distribution."""
    player_id = data.get("player_id")
    bot = data.get("bot")
    channel_id = data.get("channel_id")

    if not player_id or not bot:
        logger.warning(f"Tutorial event {event_name} missing required data")
        return

    async with DatabaseService.get_transaction() as session:
        from src.database.models.core.player import Player
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            return

        result = await TutorialService.complete_step(session, player, event_name)
        if not result:
            return  # Already completed or invalid

        # Send congrats message to channel
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f"🎉 **Tutorial Complete:** {result['title']}\n"
                f"{result['congrats']}\n\n"
                f"💰 Rewards: +{result['reward']['lumees']} Lumees, +{result['reward']['auric_coin']} AuricCoin"
            )

def _register_tutorial_listeners(bot):
    """Bind tutorial steps to the EventBus."""
    for trigger in ["tos_agreed", "drop_completed", "summons_completed", "fusion_completed", "collection_viewed", "leader_set"]:
        event_bus.subscribe(trigger, lambda data, e=trigger: asyncio.create_task(_handle_tutorial_event(e, data)))
    logger.info("✅ Tutorial event listeners registered")

# Subscribe to bot setup complete event to auto-register tutorial listeners
def _on_bot_setup_complete(data):
    """Auto-register tutorial listeners when bot setup is complete."""
    bot = data.get("bot")
    if bot:
        _register_tutorial_listeners(bot)

event_bus.subscribe("bot.setup_complete", _on_bot_setup_complete)
logger.info("📡 Tutorial module subscribed to bot.setup_complete event")
