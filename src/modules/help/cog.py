"""
Interactive help system with module-based command discovery.

Provides a Discord UI for browsing available commands organized by module/cog,
with automatic command discovery and examples.

LUMEN LAW Compliance:
- Article VI: Discord layer only
- Article VII: No business logic, pure UI/documentation
"""

import discord
from discord.ext import commands
from typing import Dict, Optional
import time

from src.core.bot.base_cog import BaseCog
from src.core.config.config_manager import ConfigManager
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder


class HelpCog(BaseCog):
    """
    Interactive help system with module-based command discovery.

    Automatically discovers commands from all loaded cogs and organizes
    them by module for easy browsing via dropdown interface.
    """

    # Module display names and descriptions
    MODULE_INFO = {
        "PlayerCog": {
            "name": "👤 Account & Profile",
            "icon": "👤",
            "description": "Player registration, profiles, and account management"
        },
        "DailyCog": {
            "name": "🎁 Daily Rewards",
            "icon": "🎁",
            "description": "Daily login rewards and streaks"
        },
        "DropCog": {
            "name": "🪙 Resources",
            "icon": "🪙",
            "description": "Drop auric coin and manage resources"
        },
        "SummonCog": {
            "name": "✨ Summoning",
            "icon": "✨",
            "description": "Summon maidens using auric coin"
        },
        "MaidenCog": {
            "name": "🎴 Maiden Collection",
            "icon": "🎴",
            "description": "View and manage your maiden collection"
        },
        "FusionCog": {
            "name": "⚗️ Fusion",
            "icon": "⚗️",
            "description": "Fuse maidens to increase their tier"
        },
        "GuildCog": {
            "name": "🏰 Guilds",
            "icon": "🏰",
            "description": "Create and manage guilds with other players"
        },
        "ExplorationCog": {
            "name": "🗺️ Exploration",
            "icon": "🗺️",
            "description": "Explore sectors and gain mastery rewards"
        },
        "AscensionCog": {
            "name": "🗼 Ascension Tower",
            "icon": "🗼",
            "description": "Climb the infinite tower and collect tokens"
        },
        "ShrineCog": {
            "name": "⛩️ Shrines",
            "icon": "⛩️",
            "description": "Manage personal shrines for passive income"
        },
        "LeaderboardCog": {
            "name": "🏆 Leaderboards",
            "icon": "🏆",
            "description": "View global rankings and your position"
        },
        "TutorialCog": {
            "name": "📚 Tutorial",
            "icon": "📚",
            "description": "View tutorial progress and earn rewards"
        },
        "SystemTasksCog": {
            "name": "🔧 System",
            "icon": "🔧",
            "description": "System administration and maintenance (Admin only)"
        },
        "HelpCog": {
            "name": "❓ Help",
            "icon": "❓",
            "description": "This help system"
        }
    }

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, self.__class__.__name__)
        self.bot = bot

    @commands.command(
        name="help",
        aliases=["h", "commands"],
        description="View all available commands organized by module",
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.help.main.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.help.main.period", 60),
        command_name="help"
    )
    async def help(self, ctx: commands.Context, *, query: Optional[str] = None):
        """Display interactive help menu or search for specific command."""
        start_time = time.perf_counter()
        await ctx.defer(ephemeral=True)

        try:
            if query:
                await self._show_command_help(ctx, query)
            else:
                await self._show_main_help(ctx)

            # Log successful execution
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "help",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                query=query
            )

        except Exception as e:
            # Standardized error handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "help",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                query=query
            )

            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Help System Error",
                    "Unable to load help information.",
                    help_text="Please try again shortly."
                )

    async def _show_main_help(self, ctx: commands.Context):
        """Show main help menu with module selector."""
        # Count visible commands
        visible_cmds = [c for c in self.bot.commands if not c.hidden]

        embed = discord.Embed(
            title="🎮 Lumen RPG - Command Help",
            description=(
                "Welcome to **Lumen RPG**! Collect and empower maidens through "
                "drops, fusions, exploration, and guild activities.\n\n"
                "**Select a module below** to view all commands in that category."
            ),
            color=0x5865F2,  # Discord Blurple
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="📊 Available Commands",
            value=f"**{len(visible_cmds)}** commands across **{len(self.bot.cogs)}** modules",
            inline=False,
        )

        embed.add_field(
            name="💡 Quick Start",
            value=(
                "1️⃣ `;register` to create your account\n"
                "2️⃣ `;drop` to gain auric coin\n"
                "3️⃣ `;summon` to collect maidens\n"
                "4️⃣ `;fusion` to upgrade them\n"
                "5️⃣ `;tutorial` to track your progress"
            ),
            inline=True,
        )

        embed.add_field(
            name="🔍 Command Usage",
            value=(
                "• All commands use `;` prefix\n"
                "• Example: `;summon`, `;charge`, `;guild`\n"
                "• Use `;help <command>` for details\n"
                "• Many commands have short aliases!"
            ),
            inline=True,
        )

        embed.set_footer(
            text="Use the dropdown menu below to browse commands by module"
        )

        # Create module selector view
        view = ModuleSelectorView(ctx.author.id, self.bot, self.MODULE_INFO)
        message = await ctx.send(embed=embed, view=view, ephemeral=True)
        view.message = message

    async def _show_command_help(self, ctx: commands.Context, query: str):
        """Show help for specific command or search results."""
        query_lower = query.lower()

        # Try exact match first
        cmd = self.bot.get_command(query_lower)

        if cmd and not cmd.hidden:
            await self._show_single_command(ctx, cmd)
            return

        # Search for partial matches
        matches = []
        for command in self.bot.commands:
            if command.hidden:
                continue

            # Check name and aliases
            if query_lower in command.name.lower():
                matches.append(command)
            elif any(query_lower in alias.lower() for alias in command.aliases):
                matches.append(command)

        if not matches:
            embed = EmbedBuilder.error(
                title="Command Not Found",
                description=f"No command matching `{query}` was found.",
                help_text="Use `;help` to see all available commands."
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        if len(matches) == 1:
            await self._show_single_command(ctx, matches[0])
        else:
            # Show search results
            embed = discord.Embed(
                title=f"🔍 Search Results for '{query}'",
                description=f"Found **{len(matches)}** matching commands:",
                color=0x5865F2,
                timestamp=discord.utils.utcnow()
            )

            for cmd in matches[:10]:  # Limit to 10 results
                aliases_str = f" (aliases: {', '.join(f'`{a}`' for a in cmd.aliases)})" if cmd.aliases else ""
                embed.add_field(
                    name=f"`;{cmd.name}`{aliases_str}",
                    value=cmd.description or "No description available.",
                    inline=False
                )

            if len(matches) > 10:
                embed.set_footer(text=f"Showing first 10 of {len(matches)} results")

            await ctx.send(embed=embed, ephemeral=True)

    async def _show_single_command(self, ctx: commands.Context, cmd: commands.Command):
        """Show detailed help for a single command."""
        embed = discord.Embed(
            title=f"`;{cmd.name}`",
            description=cmd.description or "No description available.",
            color=0x5865F2,
            timestamp=discord.utils.utcnow()
        )

        # Aliases
        if cmd.aliases:
            alias_str = ", ".join(f"`;{alias}`" for alias in cmd.aliases)
            embed.add_field(
                name="📝 Aliases",
                value=alias_str,
                inline=False
            )

        # Usage pattern
        params = []
        for name, param in cmd.clean_params.items():
            if param.default == param.empty:
                params.append(f"<{name}>")
            else:
                params.append(f"[{name}]")

        usage = f"`;{cmd.name} {' '.join(params)}`"
        embed.add_field(
            name="💻 Usage",
            value=usage,
            inline=False
        )

        # Examples for specific commands
        examples = {
            "summon": "`;summon 5` — Summon 5 maidens at once\n`;summon` — Summon a single maiden",
            "drop": "`;drop` — Charge auric coin (1 drop charge)\n`;d` — Quick alias for charge",
            "fusion": "`;fusion` — Open the fusion interface",
            "explore": "`;explore` — Open exploration interface with Venture & Mastery buttons\n`;explore 1 1` — Directly explore Sector 1, Sublevel 1\n`;e` — Quick alias",
            "mastery": "`;mastery` — View all mastery progress\n`;mastery 1` — View Sector 1 mastery details",
            "guild": "`;guild` — Show guild menu\n`;g` — Quick alias\n`;guild create MyGuild` — Create a guild",
            "top": "`;top` — Show leaderboard menu\n`;top power` — View power rankings",
            "register": "`;register` — Register your Lumen RPG account\n`;reg` — Quick alias",
        }

        if cmd.name in examples:
            embed.add_field(
                name="💡 Examples",
                value=examples[cmd.name],
                inline=False
            )

        # Show parent command if it's a subcommand
        if hasattr(cmd, 'parent') and cmd.parent:
            embed.add_field(
                name="📂 Parent Command",
                value=f"`;{cmd.parent.name}`",
                inline=True
            )

        # Show subcommands if it's a group
        if isinstance(cmd, commands.Group):
            subcommands = [c for c in cmd.commands if not c.hidden]
            if subcommands:
                sub_list = ", ".join(f"`;{cmd.name} {c.name}`" for c in subcommands[:5])
                if len(subcommands) > 5:
                    sub_list += f" ... (+{len(subcommands) - 5} more)"
                embed.add_field(
                    name="📋 Subcommands",
                    value=sub_list,
                    inline=False
                )

        embed.set_footer(text="Use ;help to see all commands")
        await ctx.send(embed=embed, ephemeral=True)


class ModuleSelectorView(discord.ui.View):
    """Dropdown view for selecting a module to view its commands."""

    def __init__(self, user_id: int, bot: commands.Bot, module_info: Dict):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.bot = bot
        self.module_info = module_info
        self.message: Optional[discord.Message] = None

        # Add the dropdown
        self.add_item(ModuleSelectDropdown(user_id, bot, module_info))

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            item.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class ModuleSelectDropdown(discord.ui.Select):
    """Dropdown for selecting which module's commands to view."""

    def __init__(self, user_id: int, bot: commands.Bot, module_info: Dict):
        self.user_id = user_id
        self.bot = bot
        self.module_info = module_info

        # Build options from loaded cogs
        options = []
        for cog_name, cog in sorted(bot.cogs.items()):
            # Skip internal/hidden cogs
            if cog_name.startswith("_"):
                continue

            # Get module info or use defaults
            info = module_info.get(cog_name, {
                "name": cog_name.replace("Cog", ""),
                "icon": "📦",
                "description": "No description available"
            })

            # Count commands in this cog
            cog_commands = [c for c in cog.get_commands() if not c.hidden]
            if not cog_commands:
                continue  # Skip empty cogs

            options.append(discord.SelectOption(
                label=info["name"],
                value=cog_name,
                description=f"{len(cog_commands)} commands - {info['description'][:50]}",
                emoji=info["icon"]
            ))

        super().__init__(
            placeholder="📂 Select a module to view its commands...",
            min_values=1,
            max_values=1,
            options=options[:25],  # Discord limit
            custom_id="module_select"
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle module selection."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This menu is not for you!",
                ephemeral=True
            )
            return

        cog_name = self.values[0]
        cog = self.bot.get_cog(cog_name)

        if not cog:
            await interaction.response.send_message(
                "Module not found!",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Get module info
        info = self.module_info.get(cog_name, {
            "name": cog_name.replace("Cog", ""),
            "icon": "📦",
            "description": "No description available"
        })

        # Build embed with all commands in this module
        embed = discord.Embed(
            title=f"{info['icon']} {info['name']}",
            description=info['description'],
            color=0x5865F2,
            timestamp=discord.utils.utcnow()
        )

        # Get all commands from this cog
        commands_list = [c for c in cog.get_commands() if not c.hidden]

        # Organize by command groups
        standalone = []
        groups = {}

        for cmd in commands_list:
            if isinstance(cmd, commands.Group):
                # It's a group - list it with its subcommands
                subcommands = [c for c in cmd.commands if not c.hidden]
                groups[cmd.name] = {
                    "cmd": cmd,
                    "subcommands": subcommands
                }
            elif not hasattr(cmd, 'parent') or cmd.parent is None:
                # Standalone command
                standalone.append(cmd)

        # Add standalone commands
        if standalone:
            lines = []
            for cmd in standalone:
                aliases = f" (aliases: {', '.join(f'`{a}`' for a in cmd.aliases)})" if cmd.aliases else ""
                desc = cmd.description[:60] + "..." if len(cmd.description or "") > 60 else (cmd.description or "")
                lines.append(f"**`;{cmd.name}`**{aliases}\n└ {desc}")

            embed.add_field(
                name="📌 Commands",
                value="\n\n".join(lines),
                inline=False
            )

        # Add command groups
        for _, group_data in groups.items():
            cmd = group_data["cmd"]
            subcommands = group_data["subcommands"]

            lines = [f"*{cmd.description or 'No description'}*\n"]
            for subcmd in subcommands[:10]:  # Limit subcommands shown
                lines.append(f"• `;{cmd.name} {subcmd.name}` - {subcmd.description or 'No description'}")

            if len(subcommands) > 10:
                lines.append(f"*... and {len(subcommands) - 10} more subcommands*")

            embed.add_field(
                name=f"📂 `;{cmd.name}` Command Group",
                value="\n".join(lines),
                inline=False
            )

        embed.set_footer(
            text=f"{len(commands_list)} total commands • Use ;help <command> for details"
        )

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
