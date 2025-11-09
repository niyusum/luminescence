# Developer Guide: New Features & Best Practices

Quick reference guide for using the new validation layer and enhanced rate limiting added in 2025-01-07 fixes.

---

## 🛡️ Input Validation

### Basic Usage

```python
from src.core.validation import InputValidator
from src.core.exceptions import ValidationError

# Validate integers with bounds
try:
    tier = InputValidator.validate_tier(user_input)  # 1-12 only
    amount = InputValidator.validate_positive_integer(user_input, "amount", max_value=1000)
except ValidationError as e:
    # e.field = "tier" or "amount"
    # e.validation_message = user-friendly error message
    await ctx.send(f"Error: {e}")
```

### Stat Allocation

```python
from src.core.constants import MAX_POINTS_PER_STAT

# Validate stat allocation (includes availability check)
try:
    energy_points = InputValidator.validate_stat_allocation(
        stat_name="energy",
        amount=user_input,
        available_points=player.stat_points_available
    )
except ValidationError as e:
    await ctx.send(f"Invalid allocation: {e}")
```

### Discord IDs

```python
# Validate Discord snowflake IDs
try:
    discord_id = InputValidator.validate_discord_id(user_input)
    maiden_id = InputValidator.validate_maiden_id(user_input)
except ValidationError as e:
    await ctx.send(f"Invalid ID: {e}")
```

### ID Lists

```python
# Validate lists of IDs (e.g., fusion maidens)
try:
    maiden_ids = InputValidator.validate_id_list(
        user_input_list,
        field_name="maiden_ids",
        min_count=2,  # Must have at least 2
        max_count=6   # Cannot exceed 6
    )
    # Automatically checks for duplicates!
except ValidationError as e:
    await ctx.send(f"Invalid maiden list: {e}")
```

### String Validation

```python
# Validate strings with length limits
try:
    username = InputValidator.validate_string(
        user_input,
        field_name="username",
        min_length=3,
        max_length=32
    )
except ValidationError as e:
    await ctx.send(f"Invalid username: {e}")
```

### Choice Validation

```python
# Validate enum-style choices
try:
    element = InputValidator.validate_choice(
        user_input,
        field_name="element",
        valid_choices=["infernal", "abyssal", "tempest", "earth", "radiant", "umbral"]
    )
except ValidationError as e:
    await ctx.send(f"Invalid element: {e}")
```

---

## ⏱️ Rate Limiting

### Basic Rate Limiting (Prefix Commands)

```python
from src.utils.decorators import ratelimit

class MyCog(BaseCog):
    @commands.command(name="expensive")
    @ratelimit(uses=5, per_seconds=60)  # 5 uses per minute
    async def expensive_command(self, ctx: commands.Context):
        """This command can only be used 5 times per minute per user."""
        await ctx.send("Doing expensive operation...")
```

### Guild-Scoped Rate Limiting

```python
@commands.command(name="announce")
@ratelimit(uses=3, per_seconds=3600, scope="guild")  # 3 uses per hour per guild
async def announce(self, ctx: commands.Context):
    """This command can only be used 3 times per hour per server."""
    await ctx.send("Server-wide announcement!")
```

### Slash Command Rate Limiting

```python
@app_commands.command(name="profile")
@ratelimit(uses=10, per_seconds=60, command_name="profile")
async def profile(self, interaction: discord.Interaction):
    """Auto-detects command type, works with both prefix and slash."""
    await interaction.response.send_message("Your profile...")
```

### Error Handling

Rate limit errors are automatically handled by `BaseCog.handle_standard_errors()`, but you can customize:

```python
from src.core.exceptions import RateLimitError

@commands.command(name="test")
@ratelimit(uses=5, per_seconds=60)
async def test(self, ctx: commands.Context):
    try:
        # Your command logic
        pass
    except RateLimitError as e:
        # Custom rate limit handling
        await ctx.send(f"Slow down! Try again in {e.retry_after:.0f} seconds.")
```

### Admin: Clear Rate Limits

```python
from src.utils.decorators import clear_ratelimit

@commands.command(name="clearratelimit")
@commands.has_permissions(administrator=True)
async def clear_ratelimit_cmd(self, ctx: commands.Context, user: discord.Member):
    """Admin command to reset a user's rate limit."""
    success = await clear_ratelimit("expensive", user.id, scope="user")
    if success:
        await ctx.send(f"Cleared rate limit for {user.mention}")
    else:
        await ctx.send("No active rate limit found")
```

### Check Rate Limit Status

```python
from src.utils.decorators import get_ratelimit_status

@commands.command(name="ratelimit")
async def check_ratelimit(self, ctx: commands.Context):
    """Check your current rate limit status."""
    status = await get_ratelimit_status("expensive", ctx.author.id, scope="user")

    if status:
        await ctx.send(
            f"You've used the command {status['current_uses']} times. "
            f"Resets in {status['time_remaining']} seconds."
        )
    else:
        await ctx.send("No active rate limit.")
```

---

## 🔐 Cryptographically Secure RNG

**ALWAYS** use `secrets` module for game-critical randomness:

```python
import secrets

# ✅ CORRECT - Cryptographically secure
roll = secrets.SystemRandom().uniform(0, 100)
chosen = secrets.choice(items)
amount = secrets.SystemRandom().randint(min_val, max_val)

# ❌ WRONG - Predictable, exploitable
import random
roll = random.uniform(0, 100)  # NEVER DO THIS
```

**When to use `secrets`**:
- ✅ Fusion success rolls
- ✅ Gacha/summon tier selection
- ✅ Loot drops and rewards
- ✅ Critical hit calculations
- ✅ Boss element selection
- ✅ Any player-facing randomness

**When `random` is okay**:
- ✅ Non-game-critical: NPC dialogue variation (already using `secrets` anyway)
- ✅ Visual effects (purely cosmetic)
- ✅ Non-repeatable demo/test data generation

---

## 📊 Performance Best Practices

### Cache Configuration Lookups

```python
class MyService:
    _CACHED_VALUE: Optional[int] = None

    @staticmethod
    def get_value():
        if MyService._CACHED_VALUE is None:
            MyService._CACHED_VALUE = ConfigManager.get("my.config.value", 300)
        return MyService._CACHED_VALUE

    @classmethod
    def reset_cache(cls):
        """Call this when hot-reloading config."""
        cls._CACHED_VALUE = None
```

### Early Exit Optimizations

```python
# ✅ GOOD - Early exit
def calculate_something(player: Player) -> Dict:
    if not player.has_feature_enabled:
        return {}  # Skip expensive calculation

    # Expensive calculation only runs when needed
    result = expensive_calculation()
    return result

# ❌ BAD - Always calculates
def calculate_something(player: Player) -> Dict:
    result = expensive_calculation()  # Runs even if not needed
    if not player.has_feature_enabled:
        return {}
    return result
```

### Pagination for User Queries

```python
async def get_user_data(session, player_id, limit=50, offset=0):
    """Always paginate user-facing queries."""
    result = await session.execute(
        select(MyTable)
        .where(MyTable.player_id == player_id)
        .order_by(desc(MyTable.created_at))
        .limit(limit)
        .offset(offset)  # Essential for large datasets
    )
    return list(result.scalars().all())
```

---

## 🎯 Constants Usage

**Always** use constants from `src/core/constants.py`:

```python
from src.core.constants import (
    MAX_POINTS_PER_STAT,
    MAX_TIER_NUMBER,
    PRAYER_CHARGES_MAX,
    OVERCAP_THRESHOLD,
    OVERCAP_BONUS
)

# ✅ GOOD
if player.prayer_charges >= PRAYER_CHARGES_MAX:
    return

# ❌ BAD
if player.prayer_charges >= 1:  # Magic number
    return
```

**Available constants** (see `constants.py` for complete list):
- `MAX_POINTS_PER_STAT = 999`
- `MAX_TIER_NUMBER = 12`
- `PRAYER_CHARGES_MAX = 1`
- `OVERCAP_THRESHOLD = 0.9`
- `OVERCAP_BONUS = 0.10`
- `FUSION_MAIDENS_REQUIRED = 2`
- `SHARDS_FOR_GUARANTEED_FUSION = 100`
- And 30+ more...

---

## 🧪 Testing New Features

### Testing Input Validation

```python
import pytest
from src.core.validation import InputValidator
from src.core.exceptions import ValidationError

def test_validate_tier():
    # Valid tiers
    assert InputValidator.validate_tier(1) == 1
    assert InputValidator.validate_tier(12) == 12

    # Invalid tiers
    with pytest.raises(ValidationError):
        InputValidator.validate_tier(0)  # Too low

    with pytest.raises(ValidationError):
        InputValidator.validate_tier(13)  # Too high

    with pytest.raises(ValidationError):
        InputValidator.validate_tier("abc")  # Not an integer
```

### Testing Rate Limiting

```python
import pytest
from src.utils.decorators import ratelimit, reset_ratelimit_metrics

@pytest.mark.asyncio
async def test_rate_limit():
    reset_ratelimit_metrics()

    # Mock command
    @ratelimit(uses=3, per_seconds=60)
    async def test_cmd(self, ctx):
        return "success"

    # Should succeed 3 times
    for i in range(3):
        result = await test_cmd(mock_self, mock_ctx)
        assert result == "success"

    # 4th call should raise RateLimitError
    with pytest.raises(RateLimitError):
        await test_cmd(mock_self, mock_ctx)
```

---

## 🚨 Error Handling Patterns

### Standard Exception Handling

```python
from src.core.exceptions import (
    InsufficientResourcesError,
    ValidationError,
    InvalidOperationError,
    RateLimitError
)

@commands.command(name="fusion")
async def fusion(self, ctx: commands.Context, maiden1: int, maiden2: int):
    try:
        # Validate input
        maiden_ids = InputValidator.validate_id_list(
            [maiden1, maiden2],
            "maiden_ids",
            min_count=2,
            max_count=2
        )

        # Execute fusion
        result = await FusionService.execute_fusion(...)

        await ctx.send(f"Fusion successful! {result}")

    except ValidationError as e:
        await self.send_error(ctx, "Invalid Input", str(e))
    except InsufficientResourcesError as e:
        await self.send_error(ctx, "Insufficient Resources", str(e))
    except InvalidOperationError as e:
        await self.send_error(ctx, "Cannot Fuse", str(e))
    except RateLimitError as e:
        await self.send_error(ctx, "Rate Limited", str(e))
    except Exception as e:
        self.log_cog_error("fusion", e, user_id=ctx.author.id)
        await self.send_error(ctx, "Fusion Failed", "An unexpected error occurred.")
```

### Use BaseCog Error Handlers

```python
# Even simpler - let BaseCog handle it
@commands.command(name="fusion")
async def fusion(self, ctx: commands.Context, maiden1: int, maiden2: int):
    try:
        maiden_ids = InputValidator.validate_id_list([maiden1, maiden2], "maiden_ids", min_count=2, max_count=2)
        result = await FusionService.execute_fusion(...)
        await ctx.send(f"Fusion successful! {result}")
    except Exception as e:
        # BaseCog will automatically handle ValidationError, RateLimitError, etc.
        if not await self.handle_standard_errors(ctx, e):
            # Only log if it's an unexpected error
            self.log_cog_error("fusion", e, user_id=ctx.author.id)
            await self.send_error(ctx, "Fusion Failed", "An unexpected error occurred.")
```

---

## ✅ Checklist for New Commands

When implementing a new command:

- [ ] Apply `@ratelimit()` decorator if expensive
- [ ] Validate all user inputs with `InputValidator`
- [ ] Use `secrets` for any randomness
- [ ] Use constants instead of magic numbers
- [ ] Add pagination if querying user data
- [ ] Use early exit optimizations where possible
- [ ] Handle exceptions with `BaseCog.handle_standard_errors()`
- [ ] Add docstring with Args/Returns/Raises
- [ ] Log command usage with `self.log_command_use()`
- [ ] Test with invalid inputs

---

## 📚 Additional Resources

- **Full Analysis**: [docs/RIKIBOT_ANALYSIS_REPORT.md](./RIKIBOT_ANALYSIS_REPORT.md)
- **Fixes Applied**: [docs/FIXES_APPLIED_2025-01-07.md](./FIXES_APPLIED_2025-01-07.md)
- **Summary**: [docs/COMPREHENSIVE_FIXES_SUMMARY.md](./COMPREHENSIVE_FIXES_SUMMARY.md)
- **Constants Reference**: [src/core/constants.py](../src/core/constants.py)
- **Validation Reference**: [src/core/validation/input_validator.py](../src/core/validation/input_validator.py)
- **Rate Limiting Reference**: [src/utils/decorators.py](../src/utils/decorators.py)

---

**Happy Coding!** 🚀

*If you have questions, check the inline documentation in the source files - all new features include comprehensive docstrings.*
