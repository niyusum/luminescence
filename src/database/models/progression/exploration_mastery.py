"""
Exploration mastery tracking for sector completion and progression.

Each sector has 3 mastery ranks that can be completed sequentially.
Completing each rank grants permanent stat bonuses via mastery items.
Players must complete Rank 1 before Rank 2, and Rank 2 before Rank 3.

LUMEN LAW Compliance:
- Article I: Core domain model with proper indexing
- Article II: Complete audit trail (created_at, updated_at, completion timestamps)
- Article IV: Tunable rank requirements via ConfigManager
- Article VII: Business logic in ExplorationMasteryService, not model

Features:
- 3-tier mastery system per sector
- Sequential rank completion (must complete in order)
- Timestamp tracking for each rank completion
- Helper methods for rank checking and progression
- Unique constraint per player-sector combination
- Performance indexes for leaderboards and queries

Database Design:
- One row per player-sector combination
- Boolean flags for completion status
- Timestamps for audit trail and analytics
- Composite unique constraint prevents duplicates
"""

from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index, UniqueConstraint, DateTime
from datetime import datetime


class ExplorationMastery(SQLModel, table=True):
    """
    Exploration mastery progression tracking for exploration sectors.
    
    Each sector can be completed in 3 mastery ranks (Rank 1, 2, 3).
    Ranks must be completed sequentially - Rank 2 requires Rank 1, etc.
    Each rank completion grants permanent stat bonuses via mastery items.
    
    Attributes:
        id: Primary key
        player_id: Foreign key to players.discord_id
        sector_id: Sector identifier (1-N)
        rank_1_complete: Rank 1 completion status
        rank_2_complete: Rank 2 completion status
        rank_3_complete: Rank 3 completion status
        rank_1_completed_at: Timestamp of Rank 1 completion
        rank_2_completed_at: Timestamp of Rank 2 completion
        rank_3_completed_at: Timestamp of Rank 3 completion
        created_at: Record creation timestamp
        updated_at: Record last update timestamp
    
    Indexes:
        - player_id (for player queries)
        - sector_id (for sector leaderboards)
        - rank_1_complete, rank_2_complete, rank_3_complete (completion queries)
        - Unique constraint on (player_id, sector_id)
    
    Example Usage:
        >>> mastery = ExplorationMastery(player_id=123456789, sector_id=5)
        >>> mastery.get_current_rank()  # Returns 0 (no ranks complete)
        >>> mastery.rank_1_complete = True
        >>> mastery.get_current_rank()  # Returns 1
        >>> mastery.get_next_rank()  # Returns 2
        >>> mastery.is_fully_mastered()  # Returns False
    """
    
    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================
    
    __tablename__ = "exploration_mastery"
    __table_args__ = (
        UniqueConstraint("player_id", "sector_id", name="uq_player_sector_exploration_mastery"),
        Index("ix_exploration_mastery_player", "player_id"),
        Index("ix_exploration_mastery_sector", "sector_id"),
        Index("ix_exploration_mastery_rank1", "rank_1_complete"),
        Index("ix_exploration_mastery_rank2", "rank_2_complete"),
        Index("ix_exploration_mastery_rank3", "rank_3_complete"),
        Index("ix_exploration_mastery_player_sector", "player_id", "sector_id"),  # Composite lookup
    )
    
    # ========================================================================
    # PRIMARY KEY & FOREIGN KEYS
    # ========================================================================
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    sector_id: int = Field(ge=1, nullable=False, index=True)
    
    # ========================================================================
    # MASTERY RANKS (BOOLEAN FLAGS)
    # ========================================================================
    
    rank_1_complete: bool = Field(default=False, nullable=False, index=True)
    rank_2_complete: bool = Field(default=False, nullable=False, index=True)
    rank_3_complete: bool = Field(default=False, nullable=False, index=True)
    
    # ========================================================================
    # COMPLETION TIMESTAMPS (AUDIT TRAIL)
    # ========================================================================
    
    rank_1_completed_at: Optional[datetime] = Field(default=None)
    rank_2_completed_at: Optional[datetime] = Field(default=None)
    rank_3_completed_at: Optional[datetime] = Field(default=None)
    
    # ========================================================================
    # RECORD TIMESTAMPS
    # ========================================================================
    
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.utcnow}
    )
    
    # ========================================================================
    # RANK CHECKING METHODS
    # ========================================================================
    
    def get_current_rank(self) -> int:
        """
        Get highest completed rank.
        
        Returns:
            Integer from 0-3:
                0 = No ranks complete
                1 = Rank 1 complete
                2 = Rank 2 complete
                3 = All ranks complete (fully mastered)
        
        Example:
            >>> mastery.rank_1_complete = True
            >>> mastery.rank_2_complete = True
            >>> mastery.get_current_rank()
            2
        """
        if self.rank_3_complete:
            return 3
        elif self.rank_2_complete:
            return 2
        elif self.rank_1_complete:
            return 1
        else:
            return 0
    
    def get_next_rank(self) -> Optional[int]:
        """
        Get next incomplete rank that can be attempted.
        
        Returns:
            Integer 1-3 for next rank, or None if all ranks complete
        
        Example:
            >>> mastery.rank_1_complete = True
            >>> mastery.get_next_rank()
            2
            >>> mastery.rank_3_complete = True  # All complete
            >>> mastery.get_next_rank()
            None
        """
        current = self.get_current_rank()
        if current < 3:
            return current + 1
        return None
    
    def is_fully_mastered(self) -> bool:
        """
        Check if all 3 ranks are complete.
        
        Returns:
            True if all ranks complete, False otherwise
        
        Example:
            >>> mastery.rank_1_complete = True
            >>> mastery.rank_2_complete = True
            >>> mastery.rank_3_complete = True
            >>> mastery.is_fully_mastered()
            True
        """
        return self.rank_1_complete and self.rank_2_complete and self.rank_3_complete
    
    def can_attempt_rank(self, rank: int) -> bool:
        """
        Check if player can attempt specific rank.
        
        Ranks must be completed sequentially:
        - Rank 1: Always available if not complete
        - Rank 2: Requires Rank 1 complete
        - Rank 3: Requires Rank 2 complete
        
        Args:
            rank: Rank to check (1-3)
        
        Returns:
            True if rank can be attempted, False otherwise
        
        Raises:
            ValueError: If rank not in range 1-3
        
        Example:
            >>> mastery.rank_1_complete = True
            >>> mastery.can_attempt_rank(1)  # Already complete
            False
            >>> mastery.can_attempt_rank(2)  # Rank 1 done, can do Rank 2
            True
            >>> mastery.can_attempt_rank(3)  # Rank 2 not done yet
            False
        """
        if rank not in (1, 2, 3):
            raise ValueError(f"Rank must be 1-3, got {rank}")
        
        if rank == 1:
            return not self.rank_1_complete
        elif rank == 2:
            return self.rank_1_complete and not self.rank_2_complete
        elif rank == 3:
            return self.rank_2_complete and not self.rank_3_complete
        
        return False
    
    def get_completion_progress(self) -> float:
        """
        Get mastery completion progress as percentage.
        
        Returns:
            Float from 0.0 to 100.0 representing completion percentage
        
        Example:
            >>> mastery.rank_1_complete = True
            >>> mastery.get_completion_progress()
            33.33
            >>> mastery.rank_2_complete = True
            >>> mastery.get_completion_progress()
            66.67
        """
        completed_ranks = sum([
            self.rank_1_complete,
            self.rank_2_complete,
            self.rank_3_complete
        ])
        return (completed_ranks / 3.0) * 100.0
    
    # ========================================================================
    # DISPLAY METHODS (FOR DISCORD EMBEDS)
    # ========================================================================
    
    def get_rank_display(self) -> str:
        """
        Format rank progress for Discord embeds.
        
        Returns:
            String with emoji indicators for each rank
        
        Example:
            >>> mastery.rank_1_complete = True
            >>> mastery.rank_2_complete = True
            >>> mastery.get_rank_display()
            "✅ Rank 1 | ✅ Rank 2 | ❌ Rank 3"
        """
        rank_1_icon = "✅" if self.rank_1_complete else "❌"
        rank_2_icon = "✅" if self.rank_2_complete else "❌"
        rank_3_icon = "✅" if self.rank_3_complete else "❌"
        
        return f"{rank_1_icon} Rank 1 | {rank_2_icon} Rank 2 | {rank_3_icon} Rank 3"
    
    def get_mastery_badge(self) -> str:
        """
        Get mastery badge emoji based on completion.
        
        Returns:
            Emoji string representing mastery level:
                - 🥉 Bronze (Rank 1)
                - 🥈 Silver (Rank 2)
                - 🥇 Gold (Rank 3 - fully mastered)
                - ⭐ None (no ranks complete)
        
        Example:
            >>> mastery.rank_1_complete = True
            >>> mastery.get_mastery_badge()
            "🥉"
        """
        current_rank = self.get_current_rank()
        
        if current_rank == 3:
            return "🥇"  # Gold - fully mastered
        elif current_rank == 2:
            return "🥈"  # Silver
        elif current_rank == 1:
            return "🥉"  # Bronze
        else:
            return "⭐"  # No mastery
    
    def get_time_to_complete_rank(self, rank: int) -> Optional[str]:
        """
        Get formatted time taken to complete specific rank.
        
        Calculates time between rank completions:
        - Rank 1: created_at → rank_1_completed_at
        - Rank 2: rank_1_completed_at → rank_2_completed_at
        - Rank 3: rank_2_completed_at → rank_3_completed_at
        
        Args:
            rank: Rank to check (1-3)
        
        Returns:
            Formatted string like "2d 5h 30m" or None if not complete
        
        Example:
            >>> mastery.get_time_to_complete_rank(1)
            "1d 3h 45m"
        """
        if rank == 1 and self.rank_1_completed_at:
            delta = self.rank_1_completed_at - self.created_at
        elif rank == 2 and self.rank_2_completed_at and self.rank_1_completed_at:
            delta = self.rank_2_completed_at - self.rank_1_completed_at
        elif rank == 3 and self.rank_3_completed_at and self.rank_2_completed_at:
            delta = self.rank_3_completed_at - self.rank_2_completed_at
        else:
            return None
        
        # Format timedelta
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    # ========================================================================
    # REPR
    # ========================================================================
    
    def __repr__(self) -> str:
        return (
            f"<ExplorationMastery(player_id={self.player_id}, "
            f"sector={self.sector_id}, rank={self.get_current_rank()}/3)>"
        )