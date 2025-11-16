"""
TokenService - Business logic for token management and redemption
==================================================================

Handles:
- Token inventory management (awarding, spending)
- Token redemption for maiden summons
- Tier range determination per token type
- Multi-pull redemption
- Token balance validation

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven tier ranges and costs
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import select

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import InvalidOperationError, NotFoundError, ValidationError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.economy.token import Token

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class TokenService(BaseService):
    """
    TokenService handles all token inventory and redemption operations.

    Business Logic:
    - Token types map to maiden tier ranges via config
    - Redemption validates sufficient balance before decrementing
    - Multi-pull provides batch redemption with guaranteed bonuses
    - Token awarding increments existing inventory or creates new record
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize TokenService with Token repository."""
        super().__init__(config_manager, event_bus, logger)
        self._token_repo = BaseRepository[Token](Token, self.log)

    # -------------------------------------------------------------------------
    # Token Inventory Management
    # -------------------------------------------------------------------------

    async def award_tokens(
        self,
        player_id: int,
        token_type: str,
        quantity: int,
        source: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Award tokens to a player's inventory.

        Args:
            player_id: Discord ID of player
            token_type: Type of token (e.g., 'standard', 'premium', 'special')
            quantity: Number of tokens to award
            source: Source of tokens (e.g., 'daily_quest', 'ascension_floor_10')
            context: Operation context for audit

        Returns:
            Dict with updated token balance

        Raises:
            ValidationError: Invalid parameters
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        token_type = InputValidator.validate_string(token_type, "token_type", min_length=1)
        quantity = InputValidator.validate_positive_integer(quantity, "quantity")
        source = InputValidator.validate_string(source, "source", min_length=1)

        async with DatabaseService.get_transaction() as session:
            # Get or create token record with pessimistic lock
            token = await self._token_repo.find_one_where(
                session,
                Token.player_id == player_id,
                Token.token_type == token_type,
                for_update=True,
            )

            if token:
                old_quantity = token.quantity
                token.quantity += quantity
                new_quantity = token.quantity
            else:
                # Create new token record
                token = Token(
                    player_id=player_id,
                    token_type=token_type,
                    quantity=quantity,
                )
                session.add(token)
                await session.flush()
                old_quantity = 0
                new_quantity = quantity

            # Emit event
            await self.emit_event(
                "token.awarded",
                {
                    "player_id": player_id,
                    "token_type": token_type,
                    "quantity_awarded": quantity,
                    "old_quantity": old_quantity,
                    "new_quantity": new_quantity,
                    "source": source,
                },
            )

            return {
                "player_id": player_id,
                "token_type": token_type,
                "quantity_awarded": quantity,
                "new_balance": new_quantity,
                "source": source,
            }

    async def spend_tokens(
        self,
        player_id: int,
        token_type: str,
        quantity: int,
        purpose: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Spend tokens from a player's inventory.

        Args:
            player_id: Discord ID of player
            token_type: Type of token
            quantity: Number of tokens to spend
            purpose: Purpose of spending (e.g., 'maiden_summon', 'shop_purchase')
            context: Operation context for audit

        Returns:
            Dict with updated token balance

        Raises:
            ValidationError: Invalid parameters
            ResourceNotFoundError: No tokens of this type
            BusinessRuleViolation: Insufficient tokens
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        token_type = InputValidator.validate_string(token_type, "token_type", min_length=1)
        quantity = InputValidator.validate_positive_integer(quantity, "quantity")
        purpose = InputValidator.validate_string(purpose, "purpose", min_length=1)

        async with DatabaseService.get_transaction() as session:
            # Get token record with pessimistic lock
            token = await self._token_repo.find_one_where(
                session,
                Token.player_id == player_id,
                Token.token_type == token_type,
                for_update=True,
            )

            if not token:
                raise NotFoundError(
                    f"Player {player_id} has no tokens of type '{token_type}'"
                )

            # Validate sufficient balance
            if token.quantity < quantity:
                raise InvalidOperationError(
                    "spend_tokens",
                    f"Insufficient {token_type} tokens. Required: {quantity}, Available: {token.quantity}"
                )

            # Deduct tokens
            old_quantity = token.quantity
            token.quantity -= quantity
            new_quantity = token.quantity

            # Emit event
            await self.emit_event(
                "token.spent",
                {
                    "player_id": player_id,
                    "token_type": token_type,
                    "quantity_spent": quantity,
                    "old_quantity": old_quantity,
                    "new_quantity": new_quantity,
                    "purpose": purpose,
                },
            )

            return {
                "player_id": player_id,
                "token_type": token_type,
                "quantity_spent": quantity,
                "new_balance": new_quantity,
                "purpose": purpose,
            }

    # -------------------------------------------------------------------------
    # Token Redemption
    # -------------------------------------------------------------------------

    async def redeem_token_for_summon(
        self,
        player_id: int,
        token_type: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Redeem a single token for a maiden summon.

        Args:
            player_id: Discord ID of player
            token_type: Type of token to redeem
            context: Operation context for audit

        Returns:
            Dict with summon details (tier_range, cost, new_balance)

        Raises:
            ValidationError: Invalid parameters
            ResourceNotFoundError: No tokens of this type
            BusinessRuleViolation: Insufficient tokens
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        token_type = InputValidator.validate_string(token_type, "token_type", min_length=1)

        # Get token cost for single summon
        token_cost = self.get_config(f"tokens.{token_type}.cost_per_summon", default=1)

        # Spend tokens
        spend_result = await self.spend_tokens(
            player_id=player_id,
            token_type=token_type,
            quantity=token_cost,
            purpose="maiden_summon_single",
            context=context,
        )

        # Get tier range from config
        tier_range = self._get_tier_range(token_type)

        # Emit redemption event (actual summon handled by summon service)
        await self.emit_event(
            "token.redeemed",
            {
                "player_id": player_id,
                "token_type": token_type,
                "redemption_type": "single",
                "tier_range": tier_range,
                "tokens_spent": token_cost,
            },
        )

        return {
            "player_id": player_id,
            "token_type": token_type,
            "redemption_type": "single",
            "tier_range": tier_range,
            "tokens_spent": token_cost,
            "new_token_balance": spend_result["new_balance"],
        }

    async def redeem_tokens_for_multi_summon(
        self,
        player_id: int,
        token_type: str,
        pull_count: int = 10,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Redeem multiple tokens for a multi-pull summon.

        Args:
            player_id: Discord ID of player
            token_type: Type of token to redeem
            pull_count: Number of pulls (default 10)
            context: Operation context for audit

        Returns:
            Dict with multi-summon details (tier_range, cost, guaranteed_bonuses)

        Raises:
            ValidationError: Invalid parameters
            ResourceNotFoundError: No tokens of this type
            BusinessRuleViolation: Insufficient tokens, invalid pull count
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        token_type = InputValidator.validate_string(token_type, "token_type", min_length=1)

        # Validate pull count
        valid_pull_counts = self.get_config("tokens.valid_multi_pull_counts", default=[10])
        if pull_count not in valid_pull_counts:
            raise ValidationError(
                "pull_count",
                f"Invalid pull count {pull_count}. Valid counts: {valid_pull_counts}"
            )

        # Get token cost for multi summon (may have discount)
        cost_per_summon = self.get_config(f"tokens.{token_type}.cost_per_summon", default=1)
        multi_discount = self.get_config(
            f"tokens.{token_type}.multi_pull_{pull_count}_discount", default=0
        )
        total_cost = int((cost_per_summon * pull_count) * (1 - multi_discount))

        # Spend tokens
        spend_result = await self.spend_tokens(
            player_id=player_id,
            token_type=token_type,
            quantity=total_cost,
            purpose=f"maiden_summon_multi_{pull_count}",
            context=context,
        )

        # Get tier range and guaranteed bonuses from config
        tier_range = self._get_tier_range(token_type)
        guaranteed_bonuses = self.get_config(
            f"tokens.{token_type}.multi_pull_{pull_count}_guarantees", default={}
        )

        # Emit redemption event (actual summons handled by summon service)
        await self.emit_event(
            "token.redeemed",
            {
                "player_id": player_id,
                "token_type": token_type,
                "redemption_type": f"multi_{pull_count}",
                "tier_range": tier_range,
                "tokens_spent": total_cost,
                "pull_count": pull_count,
                "guaranteed_bonuses": guaranteed_bonuses,
            },
        )

        return {
            "player_id": player_id,
            "token_type": token_type,
            "redemption_type": f"multi_{pull_count}",
            "tier_range": tier_range,
            "tokens_spent": total_cost,
            "pull_count": pull_count,
            "guaranteed_bonuses": guaranteed_bonuses,
            "new_token_balance": spend_result["new_balance"],
        }

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    async def get_player_token_balance(
        self,
        player_id: int,
        token_type: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a player's token balance.

        Args:
            player_id: Discord ID of player
            token_type: Optional specific token type, or None for all tokens
            context: Operation context for audit

        Returns:
            Dict with token balances
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            if token_type:
                # Get specific token type
                token = await self._token_repo.find_one_where(
                    session,
                    Token.player_id == player_id,
                    Token.token_type == token_type,
                )

                if not token:
                    return {
                        "player_id": player_id,
                        "token_type": token_type,
                        "quantity": 0,
                    }

                return {
                    "player_id": player_id,
                    "token_type": token.token_type,
                    "quantity": token.quantity,
                    "last_updated": token.updated_at,
                }
            else:
                # Get all token types (query with order_by)
                stmt = select(Token).where(Token.player_id == player_id).order_by(Token.token_type)
                result = await session.execute(stmt)
                tokens = list(result.scalars().all())

                balances = [
                    {
                        "token_type": token.token_type,
                        "quantity": token.quantity,
                        "last_updated": token.updated_at,
                    }
                    for token in tokens
                ]

                return {
                    "player_id": player_id,
                    "balances": balances,
                    "total_token_types": len(balances),
                }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _get_tier_range(self, token_type: str) -> Dict[str, int]:
        """
        Get the maiden tier range for a token type from config.

        Args:
            token_type: Type of token

        Returns:
            Dict with min_tier and max_tier

        Example config:
            tokens:
              standard:
                tier_range:
                  min_tier: 1
                  max_tier: 3
        """
        tier_range = self.get_config(f"tokens.{token_type}.tier_range", default={})

        min_tier = tier_range.get("min_tier", 1)
        max_tier = tier_range.get("max_tier", 5)

        return {
            "min_tier": min_tier,
            "max_tier": max_tier,
        }
