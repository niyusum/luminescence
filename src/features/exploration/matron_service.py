"""
Matron boss system with speed-based rewards.

Matrons are powerful maiden guardians that don't fight back.
Challenge is defeating them within turn limit for optimal rewards.

RIKI LAW Compliance:
- Article III: Pure business logic service
- Article II: Comprehensive audit trails
- Article VII: No Discord dependencies
"""

from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import random

from src.database.models.core.player import Player
from src.database.models.progression.sector_progress import SectorProgress
from src.core.config.config_manager import ConfigManager
from src.features.resource.service import ResourceService
from src.features.combat.service import CombatService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# MATRON DISMISSAL FLAVOR TEXT
# ============================================================================

MATRON_DISMISSAL_LINES = {
    "early": [  # Turns 21-25
        "{matron_name} sighs. \"You lack the strength. Come back when you're ready.\"",
        "The Matron waves her hand dismissively. \"This is taking too long. Leave.\"",
        "{matron_name} grows impatient. \"I have no time for this. Begone.\"",
    ],
    "mid": [  # Turns 26-30
        "{matron_name} shakes her head. \"Your power is... insufficient.\"",
        "\"You're too weak for this sector,\" {matron_name} states coldly.",
        "The Matron crosses her arms. \"Train more. Then return.\"",
    ],
    "late": [  # Turns 31+
        "{matron_name} looks bored. \"This is embarrassing. Leave my sight.\"",
        "\"Are you even trying?\" {matron_name} scoffs before teleporting away.",
        "The Matron yawns. \"I've wasted enough time. Goodbye.\"",
    ],
    "special": {  # Sector bosses
        1: "Infernia laughs, flames dancing. \"Return when you can withstand the heat, little one.\"",
        2: "Aquaris' voice echoes through the depths. \"The ocean does not wait for the weak.\"",
        3: "Zephyra vanishes in a gust. \"You cannot catch the wind if you cannot keep pace.\"",
        4: "Terraxis sinks into the ground. \"The earth is patient. You should be stronger.\"",
        5: "Lumina fades into light. \"Even dawn must wait for those unready.\"",
        6: "Noctara dissolves into shadow. \"The night reveals your inadequacy. Improve.\"",
    }
}


# ============================================================================
# SECTOR THEMES
# ============================================================================

SECTOR_THEMES = {
    1: {
        "element": "infernal",
        "subsector_names": ["Emberguard", "Flameheart", "Cinderwatch", "Blazewarden", 
                            "Pyrekeeper", "Infernwatch", "Scorchguard", "Ashveil"],
        "sector_boss": "Infernia, Keeper of the First Seal"
    },
    2: {
        "element": "abyssal",
        "subsector_names": ["Tidewhisper", "Deepcurrent", "Aquashield", "Wavewarden",
                            "Depthkeeper", "Abysswatch", "Coralguard", "Nautilus"],
        "sector_boss": "Aquaris, Lady of Abyssal Depths"
    },
    3: {
        "element": "tempest",
        "subsector_names": ["Stormcaller", "Windweaver", "Tempestborn", "Galeguard",
                            "Thunderwatch", "Skywarden", "Cyclonekeep", "Zephyrveil"],
        "sector_boss": "Zephyra, Mistress of Endless Storms"
    },
    4: {
        "element": "earth",
        "subsector_names": ["Earthshaper", "Rootwarden", "Stoneheart", "Verdantkeep",
                            "Terrawarden", "Mossguard", "Crystalveil", "Grovewatch"],
        "sector_boss": "Terraxis, Guardian of Ancient Roots"
    },
    5: {
        "element": "radiant",
        "subsector_names": ["Lightbringer", "Dawnkeeper", "Radiantveil", "Sunwarden",
                            "Luminguard", "Glowkeeper", "Pristinewatch", "Auraveil"],
        "sector_boss": "Lumina, Herald of Eternal Dawn"
    },
    6: {
        "element": "umbral",
        "subsector_names": ["Shadowveil", "Nightwhisper", "Umbralis", "Duskwarden",
                            "Eclipseguard", "Darkmoon", "Voidkeeper", "Obsidianwatch"],
        "sector_boss": "Noctara, Sovereign of Endless Night"
    }
}


# ============================================================================
# MATRON SERVICE
# ============================================================================

class MatronService:
    """
    Matron boss system with speed-based rewards.
    
    Matrons don't fight back but have turn limits.
    Faster clear = better rewards.
    """
    
    # ========================================================================
    # MATRON GENERATION
    # ========================================================================
    
    @staticmethod
    def generate_matron(sector_id: int, sublevel: int) -> Dict[str, Any]:
        """
        Generate Matron boss with HP scaled to player's total power.
        
        Matrons are XP sponges designed to be beaten in 3-8 turns.
        
        Args:
            sector_id: Sector number (1-7)
            sublevel: Sublevel number (1-9)
        
        Returns:
            {
                "name": "Emberguard Sentinel",
                "hp": 250000,
                "max_hp": 250000,
                "element": "infernal",
                "sector_id": 1,
                "sublevel": 5,
                "is_sector_boss": False,
                "turn_limit": 20,
                "optimal_turns": 5
            }
        """
        # Get base HP from config
        base_hp = ConfigManager.get(f"matron_system.sector_{sector_id}_hp_base", 100000)
        
        # Scale by sublevel
        sublevel_mult = 1 + (sublevel * 0.15)
        final_hp = int(base_hp * sublevel_mult)
        
        # Sector boss (sublevel 9) has 2x HP
        is_sector_boss = (sublevel == 9)
        if is_sector_boss:
            final_hp *= 2
        
        # Generate name
        name = MatronService._generate_matron_name(sector_id, sublevel)
        
        # Get element
        theme = SECTOR_THEMES.get(sector_id, SECTOR_THEMES[1])
        element = theme["element"]
        
        return {
            "name": name,
            "hp": final_hp,
            "max_hp": final_hp,
            "element": element,
            "sector_id": sector_id,
            "sublevel": sublevel,
            "is_sector_boss": is_sector_boss,
            "turn_limit": 20,
            "optimal_turns": 5
        }
    
    @staticmethod
    def _generate_matron_name(sector_id: int, sublevel: int) -> str:
        """Generate thematic Matron name."""
        theme = SECTOR_THEMES.get(sector_id, SECTOR_THEMES[1])
        
        if sublevel == 9:
            # Sector boss
            return theme["sector_boss"]
        else:
            # Subsector matron
            names = theme["subsector_names"]
            # Use sublevel to pick consistent name
            name_index = (sublevel - 1) % len(names)
            prefix = names[name_index]
            
            titles = ["Sentinel", "Warden", "Protector", "Guardian"]
            title = titles[sublevel % len(titles)]
            
            return f"{prefix} {title}"
    
    # ========================================================================
    # COMBAT
    # ========================================================================
    
    @staticmethod
    async def attack_matron(
        session: AsyncSession,
        player: Player,
        matron: Dict[str, Any],
        attack_type: str,
        turn_count: int
    ) -> Dict[str, Any]:
        """
        Execute attack on Matron (no counter-attack).
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            matron: Matron data
            attack_type: "x1", "x3", or "x10"
            turn_count: Current turn number
        
        Returns:
            {
                "damage_dealt": int,
                "matron_hp": int,
                "turns_taken": int,
                "victory": bool,
                "dismissed": bool,
                "turn_bonus": Optional[str],
                "rewards": Optional[Dict],
                "dismissal_text": Optional[str],
                "stamina_cost": int,
                "gem_cost": int
            }
        """
        # Validate and consume resources
        costs = MatronService.get_attack_cost(attack_type)
        stamina_cost = costs["stamina"]
        gem_cost = costs["gems"]
        
        if player.stamina < stamina_cost:
            raise InsufficientResourcesError("stamina", stamina_cost, player.stamina)
        
        if gem_cost > 0 and player.riki_gems < gem_cost:
            raise InsufficientResourcesError("riki_gems", gem_cost, player.riki_gems)
        
        # Consume resources
        player.stamina -= stamina_cost
        if gem_cost > 0:
            player.riki_gems -= gem_cost
        
        # Calculate damage (uses total power, not strategic)
        player_power = await CombatService.calculate_total_power(
            session, player.discord_id, include_leader_bonus=True
        )
        
        attack_mult = {"x1": 1, "x3": 3, "x10": 10}[attack_type]
        damage = player_power * attack_mult
        
        # Matron HP reduction
        matron["hp"] -= damage
        victory = matron["hp"] <= 0
        
        # Check turn limit
        dismissed = (turn_count > matron["turn_limit"])
        
        result = {
            "damage_dealt": damage,
            "matron_hp": max(0, matron["hp"]),
            "turns_taken": turn_count,
            "victory": victory,
            "dismissed": dismissed,
            "stamina_cost": stamina_cost,
            "gem_cost": gem_cost
        }
        
        if victory:
            # Calculate turn-based reward bonus
            optimal_turns = matron["optimal_turns"]
            
            if turn_count <= optimal_turns:
                turn_bonus = "perfect"
                reward_mult = 2.0
            elif turn_count <= optimal_turns + 3:
                turn_bonus = "fast"
                reward_mult = 1.5
            elif turn_count <= matron["turn_limit"]:
                turn_bonus = "standard"
                reward_mult = 1.0
            else:
                # Should not happen (dismissed would be true)
                turn_bonus = "slow"
                reward_mult = 0.5
            
            # Base rewards
            base_rikis = ConfigManager.get(
                f"matron_rewards.sector_{matron['sector_id']}_rikis", 5000
            )
            base_xp = ConfigManager.get(
                f"matron_rewards.sector_{matron['sector_id']}_xp", 200
            )
            
            # Apply turn bonus
            rewards = {
                "rikis": int(base_rikis * reward_mult),
                "xp": int(base_xp * reward_mult),
                "turn_bonus": turn_bonus
            }
            
            # Sector boss bonus (sublevel 9)
            if matron["is_sector_boss"]:
                rewards["sector_clear_bonus"] = {
                    "rikis": base_rikis,
                    "silver_token": 1
                }
            
            # Grant rewards
            await ResourceService.grant_resources(
                session=session,
                player=player,
                resources={"rikis": rewards["rikis"]},
                source="matron_victory",
                context={
                    "sector": matron["sector_id"],
                    "sublevel": matron["sublevel"],
                    "turns": turn_count,
                    "bonus": turn_bonus
                }
            )
            
            # XP
            from src.features.player.service import PlayerService
            await PlayerService.add_xp_and_level_up(player, rewards["xp"])
            
            # Tokens (if sector boss)
            if matron["is_sector_boss"]:
                from src.features.ascension.token_service import TokenService
                await TokenService.grant_token(
                    session=session,
                    player_id=player.discord_id,
                    token_type="silver",
                    quantity=1,
                    source=f"sector_{matron['sector_id']}_boss"
                )
            
            # Log transaction
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="matron_victory",
                details={
                    "matron": matron["name"],
                    "sector": matron["sector_id"],
                    "sublevel": matron["sublevel"],
                    "turns": turn_count,
                    "damage": damage,
                    "bonus": turn_bonus,
                    "rewards": rewards
                },
                context="exploration_combat"
            )
            
            logger.info(
                f"Player {player.discord_id} defeated matron {matron['name']} "
                f"in {turn_count} turns ({turn_bonus} clear)"
            )
            
            result["turn_bonus"] = turn_bonus
            result["rewards"] = rewards
        
        elif dismissed:
            # Dismissed after turn limit
            dismissal_text = MatronService.get_dismissal_line(matron, turn_count)
            
            # Log dismissal
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="matron_dismissed",
                details={
                    "matron": matron["name"],
                    "sector": matron["sector_id"],
                    "sublevel": matron["sublevel"],
                    "turns": turn_count,
                    "stamina_wasted": stamina_cost
                },
                context="exploration_combat"
            )
            
            logger.info(
                f"Player {player.discord_id} dismissed by matron {matron['name']} "
                f"after {turn_count} turns"
            )
            
            result["dismissal_text"] = dismissal_text
        
        await session.flush()
        
        return result
    
    # ========================================================================
    # UTILITY
    # ========================================================================
    
    @staticmethod
    def get_attack_cost(attack_type: str) -> Dict[str, int]:
        """
        Get resource costs for attack type.
        
        Returns:
            {"stamina": int, "gems": int}
        """
        costs = {
            "x1": {"stamina": 1, "gems": 0},
            "x3": {"stamina": 3, "gems": 0},
            "x10": {"stamina": 10, "gems": 10}
        }
        return costs.get(attack_type, {"stamina": 1, "gems": 0})
    
    @staticmethod
    def get_dismissal_line(matron: Dict[str, Any], turns_taken: int) -> str:
        """Get flavor text for matron dismissal."""
        # Sector boss special lines
        if matron["is_sector_boss"]:
            sector_id = matron["sector_id"]
            if sector_id in MATRON_DISMISSAL_LINES["special"]:
                return MATRON_DISMISSAL_LINES["special"][sector_id]
        
        # Generic lines by turn range
        if turns_taken <= 25:
            pool = MATRON_DISMISSAL_LINES["early"]
        elif turns_taken <= 30:
            pool = MATRON_DISMISSAL_LINES["mid"]
        else:
            pool = MATRON_DISMISSAL_LINES["late"]
        
        line = random.choice(pool)
        return line.format(matron_name=matron["name"])