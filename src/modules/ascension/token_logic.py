"""
Token granting and redemption system.

Tokens are earned from ascension and redeemed for random maidens in tier range.

RIKI LAW Compliance:
- Article III: Pure business logic service
- Article II: Comprehensive transaction logging
- Article VII: Domain exceptions only
- Article I.1: Pessimistic locking for token transactions
"""

from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import secrets

from src.database.models.core.player import Player
from src.database.models.economy.token import Token
from src.database.models.core.maiden_base import MaidenBase
from src.modules.ascension.constants import (
    TOKEN_TIERS,
    validate_token_type,
    get_token_tier_range
)
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class TokenService:
    """
    Token granting and redemption system.
    
    Manages token economy for ascension rewards and maiden redemption.
    All token operations use pessimistic locking for transaction safety.
    """
    
    # ========================================================================
    # TOKEN GRANTING
    # ========================================================================
    
    @staticmethod
    async def grant_token(
        session: AsyncSession,
        player_id: int,
        token_type: str,
        quantity: int = 1,
        source: str = "ascension_reward"
    ) -> None:
        """
        Grant tokens to player.
        
        Uses pessimistic locking to prevent race conditions.
        
        Args:
            session: Database session
            player_id: Discord ID
            token_type: Token type (bronze/silver/gold/platinum/diamond)
            quantity: Number to grant
            source: Source of tokens for audit trail
        
        Raises:
            InvalidOperationError: Invalid token type
        """
        if not validate_token_type(token_type):
            raise InvalidOperationError(f"Invalid token type: {token_type}")
        
        token_type = token_type.lower()
        
        # Get or create token record with pessimistic lock
        result = await session.execute(
            select(Token).where(
                Token.player_id == player_id,
                Token.token_type == token_type
            ).with_for_update()
        )
        token = result.scalar_one_or_none()
        
        if not token:
            token = Token(
                player_id=player_id,
                token_type=token_type,
                quantity=quantity
            )
            session.add(token)
        else:
            token.quantity += quantity
        
        # Log transaction
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="token_granted",
            details={
                "token_type": token_type,
                "quantity": quantity,
                "new_total": token.quantity,
                "source": source
            },
            context="token_grant"
        )
        
        logger.info(
            f"Granted {quantity}x {token_type} token to player {player_id} "
            f"(source: {source}, new total: {token.quantity})"
        )
        
        await session.flush()
    
    # ========================================================================
    # TOKEN REDEMPTION
    # ========================================================================
    
    @staticmethod
    async def redeem_token(
        session: AsyncSession,
        player: Player,
        token_type: str
    ) -> Dict[str, Any]:
        """
        Redeem token for random maiden in tier range.
        
        Uses pessimistic locking to prevent double-redemption.
        Generates random tier within token's range, then selects random maiden.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            token_type: Token type to redeem
        
        Returns:
            {
                "maiden_base": MaidenBase object,
                "tier": int (rolled tier),
                "element": str,
                "token_type": str,
                "tokens_remaining": int
            }
        
        Raises:
            InsufficientResourcesError: Not enough tokens
            InvalidOperationError: Invalid token type or no maidens available
        """
        if not validate_token_type(token_type):
            raise InvalidOperationError(f"Invalid token type: {token_type}")
        
        token_type = token_type.lower()
        
        # Get token with pessimistic lock
        result = await session.execute(
            select(Token).where(
                Token.player_id == player.discord_id,
                Token.token_type == token_type
            ).with_for_update()
        )
        token = result.scalar_one_or_none()
        
        if not token or token.quantity < 1:
            raise InsufficientResourcesError(
                resource_type="token",
                required=1,
                current=token.quantity if token else 0
            )
        
        # Consume token
        token.quantity -= 1
        
        # Get tier range and roll random tier
        tier_range = get_token_tier_range(token_type)
        min_tier, max_tier = tier_range
        tier = secrets.SystemRandom().randint(min_tier, max_tier)
        
        # Get all maidens of rolled tier
        result = await session.execute(
            select(MaidenBase).where(
                MaidenBase.base_tier == tier
            )
        )
        maiden_pool = result.scalars().all()
        
        if not maiden_pool:
            raise InvalidOperationError(
                f"No maidens available for tier {tier}. "
                f"This is a data issue - please report to developers."
            )
        
        # Select random maiden from pool
        maiden_base = secrets.choice(maiden_pool)
        
        # Add maiden to player inventory
        from src.modules.maiden.service import MaidenService
        maiden = await MaidenService.add_maiden_to_inventory(
            session=session,
            player_id=player.discord_id,
            maiden_base_id=maiden_base.id,
            tier=tier,
            quantity=1,
            acquired_from=f"token_redeem_{token_type}"
        )
        
        # Log transaction
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type="token_redeemed",
            details={
                "token_type": token_type,
                "maiden_id": maiden_base.id,
                "maiden_name": maiden_base.name,
                "tier": tier,
                "element": maiden_base.element,
                "tokens_remaining": token.quantity
            },
            context="token_redemption"
        )
        
        logger.info(
            f"Player {player.discord_id} redeemed {token_type} token: "
            f"received {maiden_base.name} (T{tier}), "
            f"{token.quantity} tokens remaining"
        )
        
        await session.flush()
        
        return {
            "maiden_base": maiden_base,
            "tier": tier,
            "element": maiden_base.element,
            "token_type": token_type,
            "tokens_remaining": token.quantity
        }
    
    # ========================================================================
    # QUERY
    # ========================================================================
    
    @staticmethod
    async def get_player_tokens(
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, int]:
        """
        Get player's token inventory.
        
        Returns all token types with quantity (0 if player has none).
        
        Args:
            session: Database session
            player_id: Discord ID
        
        Returns:
            Dictionary of token_type -> quantity
            Example: {"bronze": 5, "silver": 2, "gold": 0, "platinum": 0, "diamond": 1}
        """
        result = await session.execute(
            select(Token).where(Token.player_id == player_id)
        )
        tokens = result.scalars().all()
        
        # Initialize all token types to 0
        inventory = {token_type: 0 for token_type in TOKEN_TIERS.keys()}
        
        # Fill in actual quantities
        for token in tokens:
            inventory[token.token_type] = token.quantity
        
        return inventory
    
    @staticmethod
    async def get_token_count(
        session: AsyncSession,
        player_id: int,
        token_type: str
    ) -> int:
        """
        Get count of specific token type.
        
        Args:
            session: Database session
            player_id: Discord ID
            token_type: Token type to check
        
        Returns:
            Token quantity (0 if none)
        
        Raises:
            InvalidOperationError: Invalid token type
        """
        if not validate_token_type(token_type):
            raise InvalidOperationError(f"Invalid token type: {token_type}")
        
        token_type = token_type.lower()
        
        result = await session.execute(
            select(Token).where(
                Token.player_id == player_id,
                Token.token_type == token_type
            )
        )
        token = result.scalar_one_or_none()
        
        return token.quantity if token else 0