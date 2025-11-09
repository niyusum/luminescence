from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config.config_manager import ConfigManager
from src.core.exceptions import InvalidOperationError
from src.core.logging.logger import get_logger
from src.core.infra.transaction_logger import TransactionLogger

from src.database.models.social.guild import (
    Guild,
    GuildMember,
    GuildInvite,
    GuildAudit,
    GuildRole,
)
from src.database.models import Player  # adjust to your aggregator if needed
from src.modules.resource.service import ResourceService

logger = get_logger(__name__)


class GuildService:
    """
    Guild feature service.
    RIKI LAW: single-transaction ops, config-driven economics, immutable audit, no cog logic here.
    """

    # ======================
    # Helpers / Permissions
    # ======================

    @staticmethod
    async def _get_membership(session: AsyncSession, player_id: int) -> Optional[GuildMember]:
        return (
            await session.execute(
                select(GuildMember).where(GuildMember.player_id == player_id)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _require_membership(session: AsyncSession, player_id: int) -> GuildMember:
        m = await GuildService._get_membership(session, player_id)
        if not m:
            raise InvalidOperationError("Player is not in a guild.")
        return m

    @staticmethod
    def _require_role(member: GuildMember, allowed: Tuple[GuildRole, ...]) -> None:
        if member.role not in allowed:
            raise InvalidOperationError("Insufficient permissions for this action.")

    @staticmethod
    def _validate_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise InvalidOperationError("Name cannot be empty.")
        if len(name) > 50:
            raise InvalidOperationError("Name too long (max 50).")
        return name

    @staticmethod
    def _validate_emblem(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidOperationError("Invalid emblem URL.")
        if len(url) > 512:
            raise InvalidOperationError("Emblem URL too long.")
        return url

    # ======================
    # Creation / Identity
    # ======================

    @staticmethod
    async def create_guild(
        session: AsyncSession, owner_id: int, name: str, description: Optional[str] = None
    ) -> Guild:
        name = GuildService._validate_name(name)

        existing = (
            await session.execute(select(Guild).where(Guild.name == name))
        ).scalar_one_or_none()
        if existing:
            raise InvalidOperationError("A guild with that name already exists.")

        already_in = await GuildService._get_membership(session, owner_id)
        if already_in:
            raise InvalidOperationError("You must leave your current guild first.")

        max_members_default = int(ConfigManager.get("guilds.base_max_members", 10))

        g = Guild(
            name=name,
            owner_id=owner_id,
            description=(description or "A new guild begins.")[:250],
            member_count=1,
            max_members=max_members_default,
        )
        session.add(g)
        await session.flush()

        # Leader membership
        leader = GuildMember(guild_id=g.id, player_id=owner_id, role=GuildRole.leader)
        session.add(leader)

        # Audit + activity
        session.add(GuildAudit(guild_id=g.id, actor_player_id=owner_id, action="create", meta={"name": name}))
        g.add_activity("create_guild", str(owner_id), {"name": name})

        logger.info("Guild created name=%s owner=%s id=%s", name, owner_id, g.id)
        return g

    @staticmethod
    async def rename_guild(session: AsyncSession, actor_id: int, new_name: str) -> Guild:
        new_name = GuildService._validate_name(new_name)
        membership = await GuildService._require_membership(session, actor_id)
        guild = await session.get(Guild, membership.guild_id, with_for_update=True)
        GuildService._require_role(membership, (GuildRole.leader,))

        other = (await session.execute(select(Guild).where(Guild.name == new_name))).scalar_one_or_none()
        if other and other.id != guild.id:
            raise InvalidOperationError("Another guild already uses that name.")

        old = guild.name
        guild.name = new_name
        session.add(GuildAudit(guild_id=guild.id, actor_player_id=actor_id, action="rename", meta={"old": old, "new": new_name}))
        guild.add_activity("rename", str(actor_id), {"old": old, "new": new_name})
        logger.info("Guild %s renamed to %s by %s", old, new_name, actor_id)
        return guild

    @staticmethod
    async def set_description(session: AsyncSession, actor_id: int, text: Optional[str]) -> Guild:
        membership = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(membership, (GuildRole.leader, GuildRole.officer))
        guild = await session.get(Guild, membership.guild_id, with_for_update=True)
        text = (text or "").strip()
        if len(text) > 250:
            raise InvalidOperationError("Description too long (max 250).")
        guild.description = text or None
        session.add(GuildAudit(guild_id=guild.id, actor_player_id=actor_id, action="edit_description", meta={}))
        guild.add_activity("edit_description", str(actor_id))
        return guild

    @staticmethod
    async def set_emblem(session: AsyncSession, actor_id: int, emblem_url: Optional[str]) -> Guild:
        membership = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(membership, (GuildRole.leader, GuildRole.officer))
        guild = await session.get(Guild, membership.guild_id, with_for_update=True)
        guild.emblem_url = GuildService._validate_emblem(emblem_url)
        session.add(GuildAudit(guild_id=guild.id, actor_player_id=actor_id, action="edit_emblem", meta={}))
        guild.add_activity("edit_emblem", str(actor_id))
        return guild

    # ===============
    # Invites / Join
    # ===============

    @staticmethod
    async def invite(
        session: AsyncSession, actor_id: int, target_player_id: int, expires_in_hours: Optional[int] = 72
    ) -> GuildInvite:
        actor = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(actor, (GuildRole.leader, GuildRole.officer))

        guild = await session.get(Guild, actor.guild_id)
        if guild.member_count >= guild.max_members:
            raise InvalidOperationError("Guild is full.")

        # ensure target not already in a guild
        tgt_membership = await GuildService._get_membership(session, target_player_id)
        if tgt_membership:
            raise InvalidOperationError("Target is already in a guild.")

        existing = (
            await session.execute(
                select(GuildInvite).where(
                    GuildInvite.guild_id == guild.id,
                    GuildInvite.target_player_id == target_player_id,
                    GuildInvite.active.is_(True),
                )
            )
        ).scalar_one_or_none()

        if existing:
            return existing

        invite = GuildInvite(
            guild_id=guild.id,
            inviter_player_id=actor_id,
            target_player_id=target_player_id,
            active=True,
            expires_at=(datetime.utcnow() + timedelta(hours=expires_in_hours)) if expires_in_hours else None,
        )
        session.add(invite)
        session.add(GuildAudit(guild_id=guild.id, actor_player_id=actor_id, action="invite", meta={"target": target_player_id}))
        guild.add_activity("invite", str(actor_id), {"target": target_player_id})
        await session.flush()
        return invite

    @staticmethod
    async def revoke_invite(session: AsyncSession, actor_id: int, target_player_id: int) -> None:
        actor = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(actor, (GuildRole.leader, GuildRole.officer))

        inv = (
            await session.execute(
                select(GuildInvite).where(
                    GuildInvite.guild_id == actor.guild_id,
                    GuildInvite.target_player_id == target_player_id,
                    GuildInvite.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not inv:
            raise InvalidOperationError("Active invite not found.")

        inv.active = False
        session.add(GuildAudit(guild_id=actor.guild_id, actor_player_id=actor_id, action="invite_revoke", meta={"target": target_player_id}))

    @staticmethod
    async def accept_invite(session: AsyncSession, player_id: int, guild_id: int) -> GuildMember:
        # ensure not in guild
        if await GuildService._get_membership(session, player_id):
            raise InvalidOperationError("You are already in a guild.")

        inv = (
            await session.execute(
                select(GuildInvite).where(
                    GuildInvite.guild_id == guild_id,
                    GuildInvite.target_player_id == player_id,
                    GuildInvite.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not inv:
            raise InvalidOperationError("No active invite found.")

        if inv.expires_at and inv.expires_at < datetime.utcnow():
            inv.active = False
            raise InvalidOperationError("Invite expired.")

        guild = await session.get(Guild, guild_id, with_for_update=True)
        if guild.member_count >= guild.max_members:
            raise InvalidOperationError("Guild is full.")

        member = GuildMember(guild_id=guild_id, player_id=player_id, role=GuildRole.member)
        session.add(member)
        guild.member_count += 1

        inv.active = False
        session.add(GuildAudit(guild_id=guild_id, actor_player_id=player_id, action="join", meta={"accepted_invite": True}))
        guild.add_activity("join", str(player_id))
        await session.flush()
        return member

    @staticmethod
    async def join_by_name(session: AsyncSession, player_id: int, name: str) -> GuildMember:
        if await GuildService._get_membership(session, player_id):
            raise InvalidOperationError("You are already in a guild.")
        name = GuildService._validate_name(name)
        guild = (
            await session.execute(select(Guild).where(Guild.name == name))
        ).scalar_one_or_none()
        if not guild:
            raise InvalidOperationError("Guild not found.")

        # Optional: require open guild / settings. For now assume open join disabled.
        raise InvalidOperationError("Open join is disabled. Ask for an invite.")

    # =========
    # Leaving
    # =========

    @staticmethod
    async def leave(session: AsyncSession, player_id: int) -> None:
        membership = await GuildService._require_membership(session, player_id)
        guild = await session.get(Guild, membership.guild_id, with_for_update=True)

        is_leader = membership.role == GuildRole.leader
        session.delete(membership)
        guild.member_count = max(0, guild.member_count - 1)
        session.add(GuildAudit(guild_id=guild.id, actor_player_id=player_id, action="leave", meta={}))
        guild.add_activity("leave", str(player_id))

        # Promote next oldest member if leader leaves and guild not empty
        if is_leader and guild.member_count > 0:
            next_member = (
                await session.execute(
                    select(GuildMember)
                    .where(GuildMember.guild_id == guild.id)
                    .order_by(GuildMember.joined_at.asc())
                )
            ).scalars().first()
            if next_member:
                next_member.role = GuildRole.leader
                guild.owner_id = next_member.player_id
                session.add(
                    GuildAudit(
                        guild_id=guild.id,
                        actor_player_id=player_id,
                        action="transfer_leadership",
                        meta={"new_owner": next_member.player_id},
                    )
                )
                guild.add_activity("transfer_leadership", str(player_id), {"new_owner": next_member.player_id})

    # ===================
    # Roles / Moderation
    # ===================

    @staticmethod
    async def promote(session: AsyncSession, actor_id: int, target_player_id: int) -> GuildMember:
        actor = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(actor, (GuildRole.leader,))
        target = (
            await session.execute(
                select(GuildMember).where(
                    GuildMember.guild_id == actor.guild_id,
                    GuildMember.player_id == target_player_id,
                )
            )
        ).scalar_one_or_none()
        if not target:
            raise InvalidOperationError("Target is not a member of your guild.")

        if target.role == GuildRole.member:
            target.role = GuildRole.officer
        elif target.role == GuildRole.officer:
            target.role = GuildRole.leader
            # demote old leader
            actor.role = GuildRole.officer
        else:
            raise InvalidOperationError("Cannot promote above leader.")

        session.add(GuildAudit(guild_id=actor.guild_id, actor_player_id=actor_id, action="promote", meta={"target": target_player_id, "new_role": target.role.value}))
        return target

    @staticmethod
    async def demote(session: AsyncSession, actor_id: int, target_player_id: int) -> GuildMember:
        actor = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(actor, (GuildRole.leader,))
        target = (
            await session.execute(
                select(GuildMember).where(
                    GuildMember.guild_id == actor.guild_id,
                    GuildMember.player_id == target_player_id,
                )
            )
        ).scalar_one_or_none()
        if not target:
            raise InvalidOperationError("Target is not a member of your guild.")

        if target.role == GuildRole.leader:
            raise InvalidOperationError("Cannot demote the leader directly. Transfer leadership instead.")
        if target.role == GuildRole.officer:
            target.role = GuildRole.member
        else:
            raise InvalidOperationError("Target is already member rank.")

        session.add(GuildAudit(guild_id=actor.guild_id, actor_player_id=actor_id, action="demote", meta={"target": target_player_id, "new_role": target.role.value}))
        return target

    @staticmethod
    async def kick(session: AsyncSession, actor_id: int, target_player_id: int) -> None:
        actor = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(actor, (GuildRole.leader, GuildRole.officer))
        if actor.player_id == target_player_id:
            raise InvalidOperationError("You cannot kick yourself.")

        target = (
            await session.execute(
                select(GuildMember).where(
                    GuildMember.guild_id == actor.guild_id,
                    GuildMember.player_id == target_player_id,
                )
            )
        ).scalar_one_or_none()
        if not target:
            raise InvalidOperationError("Target is not a member of your guild.")

        if target.role == GuildRole.leader:
            raise InvalidOperationError("Cannot kick the leader.")
        guild = await session.get(Guild, actor.guild_id, with_for_update=True)

        session.delete(target)
        guild.member_count = max(0, guild.member_count - 1)
        session.add(GuildAudit(guild_id=guild.id, actor_player_id=actor_id, action="kick", meta={"target": target_player_id}))
        guild.add_activity("kick", str(actor_id), {"target": target_player_id})

    @staticmethod
    async def transfer_leadership(session: AsyncSession, actor_id: int, new_leader_player_id: int) -> None:
        actor = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(actor, (GuildRole.leader,))
        if actor.player_id == new_leader_player_id:
            raise InvalidOperationError("You are already the leader.")

        target = (
            await session.execute(
                select(GuildMember).where(
                    GuildMember.guild_id == actor.guild_id,
                    GuildMember.player_id == new_leader_player_id,
                )
            )
        ).scalar_one_or_none()
        if not target:
            raise InvalidOperationError("Target is not a member of your guild.")

        guild = await session.get(Guild, actor.guild_id, with_for_update=True)
        actor.role = GuildRole.officer
        target.role = GuildRole.leader
        guild.owner_id = target.player_id

        session.add(
            GuildAudit(
                guild_id=guild.id,
                actor_player_id=actor_id,
                action="transfer_leadership",
                meta={"new_owner": new_leader_player_id},
            )
        )
        guild.add_activity("transfer_leadership", str(actor_id), {"new_owner": new_leader_player_id})

    # ====================
    # Treasury / Upgrades
    # ====================

    @staticmethod
    async def donate_to_treasury(session: AsyncSession, player_id: int, rikis: int) -> Dict[str, Any]:
        if rikis <= 0:
            raise InvalidOperationError("Donation amount must be positive.")

        membership = await GuildService._require_membership(session, player_id)
        guild = await session.get(Guild, membership.guild_id, with_for_update=True)
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise InvalidOperationError("Player not found.")

        # Deduct from player via ResourceService (ensures lock + audit)
        await ResourceService.consume_resources(
            session=session,
            player=player,
            resources={"rikis": rikis},
            source="guild_donation",
            context={"guild_id": guild.id, "guild_name": guild.name},
        )

        guild.treasury += rikis

        session.add(GuildAudit(guild_id=guild.id, actor_player_id=player_id, action="donate", meta={"rikis": rikis}))
        guild.add_activity("donate", str(player_id), {"rikis": rikis})

        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="guild_donate",
            details={"rikis": rikis, "guild_id": guild.id, "guild_name": guild.name},
            context="guild",
        )
        await session.flush()
        return {"treasury": guild.treasury}

    @staticmethod
    async def upgrade_guild(session: AsyncSession, actor_id: int) -> Guild:
        membership = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(membership, (GuildRole.leader, GuildRole.officer))

        guild = await session.get(Guild, membership.guild_id, with_for_update=True)
        next_level = guild.level + 1
        costs = ConfigManager.get("guilds.upgrade_costs", {})
        cost = int(costs.get(f"level_{next_level}", ConfigManager.get("guilds.base_upgrade_cost", 25000)))

        if guild.treasury < cost:
            raise InvalidOperationError("Insufficient treasury.")

        guild.treasury -= cost
        guild.level = next_level

        # Progression knobs
        growth = int(ConfigManager.get("guilds.member_growth_per_level", 2))
        guild.max_members += max(0, growth)

        # Example perk bump
        perks = guild.perks or {}
        perks["income_boost"] = int(perks.get("income_boost", 0)) + 5
        guild.perks = perks

        session.add(
            GuildAudit(
                guild_id=guild.id,
                actor_player_id=actor_id,
                action="upgrade",
                meta={"cost": cost, "level": guild.level, "new_max_members": guild.max_members},
            )
        )
        guild.add_activity("upgrade", str(actor_id), {"level": guild.level, "cost": cost})

        await TransactionLogger.log_transaction(
            session=session,
            player_id=actor_id,
            transaction_type="guild_upgrade",
            details={"cost": cost, "guild_id": guild.id, "new_level": guild.level},
            context="guild",
        )

        await session.flush()
        return guild

    # ==================
    # Disband / Summary
    # ==================

    @staticmethod
    async def disband(session: AsyncSession, actor_id: int) -> None:
        membership = await GuildService._require_membership(session, actor_id)
        GuildService._require_role(membership, (GuildRole.leader,))
        guild = await session.get(Guild, membership.guild_id, with_for_update=True)

        # Soft-delete approach: mark inactive; cascade handles members via model if configured.
        guild.is_active = False
        session.add(GuildAudit(guild_id=guild.id, actor_player_id=actor_id, action="disband", meta={}))
        guild.add_activity("disband", str(actor_id))
        logger.info("Guild %s disbanded by %s", guild.name, actor_id)

    @staticmethod
    async def get_guild_summary(session: AsyncSession, guild_id: int) -> Dict[str, Any]:
        from sqlalchemy.orm import selectinload

        # ✅ Optimized: Use eager loading to prevent N+1 queries
        result = await session.execute(
            select(Guild)
            .options(selectinload(Guild.members), selectinload(Guild.invites))
            .where(Guild.id == guild_id)
        )
        guild = result.scalar_one_or_none()

        if not guild:
            raise InvalidOperationError("Guild not found.")

        # Filter and sort members (already loaded)
        members = sorted(
            guild.members,
            key=lambda m: m.joined_at
        )

        # Filter active invites (already loaded)
        invites = [inv for inv in guild.invites if inv.active]

        return {
            "id": guild.id,
            "name": guild.name,
            "level": guild.level,
            "treasury": guild.treasury,
            "member_count": guild.member_count,
            "max_members": guild.max_members,
            "perks": guild.perks or {},
            "emblem_url": guild.emblem_url,
            "description": guild.description,
            "created_at": guild.created_at,
            "members": [{"player_id": m.player_id, "role": m.role.value, "joined_at": m.joined_at} for m in members],
            "active_invites": [
                {"target_player_id": i.target_player_id, "expires_at": i.expires_at} for i in invites
            ],
            "activity_sample": guild.activity_log[:10] if guild.activity_log else [],
        }
