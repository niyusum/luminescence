from __future__ import annotations
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
from math import pow

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.social.guild import Guild
from src.database.models.economy.guild_shrine import GuildShrine
from src.core.config.config_manager import ConfigManager
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import InvalidOperationError
from src.core.logging.logger import get_logger
from src.modules.resource.service import ResourceService

logger = get_logger(__name__)


class GuildShrineService:
    """
    Guild Shrine System
    -------------------
    Cooperative shrine owned by a guild, feeding treasury yields.

    Responsibilities:
      - Manage shrine creation, upgrades, collection, cooldowns.
      - Use ConfigManager for cost/yield multipliers.
      - Route resource flow to Guild.treasury (not players).
      - Transaction-safe under RIKI LAW (single DB session).
    """

    # ---------- Retrieval / Creation ----------

    @staticmethod
    async def get_or_create_shrine(
        session: AsyncSession,
        guild_id: int,
        shrine_type: str,
    ) -> GuildShrine:
        shrine = (await session.execute(
            select(GuildShrine)
            .where(GuildShrine.guild_id == guild_id, GuildShrine.shrine_type == shrine_type)
        )).scalar_one_or_none()

        if shrine:
            return shrine

        conf = ConfigManager.get(f"shrines.{shrine_type}", {})
        if not conf:
            raise InvalidOperationError(f"Invalid shrine type: {shrine_type}")

        shrine = GuildShrine(guild_id=guild_id, shrine_type=shrine_type, level=1)
        session.add(shrine)
        await session.flush()

        logger.info("Created guild shrine type=%s for guild=%s", shrine_type, guild_id)
        return shrine

    # ---------- Upgrade ----------

    @staticmethod
    def _next_level_cost(conf: Dict[str, Any], current_level: int) -> int:
        base = int(conf.get("base_cost", 10000))
        mult = float(conf.get("cost_multiplier", 2.0))
        return int(round(base * pow(mult, max(0, current_level - 1))))

    @staticmethod
    async def upgrade_shrine(session: AsyncSession, guild_id: int, shrine_type: str) -> GuildShrine:
        shrine = await GuildShrineService.get_or_create_shrine(session, guild_id, shrine_type)
        conf = ConfigManager.get(f"shrines.{shrine_type}", {})
        max_level = int(conf.get("max_level", 12))

        if shrine.level >= max_level:
            raise InvalidOperationError("Shrine is already at maximum level.")

        cost = GuildShrineService._next_level_cost(conf, shrine.level)
        guild = await session.get(Guild, guild_id, with_for_update=True)
        if not guild:
            raise InvalidOperationError("Guild not found.")

        if guild.treasury < cost:
            raise InvalidOperationError(f"Guild treasury has insufficient rikis. Need {cost}, have {guild.treasury}.")

        guild.treasury -= cost
        shrine.level += 1
        await session.flush()

        await TransactionLogger.log_transaction(
            session=session,
            player_id=None,
            transaction_type="guild_shrine_upgrade",
            details={"guild_id": guild_id, "type": shrine_type, "level": shrine.level, "cost": cost},
            context="guild",
        )

        logger.info("Upgraded guild shrine type=%s to level=%s (cost=%s) for guild=%s",
                    shrine_type, shrine.level, cost, guild_id)
        return shrine

    # ---------- Yield / Collection ----------

    @staticmethod
    def _compute_yield(conf: Dict[str, Any], level: int) -> Tuple[str, int]:
        base_yield = conf.get("base_yield", 50)
        y_mult = float(conf.get("yield_multiplier", 2.0))
        target = str(conf.get("target", "grace"))
        if isinstance(base_yield, float) and base_yield <= 1.0:
            # Percent-based (of treasury or static reference)
            # For guild shrines, percent yield applies to guild treasury
            return target, 0  # placeholder; not used for guild treasury self-reference
        return target, int(round(int(base_yield) * pow(y_mult, max(0, level - 1))))

    @staticmethod
    async def collect_yield(session: AsyncSession, guild_id: int, shrine_type: str) -> Dict[str, Any]:
        shrine = await GuildShrineService.get_or_create_shrine(session, guild_id, shrine_type)
        conf = ConfigManager.get(f"shrines.{shrine_type}", {})
        cap_hours = int(conf.get("collection_cap_hours", 24))
        now = datetime.utcnow()

        if shrine.last_collected_at:
            elapsed = (now - shrine.last_collected_at) / timedelta(hours=1)
            if elapsed < cap_hours:
                remaining = cap_hours - elapsed
                raise InvalidOperationError(f"Shrine not ready. Try again in ~{int(round(remaining))}h.")

        guild = await session.get(Guild, guild_id, with_for_update=True)
        if not guild:
            raise InvalidOperationError("Guild not found.")

        target_key, amount = GuildShrineService._compute_yield(conf, shrine.level)
        guild.treasury += amount
        shrine.last_collected_at = now

        entry = {"ts": now.isoformat(), "amount": amount, "target": target_key}
        history = shrine.yield_history or []
        history.insert(0, entry)
        if len(history) > 25:
            del history[25:]
        shrine.yield_history = history

        await session.flush()

        await TransactionLogger.log_transaction(
            session=session,
            player_id=None,
            transaction_type="guild_shrine_collect",
            details={"guild_id": guild_id, "type": shrine_type, "yield": {target_key: amount}, "level": shrine.level},
            context="guild",
        )

        logger.info("Guild %s collected shrine '%s' yield: +%s %s to treasury",
                    guild_id, shrine_type, amount, target_key)

        return {"added_to_treasury": amount, "level": shrine.level, "target": target_key}

    # ---------- Bulk Collection ----------

    @staticmethod
    async def collect_all_guild(session: AsyncSession, guild_id: int) -> Dict[str, Any]:
        shrines = (await session.execute(
            select(GuildShrine)
            .where(GuildShrine.guild_id == guild_id, GuildShrine.is_active.is_(True))
        )).scalars().all()

        totals: Dict[str, int] = {}
        collected, pending = [], []

        for shrine in shrines:
            conf = ConfigManager.get(f"shrines.{shrine.shrine_type}", {})
            cap_hours = int(conf.get("collection_cap_hours", 24))
            now = datetime.utcnow()
            if shrine.last_collected_at:
                elapsed = (now - shrine.last_collected_at) / timedelta(hours=1)
                if elapsed < cap_hours:
                    pending.append({
                        "type": shrine.shrine_type,
                        "level": shrine.level,
                        "eta_hours": round(cap_hours - elapsed, 2)
                    })
                    continue

            try:
                result = await GuildShrineService.collect_yield(session, guild_id, shrine.shrine_type)
                k = result["target"]
                totals[k] = totals.get(k, 0) + result["added_to_treasury"]
                collected.append(result)
            except InvalidOperationError as e:
                pending.append({"type": shrine.shrine_type, "level": shrine.level, "error": str(e)})

        return {"totals": totals, "collected": collected, "pending": pending}
