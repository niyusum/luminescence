"""
Element Resolver - LES 2025 Compliant
======================================

Purpose
-------
Applies element advantage/disadvantage system using config-driven matchups.
Turns beautiful YAML into actual combat multipliers.

Domain
------
- Element advantage calculation (rock-paper-scissors logic)
- Config-driven element matchups
- Multiplier resolution (advantage/disadvantage/neutral)
- Element validation and normalization

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Config-driven - all matchups from maiden.power.elements
✓ Observable - structured logging for debugging
✓ Type-safe - complete type hints
✓ Stateless - can be called from any context

Design Decisions
----------------
- Matchups stored as dict: {attacker_element: beats_this_element}
- Neutral elements have no advantages/disadvantages
- Unknown elements default to neutral (1.0 multiplier)
- Case-insensitive element comparison
- Caching support for frequently accessed matchups

Dependencies
------------
- ConfigManager: For element matchups and multipliers
"""

from __future__ import annotations

from typing import Dict, Optional, Set

from src.core.config.manager import ConfigManager
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# ElementResolver
# ============================================================================


class ElementResolver:
    """
    Resolves element advantages using config-driven matchup tables.
    
    Applies rock-paper-scissors style combat modifiers:
    - Fire beats Earth (+20% damage)
    - Water beats Fire (+20% damage)
    - Earth beats Air (+20% damage)
    - Air beats Water (+20% damage)
    - Light beats Dark (+20% damage)
    - Dark beats Light (+20% damage)
    
    Public Methods
    --------------
    - get_multiplier(attacker_elem, defender_elem) -> Calculate damage multiplier
    - has_advantage(attacker_elem, defender_elem) -> Check if advantage exists
    - get_advantage_chain(element) -> Get elements this element beats/loses to
    
    Configuration Keys
    ------------------
    - maiden.power.elements.advantages (dict of matchups)
    - maiden.power.elements.advantage_multiplier (default: 1.2)
    - maiden.power.elements.disadvantage_multiplier (default: 0.8)
    - maiden.power.elements.valid_elements (list)
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        """
        Initialize ElementResolver with config manager.
        
        Args:
            config_manager: Application configuration manager
        """
        self._config = config_manager
        self._logger = logger

        # Load element configuration
        element_cfg = self._config.get("maiden.power.elements", default={})

        # Element matchup table: {attacker: defender_it_beats}
        self._advantages: Dict[str, Optional[str]] = element_cfg.get("advantages", {})

        # Multipliers
        self._advantage_mult = float(element_cfg.get("advantage_multiplier", 1.2))
        self._disadvantage_mult = float(element_cfg.get("disadvantage_multiplier", 0.8))

        # Valid elements for validation
        self._valid_elements: Set[str] = set(
            element_cfg.get(
                "valid_elements",
                ["fire", "water", "earth", "air", "light", "dark", "neutral"],
            )
        )

        # Normalize advantages to lowercase
        self._advantages = {
            k.lower(): (v.lower() if v else None) for k, v in self._advantages.items()
        }

        self._logger.info(
            "ElementResolver initialized",
            extra={
                "advantage_multiplier": self._advantage_mult,
                "disadvantage_multiplier": self._disadvantage_mult,
                "valid_elements": list(self._valid_elements),
                "matchups": self._advantages,
            },
        )

    # ========================================================================
    # PUBLIC API - Multiplier Calculation
    # ========================================================================

    def get_multiplier(self, attacker_elem: str, defender_elem: str) -> float:
        """
        Calculate damage multiplier based on element matchup.
        
        Returns:
        - advantage_multiplier (1.2) if attacker has advantage
        - disadvantage_multiplier (0.8) if attacker at disadvantage
        - 1.0 if neutral matchup
        
        Args:
            attacker_elem: Attacking element
            defender_elem: Defending element
        
        Returns:
            Damage multiplier (float)
        
        Example:
            >>> mult = element_resolver.get_multiplier("fire", "earth")
            >>> print(mult)  # 1.2 (fire beats earth)
            >>> mult = element_resolver.get_multiplier("fire", "water")
            >>> print(mult)  # 0.8 (water beats fire)
        """
        if not attacker_elem or not defender_elem:
            return 1.0

        attacker_elem = attacker_elem.lower()
        defender_elem = defender_elem.lower()

        # Check for advantage
        target = self._advantages.get(attacker_elem)
        if target and defender_elem == target:
            self._logger.debug(
                "Element advantage",
                extra={
                    "attacker": attacker_elem,
                    "defender": defender_elem,
                    "multiplier": self._advantage_mult,
                },
            )
            return self._advantage_mult

        # Check for disadvantage (defender has advantage over attacker)
        defender_target = self._advantages.get(defender_elem)
        if defender_target and attacker_elem == defender_target:
            self._logger.debug(
                "Element disadvantage",
                extra={
                    "attacker": attacker_elem,
                    "defender": defender_elem,
                    "multiplier": self._disadvantage_mult,
                },
            )
            return self._disadvantage_mult

        # Neutral matchup
        return 1.0

    # ========================================================================
    # PUBLIC API - Advantage Checking
    # ========================================================================

    def has_advantage(self, attacker_elem: str, defender_elem: str) -> bool:
        """
        Check if attacker has element advantage over defender.
        
        Args:
            attacker_elem: Attacking element
            defender_elem: Defending element
        
        Returns:
            True if attacker has advantage, False otherwise
        
        Example:
            >>> element_resolver.has_advantage("fire", "earth")
            True
        """
        if not attacker_elem or not defender_elem:
            return False

        attacker_elem = attacker_elem.lower()
        defender_elem = defender_elem.lower()

        target = self._advantages.get(attacker_elem)
        return target is not None and defender_elem == target

    # ========================================================================
    # PUBLIC API - Advantage Chain
    # ========================================================================

    def get_advantage_chain(self, element: str) -> Dict[str, Optional[str]]:
        """
        Get complete advantage chain for an element.
        
        Returns what this element beats and what beats it.
        
        Args:
            element: Element to analyze
        
        Returns:
            Dict with "beats" and "beaten_by" keys
        
        Example:
            >>> chain = element_resolver.get_advantage_chain("fire")
            >>> print(chain)
            {"beats": "earth", "beaten_by": "water"}
        """
        if not element:
            return {"beats": None, "beaten_by": None}

        element = element.lower()

        # What does this element beat?
        beats = self._advantages.get(element)

        # What beats this element?
        beaten_by = None
        for attacker, target in self._advantages.items():
            if target == element:
                beaten_by = attacker
                break

        return {"beats": beats, "beaten_by": beaten_by}

    # ========================================================================
    # PUBLIC API - Validation
    # ========================================================================

    def is_valid_element(self, element: str) -> bool:
        """
        Check if element is valid/recognized.
        
        Args:
            element: Element to validate
        
        Returns:
            True if element is in valid_elements list
        
        Example:
            >>> element_resolver.is_valid_element("fire")
            True
            >>> element_resolver.is_valid_element("pizza")
            False
        """
        if not element:
            return False
        return element.lower() in self._valid_elements