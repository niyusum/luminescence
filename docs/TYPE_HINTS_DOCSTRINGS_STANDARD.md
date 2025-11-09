# Type Hints and Docstrings Standard (QUAL-05)

**Status**: ✅ Standard Defined
**Date**: 2025-01-08
**Compliance**: Python PEP 484 (Type Hints) & PEP 257 (Docstring Conventions)

---

## 📋 Overview

All public methods, functions, and classes **MUST** have:
1. **Type hints** for all parameters and return values
2. **Comprehensive docstrings** in Google or NumPy style

This ensures:
- Better IDE autocomplete and type checking
- Self-documenting code
- Easier onboarding for new developers
- Fewer runtime type errors

---

## ✅ Type Hints Standard

### Required Type Hints

**ALL** of the following must have type hints:
- Function parameters
- Return types
- Class attributes
- Module-level variables (when non-obvious)

### Correct Examples

```python
from typing import Dict, List, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession

# Service method
async def get_player_maidens(
    session: AsyncSession,
    player_id: int,
    tier_filter: Optional[int] = None,
    locked_only: bool = False
) -> List[Dict[str, Any]]:
    """Retrieve all maidens owned by player."""
    # Implementation...
    return results

# Helper method with complex types
def calculate_fusion_rate(
    base_rate: float,
    tier: int,
    event_bonus: float = 0.0
) -> float:
    """Calculate final fusion success rate."""
    return min(base_rate + event_bonus, 100.0)

# Class with typed attributes
class FusionResult:
    """Result of a fusion attempt."""

    success: bool
    tier: int
    result_maiden_id: Optional[int]
    shards_gained: int

    def __init__(
        self,
        success: bool,
        tier: int,
        result_maiden_id: Optional[int] = None,
        shards_gained: int = 0
    ) -> None:
        self.success = success
        self.tier = tier
        self.result_maiden_id = result_maiden_id
        self.shards_gained = shards_gained
```

### Special Cases

#### Discord.py Types

```python
import discord
from discord.ext import commands

async def my_command(self, ctx: commands.Context, amount: int) -> None:
    """Command with Discord types."""
    pass

async def button_callback(
    self,
    interaction: discord.Interaction,
    button: discord.ui.Button
) -> None:
    """Button callback with interaction type."""
    pass
```

#### Union Types

```python
from typing import Union

def get_cost(tier: Union[int, str]) -> int:
    """Get cost, accepting tier as int or string."""
    if isinstance(tier, str):
        tier = int(tier.replace("tier_", ""))
    return tier * 100
```

#### Generics

```python
from typing import TypeVar, Generic, List

T = TypeVar('T')

class Cache(Generic[T]):
    """Generic cache for any type."""

    def __init__(self) -> None:
        self._data: Dict[str, T] = {}

    def get(self, key: str) -> Optional[T]:
        return self._data.get(key)

    def set(self, key: str, value: T) -> None:
        self._data[key] = value
```

---

## 📝 Docstring Standard

### Required Elements

Every public method/function/class **MUST** have:

1. **Summary line**: One-line description (imperative mood)
2. **Extended description** (if needed)
3. **Args section**: Document all parameters
4. **Returns section**: Document return value(s)
5. **Raises section**: Document exceptions raised
6. **Example section** (optional but recommended for complex logic)

### Google Style (Preferred)

```python
async def execute_fusion(
    session: AsyncSession,
    player_id: int,
    maiden_ids: List[int],
    use_shards: bool = False
) -> Dict[str, Any]:
    """
    Execute complete fusion workflow with pessimistic locking.

    Performs a full transaction-safe fusion process including lock acquisition,
    validation, resource consumption, RNG rolling, and transaction logging.

    Args:
        session: Database session (transaction managed by caller)
        player_id: Player's Discord ID
        maiden_ids: List of exactly 2 maiden IDs to fuse
        use_shards: Whether to use shards for guaranteed fusion (default False)

    Returns:
        Dictionary with fusion results:
            - success (bool): Whether fusion succeeded
            - tier (int): Input maiden tier
            - result_tier (int): Output maiden tier (if success)
            - result_maiden_id (int): New maiden ID (if success)
            - cost (int): Rikis consumed

    Raises:
        InvalidFusionError: If maiden_ids length != 2 or tier >= 12
        MaidenNotFoundError: If maidens don't exist or aren't owned
        InsufficientResourcesError: If player lacks rikis or shards
        RuntimeError: If cannot acquire fusion lock

    Example:
        >>> async with DatabaseService.get_transaction() as session:
        ...     result = await FusionService.execute_fusion(
        ...         session, player_id, [maiden_id1, maiden_id2]
        ...     )
        ...     if result["success"]:
        ...         print(f"Created Tier {result['result_tier']} maiden!")
    """
    # Implementation...
```

### NumPy Style (Alternative)

```python
def calculate_fusion_cost(tier: int) -> int:
    """
    Calculate rikis cost for fusing maidens of given tier.

    The cost increases exponentially with tier level following the formula:
    cost = base_cost * (multiplier ^ tier)

    Parameters
    ----------
    tier : int
        Tier of the maidens being fused (1-11)

    Returns
    -------
    int
        Rikis cost for the fusion

    Examples
    --------
    >>> calculate_fusion_cost(1)
    100
    >>> calculate_fusion_cost(5)
    10000
    """
    base_cost = ConfigManager.get("fusion_system.base_cost", 100)
    multiplier = ConfigManager.get("fusion_system.cost_multiplier", 2.0)
    return int(base_cost * (multiplier ** tier))
```

### Short Methods

For simple, self-explanatory methods, a one-line docstring is acceptable:

```python
def is_locked(self) -> bool:
    """Return whether the maiden is locked."""
    return self.is_locked

def get_display_name(self) -> str:
    """Return the maiden's formatted display name."""
    return f"{self.tier}★ {self.name}"
```

### Property Docstrings

```python
@property
def total_power(self) -> int:
    """
    Total combat power from all maidens.

    Calculated as the sum of individual maiden power values,
    updated automatically when maidens are added or removed.
    """
    return self._total_power

@property
def is_max_level(self) -> bool:
    """Return True if player is at maximum level."""
    max_level = ConfigManager.get("player_system.max_level", 100)
    return self.level >= max_level
```

---

## 🔴 Incorrect Examples

### ❌ Missing Type Hints

```python
# WRONG - No type hints
def calculate_damage(attack, defense):
    return max(attack - defense, 0)

# CORRECT
def calculate_damage(attack: int, defense: int) -> int:
    """Calculate damage dealt in combat."""
    return max(attack - defense, 0)
```

### ❌ Missing Return Type

```python
# WRONG - No return type
async def get_player(session: AsyncSession, player_id: int):
    return await session.get(Player, player_id)

# CORRECT
async def get_player(
    session: AsyncSession,
    player_id: int
) -> Optional[Player]:
    """Retrieve player by Discord ID."""
    return await session.get(Player, player_id)
```

### ❌ Incomplete Docstring

```python
# WRONG - No Args or Returns sections
def fusion_cost(tier):
    """Get cost."""
    return tier * 100

# CORRECT
def fusion_cost(tier: int) -> int:
    """
    Calculate fusion cost for given tier.

    Args:
        tier: Maiden tier level (1-11)

    Returns:
        Rikis cost for fusion
    """
    return tier * 100
```

### ❌ Vague Documentation

```python
# WRONG - Vague description
def do_stuff(session, data):
    """Do stuff with data."""
    pass

# CORRECT
async def process_daily_rewards(
    session: AsyncSession,
    reward_data: Dict[str, int]
) -> None:
    """
    Grant daily login rewards to player.

    Validates reward amounts, updates player resources via ResourceService,
    and logs transaction for audit trail.

    Args:
        session: Active database transaction
        reward_data: Dictionary mapping resource names to amounts
    """
    pass
```

---

## 🛠️ Special Cases

### Discord Cog Commands

```python
@commands.command(
    name="fuse",
    aliases=["fusion"],
    description="Fuse two maidens to create a higher tier maiden"
)
@ratelimit(uses=15, per_seconds=60, command_name="fusion")
async def fusion(self, ctx: commands.Context) -> None:
    """
    Open the fusion interface.

    Allows players to select two maidens of the same tier to fuse into
    a higher tier maiden. Shows available maidens, fusion rates, and
    provides an interactive selection UI.

    Args:
        ctx: Discord command context

    Raises:
        RateLimitError: If command used too frequently
    """
    # Implementation...
```

### View Callbacks

```python
@discord.ui.button(label="Execute Fusion", style=discord.ButtonStyle.green)
async def execute_button(
    self,
    interaction: discord.Interaction,
    button: discord.ui.Button
) -> None:
    """
    Execute the fusion attempt.

    Validates user authorization, performs fusion via FusionService,
    and updates the UI with results.

    Args:
        interaction: Discord interaction from button press
        button: Button component that triggered callback
    """
    # Implementation...
```

### Private Methods

Private methods (starting with `_`) still need docstrings:

```python
def _validate_fusion_requirements(
    self,
    player: Player,
    maiden_1: Maiden,
    maiden_2: Maiden
) -> None:
    """
    Validate that fusion requirements are met.

    Internal helper for execute_fusion. Checks ownership, tier matching,
    quantity requirements, and tier limits.

    Args:
        player: Player attempting fusion
        maiden_1: First maiden to fuse
        maiden_2: Second maiden to fuse

    Raises:
        InvalidFusionError: If requirements not met
        MaidenNotFoundError: If maidens not owned by player
    """
    # Implementation...
```

---

## 📊 Compliance Checklist

When writing or reviewing code:

### Type Hints
- [ ] All function parameters have type hints
- [ ] All function return types specified (use `-> None` if no return)
- [ ] Complex types use `typing` module (`List`, `Dict`, `Optional`, etc.)
- [ ] Discord types use proper imports (`discord.Interaction`, `commands.Context`)
- [ ] No use of `Any` type unless absolutely necessary

### Docstrings
- [ ] All public methods have docstrings
- [ ] Docstring starts with imperative verb ("Calculate...", "Return...", "Execute...")
- [ ] Args section documents all parameters
- [ ] Returns section documents return value (if not None)
- [ ] Raises section documents exceptions
- [ ] Examples provided for complex methods
- [ ] Private methods (`_method`) have docstrings

---

## 🔍 Automated Checking

### MyPy Configuration

Add to `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
```

### Pydocstyle Configuration

```toml
[tool.pydocstyle]
convention = "google"
add_ignore = ["D100", "D104"]  # Allow missing docstrings in __init__.py
```

### Running Checks

```bash
# Type checking
mypy src/

# Docstring linting
pydocstyle src/
```

---

## 🎯 Migration Priority

### High Priority (Public APIs)
1. Service layer methods (FusionService, PlayerService, ResourceService)
2. Database models (Player, Maiden, MaidenBase)
3. Cog command methods
4. Core utilities (validators, decorators)

### Medium Priority
5. View callbacks and UI interactions
6. Helper methods in services
7. Configuration classes

### Low Priority
8. Simple `__init__` methods
9. One-line property getters/setters
10. Private implementation details (when self-explanatory)

---

## 📖 Resources

- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- [PEP 257 - Docstring Conventions](https://peps.python.org/pep-0257/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [MyPy Documentation](https://mypy.readthedocs.io/)

---

## ✨ Benefits

✅ **IDE Support**: Better autocomplete and inline documentation
✅ **Type Safety**: Catch bugs before runtime
✅ **Self-Documenting**: Code intent is clear from signatures
✅ **Easier Refactoring**: Type checker validates changes
✅ **Better Onboarding**: New developers understand code faster
✅ **Maintainability**: Clear contracts between functions

---

**Last Updated**: 2025-01-08
**Maintained By**: RIKIBOT Core Team
