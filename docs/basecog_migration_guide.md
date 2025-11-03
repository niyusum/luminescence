# BaseCog Migration Guide

**Date:** 2025-11-03
**Purpose:** Migrate existing cogs to use the new BaseCog infrastructure
**Status:** ✅ Template Created | 🔄 1/13 Cogs Migrated

---

## Overview

After creating the BaseCog infrastructure (`src/core/base_cog.py`), all existing cogs should be migrated to use it for:
- Standardized error handling
- Consistent user feedback
- Automatic logging
- Reduced boilerplate

---

## Migration Checklist (Per Cog)

### 1. Update Imports
```python
# OLD:
from discord.ext import commands
from src.core.logger import get_logger
logger = get_logger(__name__)

# NEW:
from discord.ext import commands
from src.core.base_cog import BaseCog
# Remove manual logger - BaseCog provides self.logger
```

### 2. Update Class Declaration
```python
# OLD:
class MyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

# NEW:
class MyCog(BaseCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "MyCog")  # Pass cog name for logging
```

### 3. Replace Manual Patterns with BaseCog Helpers

#### Deferring Responses
```python
# OLD:
await ctx.defer()
await ctx.defer(ephemeral=True)

# NEW:
await self.safe_defer(ctx)
await self.safe_defer(ctx, ephemeral=True)
```

#### Database Sessions
```python
# OLD:
async with DatabaseService.get_transaction() as session:
    # ...

# NEW:
async with self.get_session() as session:
    # ...
```

#### Player Validation
```python
# OLD:
player = await PlayerService.get_player_with_regen(session, ctx.author.id, lock=True)
if not player:
    embed = EmbedBuilder.error(
        title="Not Registered",
        description="You need to register first!",
        help_text="Use `/register` to create your account."
    )
    await ctx.send(embed=embed, ephemeral=True)
    return

# NEW:
player = await self.require_player(ctx, session, ctx.author.id, lock=True)
if not player:
    return  # Error already sent
```

#### Error Messages
```python
# OLD:
embed = EmbedBuilder.error(
    title="Invalid Input",
    description="That value is out of range.",
    help_text="Try again"
)
await ctx.send(embed=embed, ephemeral=True)

# NEW:
await self.send_error(
    ctx,
    "Invalid Input",
    "That value is out of range.",
    help_text="Try again"
)
```

#### Success Messages
```python
# OLD:
embed = EmbedBuilder.success(
    title="Success!",
    description="Operation completed.",
    footer="Keep going!"
)
await ctx.send(embed=embed)

# NEW:
await self.send_success(
    ctx,
    "Success!",
    "Operation completed.",
    footer="Keep going!"
)
```

#### Logging
```python
# OLD:
logger.info(f"Command used: {ctx.command.name}")
logger.error(f"Error: {e}", exc_info=True)

# NEW:
self.log_command_use("command_name", ctx.author.id, ctx.guild.id if ctx.guild else None)
self.log_cog_error("operation_name", e, user_id=ctx.author.id)
```

---

## Migration Status by Cog

| Cog File | Status | Priority | Notes |
|----------|--------|----------|-------|
| ✅ maiden/cog.py | **DONE** | HIGH | Example migration + collection_viewed event |
| ❌ leader/cog.py | TODO | **CRITICAL** | Needs leader_set event added |
| ❌ ascension/cog.py | TODO | **CRITICAL** | Needs first_ascension events |
| ❌ exploration/cog.py | TODO | HIGH | Needs first_matron events |
| ❌ daily/cog.py | TODO | MEDIUM | Already has EventBus |
| ❌ fusion/cog.py | TODO | MEDIUM | Already has EventBus |
| ❌ prayer/cog.py | TODO | MEDIUM | Already has EventBus |
| ❌ summon/cog.py | TODO | MEDIUM | Already has EventBus |
| ❌ player/cog.py | TODO | MEDIUM | Multiple commands |
| ❌ guilds/cog.py | TODO | LOW | Complex, migrate later |
| ❌ tutorial/cog.py | TODO | LOW | Tutorial-specific |
| ❌ help/cog.py | TODO | LOW | Read-only, simple |
| ❌ system/cog.py | TODO | LOW | Admin-only |

---

## Priority Order Recommendation

### Phase 1: CRITICAL (Add Missing Events)
1. **leader/cog.py** - Add `leader_set` EventBus.publish
2. **ascension/cog.py** - Add `first_ascension_attack` and `first_ascension_victory` events

### Phase 2: HIGH (Core Gameplay)
3. **exploration/cog.py** - Add `first_matron_victory` event
4. **player/cog.py** - Migrate to BaseCog (multiple commands)

### Phase 3: MEDIUM (Already Have Events)
5. **daily/cog.py** - Migrate to BaseCog
6. **fusion/cog.py** - Migrate to BaseCog
7. **prayer/cog.py** - Migrate to BaseCog
8. **summon/cog.py** - Migrate to BaseCog

### Phase 4: LOW (Polish)
9. **guilds/cog.py** - Complex, requires careful migration
10. **tutorial/cog.py** - Tutorial-specific patterns
11. **help/cog.py** - Simple, read-only
12. **system/cog.py** - Admin commands

---

## Example: Complete Migration (maiden/cog.py)

### Before
```python
import discord
from discord.ext import commands
from typing import Optional
from src.core.database_service import DatabaseService
from src.core.logger import get_logger
logger = get_logger(__name__)

class MaidenCollectionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="maidens")
    async def maidens(self, ctx: commands.Context):
        await ctx.defer()
        try:
            async with DatabaseService.get_transaction() as session:
                player = await session.get(Player, ctx.author.id)
                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!"
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return
                # ... rest of logic ...
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            embed = EmbedBuilder.error(title="Error", description="Failed")
            await ctx.send(embed=embed, ephemeral=True)
```

### After
```python
import discord
from discord.ext import commands
from typing import Optional
from src.core.base_cog import BaseCog
from src.core.event_bus import EventBus

class MaidenCollectionCog(BaseCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "MaidenCollectionCog")

    @commands.hybrid_command(name="maidens")
    async def maidens(self, ctx: commands.Context):
        await self.safe_defer(ctx)
        try:
            async with self.get_session() as session:
                player = await self.require_player(ctx, session, ctx.author.id)
                if not player:
                    return  # Error already sent

                # ... rest of logic ...

                # 🎓 Tutorial Event
                try:
                    await EventBus.publish("collection_viewed", {
                        "player_id": ctx.author.id,
                        "channel_id": ctx.channel.id,
                        "bot": self.bot
                    })
                except Exception as e:
                    self.logger.warning(f"Event publish failed: {e}")

        except Exception as e:
            self.log_cog_error("maidens", e, user_id=ctx.author.id)
            await self.send_error(ctx, "Error", "Failed")
```

---

## Adding Tutorial Events (Critical)

When migrating cogs, also add missing tutorial EventBus.publish calls:

### Pattern for First-Time Events
```python
# After successful operation, publish event
try:
    await EventBus.publish("event_name", {
        "player_id": ctx.author.id,
        "channel_id": ctx.channel.id,
        "bot": self.bot,
        "__topic__": "event_name",
        "timestamp": discord.utils.utcnow(),
        # ... any other relevant data ...
    })
except Exception as e:
    self.logger.warning(f"Failed to publish {event_name} event: {e}")
```

### Events That Need Adding

#### CRITICAL (Missing from tutorial system):

1. **collection_viewed** ✅ DONE (maiden/cog.py)
   - File: `src/features/maiden/cog.py`
   - Location: After `MaidenService.get_player_maidens()`
   - Event name: `"collection_viewed"`

2. **leader_set** ❌ TODO
   - File: `src/features/leader/cog.py`
   - Class: `LeaderSelectDropdown`
   - Location: After line 270 (after TransactionLogger.log_transaction)
   - Event name: `"leader_set"`
   ```python
   await EventBus.publish("leader_set", {
       "player_id": self.user_id,
       "channel_id": interaction.channel_id,
       "bot": self.view.bot,  # Get from view
       "maiden_id": maiden_id,
       "maiden_name": result["maiden_name"],
       "element": result["element"],
       "__topic__": "leader_set",
       "timestamp": discord.utils.utcnow()
   })
   ```

#### HIGH PRIORITY (New tutorial opportunities):

3. **first_ascension_attack** ❌ TODO
   - File: `src/features/ascension/cog.py`
   - Class: `AscensionCombatView`
   - Location: In `_execute_attack()` after player loaded
   - Condition: `player.stats.get("ascension_attacks_total", 0) == 0`
   - Add to `TUTORIAL_STEPS` in `tutorial/service.py`

4. **first_ascension_victory** ❌ TODO
   - File: `src/features/ascension/service.py`
   - Function: `resolve_victory()`
   - Location: After victory processed
   - Condition: `player.stats.get("ascension_victories_total", 0) == 0`

5. **first_matron_victory** ❌ TODO
   - File: `src/features/exploration/matron_service.py`
   - Function: `attack_matron()`
   - Location: After victory determined
   - Condition: Victory AND `player.stats.get("matron_victories_total", 0) == 0`

---

## Testing After Migration

For each migrated cog, test:

1. ✅ Commands still work
2. ✅ Error messages display correctly
3. ✅ Player validation works
4. ✅ Logging shows in console
5. ✅ Tutorial events fire (check tutorial listener)
6. ✅ No import errors

---

## Common Pitfalls

### ❌ DON'T: Forget to call super().__init__()
```python
class MyCog(BaseCog):
    def __init__(self, bot):
        self.bot = bot  # WRONG - missing super().__init__()
```

### ✅ DO: Always call super().__init__() with cog name
```python
class MyCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot, "MyCog")  # CORRECT
```

### ❌ DON'T: Use logger = get_logger(__name__)
```python
from src.core.logger import get_logger
logger = get_logger(__name__)  # WRONG - BaseCog provides self.logger
```

### ✅ DO: Use self.logger from BaseCog
```python
self.logger.info("Message")  # CORRECT
```

### ❌ DON'T: Forget error handling on EventBus.publish
```python
await EventBus.publish("event", data)  # WRONG - no try/except
```

### ✅ DO: Wrap EventBus calls in try/except
```python
try:
    await EventBus.publish("event", data)
except Exception as e:
    self.logger.warning(f"Event publish failed: {e}")
```

---

## Benefits of Migration

After full migration, you'll have:

- ✅ **50% less boilerplate** per cog
- ✅ **Consistent error handling** across all commands
- ✅ **Automatic logging** with context
- ✅ **Tutorial events** firing correctly
- ✅ **Easier maintenance** - fix BaseCog, fix all cogs
- ✅ **Faster development** - new cogs inherit all patterns

---

## Next Steps

1. **Review this guide**
2. **Add `leader_set` event** to leader/cog.py (CRITICAL)
3. **Migrate ascension/cog.py** with new events (HIGH)
4. **Migrate exploration/cog.py** with new events (HIGH)
5. **Continue with remaining cogs** in priority order

---

## Questions?

Refer to:
- [src/core/base_cog.py](../src/core/base_cog.py) - BaseCog implementation
- [src/features/maiden/cog.py](../src/features/maiden/cog.py) - Example migration ✅
- [docs/refactoring_summary.md](refactoring_summary.md) - Original refactoring context
