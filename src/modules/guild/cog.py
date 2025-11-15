from __future__ import annotations

import discord
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import time # ADDED: For latency logging

from src.bot.base_cog import BaseCog

from src.core.logging.logger import get_logger
from src.core.exceptions import InvalidOperationError
from src.core.infra.database_service import DatabaseService
from src.core.infra.redis_service import RedisService
from src.modules.guild.service import GuildService
from src.core.config import ConfigManager
from src.ui.emojis import Emojis
from src.ui import EmbedFactory, BaseView
from src.utils.decorators import ratelimit

if TYPE_CHECKING:
    from typing import Callable # ADDED: For passing structured logger

logger = get_logger(__name__)


def _ok(title: str, desc: str = "") -> discord.Embed:
    """Success embed for guild operations."""
    return EmbedFactory.success(title=title, description=desc)


def _err(title: str, desc: str = "") -> discord.Embed:
    """Error embed for guild operations."""
    return EmbedFactory.error(title=title, description=desc)


def _gid(ctx: commands.Context) -> Optional[int]:
    """Safely get guild ID from context or None."""
    return getattr(getattr(ctx, "guild", None), "id", None)


class GuildCog(BaseCog):
    """
    Guild command suite for managing guilds.
    Thin UI layer that delegates all business logic to GuildService.

    LUMEN LAW Compliance:
        - Article I.2: All state mutations log success/failure using BaseCog's structured logger.
        - Article I.3: Redis locks used on treasury mutations (donate/upgrade).
        - Article I.5: Graceful exception handling for InvalidOperationError.
        - Article II: Logging utilities passed to the interactive view.
        - Architecture: Uses @commands.guild_only() for stable execution.
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "GuildCog")

    # ------------- HELP / MENU (prefix quick view) -------------

    @commands.command(name="guild", aliases=["g"])
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.menu.uses", 5),
        per_seconds=ConfigManager.get("rate_limits.guild.menu.period", 30),
        command_name="guild"
    )
    async def guild_menu(self, ctx: commands.Context):
        """Guild command menu with interactive buttons."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)

        try:
            embed = _ok(
                f"{Emojis.GUILD} Guild Commands",
                (
                    "**Available Commands** (use `;guild` or `;g`)\n"
                    "• `;guild create <name>` — Create your guild\n"
                    "• `;guild invite <@user>` — Invite a player (leader/officer)\n"
                    "• `;guild accept <guild_id>` — Accept an invite to a guild\n"
                    "• `;guild donate <lumees>` — Donate to guild treasury\n"
                    "• `;guild upgrade` — Upgrade guild level\n"
                    "• `;guild promote <@user>` — Promote a member (leader)\n"
                    "• `;guild demote <@user>` — Demote a member (leader)\n"
                    "• `;guild kick <@user>` — Kick a member (leader/officer)\n"
                    "• `;guild transfer <@user>` — Transfer leadership (leader)\n"
                    "• `;guild leave` — Leave your guild\n"
                    "• `;guild info [guild_id]` — Show guild overview\n"
                    "• `;guild set_description <text>` — Set description (leader/officer)\n"
                    "• `;guild set_emblem <url>` — Set emblem URL (leader/officer)\n"
                    "• `;guild revoke_invite <@user>` — Revoke pending invite (leader/officer)\n\n"
                    "**Tips**\n"
                    "• Use `;guild info` to see your guild's treasury, perks, members, & recent activity.\n"
                    "• Officers can invite & manage members; only leaders can transfer leadership.\n\n"
                    "Use the buttons below for quick access to common actions!"
                )
            )

            # LUMEN LAW II: Pass structured logger method to view for auditable failures
            view = GuildMenuView(ctx.author.id, self.log_cog_error)
            # MODIFIED: Combined sends into a single call
            message = await ctx.send(embed=embed, view=view)
            view.message = message  # Track message for visual timeout disable
            
            # Log success
            self.log_command_use(
                "guild_menu", ctx.author.id, guild_id=_gid(ctx),
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )

        except Exception as e:
            # Log unexpected failure
            self.log_cog_error(
                "guild_menu", e, ctx.author.id, guild_id=_gid(ctx),
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__
            )
            # MODIFIED: Indentation fix to ensure error message is sent if needed
            if not await self.handle_standard_errors(ctx, e):
                 await self.send_error(
                    ctx,
                    "Guild Menu Error",
                    "Unable to load guild interface. The system has been notified.",
                )

    # ------------- GUILD GROUP -------------

    @commands.group(name="guild", aliases=[])
    @commands.guild_only() # ADDED: Mandatory decorator
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.group.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.guild.group.period", 60),
        command_name="guild"
    )
    async def guild(self, ctx: commands.Context):
        """Top-level guild command group."""
        if ctx.invoked_subcommand is None:
            await self.guild_menu(ctx)

    # ------------- SUBCOMMANDS (LUMEN LAW I.2, I.5) -------------

    @guild.command(name="create")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.create.uses", 3),
        per_seconds=ConfigManager.get("rate_limits.guild.create.period", 300),
        command_name="guild_create"
    )
    async def guild_create(self, ctx: commands.Context, name: str):
        """Create a new guild where you are the leader."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        owner_id = ctx.author.id
        log_context = {"name": name}

        try:
            async with DatabaseService.get_transaction() as session:
                g = await GuildService.create_guild(session, owner_id=owner_id, name=name, description=None)
                embed = _ok("Guild Created",
                            f"**{g.name}** is live!\nLeader: <@{owner_id}>\nMembers: 1 / {g.max_members}\nLevel: {g.level}")

            # Log success
            self.log_command_use(
                "guild_create", owner_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_create", e, owner_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Create Guild", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_create", e, owner_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Something went wrong creating the guild. The system has been notified."))

    @guild.command(name="invite")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.invite.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.guild.invite.period", 60),
        command_name="guild_invite"
    )
    async def guild_invite(self, ctx: commands.Context, user: discord.Member):
        """Invite a player to your guild (leader/officer only)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        target_id = user.id
        log_context = {"target_id": target_id}

        try:
            async with DatabaseService.get_transaction() as session:
                inv = await GuildService.invite(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Invite Sent", f"Invited <@{target_id}> to your guild.\nInvite expires: {inv.expires_at or 'no expiry'}")

            self.log_command_use(
                "guild_invite", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_invite", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Invite", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_invite", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Failed to send invite."))

    @guild.command(name="revoke_invite")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.revoke.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.guild.revoke.period", 60),
        command_name="guild_revoke"
    )
    async def guild_revoke_invite(self, ctx: commands.Context, user: discord.Member):
        """Revoke a pending invite (leader/officer only)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        target_id = user.id
        log_context = {"target_id": target_id}

        try:
            async with DatabaseService.get_transaction() as session:
                await GuildService.revoke_invite(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Invite Revoked", f"Revoked invite for <@{target_id}>.")

            self.log_command_use(
                "guild_revoke_invite", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_revoke_invite", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Revoke", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_revoke_invite", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Failed to revoke invite."))

    @guild.command(name="accept")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.accept.uses", 5),
        per_seconds=ConfigManager.get("rate_limits.guild.accept.period", 60),
        command_name="guild_accept"
    )
    async def guild_accept(self, ctx: commands.Context, guild_id: int):
        """Accept an invite to a guild."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        player_id = ctx.author.id
        log_context = {"guild_id": guild_id}

        try:
            async with DatabaseService.get_transaction() as session:
                mem = await GuildService.accept_invite(session, player_id=player_id, guild_id=guild_id)
                embed = _ok("Joined Guild", f"You joined guild **{mem.guild_id}**.")

            self.log_command_use(
                "guild_accept", player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_accept", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Join", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_accept", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Failed to accept invite."))

    @guild.command(name="donate")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.donate.uses", 20),
        per_seconds=ConfigManager.get("rate_limits.guild.donate.period", 60),
        command_name="guild_donate"
    )
    async def guild_donate(self, ctx: commands.Context, lumees: int):
        """Donate lumees to the guild treasury."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        player_id = ctx.author.id
        log_context = {"lumees": lumees}

        try:
            async with DatabaseService.get_transaction() as session:
                mem = await GuildService._get_membership(session, player_id)
                if not mem:
                    raise InvalidOperationError("You are not in a guild.")

                guild_id = mem.guild_id
                log_context["guild_id"] = guild_id
                
                # LUMEN LAW I.3: Redis lock for shared treasury state mutation
                lock_key = f"guild_treasury:{guild_id}"
                async with RedisService.acquire_lock(lock_key, timeout=5):
                    res = await GuildService.donate_to_treasury(session, player_id=player_id, lumees=lumees)
                
                embed = _ok("Donation Complete", f"Donated **{lumees:,}** lumees.\nTreasury: **{res['treasury']:,}**")

            # Log success
            self.log_command_use(
                "guild_donate", player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_donate", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Donate", str(e)))

        except Exception as e:
            # Logs Redis lock failure/timeout or other system error
            self.log_cog_error(
                "guild_donate", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Donation failed due to a system error. The team has been notified."))

    @guild.command(name="upgrade")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.upgrade.uses", 5),
        per_seconds=ConfigManager.get("rate_limits.guild.upgrade.period", 60),
        command_name="guild_upgrade"
    )
    async def guild_upgrade(self, ctx: commands.Context):
        """Upgrade your guild level (treasury pays the cost)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        log_context = {}

        try:
            async with DatabaseService.get_transaction() as session:
                mem = await GuildService._get_membership(session, actor_id)
                if not mem:
                    raise InvalidOperationError("You are not in a guild.")

                guild_id = mem.guild_id
                log_context["guild_id"] = guild_id
                
                # LUMEN LAW I.3: Redis lock for shared treasury state mutation
                lock_key = f"guild_treasury:{guild_id}"
                async with RedisService.acquire_lock(lock_key, timeout=5):
                    g = await GuildService.upgrade_guild(session, actor_id=actor_id)
                
                embed = _ok(
                    "Guild Upgraded",
                    f"**{g.name}** is now **Level {g.level}**!\n"
                    f"Max Members: **{g.max_members}**\n"
                    f"Treasury: **{g.treasury:,}**"
                )

            # Log success
            self.log_command_use(
                "guild_upgrade", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_upgrade", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Upgrade", str(e)))

        except Exception as e:
            # Logs Redis lock failure/timeout or other system error
            self.log_cog_error(
                "guild_upgrade", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Upgrade failed due to a system error. The team has been notified."))

    @guild.command(name="promote")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.promote.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.guild.promote.period", 60),
        command_name="guild_promote"
    )
    async def guild_promote(self, ctx: commands.Context, user: discord.Member):
        """Promote a member (leader → officer, officer → leader)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        target_id = user.id
        log_context = {"target_id": target_id}

        try:
            async with DatabaseService.get_transaction() as session:
                mem = await GuildService.promote(session, actor_id=actor_id, target_player_id=target_id)
                role_name = getattr(mem.role, 'value', str(mem.role))
                embed = _ok("Member Promoted", f"<@{target_id}> is now **{role_name}**.")

            self.log_command_use(
                "guild_promote", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_promote", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Promote", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_promote", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Promotion failed."))

    @guild.command(name="demote")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.demote.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.guild.demote.period", 60),
        command_name="guild_demote"
    )
    async def guild_demote(self, ctx: commands.Context, user: discord.Member):
        """Demote a member (leader only)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        target_id = user.id
        log_context = {"target_id": target_id}

        try:
            async with DatabaseService.get_transaction() as session:
                mem = await GuildService.demote(session, actor_id=actor_id, target_player_id=target_id)
                role_name = getattr(mem.role, 'value', str(mem.role))
                embed = _ok("Member Demoted", f"<@{target_id}> is now **{role_name}**.")

            self.log_command_use(
                "guild_demote", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_demote", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Demote", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_demote", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Demotion failed."))

    @guild.command(name="kick")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.kick.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.guild.kick.period", 60),
        command_name="guild_kick"
    )
    async def guild_kick(self, ctx: commands.Context, user: discord.Member):
        """Kick a member (leader/officer)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        target_id = user.id
        log_context = {"target_id": target_id}

        try:
            async with DatabaseService.get_transaction() as session:
                await GuildService.kick(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Member Kicked", f"Removed <@{target_id}> from the guild.")

            self.log_command_use(
                "guild_kick", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_kick", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Kick", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_kick", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Kick failed."))

    @guild.command(name="transfer")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.transfer.uses", 2),
        per_seconds=ConfigManager.get("rate_limits.guild.transfer.period", 300),
        command_name="guild_transfer"
    )
    async def guild_transfer(self, ctx: commands.Context, user: discord.Member):
        """Transfer leadership to another member (leader only)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        target_id = user.id
        log_context = {"target_id": target_id}

        try:
            async with DatabaseService.get_transaction() as session:
                await GuildService.transfer_leadership(session, actor_id=actor_id, new_leader_player_id=target_id)
                embed = _ok("Leadership Transferred", f"Leadership granted to <@{target_id}>.")

            self.log_command_use(
                "guild_transfer", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_transfer", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Transfer", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_transfer", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Transfer failed."))

    @guild.command(name="leave")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.leave.uses", 5),
        per_seconds=ConfigManager.get("rate_limits.guild.leave.period", 60),
        command_name="guild_leave"
    )
    async def guild_leave(self, ctx: commands.Context):
        """Leave your current guild."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        player_id = ctx.author.id
        log_context = {}

        try:
            async with DatabaseService.get_transaction() as session:
                await GuildService.leave(session, player_id=player_id)
                embed = _ok("Left Guild", "You have left your guild.")

            self.log_command_use(
                "guild_leave", player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_leave", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Leave", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_leave", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Failed to leave guild."))

    @guild.command(name="info")
    # NOTE: No @commands.guild_only() as it supports rg info [guild_id] which may be used in DM/non-guild context
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.info.uses", 30),
        per_seconds=ConfigManager.get("rate_limits.guild.info.period", 60),
        command_name="guild_info"
    )
    async def guild_info(self, ctx: commands.Context, guild_id: Optional[int] = None):
        """Show an overview embed for a guild."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        player_id = ctx.author.id
        log_context = {"target_guild_id": guild_id or "self"}

        try:
            async with DatabaseService.get_transaction() as session:
                target_guild_id = guild_id
                if target_guild_id is None:
                    mem = await GuildService._get_membership(session, player_id)
                    if not mem:
                        raise InvalidOperationError("You are not in a guild. Use `;guild info <guild_id>`.")
                    target_guild_id = mem.guild_id

                log_context["resolved_guild_id"] = target_guild_id
                data = await GuildService.get_guild_summary(session, guild_id=target_guild_id)

                # Build a rich embed (Formatting left in cog as it's UI presentation)
                title = f"{data['name']} — L{data['level']}"
                desc = (
                    f"Treasury: **{data['treasury']:,}** lumees\n"
                    f"Members: **{data['member_count']} / {data['max_members']}**\n"
                )
                embed = _ok(title, desc)
                if data.get("emblem_url"):
                    embed.set_thumbnail(url=data["emblem_url"])
                if data.get("description"):
                    embed.add_field(name="Description", value=data["description"], inline=False)

                # Perks
                perks = data.get("perks") or {}
                if perks:
                    perks_lines = [f"• {k.replace('_',' ').title()}: +{v}%" for k, v in perks.items() if isinstance(v, int) and v > 0]
                    embed.add_field(name="Perks", value="\n".join(perks_lines) or "None", inline=False)

                # Members (first 12)
                roster = data.get("members") or []
                if roster:
                    names = [f"<@{m['player_id']}> — {m['role']}" for m in roster[:12]]
                    more = f"\n…and {len(roster)-12} more" if len(roster) > 12 else ""
                    embed.add_field(name="Roster", value="\n".join(names) + more, inline=False)

                # Activity (last 5)
                act = data.get("activity_sample") or []
                if act:
                    lines = []
                    for a in act[:5]:
                        action = a.get("action", "event")
                        user = a.get("user", "?")
                        ts = a.get("ts", "")
                        lines.append(f"• `{ts}` — **{action}** by {user}")
                    embed.add_field(name="Recent Activity", value="\n".join(lines), inline=False)

            self.log_command_use(
                "guild_info", player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_info", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Show Guild", str(e)))
        
        except Exception as e:
            self.log_cog_error(
                "guild_info", e, player_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Failed to load guild info."))

    @guild.command(name="set_description")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.set_description.uses", 5),
        per_seconds=ConfigManager.get("rate_limits.guild.set_description.period", 300),
        command_name="guild_set_desc"
    )
    async def guild_set_description(self, ctx: commands.Context, *, text: str):
        """Set or clear the guild description (leader/officer)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        log_context = {"text_length": len(text)}

        try:
            async with DatabaseService.get_transaction() as session:
                g = await GuildService.set_description(session, actor_id=actor_id, text=text)
                embed = _ok("Description Updated", g.description or "_(cleared)_")

            self.log_command_use(
                "guild_set_description", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_set_description", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Update Description", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_set_description", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Failed to update description."))

    @guild.command(name="set_emblem")
    @commands.guild_only() # ADDED
    @ratelimit(
        uses=ConfigManager.get("rate_limits.guild.set_emblem.uses", 5),
        per_seconds=ConfigManager.get("rate_limits.guild.set_emblem.period", 300),
        command_name="guild_set_emblem"
    )
    async def guild_set_emblem(self, ctx: commands.Context, url: str):
        """Set the guild emblem URL (leader/officer)."""
        start_time = time.perf_counter()
        await self.safe_defer(ctx)
        actor_id = ctx.author.id
        log_context = {"url_length": len(url)}

        try:
            async with DatabaseService.get_transaction() as session:
                g = await GuildService.set_emblem(session, actor_id=actor_id, emblem_url=url)
                embed = _ok("Emblem Updated", f"Now using: {g.emblem_url or '(none)'}")

            self.log_command_use(
                "guild_set_emblem", actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="success", **log_context
            )
            await ctx.send(embed=embed)

        except InvalidOperationError as e:
            self.log_cog_error(
                "guild_set_emblem", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="domain_error", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("Cannot Update Emblem", str(e)))

        except Exception as e:
            self.log_cog_error(
                "guild_set_emblem", e, actor_id, guild_id=_gid(ctx), 
                latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                status="unexpected_failure", error_type=type(e).__name__, **log_context
            )
            await ctx.send(embed=_err("System Error", "Failed to set emblem."))


class GuildMenuView(discord.ui.View):
    """Interactive menu for guild quick actions."""

    # MODIFIED: Added cog_logger for LUMEN LAW II compliance
    def __init__(self, user_id: int, cog_logger: 'Callable'):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.cog_logger = cog_logger # LUMEN LAW II: Keep logger method
        self.message: Optional[discord.Message] = None

    @discord.ui.button(
        label=f"{Emojis.INFO} Guild Info",
        style=discord.ButtonStyle.primary,
        custom_id="guild_info"
    )
    async def guild_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show guild info."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return

        # LUMEN LAW II: Log interaction use
        self.cog_logger(
            "guild_menu_button", 
            None, 
            self.user_id, 
            guild_id=interaction.guild_id, 
            status="success", 
            action="info_button"
        )
        
        await interaction.response.send_message(
            "Use `;guild info` to view your guild's details!",
            ephemeral=True
        )

    @discord.ui.button(
        label=f"{Emojis.LUMEES} Donate",
        style=discord.ButtonStyle.success,
        custom_id="guild_donate"
    )
    async def guild_donate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Quick donate to guild."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return
            
        self.cog_logger(
            "guild_menu_button", 
            None, 
            self.user_id, 
            guild_id=interaction.guild_id, 
            status="success", 
            action="donate_button"
        )

        await interaction.response.send_message(
            "Use `;guild donate <amount>` to donate lumees to your guild treasury!",
            ephemeral=True
        )

    @discord.ui.button(
        label=f"{Emojis.UPGRADE} Upgrade",
        style=discord.ButtonStyle.success,
        custom_id="guild_upgrade"
    )
    async def guild_upgrade_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Quick upgrade guild."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return
            
        self.cog_logger(
            "guild_menu_button", 
            None, 
            self.user_id, 
            guild_id=interaction.guild_id, 
            status="success", 
            action="upgrade_button"
        )

        await interaction.response.send_message(
            "Use `;guild upgrade` to level up your guild!",
            ephemeral=True
        )

    @discord.ui.button(
        label="👥 Invite",
        style=discord.ButtonStyle.secondary,
        custom_id="guild_invite"
    )
    async def guild_invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Quick invite to guild."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button isn't for you!",
                ephemeral=True
            )
            return
            
        self.cog_logger(
            "guild_menu_button", 
            None, 
            self.user_id, 
            guild_id=interaction.guild_id, 
            status="success", 
            action="invite_button"
        )

        await interaction.response.send_message(
            "Use `;guild invite @user` to invite someone to your guild!",
            ephemeral=True
        )

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        try:
            # If we still have access to the sent message, edit to reflect disabled state
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildCog(bot))