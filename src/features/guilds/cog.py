from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from src.core.logger import get_logger
from src.core.exceptions import InvalidOperationError
from src.core.database_service import DatabaseService
from src.features.guilds.service import GuildService
from src.core.config_manager import ConfigManager
from src.utils.embed_builder import EmbedBuilder  # assumes your shared embed util

logger = get_logger(__name__)


def _ok(title: str, desc: str = "") -> discord.Embed:
    """Success embed for guild operations."""
    return EmbedBuilder.success(title=title, description=desc)


def _err(title: str, desc: str = "") -> discord.Embed:
    """Error embed for guild operations."""
    return EmbedBuilder.error(title=title, description=desc)


async def _send_ctx(ctx: commands.Context, embed: discord.Embed, *, ephemeral: bool = True):
    """
    Send a response that works for both prefix and slash (hybrid) calls.
    """
    if getattr(ctx, "interaction", None):
        intr = ctx.interaction
        try:
            if not intr.response.is_done():
                await intr.response.send_message(embed=embed, ephemeral=ephemeral)
            else:
                await intr.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception:
            # Fallback if response state is odd
            await ctx.send(embed=embed)
    else:
        await ctx.send(embed=embed)


class GuildCog(commands.Cog, name="Guild"):
    """
    /guild command suite (also available via prefix as 'rguild' / 'rg' menu).
    Thin UI layer that delegates all business logic to GuildService.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------- HELP / MENU (prefix quick view) -------------

    @commands.command(name="rguild", aliases=["rg"])
    async def rguild_menu(self, ctx: commands.Context):
        """Prefix quick menu for guild commands."""
        embed = _ok(
            "Guild Commands",
            (
                "**Slash / Hybrid**\n"
                "• `/guild create <name>` — Create your guild\n"
                "• `/guild invite <@user>` — Invite a player (leader/officer)\n"
                "• `/guild accept <guild_id>` — Accept an invite to a guild\n"
                "• `/guild donate <rikis>` — Donate to guild treasury\n"
                "• `/guild upgrade` — Upgrade guild level\n"
                "• `/guild promote <@user>` — Promote a member (leader)\n"
                "• `/guild demote <@user>` — Demote a member (leader)\n"
                "• `/guild kick <@user>` — Kick a member (leader/officer)\n"
                "• `/guild transfer <@user>` — Transfer leadership (leader)\n"
                "• `/guild leave` — Leave your guild\n"
                "• `/guild info [guild_id]` — Show guild overview\n"
                "• `/guild set_description <text>` — Set description (leader/officer)\n"
                "• `/guild set_emblem <url>` — Set emblem URL (leader/officer)\n"
                "• `/guild revoke_invite <@user>` — Revoke pending invite (leader/officer)\n\n"
                "**Tips**\n"
                "• Use `/guild info` to see your guild’s treasury, perks, members, & recent activity.\n"
                "• Officers can invite & manage members; only leaders can transfer leadership."
            )
        )
        await _send_ctx(ctx, embed, ephemeral=False)

    # ------------- HYBRID GROUP -------------

    @commands.hybrid_group(name="guild", with_app_command=True)
    async def guild(self, ctx: commands.Context):
        """Top-level guild command group."""
        if ctx.invoked_subcommand is None:
            await self.rguild_menu(ctx)

    # ------------- SUBCOMMANDS -------------

    @guild.command(name="create")
    @app_commands.describe(name="Unique guild name (max 50 chars)")
    async def guild_create(self, ctx: commands.Context, name: str):
        """Create a new guild where you are the leader."""
        owner_id = ctx.author.id
        async with DatabaseService.get_transaction() as session:
            try:
                g = await GuildService.create_guild(session, owner_id=owner_id, name=name, description=None)
                embed = _ok("Guild Created",
                            f"**{g.name}** is live!\nLeader: <@{owner_id}>\nMembers: 1 / {g.max_members}\nLevel: {g.level}")
            except InvalidOperationError as e:
                embed = _err("Cannot Create Guild", str(e))
            except Exception as e:
                logger.exception("guild_create error")
                embed = _err("Error", "Something went wrong creating the guild.")
        await _send_ctx(ctx, embed)

    @guild.command(name="invite")
    @app_commands.describe(user="User to invite")
    async def guild_invite(self, ctx: commands.Context, user: discord.Member):
        """Invite a player to your guild (leader/officer only)."""
        actor_id = ctx.author.id
        target_id = user.id
        async with DatabaseService.get_transaction() as session:
            try:
                inv = await GuildService.invite(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Invite Sent", f"Invited <@{target_id}> to your guild.\nInvite expires: {inv.expires_at or 'no expiry'}")
            except InvalidOperationError as e:
                embed = _err("Cannot Invite", str(e))
            except Exception:
                logger.exception("guild_invite error")
                embed = _err("Error", "Failed to send invite.")
        await _send_ctx(ctx, embed)

    @guild.command(name="revoke_invite")
    @app_commands.describe(user="User whose pending invite should be revoked")
    async def guild_revoke_invite(self, ctx: commands.Context, user: discord.Member):
        """Revoke a pending invite (leader/officer only)."""
        actor_id = ctx.author.id
        target_id = user.id
        async with DatabaseService.get_transaction() as session:
            try:
                await GuildService.revoke_invite(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Invite Revoked", f"Revoked invite for <@{target_id}>.")
            except InvalidOperationError as e:
                embed = _err("Cannot Revoke", str(e))
            except Exception:
                logger.exception("guild_revoke_invite error")
                embed = _err("Error", "Failed to revoke invite.")
        await _send_ctx(ctx, embed)

    @guild.command(name="accept")
    @app_commands.describe(guild_id="The guild ID you are accepting an invite for")
    async def guild_accept(self, ctx: commands.Context, guild_id: int):
        """Accept an invite to a guild."""
        player_id = ctx.author.id
        async with DatabaseService.get_transaction() as session:
            try:
                mem = await GuildService.accept_invite(session, player_id=player_id, guild_id=guild_id)
                embed = _ok("Joined Guild", f"You joined guild **{mem.guild_id}**.")
            except InvalidOperationError as e:
                embed = _err("Cannot Join", str(e))
            except Exception:
                logger.exception("guild_accept error")
                embed = _err("Error", "Failed to accept invite.")
        await _send_ctx(ctx, embed)

    @guild.command(name="donate")
    @app_commands.describe(rikis="Amount of rikis to donate to the guild treasury")
    async def guild_donate(self, ctx: commands.Context, rikis: int):
        """Donate rikis to the guild treasury."""
        player_id = ctx.author.id
        async with DatabaseService.get_transaction() as session:
            try:
                res = await GuildService.donate_to_treasury(session, player_id=player_id, rikis=rikis)
                embed = _ok("Donation Complete", f"Donated **{rikis:,}** rikis.\nTreasury: **{res['treasury']:,}**")
            except InvalidOperationError as e:
                embed = _err("Cannot Donate", str(e))
            except Exception:
                logger.exception("guild_donate error")
                embed = _err("Error", "Donation failed.")
        await _send_ctx(ctx, embed)

    @guild.command(name="upgrade")
    async def guild_upgrade(self, ctx: commands.Context):
        """Upgrade your guild level (treasury pays the cost)."""
        actor_id = ctx.author.id
        async with DatabaseService.get_transaction() as session:
            try:
                g = await GuildService.upgrade_guild(session, actor_id=actor_id)
                embed = _ok(
                    "Guild Upgraded",
                    f"**{g.name}** is now **Level {g.level}**!\n"
                    f"Max Members: **{g.max_members}**\n"
                    f"Treasury: **{g.treasury:,}**"
                )
            except InvalidOperationError as e:
                embed = _err("Cannot Upgrade", str(e))
            except Exception:
                logger.exception("guild_upgrade error")
                embed = _err("Error", "Upgrade failed.")
        await _send_ctx(ctx, embed)

    @guild.command(name="promote")
    @app_commands.describe(user="Member to promote")
    async def guild_promote(self, ctx: commands.Context, user: discord.Member):
        """Promote a member (leader → officer, officer → leader)."""
        actor_id = ctx.author.id
        target_id = user.id
        async with DatabaseService.get_transaction() as session:
            try:
                mem = await GuildService.promote(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Member Promoted", f"<@{target_id}> is now **{getattr(mem.role, 'value', str(mem.role))}**.")
            except InvalidOperationError as e:
                embed = _err("Cannot Promote", str(e))
            except Exception:
                logger.exception("guild_promote error")
                embed = _err("Error", "Promotion failed.")
        await _send_ctx(ctx, embed)

    @guild.command(name="demote")
    @app_commands.describe(user="Member to demote")
    async def guild_demote(self, ctx: commands.Context, user: discord.Member):
        """Demote a member (leader only)."""
        actor_id = ctx.author.id
        target_id = user.id
        async with DatabaseService.get_transaction() as session:
            try:
                mem = await GuildService.demote(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Member Demoted", f"<@{target_id}> is now **{getattr(mem.role, 'value', str(mem.role))}**.")
            except InvalidOperationError as e:
                embed = _err("Cannot Demote", str(e))
            except Exception:
                logger.exception("guild_demote error")
                embed = _err("Error", "Demotion failed.")
        await _send_ctx(ctx, embed)

    @guild.command(name="kick")
    @app_commands.describe(user="Member to kick")
    async def guild_kick(self, ctx: commands.Context, user: discord.Member):
        """Kick a member (leader/officer)."""
        actor_id = ctx.author.id
        target_id = user.id
        async with DatabaseService.get_transaction() as session:
            try:
                await GuildService.kick(session, actor_id=actor_id, target_player_id=target_id)
                embed = _ok("Member Kicked", f"Removed <@{target_id}> from the guild.")
            except InvalidOperationError as e:
                embed = _err("Cannot Kick", str(e))
            except Exception:
                logger.exception("guild_kick error")
                embed = _err("Error", "Kick failed.")
        await _send_ctx(ctx, embed)

    @guild.command(name="transfer")
    @app_commands.describe(user="New leader")
    async def guild_transfer(self, ctx: commands.Context, user: discord.Member):
        """Transfer leadership to another member (leader only)."""
        actor_id = ctx.author.id
        target_id = user.id
        async with DatabaseService.get_transaction() as session:
            try:
                await GuildService.transfer_leadership(session, actor_id=actor_id, new_leader_player_id=target_id)
                embed = _ok("Leadership Transferred", f"Leadership granted to <@{target_id}>.")
            except InvalidOperationError as e:
                embed = _err("Cannot Transfer", str(e))
            except Exception:
                logger.exception("guild_transfer error")
                embed = _err("Error", "Transfer failed.")
        await _send_ctx(ctx, embed)

    @guild.command(name="leave")
    async def guild_leave(self, ctx: commands.Context):
        """Leave your current guild."""
        player_id = ctx.author.id
        async with DatabaseService.get_transaction() as session:
            try:
                await GuildService.leave(session, player_id=player_id)
                embed = _ok("Left Guild", "You have left your guild.")
            except InvalidOperationError as e:
                embed = _err("Cannot Leave", str(e))
            except Exception:
                logger.exception("guild_leave error")
                embed = _err("Error", "Failed to leave guild.")
        await _send_ctx(ctx, embed)

    @guild.command(name="info")
    @app_commands.describe(guild_id="Optional guild ID. If omitted, shows your guild.")
    async def guild_info(self, ctx: commands.Context, guild_id: Optional[int] = None):
        """Show an overview embed for a guild."""
        async with DatabaseService.get_transaction() as session:
            try:
                if guild_id is None:
                    # Find caller's guild membership
                    mem = await GuildService._get_membership(session, ctx.author.id)
                    if not mem:
                        raise InvalidOperationError("You are not in a guild.")
                    guild_id = mem.guild_id

                data = await GuildService.get_guild_summary(session, guild_id=guild_id)

                # Build a rich embed
                title = f"{data['name']} — L{data['level']}"
                desc = (
                    f"Treasury: **{data['treasury']:,}** rikis\n"
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

            except InvalidOperationError as e:
                embed = _err("Cannot Show Guild", str(e))
            except Exception:
                logger.exception("guild_info error")
                embed = _err("Error", "Failed to load guild info.")
        await _send_ctx(ctx, embed, ephemeral=False)

    @guild.command(name="set_description")
    @app_commands.describe(text="New guild description (max 250 chars)")
    async def guild_set_description(self, ctx: commands.Context, *, text: str):
        """Set or clear the guild description (leader/officer)."""
        actor_id = ctx.author.id
        async with DatabaseService.get_transaction() as session:
            try:
                g = await GuildService.set_description(session, actor_id=actor_id, text=text)
                embed = _ok("Description Updated", g.description or "_(cleared)_")
            except InvalidOperationError as e:
                embed = _err("Cannot Update Description", str(e))
            except Exception:
                logger.exception("guild_set_description error")
                embed = _err("Error", "Failed to update description.")
        await _send_ctx(ctx, embed)

    @guild.command(name="set_emblem")
    @app_commands.describe(url="Public image URL for your guild emblem")
    async def guild_set_emblem(self, ctx: commands.Context, url: str):
        """Set the guild emblem URL (leader/officer)."""
        actor_id = ctx.author.id
        async with DatabaseService.get_transaction() as session:
            try:
                g = await GuildService.set_emblem(session, actor_id=actor_id, emblem_url=url)
                embed = _ok("Emblem Updated", f"Now using: {g.emblem_url or '(none)'}")
            except InvalidOperationError as e:
                embed = _err("Cannot Update Emblem", str(e))
            except Exception:
                logger.exception("guild_set_emblem error")
                embed = _err("Error", "Failed to set emblem.")
        await _send_ctx(ctx, embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildCog(bot))
