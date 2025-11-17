"""
Ascension Token Service - LES 2025 Compliant
=============================================

Purpose
-------
Manages token rewards for ascension floor victories.
Determines token type based on floor range and handles award logic.

Domain
------
- Token type selection by floor range
- Token awarding on floor victory
- Milestone bonus token calculation
- Token eligibility checking (every N floors)
- Integration with TokenService for inventory

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Config-driven - all token rules from config
✓ Domain exceptions - raises NotFoundError, ValidationError
✓ Event-driven - emits ascension.token.* events
✓ Observable - structured logging
✓ Delegates to TokenService for actual inventory changes

Design Decisions
----------------
- Token type determined by floor range (1-10 = bronze, 11-25 = silver, etc.)
- Tokens awarded every N floors (configurable, default 5)
- Milestone floors award bonus tokens
- Special milestone floors award multiple token types
- Token quantity can scale with floor difficulty

Dependencies
------------
- TokenService: For inventory management
- ConfigManager: For token rules and floor ranges
- EventBus: For token award events
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import ValidationError

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.modules.summon.token_service import TokenService

logger = get_logger(__name__)


# ============================================================================
# AscensionTokenService
# ============================================================================


class AscensionTokenService(BaseService):
    """
    Service for ascension token reward management.
    
    Handles token type selection, eligibility checking, and award coordination
    for ascension floor victories. Delegates actual inventory changes to TokenService.
    
    Public Methods
    --------------
    - determine_token_type(floor) -> Get token type for floor
    - is_token_eligible(floor) -> Check if floor awards token
    - calculate_token_rewards(floor) -> Get all token rewards for floor
    - award_floor_tokens(player_id, floor) -> Award tokens for floor victory
    - get_milestone_bonus_tokens(floor) -> Get bonus tokens for milestone
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
        token_service: TokenService,
    ) -> None:
        """
        Initialize AscensionTokenService.
        
        Args:
            config_manager: Application configuration
            event_bus: Event bus for token events
            logger: Structured logger
            token_service: TokenService for inventory operations
        """
        super().__init__(config_manager, event_bus, logger)
        
        self._token_service = token_service

        # Load token award interval
        self._token_interval = int(
            self.get_config(
                "ascension.balance.ascension_balance.bonus_intervals.token_every_n_floors",
                default=5,
            )
        )

        # Load floor ranges for token types (from core.yaml)
        self._token_tiers = self.get_config(
            "ascension.core.ASCENSION.TOKEN_TIERS", default={}
        )

        # Load milestone bonus tokens (from balance.yaml)
        self._milestones = self.get_config(
            "ascension.balance.ascension_balance.milestones", default={}
        )

        # Token type by floor range (simplified mapping)
        self._floor_ranges = [
            (1, 10, "bronze"),
            (11, 25, "silver"),
            (26, 50, "gold"),
            (51, 100, "platinum"),
            (101, 9999, "diamond"),
        ]

        self.log.info(
            "AscensionTokenService initialized",
            extra={"token_interval": self._token_interval},
        )

    # ========================================================================
    # PUBLIC API - Token Type Determination
    # ========================================================================

    def determine_token_type(self, floor: int) -> str:
        """
        Determine which token type to award for a given floor.
        
        Uses floor range mapping from config.
        
        Args:
            floor: Floor number
        
        Returns:
            Token type string (bronze/silver/gold/platinum/diamond)
        
        Example:
            >>> token_type = ascension_token_service.determine_token_type(15)
            >>> print(token_type)  # "silver"
        """
        floor = InputValidator.validate_positive_integer(floor, "floor")

        for min_floor, max_floor, token_type in self._floor_ranges:
            if min_floor <= floor <= max_floor:
                self.log.debug(
                    f"Token type determined: {token_type}",
                    extra={"floor": floor, "token_type": token_type},
                )
                return token_type

        # Default to highest tier if floor exceeds all ranges
        return "diamond"

    def is_token_eligible(self, floor: int) -> bool:
        """
        Check if floor is eligible for token reward.
        
        Tokens awarded every N floors (configurable interval).
        
        Args:
            floor: Floor number
        
        Returns:
            True if floor awards token, False otherwise
        
        Example:
            >>> is_eligible = ascension_token_service.is_token_eligible(10)
            >>> print(is_eligible)  # True (if interval is 5)
        """
        floor = InputValidator.validate_positive_integer(floor, "floor")
        
        is_eligible = floor % self._token_interval == 0

        self.log.debug(
            f"Token eligibility check: {is_eligible}",
            extra={
                "floor": floor,
                "interval": self._token_interval,
                "is_eligible": is_eligible,
            },
        )

        return is_eligible

    # ========================================================================
    # PUBLIC API - Milestone Bonuses
    # ========================================================================

    def get_milestone_bonus_tokens(self, floor: int) -> List[Dict[str, Any]]:
        """
        Get bonus token rewards for milestone floors.
        
        Milestone floors (50, 100, 150, 200, etc.) award extra tokens
        on top of the regular interval tokens.
        
        Args:
            floor: Floor number
        
        Returns:
            List of bonus token dicts: [{"token_type": "gold", "quantity": 3}, ...]
        
        Example:
            >>> bonuses = ascension_token_service.get_milestone_bonus_tokens(100)
            >>> print(bonuses)
            [{"token_type": "platinum", "quantity": 3}, {"token_type": "diamond", "quantity": 1}]
        """
        floor = InputValidator.validate_positive_integer(floor, "floor")

        milestone_config = self._milestones.get(str(floor))
        if not milestone_config:
            return []

        bonus_tokens = []

        # Check for token awards in milestone config
        for key, value in milestone_config.items():
            if "_token" in key and isinstance(value, (int, bool)):
                # Extract token type from key (e.g., "gold_token" -> "gold")
                token_type = key.replace("_token", "")
                
                if isinstance(value, bool) and value:
                    # Boolean flag means award 1 token
                    quantity = 1
                elif isinstance(value, int):
                    # Integer means award that many tokens
                    quantity = value
                else:
                    continue

                bonus_tokens.append({"token_type": token_type, "quantity": quantity})

        self.log.debug(
            f"Milestone bonuses: {len(bonus_tokens)} token types",
            extra={"floor": floor, "bonus_tokens": bonus_tokens},
        )

        return bonus_tokens

    # ========================================================================
    # PUBLIC API - Reward Calculation
    # ========================================================================

    def calculate_token_rewards(self, floor: int) -> List[Dict[str, Any]]:
        """
        Calculate all token rewards for a floor (regular + milestone).
        
        Args:
            floor: Floor number
        
        Returns:
            List of token reward dicts: [{"token_type": "silver", "quantity": 1}, ...]
        
        Example:
            >>> rewards = ascension_token_service.calculate_token_rewards(50)
            >>> print(rewards)
            [
                {"token_type": "gold", "quantity": 1},      # Regular interval token
                {"token_type": "gold", "quantity": 3},      # Milestone bonus
                {"token_type": "platinum", "quantity": 1}   # Milestone bonus
            ]
        """
        floor = InputValidator.validate_positive_integer(floor, "floor")

        rewards = []

        # Check regular interval token
        if self.is_token_eligible(floor):
            token_type = self.determine_token_type(floor)
            rewards.append({"token_type": token_type, "quantity": 1})

        # Add milestone bonus tokens
        milestone_bonuses = self.get_milestone_bonus_tokens(floor)
        rewards.extend(milestone_bonuses)

        self.log.info(
            f"Token rewards calculated for floor {floor}",
            extra={"floor": floor, "total_rewards": len(rewards), "rewards": rewards},
        )

        return rewards

    # ========================================================================
    # PUBLIC API - Token Awarding
    # ========================================================================

    async def award_floor_tokens(
        self, player_id: int, floor: int, context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Award all tokens for a floor victory.
        
        Delegates to TokenService for actual inventory changes.
        This is a **write operation** (via TokenService.award_tokens).
        
        Args:
            player_id: Discord ID
            floor: Floor defeated
            context: Optional context string
        
        Returns:
            Dict with awarded tokens and updated balances
        
        Example:
            >>> result = await ascension_token_service.award_floor_tokens(
            ...     player_id=123,
            ...     floor=50,
            ...     context="ascension_victory"
            ... )
            >>> print(result["tokens_awarded"])
            [
                {"token_type": "gold", "quantity": 1, "new_balance": 15},
                {"token_type": "gold", "quantity": 3, "new_balance": 18},
                {"token_type": "platinum", "quantity": 1, "new_balance": 5}
            ]
        """
        player_id = InputValidator.validate_discord_id(player_id)
        floor = InputValidator.validate_positive_integer(floor, "floor")

        self.log_operation(
            "award_floor_tokens", player_id=player_id, floor=floor
        )

        # Calculate rewards
        token_rewards = self.calculate_token_rewards(floor)

        if not token_rewards:
            self.log.info(
                "No tokens to award for this floor",
                extra={"player_id": player_id, "floor": floor},
            )
            return {
                "player_id": player_id,
                "floor": floor,
                "tokens_awarded": [],
            }

        # Award each token type
        awarded_tokens = []
        for reward in token_rewards:
            token_type = reward["token_type"]
            quantity = reward["quantity"]

            result = await self._token_service.award_tokens(
                player_id=player_id,
                token_type=token_type,
                quantity=quantity,
                source=f"ascension_floor_{floor}",
                context=context,
            )

            awarded_tokens.append(
                {
                    "token_type": token_type,
                    "quantity": quantity,
                    "new_balance": result["new_balance"],
                }
            )

        # Emit event
        await self.emit_event(
            event_type="ascension.tokens_awarded",
            data={
                "player_id": player_id,
                "floor": floor,
                "tokens_awarded": awarded_tokens,
            },
        )

        self.log.info(
            f"Awarded {len(awarded_tokens)} token type(s) for floor {floor}",
            extra={
                "player_id": player_id,
                "floor": floor,
                "tokens_awarded": awarded_tokens,
            },
        )

        return {
            "player_id": player_id,
            "floor": floor,
            "tokens_awarded": awarded_tokens,
        }