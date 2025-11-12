"""
Token inventory for maiden redemption.
Tokens are earned from ascension and redeemed for random maidens in tier range.

LUMEN LAW Compliance:
- Article I: Economy domain model
- Article II: Audit trail fields
- Article VII: Pure schema only, no business logic
"""

from datetime import datetime
from sqlmodel import SQLModel, Field, Column, String, DateTime, UniqueConstraint, ForeignKey


class Token(SQLModel, table=True):
    """
    Player token inventory.

    Tokens redeem for maidens in specific tier ranges.
    Pure schema — business logic in TokenService.
    """
    __tablename__ = "tokens"

    id: int = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(ForeignKey("players.discord_id"), index=True, nullable=False)
    )
    token_type: str = Field(
        sa_column=Column(String(50), index=True, nullable=False)
    )  # bronze, silver, gold, platinum, diamond
    quantity: int = Field(default=0, nullable=False)

    # Audit trail (LUMEN LAW Article II)
    created_at: datetime = Field(
        sa_column=Column(DateTime, default=datetime.utcnow, nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    )

    __table_args__ = (
        UniqueConstraint("player_id", "token_type", name="uq_player_token_type"),
    )

    def __repr__(self) -> str:
        return f"<Token(player_id={self.player_id}, type={self.token_type}, quantity={self.quantity})>"
