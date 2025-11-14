"""
UI Subsystem - Complete Discord UI toolkit.

Centralized UI components for Lumen RPG Discord bot.
Provides emojis, colors, themes, embeds, views, and component factories.

LUMEN LAW Compliance:
- Article V: Single source of truth for all UI elements
- Article II: Consistent branding and tone across all interactions
- Article IV: ConfigManager integration for runtime tuning

Organization:
    - emojis: Emoji constants (Emojis class)
    - colors: Color palette and context-aware color resolution
    - themes: Branding, footers, field templates
    - embeds: Embed factory with specialized builders
    - views: Reusable view base classes and specialized views
    - components: Button and select menu factories

Usage Examples:
    >>> # Emojis
    >>> from src.ui import Emojis
    >>> print(f"{Emojis.MAIDEN} Your Maidens")
    >>>
    >>> # Colors
    >>> from src.ui import ColorTheme
    >>> color = ColorTheme.get_color("element", element="infernal")
    >>>
    >>> # Themes
    >>> from src.ui import BrandingTheme
    >>> footer = BrandingTheme.get_footer("combat")
    >>>
    >>> # Embeds
    >>> from src.ui import EmbedFactory
    >>> embed = EmbedFactory.success("Victory!", "You won!")
    >>>
    >>> # Views
    >>> from src.ui import PaginatedView, ConfirmationView
    >>> view = PaginatedView(user_id, total_pages=5, page_builder=build_page)
    >>>
    >>> # Components
    >>> from src.ui import CommonButtons, CommonSelects
    >>> button = CommonButtons.view_profile()
    >>> select = CommonSelects.element_select()
"""

# ============================================================================
# CORE IMPORTS
# ============================================================================

# Emojis
from src.ui.emojis import Emojis

# Colors
from src.ui.colors import (
    ColorPalette,
    ElementColors,
    TierColors,
    ColorTheme
)

# Themes
from src.ui.themes import (
    BrandingTheme,
    FieldTemplates
)

# Embeds
from src.ui.embeds import EmbedFactory, EmbedBuilder

# Formatters
from src.ui.formatters import CombatFormatters, ProgressFormatters

# ============================================================================
# VIEWS
# ============================================================================

from src.ui.views import (
    # Base
    BaseView,
    BaseModalView,

    # Pagination
    PaginatedView,
    PaginatedListView,

    # Combat
    CombatActionView,
    CombatVictoryView,

    # Menus
    DropdownMenuView,
    ButtonMenuView,

    # Confirmation
    ConfirmationView,
    AgreementView,
    DeletionConfirmationView,

    # Modals
    NumericInputModal,
    TextInputModal,
    MultiFieldModal,
)

# ============================================================================
# COMPONENTS
# ============================================================================

from src.ui.components import (
    CommonButtons,
    CommonSelects,
)

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Emojis
    "Emojis",

    # Colors
    "ColorPalette",
    "ElementColors",
    "TierColors",
    "ColorTheme",

    # Themes
    "BrandingTheme",
    "FieldTemplates",

    # Embeds
    "EmbedFactory",
    "EmbedBuilder",  # Backward compatibility alias

    # Formatters
    "CombatFormatters",
    "ProgressFormatters",

    # Views - Base
    "BaseView",
    "BaseModalView",

    # Views - Pagination
    "PaginatedView",
    "PaginatedListView",

    # Views - Combat
    "CombatActionView",
    "CombatVictoryView",

    # Views - Menus
    "DropdownMenuView",
    "ButtonMenuView",

    # Views - Confirmation
    "ConfirmationView",
    "AgreementView",
    "DeletionConfirmationView",

    # Views - Modals
    "NumericInputModal",
    "TextInputModal",
    "MultiFieldModal",

    # Components
    "CommonButtons",
    "CommonSelects",
]
