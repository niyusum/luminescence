"""
TransactionLogService - Business logic for economy audit logging
=================================================================

Handles:
- Automatic transaction log creation for all economy events
- Transaction categorization and tagging
- Sensitive data filtering (prevents logging secrets)
- Log retention and cleanup
- Query operations for transaction history

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Immutable audit trail (no updates, only creates)
- Config-driven retention policies
- Event-driven log creation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import delete, desc, select

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import ValidationError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.economy.transaction_log import TransactionLog

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class TransactionLogService(BaseService):
    """
    TransactionLogService handles all economy transaction logging.

    Business Logic:
    - All significant economy actions are logged immutably
    - Sensitive fields (passwords, tokens) are filtered out
    - Logs categorized by transaction type (earn, spend, transfer, etc.)
    - Retention policy: old logs auto-deleted after configured period
    - Query operations provide full audit trail access
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize TransactionLogService with TransactionLog repository."""
        super().__init__(config_manager, event_bus, logger)
        self._log_repo = BaseRepository[TransactionLog](TransactionLog, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def log_transaction(
        self,
        player_id: int,
        transaction_type: str,
        details: Dict[str, Any],
        context: str,
    ) -> Dict[str, Any]:
        """
        Create an immutable transaction log entry.

        Args:
            player_id: Discord ID of player
            transaction_type: Type of transaction (e.g., 'earn', 'spend', 'transfer')
            details: Transaction details (will be filtered for sensitive data)
            context: Context string (e.g., 'daily_quest_reward', 'shrine_collection')

        Returns:
            Dict with log entry ID and timestamp

        Raises:
            ValidationError: Invalid parameters
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        transaction_type = InputValidator.validate_string(
            transaction_type, "transaction_type", min_length=1
        )
        context = InputValidator.validate_string(context, "context", min_length=1)

        # Filter sensitive data from details
        filtered_details = self._filter_sensitive_data(details)

        async with DatabaseService.get_transaction() as session:
            # Create log entry (immutable - no updates allowed)
            log_entry = TransactionLog(
                player_id=player_id,
                transaction_type=transaction_type,
                details=filtered_details,
                context=context,
                timestamp=datetime.now(timezone.utc),
            )

            session.add(log_entry)
            await session.flush()

            return {
                "log_id": log_entry.id,
                "player_id": player_id,
                "transaction_type": transaction_type,
                "context": context,
                "timestamp": log_entry.timestamp,
            }

    async def log_currency_earn(
        self,
        player_id: int,
        currency_type: str,
        amount: int,
        source: str,
        context: str,
        additional_details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Log a currency earning transaction.

        Args:
            player_id: Discord ID of player
            currency_type: Type of currency (e.g., 'lumees', 'premium_currency')
            amount: Amount earned
            source: Source of earning (e.g., 'daily_quest', 'ascension_floor_10')
            context: Operation context
            additional_details: Optional additional details to log

        Returns:
            Dict with log entry info
        """
        details = {
            "currency_type": currency_type,
            "amount": amount,
            "source": source,
            **(additional_details or {}),
        }

        return await self.log_transaction(
            player_id=player_id,
            transaction_type="earn",
            details=details,
            context=context,
        )

    async def log_currency_spend(
        self,
        player_id: int,
        currency_type: str,
        amount: int,
        purpose: str,
        context: str,
        additional_details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Log a currency spending transaction.

        Args:
            player_id: Discord ID of player
            currency_type: Type of currency
            amount: Amount spent
            purpose: Purpose of spending (e.g., 'maiden_upgrade', 'shrine_purchase')
            context: Operation context
            additional_details: Optional additional details to log

        Returns:
            Dict with log entry info
        """
        details = {
            "currency_type": currency_type,
            "amount": amount,
            "purpose": purpose,
            **(additional_details or {}),
        }

        return await self.log_transaction(
            player_id=player_id,
            transaction_type="spend",
            details=details,
            context=context,
        )

    async def log_currency_transfer(
        self,
        from_player_id: int,
        to_player_id: int,
        currency_type: str,
        amount: int,
        reason: str,
        context: str,
        additional_details: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Log a currency transfer between players (creates 2 log entries).

        Args:
            from_player_id: Discord ID of sender
            to_player_id: Discord ID of receiver
            currency_type: Type of currency
            amount: Amount transferred
            reason: Reason for transfer
            context: Operation context
            additional_details: Optional additional details to log

        Returns:
            List of 2 log entry dicts (sender and receiver)
        """
        base_details = {
            "currency_type": currency_type,
            "amount": amount,
            "reason": reason,
            **(additional_details or {}),
        }

        # Log for sender (debit)
        sender_details = {**base_details, "counterparty_id": to_player_id, "direction": "outgoing"}
        sender_log = await self.log_transaction(
            player_id=from_player_id,
            transaction_type="transfer",
            details=sender_details,
            context=context,
        )

        # Log for receiver (credit)
        receiver_details = {
            **base_details,
            "counterparty_id": from_player_id,
            "direction": "incoming",
        }
        receiver_log = await self.log_transaction(
            player_id=to_player_id,
            transaction_type="transfer",
            details=receiver_details,
            context=context,
        )

        return [sender_log, receiver_log]

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    async def get_player_transaction_history(
        self,
        player_id: int,
        transaction_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get transaction history for a player.

        Args:
            player_id: Discord ID of player
            transaction_type: Optional filter by transaction type
            limit: Maximum number of records to return
            offset: Number of records to skip
            start_date: Optional start date filter
            end_date: Optional end date filter
            context: Operation context

        Returns:
            Dict with transaction history and pagination info
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        limit = min(limit, 1000)  # Cap at 1000 to prevent abuse

        async with DatabaseService.get_transaction() as session:
            # Build query conditions
            conditions = [TransactionLog.player_id == player_id]

            if transaction_type:
                conditions.append(TransactionLog.transaction_type == transaction_type)

            if start_date:
                conditions.append(TransactionLog.timestamp >= start_date)

            if end_date:
                conditions.append(TransactionLog.timestamp <= end_date)

            # Get total count
            from sqlalchemy import func

            count_stmt = select(func.count(TransactionLog.id)).where(*conditions)
            count_result = await session.execute(count_stmt)
            total_count = count_result.scalar() or 0

            # Get paginated logs (query with order_by and offset)
            stmt = (
                select(TransactionLog)
                .where(*conditions)
                .order_by(desc(TransactionLog.timestamp))
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            logs = list(result.scalars().all())

            # Convert to dicts
            log_entries = [
                {
                    "log_id": log.id,
                    "transaction_type": log.transaction_type,
                    "details": log.details,
                    "context": log.context,
                    "timestamp": log.timestamp,
                }
                for log in logs
            ]

            return {
                "player_id": player_id,
                "transaction_type_filter": transaction_type,
                "total_count": total_count,
                "returned_count": len(log_entries),
                "limit": limit,
                "offset": offset,
                "has_more": (offset + len(log_entries)) < total_count,
                "logs": log_entries,
            }

    async def get_recent_transactions(
        self,
        player_id: int,
        hours: int = 24,
        limit: int = 50,
        context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent transactions for a player within the last N hours.

        Args:
            player_id: Discord ID of player
            hours: Number of hours to look back
            limit: Maximum number of records to return
            context: Operation context

        Returns:
            List of recent transaction dicts
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)

        # Calculate cutoff time
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        async with DatabaseService.get_transaction() as session:
            # Query with order_by and limit
            stmt = (
                select(TransactionLog)
                .where(
                    TransactionLog.player_id == player_id,
                    TransactionLog.timestamp >= cutoff_time,
                )
                .order_by(desc(TransactionLog.timestamp))
                .limit(limit)
            )
            result = await session.execute(stmt)
            logs = list(result.scalars().all())

            return [
                {
                    "log_id": log.id,
                    "transaction_type": log.transaction_type,
                    "details": log.details,
                    "context": log.context,
                    "timestamp": log.timestamp,
                }
                for log in logs
            ]

    async def get_transaction_summary(
        self,
        player_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get summary statistics for a player's transactions.

        Args:
            player_id: Discord ID of player
            start_date: Optional start date filter
            end_date: Optional end date filter
            context: Operation context

        Returns:
            Dict with transaction statistics grouped by type
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            # Build query conditions
            conditions = [TransactionLog.player_id == player_id]

            if start_date:
                conditions.append(TransactionLog.timestamp >= start_date)

            if end_date:
                conditions.append(TransactionLog.timestamp <= end_date)

            # Get all matching logs
            logs = await self._log_repo.find_many_where(
                session,
                *conditions,
            )

            # Group by transaction type
            summary: Dict[str, int] = {}
            for log in logs:
                tx_type = log.transaction_type
                summary[tx_type] = summary.get(tx_type, 0) + 1

            return {
                "player_id": player_id,
                "total_transactions": len(logs),
                "breakdown_by_type": summary,
                "start_date": start_date,
                "end_date": end_date,
            }

    # -------------------------------------------------------------------------
    # Maintenance Operations
    # -------------------------------------------------------------------------

    async def cleanup_old_logs(
        self,
        retention_days: Optional[int] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Delete transaction logs older than retention period.

        Args:
            retention_days: Number of days to retain (from config if not specified)
            context: Operation context

        Returns:
            Dict with cleanup statistics

        Note: This should be called periodically (e.g., daily cron job)
        """
        # Get retention period from config if not specified
        if retention_days is None:
            retention_days = self.get_config("economy.transaction_log_retention_days", default=90)

        # Ensure retention_days is valid
        if retention_days is None:
            retention_days = 90

        # Calculate cutoff date
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        async with DatabaseService.get_transaction() as session:
            # Count logs to delete
            from sqlalchemy import func

            count_stmt = select(func.count(TransactionLog.id)).where(
                TransactionLog.timestamp < cutoff_date
            )
            count_result = await session.execute(count_stmt)
            logs_to_delete = count_result.scalar() or 0

            # Delete old logs
            delete_stmt = delete(TransactionLog).where(TransactionLog.timestamp < cutoff_date)
            await session.execute(delete_stmt)

            return {
                "retention_days": retention_days,
                "cutoff_date": cutoff_date,
                "logs_deleted": logs_to_delete,
            }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _filter_sensitive_data(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter sensitive data from transaction details.

        Removes fields like:
        - password, token, secret, api_key
        - Any field containing 'auth' or 'credential'

        Args:
            details: Original details dict

        Returns:
            Filtered details dict
        """
        sensitive_keywords = ["password", "token", "secret", "api_key", "auth", "credential"]

        filtered = {}
        for key, value in details.items():
            # Check if key contains any sensitive keyword (case-insensitive)
            is_sensitive = any(
                keyword.lower() in key.lower() for keyword in sensitive_keywords
            )

            if is_sensitive:
                filtered[key] = "[REDACTED]"
            else:
                filtered[key] = value

        return filtered
