from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin

if TYPE_CHECKING:
    from .maiden import Maiden


class MaidenBase(Base, IdMixin):
    """
    Archetypal maiden definition (base template).

    Represents immutable template data shared by all maidens of this archetype.
    Player-owned maidens reference this entity via `Maiden.maiden_base_id`.

    Fields (schema only):
    - name: unique maiden name
    - element: elemental type (string key)
    - base_tier: starting tier when summoned
    - base_atk / base_def: base stats
    - leader_effect: JSON payload describing leader skill
    - description: lore / flavor text
    - image_url: artwork URL
    - rarity_weight: gacha weighting (lower = rarer)
    - is_premium: flags limited / premium availability
    """

    __tablename__ = "maiden_bases"
    __table_args__ = (
        Index("ix_maiden_bases_name", "name", unique=True),
        Index("ix_maiden_bases_element", "element"),
        Index("ix_maiden_bases_base_tier", "base_tier"),
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    element: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    base_tier: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
    )

    # Core stats
    base_atk: Mapped[int] = mapped_column(
        nullable=False,
        default=10,
    )

    base_def: Mapped[int] = mapped_column(
        nullable=False,
        default=10,
    )

    # Metadata & lore
    leader_effect: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    image_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    # Gacha & economy
    rarity_weight: Mapped[float] = mapped_column(
        nullable=False,
        default=1.0,
    )

    is_premium: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )

    # Relationships
    maidens: Mapped[List["Maiden"]] = relationship(
        "Maiden",
        back_populates="maiden_base",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

