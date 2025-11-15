"""
Bot infrastructure and Discord integration layer for Lumen RPG.

Purpose
-------
Expose the primary bot-facing types used by the rest of the system:

- Main bot implementation (LumenBot)
- Lifecycle management and health metrics (BotLifecycle, BotMetrics, ServiceHealth, StartupMetrics)

Responsibilities
----------------
- Provide a stable import surface for bot infrastructure
- Document the high-level bot architecture and capabilities

Non-Responsibilities
--------------------
- Implement Discord events, lifecycle, or feature loading logic (handled in submodules)
- Contain any runtime logic or side effects

Design Notes
------------
- This module is intentionally thin: it only re-exports selected bot-layer types.
- Public API is explicit via __all__ to avoid leaking internal details.

Example
-------
    from src.bot import LumenBot

    bot = LumenBot()
    bot.run(...)
"""

from __future__ import annotations

from src.bot.lifecycle import BotLifecycle, BotMetrics, ServiceHealth, StartupMetrics
from src.bot.lumen_bot import LumenBot

__all__ = [
    # Main bot
    "LumenBot",
    # Lifecycle management
    "BotLifecycle",
    "BotMetrics",
    "ServiceHealth",
    "StartupMetrics",
]
