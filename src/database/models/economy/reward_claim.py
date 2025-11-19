"""
RewardClaim Model - Idempotency Guard for Reward Distribution
==============================================================

Purpose
-------
Prevents double-claiming of rewards by tracking all reward claims with
unique constraints on (player_id, claim_type, claim_key).

This table serves as an idempotency guard for:
- Combat victory rewards (encounter_id as claim_key)
- Daily quest rewards (quest_date as claim_key)
- Token redemptions (redemption_id as claim_key)
- Drop executions (drop_timestamp as claim_key)
- Any other one-time reward distribution

Schema Design
-------------
- Composite primary key prevents duplicate claims at DB level
- Indexed by player_id for efficient player-specific queries
- Indexed by claim_type for efficient type-specific queries
- created_at timestamp for audit trail and cleanup

LUMEN 2025 COMPLIANCE
---------------------
✓ Database-level idempotency (not just application logic)
✓ ON CONFLICT DO NOTHING pattern support
✓ Efficient indexing for queries
✓ Audit trail with timestamps
✓ Supports multiple claim types via flexible schema
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Column, DateTime, Index, String, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

if TYPE_CHECKING:
    pass


class RewardClaim(Base):
    """
    Tracks all reward claims to prevent double-claiming.

    Composite Primary Key: (player_id, claim_type, claim_key)
    - Ensures each unique claim can only be recorded once
    - Enables ON CONFLICT DO NOTHING for atomic idempotency checks
    """

    __tablename__ = "reward_claims"

    # ========================================================================
    # PRIMARY KEY COMPONENTS
    # ========================================================================

    player_id = Column(
        BigInteger,
        primary_key=True,
        nullable=False,
        comment="Discord ID of player claiming reward",
    )

    claim_type = Column(
        String(50),
        primary_key=True,
        nullable=False,
        comment="Type of claim (ascension_victory, daily_quest, token_redemption, etc.)",
    )

    claim_key = Column(
        String(100),
        primary_key=True,
        nullable=False,
        comment="Unique identifier for this claim (encounter_id, quest_date, etc.)",
    )

    # ========================================================================
    # AUDIT FIELDS
    # ========================================================================

    claimed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Timestamp when reward was claimed",
    )

    # ========================================================================
    # INDEXES
    # ========================================================================

    __table_args__ = (
        # Index for player-specific queries
        Index(
            "idx_reward_claims_player",
            "player_id",
            "claimed_at",
        ),
        # Index for claim-type queries
        Index(
            "idx_reward_claims_type",
            "claim_type",
            "claimed_at",
        ),
        # Index for cleanup/retention queries
        Index(
            "idx_reward_claims_claimed_at",
            "claimed_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RewardClaim("
            f"player_id={self.player_id}, "
            f"claim_type='{self.claim_type}', "
            f"claim_key='{self.claim_key}', "
            f"claimed_at={self.claimed_at}"
            f")>"
        )
