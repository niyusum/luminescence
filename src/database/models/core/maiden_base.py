from __future__ import annotations
from typing import Optional, Dict, Any, Tuple
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSON


class MaidenBase(SQLModel, table=True):
    """
    💠 **MaidenBase** — Archetypal Maiden Definition

    Shared immutable template for all maidens of a specific archetype.
    Player-owned maidens (`Maiden` model) reference this base for
    their fundamental attributes, visual metadata, and leader effects.

    ---
    ⚖️ RIKI LAW Compliance:
        - Article I.4 → All tier, element, and rarity metadata sourced via constants
        - Article II → Indexed for query optimization (element, tier, name)
        - Article V → Supports dynamic gacha weighting and rarity schemas
        - Article IX → Schema self-validates via tier-based stat checks
    ---

    Attributes:
        id (int): Primary key.
        name (str): Unique maiden name.
        element (str): Elemental type (e.g., infernal, umbral, earth, tempest, radiant, abyssal).
        base_tier (int): Starting tier when summoned (1–12).
        base_atk (int): Base attack stat.
        base_def (int): Base defense stat.
        leader_effect (dict): Optional JSON payload for leader skill data.
        description (str): Lore or flavor text.
        image_url (str): Artwork URL for this maiden.
        rarity_weight (float): Gacha weight (lower = rarer).
        is_premium (bool): Flag indicating premium/limited availability.
    """

    __tablename__ = "maiden_bases"
    __table_args__ = (
        Index("ix_maiden_bases_name", "name", unique=True),
        Index("ix_maiden_bases_element", "element"),
        Index("ix_maiden_bases_base_tier", "base_tier"),
    )

    # ────────────────────────────────────────────────────────────────
    # Core Identity
    # ────────────────────────────────────────────────────────────────

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(String(100), nullable=False, unique=True, index=True))
    element: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    base_tier: int = Field(default=1, ge=1, le=12, index=True)

    # ────────────────────────────────────────────────────────────────
    # Core Stats
    # ────────────────────────────────────────────────────────────────

    base_atk: int = Field(default=10, ge=1)
    base_def: int = Field(default=10, ge=1)

    # ────────────────────────────────────────────────────────────────
    # Metadata & Lore
    # ────────────────────────────────────────────────────────────────

    leader_effect: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    description: str = Field(sa_column=Column(Text), nullable=False)
    image_url: str = Field(sa_column=Column(String(500)), nullable=False)

    # ────────────────────────────────────────────────────────────────
    # Gacha & Economy
    # ────────────────────────────────────────────────────────────────

    rarity_weight: float = Field(default=1.0, ge=0.0)
    is_premium: bool = Field(default=False)

    # ────────────────────────────────────────────────────────────────
    # Derived Computations
    # ────────────────────────────────────────────────────────────────

    def get_base_power(self) -> int:
        """Total intrinsic power = ATK + DEF."""
        return self.base_atk + self.base_def

    # ────────────────────────────────────────────────────────────────
    # Tier Formatting Helpers
    # ────────────────────────────────────────────────────────────────

    def get_tier_display(self) -> str:
        """Full tier display (e.g., 'Tier VII – Legendary')."""
        from src.modules.maiden.constants import Tier
        if tier_data := Tier.get(self.base_tier):
            return tier_data.display_name
        return f"Tier {self.base_tier}"

    def get_tier_short_display(self) -> str:
        """Short tier display (e.g., 'T7 Legendary')."""
        from src.modules.maiden.constants import Tier
        if tier_data := Tier.get(self.base_tier):
            return tier_data.short_display
        return f"T{self.base_tier}"

    def get_tier_color(self) -> int:
        """Discord embed color for this tier."""
        from src.modules.maiden.constants import Tier
        if tier_data := Tier.get(self.base_tier):
            return tier_data.color
        return 0x2C2D31

    def get_rarity_tier_name(self) -> str:
        """Human-readable rarity name (e.g., 'Legendary', 'Ethereal')."""
        from src.modules.maiden.constants import Tier
        if tier_data := Tier.get(self.base_tier):
            return tier_data.name
        return "Unknown"

    # ────────────────────────────────────────────────────────────────
    # Element Formatting Helpers
    # ────────────────────────────────────────────────────────────────

    def get_element_emoji(self) -> str:
        """Emoji representing this element."""
        from src.modules.maiden.constants import Element
        if element_obj := Element.from_string(self.element):
            return element_obj.emoji
        return "❓"

    def get_element_color(self) -> int:
        """Discord embed color for this element."""
        from src.modules.maiden.constants import Element
        if element_obj := Element.from_string(self.element):
            return element_obj.color
        return 0x2C2D31

    # ────────────────────────────────────────────────────────────────
    # Validation & Range Helpers
    # ────────────────────────────────────────────────────────────────

    def get_stat_range(self) -> Tuple[int, int]:
        """Expected (min, max) stat range for this tier."""
        from src.modules.maiden.constants import Tier
        if tier_data := Tier.get(self.base_tier):
            return tier_data.stat_range
        return (0, 0)

    def is_stats_valid_for_tier(self) -> bool:
        """Validate if total stats fall within tier-defined range."""
        from src.modules.maiden.constants import Tier
        if not (tier_data := Tier.get(self.base_tier)):
            return False

        total_stats = self.base_atk + self.base_def
        min_stats, max_stats = tier_data.stat_range
        return min_stats <= total_stats <= max_stats

    # ────────────────────────────────────────────────────────────────
    # Leader Skill Logic
    # ────────────────────────────────────────────────────────────────

    def has_leader_effect(self) -> bool:
        """Check if a leader effect is defined."""
        return bool(self.leader_effect and self.leader_effect.get("type"))

    # ────────────────────────────────────────────────────────────────
    # Representation
    # ────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        """Developer-facing representation."""
        return (
            f"<MaidenBase(id={self.id}, name='{self.name}', "
            f"element={self.element}, tier={self.base_tier}, "
            f"power={self.get_base_power()})>"
        )
