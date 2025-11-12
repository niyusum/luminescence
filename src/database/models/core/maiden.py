from __future__ import annotations
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index, String, UniqueConstraint


class Maiden(SQLModel, table=True):
    """
    🩸 Player-Owned Maiden Instance

    Represents a specific *tiered instance* of a maiden base owned by a player.
    Multiple maidens of the same (base + tier) are stacked in one record via
    the `quantity` field.

    ---
    ⚖️ LUMEN LAW Compliance:
        - Article I.4  → Dynamic references via Tier/Element constants
        - Article II   → Indexed by ownership, tier, and fusion state
        - Article III  → No hard-coded display or color values
        - Article IX   → Schema-level audit fields (`acquired_at`, `last_modified`)
    ---

    Attributes:
        id (int): Unique internal identifier.
        player_id (int): Discord ID of the owning player.
        maiden_base_id (int): FK to `maiden_bases.id` (base template).
        quantity (int): Stack count of this base-tier combination.
        tier (int): Upgrade level, ranging from 1 to 12.
        element (str): Elemental affinity (e.g., "fire", "water", etc.).
        acquired_at (datetime): Timestamp when maiden was obtained.
        last_modified (datetime): Timestamp when record was last modified.
        acquired_from (str): Source tag (e.g., "summon", "fusion", "event").
        times_fused (int): Number of times this maiden participated in fusion.
    """

    __tablename__ = "maidens"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "maiden_base_id",
            "tier",
            name="uq_player_maiden_tier"
        ),
        Index("ix_maidens_player_id", "player_id"),
        Index("ix_maidens_base_id", "maiden_base_id"),
        Index("ix_maidens_tier", "tier"),
        Index("ix_maidens_element", "element"),
        Index("ix_maidens_fusable", "player_id", "tier", "quantity"),
    )

    # ────────────────────────────────────────────────────────────────
    # Core Fields
    # ────────────────────────────────────────────────────────────────

    id: Optional[int] = Field(default=None, primary_key=True)

    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )

    maiden_base_id: int = Field(
        foreign_key="maiden_bases.id",
        nullable=False,
        index=True
    )

    quantity: int = Field(
        default=1,
        ge=0,
        sa_column=Column(BigInteger)
    )

    tier: int = Field(
        default=1,
        ge=1,
        le=12,
        index=True
    )

    element: str = Field(
        sa_column=Column(String(20), nullable=False, index=True)
    )

    # ────────────────────────────────────────────────────────────────
    # Metadata Fields
    # ────────────────────────────────────────────────────────────────

    acquired_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_modified: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    acquired_from: str = Field(default="summon", max_length=50)
    times_fused: int = Field(default=0, ge=0)
    is_locked: bool = Field(default=False)

    # ────────────────────────────────────────────────────────────────
    # Tier Display Helpers
    # ────────────────────────────────────────────────────────────────

    def get_tier_display(self) -> str:
        """Full display (e.g., 'Tier VII – Legendary')."""
        from src.modules.maiden.constants import Tier

        if tier_data := Tier.get(self.tier):
            return tier_data.display_name
        return f"Tier {self.tier}"

    def get_tier_short_display(self) -> str:
        """Short display (e.g., 'T7 Legendary')."""
        from src.modules.maiden.constants import Tier

        if tier_data := Tier.get(self.tier):
            return tier_data.short_display
        return f"T{self.tier}"

    def get_tier_name(self) -> str:
        """Tier name only (e.g., 'Legendary')."""
        from src.modules.maiden.constants import Tier

        if tier_data := Tier.get(self.tier):
            return tier_data.name
        return "Unknown"

    def get_tier_color(self) -> int:
        """Discord embed color for this tier."""
        from src.modules.maiden.constants import Tier

        if tier_data := Tier.get(self.tier):
            return tier_data.color
        return 0x2C2D31  # Default neutral embed color

    # ────────────────────────────────────────────────────────────────
    # Element Display Helpers
    # ────────────────────────────────────────────────────────────────

    def get_element_emoji(self) -> str:
        """Emoji representing this maiden's element."""
        from src.modules.maiden.constants import Element

        if element := Element.from_string(self.element):
            return element.emoji
        return "❓"

    def get_element_color(self) -> int:
        """Discord embed color for this element."""
        from src.modules.maiden.constants import Element

        if element := Element.from_string(self.element):
            return element.color
        return 0x2C2D31

    # ────────────────────────────────────────────────────────────────
    # Functional Helpers
    # ────────────────────────────────────────────────────────────────

    def get_stack_display(self) -> str:
        """Human-readable display with quantity (e.g., 'Tier VII – Legendary ×5')."""
        base_display = self.get_tier_display()

        if self.quantity == 0:
            return f"{base_display} (Used)"
        if self.quantity == 1:
            return base_display
        return f"{base_display} ×{self.quantity:,}"

    def can_fuse(self) -> bool:
        """Whether this maiden can be fused (≥2 copies and < max tier)."""
        return self.quantity >= 2 and self.tier < 12

    def update_modification_time(self) -> None:
        """Update `last_modified` to the current UTC time."""
        self.last_modified = datetime.utcnow()

    # ────────────────────────────────────────────────────────────────
    # Representation
    # ────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        """Developer-facing representation."""
        return (
            f"<Maiden(id={self.id}, player={self.player_id}, "
            f"base={self.maiden_base_id}, T{self.tier}, qty={self.quantity})>"
        )
