"""
Transaction Service - Business logic for transaction log queries.

RIKI LAW Compliance:
- Article VII: Service layer separation (no Discord logic)
- Article I: Transaction-safe operations
- Article II: Audit trail integration
"""

from typing import List
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.economy import TransactionLog
from src.core.bot.base_service import BaseService


class TransactionService(BaseService):
    """
    Service for querying transaction logs.

    Provides methods to retrieve transaction history for players,
    abstracting database queries from the presentation layer.
    """

    @staticmethod
    async def get_recent_transactions(
        session: AsyncSession,
        player_id: int,
        limit: int = 10,
        transaction_filter: str = "resource_%"
    ) -> List[TransactionLog]:
        """
        Get recent transaction logs for a player.

        Args:
            session: Database session
            player_id: Player's Discord ID
            limit: Maximum number of transactions to return (1-20)
            transaction_filter: SQL LIKE filter for transaction types

        Returns:
            List of TransactionLog objects, ordered by timestamp descending

        Example:
            >>> logs = await TransactionService.get_recent_transactions(
            ...     session, user_id, limit=10
            ... )
        """
        # Validate limit
        limit = max(1, min(limit, 20))

        # Query transactions
        result = await session.execute(
            select(TransactionLog)
            .where(TransactionLog.player_id == player_id)
            .where(TransactionLog.transaction_type.like(transaction_filter))
            .order_by(desc(TransactionLog.timestamp))
            .limit(limit)
        )

        return list(result.scalars().all())

    @staticmethod
    async def get_all_recent_transactions(
        session: AsyncSession,
        player_id: int,
        limit: int = 10
    ) -> List[TransactionLog]:
        """
        Get recent transaction logs of ALL types for a player.

        Args:
            session: Database session
            player_id: Player's Discord ID
            limit: Maximum number of transactions to return (1-50)

        Returns:
            List of TransactionLog objects, ordered by timestamp descending
        """
        # Validate limit
        limit = max(1, min(limit, 50))

        # Query all transactions
        result = await session.execute(
            select(TransactionLog)
            .where(TransactionLog.player_id == player_id)
            .order_by(desc(TransactionLog.timestamp))
            .limit(limit)
        )

        return list(result.scalars().all())
