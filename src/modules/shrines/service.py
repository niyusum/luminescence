from __future__ import annotations

from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
from math import pow

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from modules import Player  # your Player model (import path per your aggregator)
from src.database.models.economy.shrine import PlayerShrine
from src.core.config.config_manager import ConfigManager
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import InvalidOperationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class ShrineService:
    """
    Personal Shrine economy (player-owned passive yield).

    Responsibilities
    ----------------
    - Get/create player shrines (type + slot)
    - Upgrade shrine levels (spend rikis)
    - Collect shrine yields (grant grace/rikis)
    - List and summarize shrines for UI
    - Sell (deactivate) shrines with configurable refund

    RIKI LAW
    --------
    - Transaction-safe: caller wraps in a single AsyncSession context
    - No Discord I/O here; cogs remain presentation-only
    - All balance is config-driven via ConfigManager
    - Audit logging via TransactionLogger
    - Concurrency: lock Player row when mutating resources (done by ResourceService)
    """

    # ---------- Retrieval & Creation ----------

    @staticmethod
    async def list_shrines(session: AsyncSession, player_id: int, include_inactive: bool = False) -> List[PlayerShrine]:
        q = select(PlayerShrine).where(PlayerShrine.player_id == player_id)
        if not include_inactive:
            q = q.where(PlayerShrine.is_active.is_(True))
        rows = (await session.execute(q.order_by(PlayerShrine.shrine_type.asc(), PlayerShrine.slot.asc()))).scalars().all()
        return rows

    @staticmethod
    async def get_or_create(
        session: AsyncSession,
        player_id: int,
        shrine_type: str,
        slot: int = 1,
    ) -> PlayerShrine:
        row = (await session.execute(
            select(PlayerShrine).where(
                PlayerShrine.player_id == player_id,
                PlayerShrine.shrine_type == shrine_type,
                PlayerShrine.slot == slot,
            )
        )).scalar_one_or_none()

        if row:
            return row

        # Enforce max_shrines config
        max_shrines = int(ConfigManager.get(f"shrines.{shrine_type}.max_shrines", 1))
        if slot < 1 or slot > max_shrines:
            raise InvalidOperationError(f"Invalid slot {slot}. Max shrines for '{shrine_type}' is {max_shrines}.")

        # Optional unlocks (e.g., player level requirement)
        unlock_level = int(ConfigManager.get(f"shrines.{shrine_type}.unlock_level", 1))
        player = await session.get(Player, player_id)
        if player and player.level < unlock_level:
            raise InvalidOperationError(f"{shrine_type.title()} shrine unlocks at player level {unlock_level}.")

        row = PlayerShrine(player_id=player_id, shrine_type=shrine_type, slot=slot, level=1)
        session.add(row)
        await session.flush()

        # Lightweight log (TransactionLogger handles durable trail on upgrade/collect)
        logger.info("Created personal shrine type=%s slot=%s for player=%s", shrine_type, slot, player_id)
        return row

    # ---------- Upgrade ----------

    @staticmethod
    def _next_level_cost(conf: Dict[str, Any], current_level: int) -> int:
        """
        Geometric upgrade cost from current -> next level.
        """
        base = int(conf.get("base_cost", 1000))
        mult = float(conf.get("cost_multiplier", 2.0))
        # e.g., L1->L2 cost = base * mult^(L1-1)
        return int(round(base * pow(mult, max(0, current_level - 1))))

    @staticmethod
    async def upgrade(
        session: AsyncSession,
        player_id: int,
        shrine_type: str,
        slot: int = 1,
        levels: int = 1,
    ) -> PlayerShrine:
        """
        Upgrade a player's shrine by N levels, spending rikis via ResourceService.
        """
        if levels < 1:
            raise InvalidOperationError("Levels to upgrade must be >= 1.")

        shrine = await ShrineService.get_or_create(session, player_id, shrine_type, slot)
        conf = ConfigManager.get(f"shrines.{shrine_type}", {})

        max_level = int(conf.get("max_level", 12))
        if shrine.level >= max_level:
            raise InvalidOperationError("Shrine is already at max level.")

        # Compute cumulative cost for N levels
        spend = 0
        level = shrine.level
        for _ in range(levels):
            if level >= max_level:
                break
            spend += ShrineService._next_level_cost(conf, level)
            level += 1

        if spend <= 0:
            return shrine

        # Spend rikis through ResourceService (ensures player lock + audit)
        from src.modules.resource.service import ResourceService
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise InvalidOperationError("Player not found.")

        await ResourceService.consume_resources(
            session=session,
            player=player,
            resources={"rikis": spend},
            source="shrine_upgrade",
            context={"type": shrine_type, "slot": slot, "from_level": shrine.level, "to_level": level},
        )

        shrine.level = level
        await session.flush()

        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="shrine_upgrade",
            details={"type": shrine_type, "slot": slot, "spend_rikis": spend, "new_level": shrine.level},
            context="shrine",
        )
        logger.info("Upgraded shrine type=%s slot=%s to L%s (spent %s) for player=%s",
                    shrine_type, slot, shrine.level, spend, player_id)
        return shrine

    # ---------- Yield / Collection ----------

    @staticmethod
    def _compute_yield(conf: Dict[str, Any], level: int, player_snapshot: Dict[str, Any]) -> Tuple[str, int]:
        """
        Compute the numeric yield for the shrine at `level`.

        Supports:
          - Fixed yield (int)
          - Percent-based yield if base_yield <= 1.0 (applied to a target pool)

        Target resource name is read from config: `target` (default 'grace').

        Returns: (target_resource_key, amount_int)
        """
        base_yield = conf.get("base_yield", 10)
        y_mult = float(conf.get("yield_multiplier", 2.0))
        target = str(conf.get("target", "grace"))  # e.g., 'grace' or 'rikis'

        # Percent-based yield of a reference pool (currently supports rikis)
        if isinstance(base_yield, float) and base_yield <= 1.0:
            ref_key = str(conf.get("percent_of", "rikis"))  # which pool to reference
            ref_val = int(player_snapshot.get(ref_key, 0))
            amount = int(round(ref_val * (base_yield * pow(y_mult, max(0, level - 1)))))
        else:
            amount = int(round(int(base_yield) * pow(y_mult, max(0, level - 1))))

        return target, max(0, amount)

    @staticmethod
    async def collect(
        session: AsyncSession,
        player_id: int,
        shrine_type: str,
        slot: int = 1,
    ) -> Dict[str, Any]:
        """
        Collect yield from a single shrine (respects cooldown).
        Credits player via ResourceService and logs transaction.
        """
        shrine = await ShrineService.get_or_create(session, player_id, shrine_type, slot)
        if not shrine.is_active:
            raise InvalidOperationError("Shrine is not active.")

        conf = ConfigManager.get(f"shrines.{shrine_type}", {})
        cap_hours = int(conf.get("collection_cap_hours", 24))

        now = datetime.utcnow()
        if shrine.last_collected_at:
            elapsed = (now - shrine.last_collected_at) / timedelta(hours=1)
            if elapsed < cap_hours:
                remaining = cap_hours - elapsed
                raise InvalidOperationError(f"Shrine recharging. Ready in ~{int(round(remaining))}h.")

        # Snapshot player resource pool for percent-based yields
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise InvalidOperationError("Player not found.")
        player_snapshot = {
            "rikis": int(getattr(player, "rikis", 0)),
            "grace": int(getattr(player, "grace", 0)),
            "riki_gems": int(getattr(player, "riki_gems", 0)),
        }

        target_key, amount = ShrineService._compute_yield(conf, shrine.level, player_snapshot)
        if amount <= 0:
            raise InvalidOperationError("This shrine produced nothing at this time.")

        # Apply invoker class bonus (+25% shrine rewards)
        if player.player_class == "invoker":
            amount = int(amount * 1.25)

        # Grant yield (modifiers apply by default to incomes)
        from src.modules.resource.service import ResourceService
        grant = await ResourceService.grant_resources(
            session=session,
            player=player,
            resources={target_key: amount},
            source="shrine_collect",
            apply_modifiers=True,
            context={"type": shrine_type, "slot": slot, "level": shrine.level, "invoker_bonus": player.player_class == "invoker"},
        )

        shrine.last_collected_at = now
        # Push to ring buffer (last 10)
        entry = {"ts": now.isoformat(), "amount": amount, "target": target_key}
        history = shrine.yield_history or []
        history.insert(0, entry)
        if len(history) > 10:
            del history[10:]
        shrine.yield_history = history

        await session.flush()

        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="shrine_collect",
            details={"type": shrine_type, "slot": slot, "yield": {target_key: amount}, "level": shrine.level},
            context="shrine",
        )
        logger.info("Collected shrine type=%s slot=%s -> +%s %s for player=%s",
                    shrine_type, slot, amount, target_key, player_id)

        return {"granted": grant["granted"], "modifiers_applied": grant.get("modifiers_applied", {}), "level": shrine.level}

    @staticmethod
    async def collect_all_personal(session: AsyncSession, player_id: int) -> Dict[str, Any]:
        """
        Collect from all *ready* active shrines for a player.
        Non-ready shrines are summarized with ETA.
        """
        shrines = await ShrineService.list_shrines(session, player_id)
        totals: Dict[str, int] = {}
        collected: List[Dict[str, Any]] = []
        pending: List[Dict[str, Any]] = []

        for s in shrines:
            conf = ConfigManager.get(f"shrines.{s.shrine_type}", {})
            cap_hours = int(conf.get("collection_cap_hours", 24))
            now = datetime.utcnow()
            if s.last_collected_at:
                elapsed = (now - s.last_collected_at) / timedelta(hours=1)
                if elapsed < cap_hours:
                    pending.append({
                        "type": s.shrine_type, "slot": s.slot, "level": s.level,
                        "eta_hours": round(cap_hours - elapsed, 2)
                    })
                    continue

            try:
                result = await ShrineService.collect(session, player_id, s.shrine_type, s.slot)
                for k, v in (result["granted"] or {}).items():
                    totals[k] = totals.get(k, 0) + int(v)
                collected.append({
                    "type": s.shrine_type, "slot": s.slot, "level": s.level,
                    "granted": result["granted"]
                })
            except InvalidOperationError as e:
                pending.append({"type": s.shrine_type, "slot": s.slot, "level": s.level, "error": str(e)})

        return {"totals": totals, "collected": collected, "pending": pending}

    # ---------- Sell / Deactivate ----------

    @staticmethod
    def _cumulative_cost_to_level(conf: Dict[str, Any], level: int) -> int:
        """
        Sum of geometric costs from L1 up to `level` (exclusive of next).
        """
        total = 0
        cur = 1
        while cur < max(1, level):
            total += ShrineService._next_level_cost(conf, cur)
            cur += 1
        return total

    @staticmethod
    async def sell(
        session: AsyncSession,
        player_id: int,
        shrine_type: str,
        slot: int = 1,
    ) -> Dict[str, Any]:
        """
        Deactivate (sell) a shrine and refund a percentage of cumulative spend as rikis.
        """
        shrine = (await session.execute(
            select(PlayerShrine).where(
                PlayerShrine.player_id == player_id,
                PlayerShrine.shrine_type == shrine_type,
                PlayerShrine.slot == slot,
                PlayerShrine.is_active.is_(True),
            )
        )).scalar_one_or_none()
        if not shrine:
            raise InvalidOperationError("Active shrine not found.")

        conf = ConfigManager.get(f"shrines.{shrine_type}", {})
        refund_rate = float(ConfigManager.get("shrines.sell_refund", 0.5))
        spent = ShrineService._cumulative_cost_to_level(conf, shrine.level)
        refund = int(round(max(0, spent) * max(0.0, min(1.0, refund_rate))))

        from src.modules.resource.service import ResourceService
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise InvalidOperationError("Player not found.")

        if refund > 0:
            await ResourceService.grant_resources(
                session=session,
                player=player,
                resources={"rikis": refund},
                source="shrine_sell",
                apply_modifiers=False,  # selling shouldn't apply income boosts
                context={"type": shrine_type, "slot": slot, "level": shrine.level, "spent": spent},
            )

        shrine.is_active = False
        await session.flush()

        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="shrine_sell",
            details={"type": shrine_type, "slot": slot, "refund_rikis": refund, "level_sold": shrine.level},
            context="shrine",
        )
        logger.info("Sold shrine type=%s slot=%s (L%s) refund=%s for player=%s",
                    shrine_type, slot, shrine.level, refund, player_id)
        return {"refund_rikis": refund, "level": shrine.level}
