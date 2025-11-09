# Error Handling Standardization Guide (QUAL-04)

**Status**: ✅ **COMPLETED - 100% COMPLIANT**
**Date**: 2025-01-08 (Completed: 2025-01-08)
**Compliance**: RIKI LAW Article VII (Standardized Error Handling)
**Achievement**: All 15/15 cogs now use standardized error handling

---

## 📋 Overview

All Discord command cogs **MUST** use the standardized error handling pattern provided by `BaseCog`. This ensures:
- Consistent user experience across all commands
- Comprehensive error logging with structured context
- Graceful degradation for unexpected errors
- DRY principle (Don't Repeat Yourself)

---

## ✅ Correct Pattern

```python
from src.core.bot.base_cog import BaseCog
from src.core.exceptions import (
    InsufficientResourcesError,
    InvalidOperationError,
    CooldownError,
    NotFoundError,
    RateLimitError
)
import time

class MyCog(BaseCog):
    @commands.command(name="mycommand")
    async def my_command(self, ctx: commands.Context, arg: str):
        """Command with standardized error handling."""
        start_time = time.perf_counter()

        try:
            # Command logic here
            async with DatabaseService.get_transaction() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return

                # Do something...
                await SomeService.do_something(session, player, arg)

                await self.send_success(ctx, "Success!", "Operation completed")

            # Log successful execution
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "mycommand",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

        except Exception as e:
            # Log error with context
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "mycommand",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

            # Use standardized error handling
            if not await self.handle_standard_errors(ctx, e):
                # Fallback for unexpected errors
                await self.send_error(
                    ctx,
                    "Command Failed",
                    "An unexpected error occurred. The issue has been logged."
                )
```

---

## 🔴 Incorrect Patterns (Do NOT Use)

### ❌ Manually Handling Standard Exceptions

```python
# WRONG - Duplicates BaseCog logic
except InsufficientResourcesError as e:
    embed = EmbedBuilder.error(
        title="Insufficient Resources",
        description=f"You need {e.required}, but only have {e.current}"
    )
    await ctx.send(embed=embed)

except ValidationError as e:
    embed = EmbedBuilder.error(
        title="Invalid Input",
        description=str(e)
    )
    await ctx.send(embed=embed)

except Exception as e:
    logger.error(f"Error: {e}")
    await ctx.send("Something went wrong")
```

**Problem**: This pattern:
- Duplicates logic from `BaseCog.handle_standard_errors()`
- Inconsistent error messages across cogs
- Missing structured logging
- No metrics tracking

### ❌ Not Checking Return Value

```python
# WRONG - No fallback for unhandled exceptions
except Exception as e:
    self.log_cog_error("command", e)
    await self.handle_standard_errors(ctx, e)
    # What if handle_standard_errors returns False (unhandled exception)?
```

**Problem**: If `handle_standard_errors()` doesn't recognize the exception (returns `False`), the user gets no feedback.

### ❌ Missing Error Logging

```python
# WRONG - No logging
except Exception as e:
    await self.send_error(ctx, "Error", str(e))
```

**Problem**: No observability for debugging or monitoring.

---

## 📚 What `handle_standard_errors()` Handles

The `BaseCog.handle_standard_errors()` method automatically handles these exceptions:

| Exception | User Message | Help Text |
|-----------|--------------|-----------|
| `InsufficientResourcesError` | "Insufficient Resources" | "Check your inventory and try again." |
| `InvalidOperationError` | "Invalid Operation" | *(exception message)* |
| `CooldownError` | "Cooldown Active" | "Please wait before retrying." |
| `RateLimitError` | "Rate Limit Exceeded" | "You're using this command too frequently. Please slow down." |
| `NotFoundError` | "Not Found" | *(exception message)* |

**Returns**:
- `True` if the exception was handled
- `False` if the exception was not recognized

---

## 🛠️ Implementation Checklist

When creating or refactoring a command:

- [ ] **Import BaseCog**: Inherit from `BaseCog`
- [ ] **Add timer**: Use `time.perf_counter()` at command start
- [ ] **Wrap in try/except**: All command logic in try block
- [ ] **Log success**: Call `self.log_command_use()` after success
- [ ] **Catch Exception**: Single `except Exception as e:` block
- [ ] **Log error**: Call `self.log_cog_error()` in exception handler
- [ ] **Use standard handler**: Call `if not await self.handle_standard_errors(ctx, e):`
- [ ] **Add fallback**: Generic error message if handler returns False

---

## 📊 Current Compliance Status

| Cog | Uses `handle_standard_errors()` | Compliant |
|-----|----------------------------------|-----------|
| **ascension** | ✅ Yes | ✅ Compliant |
| **combat** | ✅ Yes | ✅ Compliant |
| **daily** | ✅ Yes | ✅ Compliant |
| **exploration** | ✅ Yes | ✅ Compliant |
| **fusion** | ✅ Yes | ✅ Compliant |
| **guilds** | ✅ Yes | ✅ Compliant |
| **help** | ✅ Yes | ✅ Compliant |
| **leaderboard** | ✅ Yes | ✅ Compliant |
| **maiden** | ✅ Yes | ✅ Compliant |
| **player** | ✅ Yes | ✅ Compliant |
| **prayer** | ✅ Yes | ✅ Compliant |
| **shrines** | ✅ Yes | ✅ Compliant |
| **summon** | ✅ Yes | ✅ Compliant |
| **system** | ✅ Yes | ✅ Compliant |
| **tutorial** | ✅ Yes | ✅ Compliant |

**Compliance Rate**: 15/15 (100%) ✅
**Status**: ✅ **ALL COGS COMPLIANT**

---

## 🎯 Migration Guide

### Step 1: Add Required Imports

```python
from src.core.bot.base_cog import BaseCog
import time
```

### Step 2: Remove Manual Exception Handling

**Before**:
```python
except InsufficientResourcesError as e:
    embed = EmbedBuilder.error(...)
    await ctx.send(embed=embed)

except ValidationError as e:
    embed = EmbedBuilder.error(...)
    await ctx.send(embed=embed)

except Exception as e:
    logger.error(f"Error: {e}")
```

**After**:
```python
except Exception as e:
    latency = (time.perf_counter() - start_time) * 1000
    self.log_cog_error(
        "command_name", e,
        user_id=ctx.author.id,
        latency_ms=round(latency, 2)
    )
    if not await self.handle_standard_errors(ctx, e):
        await self.send_error(ctx, "Error", "Something went wrong")
```

### Step 3: Add Timing and Metrics

```python
start_time = time.perf_counter()

try:
    # Command logic...

    # Log success
    latency = (time.perf_counter() - start_time) * 1000
    self.log_command_use("command", ctx.author.id, latency_ms=round(latency, 2))

except Exception as e:
    # Error handling...
```

---

## 🧪 Testing Checklist

After refactoring a cog:

- [ ] Test with insufficient resources (rikis, grace, energy, etc.)
- [ ] Test with invalid input (malformed arguments)
- [ ] Test during cooldown period
- [ ] Test with rate limiting active
- [ ] Test with non-existent entity (NotFoundError)
- [ ] Test with unexpected database error
- [ ] Verify error messages are user-friendly
- [ ] Verify errors are logged with full context
- [ ] Verify latency metrics are recorded

---

## 🔍 Code Review Guidelines

When reviewing pull requests:

1. **Check for manual exception handling**: If a PR manually handles `InsufficientResourcesError`, `ValidationError`, `CooldownError`, etc., request refactor to use `handle_standard_errors()`

2. **Verify fallback exists**: Every `handle_standard_errors()` call must check return value:
   ```python
   if not await self.handle_standard_errors(ctx, e):
       # Fallback required
   ```

3. **Check logging**: All exceptions must be logged with `self.log_cog_error()`

4. **Verify metrics**: Success path must log command use with `self.log_command_use()`

---

## 📖 Additional Resources

- [base_cog.py](src/core/bot/base_cog.py) - BaseCog implementation
- [exceptions.py](src/core/exceptions.py) - Custom exception definitions
- [RIKI_LAW.md](docs/riki_law.md) - Article VII (Error Handling)

---

## 🚀 Benefits of Standardization

✅ **Consistency**: Same error experience across all commands
✅ **Maintainability**: Single source of truth for error messages
✅ **Observability**: Structured logging with full context
✅ **User Experience**: User-friendly, actionable error messages
✅ **DRY Principle**: No duplicate error handling code
✅ **Metrics**: Comprehensive latency and error tracking

---

**Last Updated**: 2025-01-08
**Maintained By**: RIKIBOT Core Team
