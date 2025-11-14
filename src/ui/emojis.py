"""
Centralized emoji definitions for the Lumen RPG bot.

This module provides a single source of truth for all emojis used throughout
the bot's UI. All emojis are Unicode standard emojis for maximum compatibility.

Usage:
    from src.ui.emojis import Emojis

    message = f"{Emojis.FUSION} Fusion System"
    embed.add_field(name=f"{Emojis.LUMEES} Balance", value="1000")

Standards:
    - LES 2025 compliant
    - All emojis are Unicode (no custom Discord emojis)
    - Organized by logical category
    - SCREAMING_SNAKE_CASE naming convention
"""


class Emojis:
    """Centralized emoji constants for Lumen RPG UI."""

    # ═══════════════════════════════════════════════════════════════
    # ELEMENTS
    # ═══════════════════════════════════════════════════════════════
    INFERNAL = "🔥"
    UMBRAL = "🌑"
    EARTH = "🌍"
    TEMPEST = "🪙"
    RADIANT = "✨"
    ABYSSAL = "🌊"

    # ═══════════════════════════════════════════════════════════════
    # RESOURCES
    # ═══════════════════════════════════════════════════════════════
    LUMEES = "💰"
    AURIC_COIN = "✨"
    LUMENITE = "💎"
    ENERGY = "🪙"
    STAMINA = "💪"
    DROP_CHARGES = "💎"
    EXPERIENCE = "📈"

    # ═══════════════════════════════════════════════════════════════
    # MASTERY & PROGRESSION
    # ═══════════════════════════════════════════════════════════════
    NO_MASTERY = "⭐"
    BRONZE = "🥉"
    SILVER = "🥈"
    GOLD = "🥇"

    # ═══════════════════════════════════════════════════════════════
    # RARITY TIERS
    # ═══════════════════════════════════════════════════════════════
    COMMON = "⚪"
    UNCOMMON = "🟢"
    RARE = "🔵"
    EPIC = "🟣"
    LEGENDARY = "🟠"
    MYTHIC = "🔴"

    # ═══════════════════════════════════════════════════════════════
    # SYSTEMS & FEATURES
    # ═══════════════════════════════════════════════════════════════
    FUSION = "⚗️"
    SUMMON = "✨"
    GUILD = "🏰"
    PLAYER = "👤"
    HELP = "❓"
    LEADERBOARD = "🏆"
    TUTORIAL = "📚"
    SYSTEM = "🔧"
    EXPLORATION = "🗺️"
    ASCENSION = "🗼"
    SHRINES = "⛩️"
    DAILY = "🎁"
    MAIDEN = "🎴"
    DROP = "💎"

    # ═══════════════════════════════════════════════════════════════
    # COMBAT & STATS
    # ═══════════════════════════════════════════════════════════════
    CRITICAL = "💥"
    ATTACK = "⚔️"
    DEFENSE = "🛡️"
    HP = "❤️"
    POWER = "⚡"

    # ═══════════════════════════════════════════════════════════════
    # UI & STATUS INDICATORS
    # ═══════════════════════════════════════════════════════════════
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "📊"
    NEW = "🆕"
    NEXT = "▶️"
    BACK = "◀"
    SKIP = "⏩"
    FINISH = "✓"
    REGENERATING = "⏳"
    TIP = "💡"
    UPGRADE = "⬆️"
    REPEAT = "🔁"
    SEARCH = "🔍"
    CELEBRATION = "🎉"
    RETREAT = "🚪"
    TOKEN = "🎫"
    DATABASE = "💾"
    CLEANING = "🧹"
    TARGET = "🎯"
    RUNNING = "🏃"
    SLOW = "🐌"
    DISMISSED = "💨"
    SCROLL = "📜"
    CHAT = "💬"
    ROCKET = "🚀"
    MAILBOX = "📬"
    CHART = "💹"
    BLUE_DIAMOND = "🔷"
    PENCIL = "✏️"
    CLIPBOARD = "📋"

    # Progress indicators
    PROGRESS_EMPTY = "🔴"
    PROGRESS_LOW = "🟠"
    PROGRESS_MEDIUM = "🟡"
    PROGRESS_HIGH = "🟢"
    PROGRESS_COMPLETE = "✅"

    # ═══════════════════════════════════════════════════════════════
    # BONUSES & BUFFS
    # ═══════════════════════════════════════════════════════════════
    SHRINE_INCOME = "🏛️"
    FUSION_SUCCESS_BOOST = "🔮"
    ATTACK_BOOST = "⚔️"
    DEFENSE_BOOST = "🛡️"
    HP_BOOST = "❤️"
    ENERGY_REGEN = "🪙"
    STAMINA_REGEN = "💪"
    XP_GAIN = "📈"
    VICTORY = "🎊"
    PITY = "🌟"

    # ═══════════════════════════════════════════════════════════════
    # CATEGORIES (for relic/bonus organization)
    # ═══════════════════════════════════════════════════════════════
    CATEGORY_ECONOMY = "💰"
    CATEGORY_COMBAT = "⚔️"
    CATEGORY_PROGRESSION = "📊"
    CATEGORY_RESOURCES = "🪙"
    CATEGORY_SURVIVAL = "❤️"
