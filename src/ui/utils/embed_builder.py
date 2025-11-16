# src/utils/embed_builder.py
"""
⚠️ DEPRECATED: This module has been moved to src.ui.embeds

This file is maintained for backward compatibility during the UI subsystem migration.
All new code should use the new location.

MIGRATION GUIDE:
    OLD: from src.utils.embed_builder import EmbedBuilder
    NEW: from src.ui.embeds import EmbedFactory

    # EmbedBuilder is now an alias for EmbedFactory
    # Both work identically, but prefer EmbedFactory for new code

Reason for deprecation:
    - LES-2025 compliance: UI components consolidated in src/ui/
    - Improved organization: All UI elements (emojis, colors, themes, embeds, views, components) in one place
    - Enhanced functionality: New specialized builders (combat_encounter, leaderboard, collection_display)
    - Better integration: Direct use of ColorTheme, BrandingTheme, FieldTemplates

Timeline:
    - Phase 1 (CURRENT): Both files work, deprecation notice added
    - Phase 2 (PLANNED): Gradual migration of cog files to new imports
    - Phase 3 (FUTURE): Remove this file after all cogs migrated

This file will be removed in a future release after all modules are migrated.
"""

# ============================================================================
# BACKWARD COMPATIBILITY LAYER
# ============================================================================

from src.ui.embeds import EmbedFactory

# Alias for backward compatibility
EmbedBuilder = EmbedFactory
