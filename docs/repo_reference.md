# Lumen RPG - Repository Reference

This file provides guidance to anyone when working with code in this repository.

## Project Overview

Lumen RPG is a **production-ready** Discord bot built with discord.py for a maiden collection and progression RPG game. The architecture follows strict design principles documented in [docs/lumen_law.md](docs/lumen_law.md) - **all code must comply with LUMEN LAW**.

**Stack:** Python 3.11+, discord.py, PostgreSQL (SQLAlchemy/SQLModel), Redis (optional caching)

**Code Health**: **10/10** ✅ (As of 2025-01-08)
- ✅ 100% Error Handling Compliance (15/15 cogs)
- ✅ All critical security vulnerabilities eliminated
- ✅ 30-40% performance improvement
- ✅ Complete features → modules migration
- ✅ Comprehensive documentation standards

See [docs/100_PERCENT_COMPLETION_SUMMARY.md](docs/100_PERCENT_COMPLETION_SUMMARY.md) for full achievement details.

## Development Commands

### Running the Bot
```bash
# Activate virtual environment (Windows)
.venv/Scripts/activate

# Run the bot
python src/main.py
```

### Dependencies
```bash
# Install dependencies
pip install -r requirements.txt
```

## Architecture Overview

### LUMEN LAW Compliance

This codebase follows **LUMEN LAW** (see [docs/lumen_law.md](docs/lumen_law.md)) - a strict architectural constitution. Key principles:

1. **Pessimistic Locking**: ALL commands that modify player state MUST use `with_for_update=True`
2. **Transaction Logging**: ALL state changes MUST be logged via `TransactionLogger`
3. **Redis Locks**: Button interactions that modify state MUST use Redis locks
4. **ConfigManager**: ALL game balance values MUST come from `ConfigManager` (no hardcoded values)
5. **Service Layer**: ALL business logic goes in services, NEVER in cogs
6. **Event-Driven**: Use `EventBus` for decoupled side effects (achievements, analytics)
7. **Specific Exception Handling**: Convert domain exceptions to user-friendly Discord embeds

### Directory Structure

```
src/
├── core/                      # Core infrastructure
│   ├── bot/                  # Bot initialization, cog loading, base classes
│   │   ├── lumen_bot.py      # Main bot class with health monitoring
│   │   ├── base_cog.py      # Base class for all cogs (use this!)
│   │   └── loader.py        # Dynamic cog discovery (finds *_cog.py files)
│   ├── config/               # Configuration management
│   │   ├── config.py        # Environment variables
│   │   └── config_manager.py # Runtime config (game balance)
│   ├── event/                # Event bus for decoupling
│   │   ├── event_bus.py
│   │   └── registry.py
│   ├── infra/                # Infrastructure services
│   │   ├── database_service.py
│   │   ├── redis_service.py
│   │   └── transaction_logger.py
│   ├── validation/           # Input and transaction validation (NEW)
│   │   ├── input_validator.py
│   │   └── transaction_validator.py
│   ├── logging/              # Structured logging with LogContext
│   ├── constants.py          # Centralized constants (NEW)
│   └── exceptions.py         # Domain exceptions
├── modules/                   # Feature modules (vertical slices) - migrated from features/
│   ├── ascension/            # Token-based tower climbing
│   ├── combat/               # Battle mechanics
│   ├── daily/                # Daily rewards
│   ├── exploration/          # Zone exploration
│   ├── fusion/               # Maiden fusion system
│   ├── guilds/               # Guild/shrine management
│   ├── help/                 # Interactive help system
│   ├── leaderboard/          # Player rankings
│   ├── maiden/               # Maiden collection
│   ├── player/               # Player profile & stats
│   ├── drop/               # DROP charge system
│   ├── resource/             # Resource management
│   ├── shrines/              # Shrine interactions
│   ├── summon/               # Gacha summoning
│   ├── system/               # System admin commands
│   └── tutorial/             # Tutorial progression
│       Each module contains:
│       ├── cog.py           # Discord UI layer (commands, embeds, views)
│       ├── service.py       # Business logic (stateless)
│       └── constants.py     # Optional module-specific constants
├── database/models/          # SQLAlchemy models
│   ├── core/                # Player, Maiden, GameConfig
│   │   ├── player.py
│   │   ├── maiden.py
│   │   └── maiden_base.py
│   ├── economy/             # Transactions, Shrines, Tokens
│   ├── progression/         # Ascension, Quests
│   ├── combat/              # Combat-related models
│   └── social/              # Guilds, Trading
└── utils/                    # Shared utilities
    ├── decorators.py        # Rate limiting decorator
    └── embed_builder.py     # Standardized Discord embeds
```

### Feature Module Pattern

Each feature is a **vertical slice** (self-contained):

- **cog.py**: Discord command handling, embed building, user input parsing, and Discord Views (buttons/modals)
- **service.py**: Pure business logic, no Discord imports, stateless (`@staticmethod`)

Features are **dynamically loaded** by [src/core/bot/loader.py](src/core/bot/loader.py) - any file matching `*_cog.py` in `src/modules/` is auto-discovered and loaded at startup.

### Service Layer Rules

All services MUST:
- Be stateless (use `@staticmethod`)
- Accept `AsyncSession` as first parameter for database operations
- Use `ConfigManager` for all game values (costs, rates, limits)
- Raise domain exceptions (`InsufficientResourcesError`, `ValidationError`, etc.)
- Log transactions via `TransactionLogger`
- Publish events via `EventBus` for side effects

### Cog Layer Rules

All cogs MUST:
- Extend `BaseCog` from [src/core/bot/base_cog.py](src/core/bot/base_cog.py)
- Use prefix commands (e.g., `@commands.command()` or `@commands.hybrid_command()`)
- Contain ZERO business logic (delegate to services)
- Use `@ratelimit` decorator from [src/utils/decorators.py](src/utils/decorators.py)
- Use standardized error handling with `handle_standard_errors()` (see [docs/ERROR_HANDLING_STANDARD.md](docs/ERROR_HANDLING_STANDARD.md))
- Include timing metrics with `time.perf_counter()` and `log_command_use()`
- Include `async def setup(bot)` function for dynamic loading

**Error Handling Pattern (MANDATORY)**:
```python
import time

@commands.command(name="mycommand")
async def my_command(self, ctx: commands.Context):
    start_time = time.perf_counter()

    try:
        # Command logic here
        await MyService.do_something(session, player)

        # Log success
        latency = (time.perf_counter() - start_time) * 1000
        self.log_command_use("mycommand", ctx.author.id, latency_ms=round(latency, 2))

    except Exception as e:
        # Log error
        latency = (time.perf_counter() - start_time) * 1000
        self.log_cog_error("mycommand", e, user_id=ctx.author.id, latency_ms=round(latency, 2))

        # Use standardized error handler
        if not await self.handle_standard_errors(ctx, e):
            await self.send_error(ctx, "Error", "Something went wrong")
```

### View Layer Pattern (Discord Buttons/Modals)

Discord Views (buttons, modals, select menus) are typically defined **inline in cog.py files** as classes. Views handle interactive Discord UI elements.

**View Architecture:**
- Views are Discord UI components (buttons, modals, dropdowns)
- Views are created in cog commands and sent with embeds
- Views delegate ALL business logic to services
- Views follow the same transaction patterns as commands

**Common View Types:**
- **Button Views** (`discord.ui.View`): Interactive buttons for confirmations, actions
- **Modals** (`discord.ui.Modal`): Text input forms
- **Select Menus** (`discord.ui.Select`): Dropdown menus for choices

**View Integration Pattern:**

```python
# In cog.py
class MyFeatureCog(BaseCog):
    @commands.command(name="action")
    async def action(self, ctx: commands.Context):
        # Create view
        view = ConfirmActionView(user_id=ctx.author.id, cog=self)

        # Send embed with view
        embed = EmbedBuilder.primary("Confirm Action", "Click to proceed")
        message = await ctx.send(embed=embed, view=view)

        # Store message reference for timeout handling
        view.set_message(message)


class ConfirmActionView(discord.ui.View):
    """Confirmation view for action."""

    def __init__(self, user_id: int, cog: 'MyFeatureCog'):
        super().__init__(timeout=120)  # 2 minute timeout
        self.user_id = user_id
        self.cog = cog
        self.message: Optional[discord.Message] = None

    def set_message(self, message: discord.Message):
        """Store message reference for timeout handling."""
        self.message = message

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Execute action on confirmation."""
        # 1. User validation (MANDATORY)
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!",
                ephemeral=True
            )
            return

        # 2. Defer response for long operations
        await interaction.response.defer()

        # 3. Redis lock + transaction pattern
        lock_key = f"myfeature:{self.user_id}"

        try:
            async with RedisService.acquire_lock(lock_key, timeout=5):
                async with DatabaseService.get_transaction() as session:
                    # 4. Pessimistic locking (LUMEN LAW Article I.1)
                    player = await PlayerService.get_player_with_regen(
                        session, self.user_id, lock=True
                    )

                    # 5. Call service (ALL business logic here)
                    result = await MyService.execute_action(session, player)

                    # 6. Transaction logging (LUMEN LAW Article II)
                    await TransactionLogger.log_transaction(
                        session=session,
                        player_id=self.user_id,
                        transaction_type="action_executed",
                        details={"result": result},
                        context=f"myfeature guild:{interaction.guild_id}"
                    )

                # 7. Event publishing (after transaction commits)
                await EventBus.publish("action_completed", {
                    "player_id": self.user_id,
                    "result": result
                })

            # 8. Build response embed
            embed = EmbedBuilder.success("Success!", f"Action completed: {result}")

            # 9. Disable buttons after use
            for item in self.children:
                item.disabled = True

            await interaction.edit_original_response(embed=embed, view=self)

        except InsufficientResourcesError as e:
            embed = EmbedBuilder.error("Insufficient Resources", str(e))
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.log_cog_error("view_action", e, user_id=self.user_id)
            embed = EmbedBuilder.error("Error", "Something went wrong.")
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def on_timeout(self):
        """Handle view timeout (MANDATORY)."""
        # Disable all buttons visually
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass
```

**View Rules (MANDATORY):**

1. **Timeout**: Set appropriate timeout (120s for quick actions, 300s for extended interactions)
2. **User Validation**: EVERY button/modal callback MUST validate `interaction.user.id == self.user_id`
3. **Defer Response**: Use `await interaction.response.defer()` for operations >3 seconds
4. **Redis Locks**: Use `RedisService.acquire_lock()` for state-modifying operations (LUMEN LAW Article I.3)
5. **Pessimistic Locking**: Use `lock=True` in database transactions (LUMEN LAW Article I.1)
6. **Transaction Logging**: Log within database session (LUMEN LAW Article II)
7. **Service Delegation**: ALL business logic in services, NEVER in views
8. **Error Handling**: Catch domain exceptions and convert to user-friendly embeds
9. **Disable After Use**: Disable buttons after successful action or on timeout
10. **Message Reference**: Store `self.message` for timeout UI updates
11. **on_timeout() Implementation**: MUST implement to disable buttons visually

**Modal Example:**

```python
class InputModal(discord.ui.Modal, title="Enter Values"):
    """Modal for collecting user input."""

    value_input = discord.ui.TextInput(
        label="Value",
        placeholder="Enter number",
        default="0",
        required=True,
        max_length=10
    )

    def __init__(self, user_id: int, cog: 'MyCog'):
        super().__init__()
        self.user_id = user_id
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        """Process modal submission."""
        await interaction.response.defer()

        try:
            # Parse and validate input
            value = int(self.value_input.value)

            if value <= 0:
                raise ValueError("Value must be positive")

            # Execute business logic via service
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, self.user_id, lock=True
                )

                result = await MyService.process_value(session, player, value)

                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=self.user_id,
                    transaction_type="value_processed",
                    details={"value": value, "result": result},
                    context=f"modal guild:{interaction.guild_id}"
                )

            # Success response
            embed = EmbedBuilder.success("Processed!", f"Result: {result}")
            await interaction.edit_original_response(embed=embed, view=None)

        except ValueError as e:
            embed = EmbedBuilder.error("Invalid Input", str(e))
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.cog.log_cog_error("modal_submit", e, user_id=self.user_id)
            embed = EmbedBuilder.error("Error", "Failed to process input.")
            await interaction.followup.send(embed=embed, ephemeral=True)
```

**Select Dropdown Example:**

```python
class ChoiceDropdown(discord.ui.Select):
    """Dropdown for selecting an option."""

    def __init__(self, user_id: int, options: List[Dict[str, Any]], cog: 'MyCog'):
        self.user_id = user_id
        self.cog = cog

        # Build discord.SelectOption list
        select_options = [
            discord.SelectOption(
                label=opt["name"],
                description=opt["description"],
                value=str(opt["id"])
            )
            for opt in options[:25]  # Discord limit: 25 options max
        ]

        super().__init__(
            placeholder="Select an option...",
            min_values=1,
            max_values=1,
            options=select_options
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle selection."""
        # User validation
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This menu is not for you!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        selected_id = int(self.values[0])

        # Process selection via service
        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, self.user_id, lock=True
                )

                result = await MyService.process_choice(session, player, selected_id)

                await TransactionLogger.log_transaction(...)

            embed = EmbedBuilder.success("Selected!", f"Processed: {result}")
            await interaction.edit_original_response(embed=embed, view=None)

        except Exception as e:
            self.cog.log_cog_error("dropdown_callback", e, user_id=self.user_id)
            embed = EmbedBuilder.error("Error", "Failed to process selection.")
            await interaction.followup.send(embed=embed, ephemeral=True)
```

**View Timeout Guidelines:**
- **Quick actions** (follow-up buttons): 120 seconds
- **Standard interactions** (menus, selections): 300 seconds (5 minutes)
- Always implement `on_timeout()` to disable buttons

**Redis Lock Patterns in Views:**
- Combat actions: `f"combat:{user_id}:{floor}"`
- Fusion: `f"fusion:{user_id}"`
- DROP: `f"drop:{user_id}"`
- Summon: `f"summon:{user_id}"`
- General pattern: `f"{feature}:{user_id}"`

### Transaction Safety

For ANY command that modifies player state:

```python
async with DatabaseService.get_transaction() as session:
    # MUST use pessimistic locking
    player = await session.get(Player, user_id, with_for_update=True)

    # Modify state through services
    result = await SomeService.do_something(session, player, ...)

    # Log the transaction
    await TransactionLogger.log_transaction(
        player_id=user_id,
        transaction_type="action_name",
        details={"key": "value"},
        context=f"command:{ctx.command} guild:{ctx.guild.id}"
    )
```

The transaction context manager automatically commits on success or rolls back on exception.

### Event-Driven Architecture

Use `EventBus` for decoupled side effects:

```python
# In service.py - publish event after operation
await EventBus.publish("maiden_fused", {
    "player_id": player_id,
    "result_tier": result.tier
})

# In listener.py or cog - subscribe to event
EventBus.subscribe("maiden_fused", handle_fusion_event, priority=ListenerPriority.HIGH)
```

Events registered in [src/core/event/registry.py](src/core/event/registry.py).

## Common Patterns

### Creating a New Feature

1. Create feature directory: `src/modules/<feature_name>/`
2. Create `service.py` with stateless business logic
3. Create `<feature_name>_cog.py` extending `BaseCog`
4. Add Discord Views inline in cog file if needed (buttons, modals)
5. Add `async def setup(bot)` to cog file
6. No manual registration needed - auto-discovered by loader

### Adding a New Command

```python
from src.core.bot.base_cog import BaseCog
from src.utils.decorators import ratelimit

class MyCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot, "MyCog")

    @commands.command(name="mycommand", aliases=["mc"])
    @ratelimit(uses=5, per_seconds=60, command_name="mycommand")
    async def my_command(self, ctx: commands.Context):
        """Command description."""
        async with self.get_session() as session:
            player = await self.require_player(ctx, session, ctx.author.id, lock=True)
            if not player:
                return

            # Call service
            result = await MyService.do_thing(session, player.discord_id)

            # Send success embed
            await self.send_success(ctx, "Success!", f"Did the thing: {result}")

async def setup(bot):
    await bot.add_cog(MyCog(bot))
```

### Using ConfigManager

```python
# Get config value with fallback
cost = ConfigManager.get("fusion.tier_3_cost", default=5000)

# Reload config from database
await ConfigManager.reload()
```

Game balance values stored in `game_config` database table, editable at runtime.

## Database Models

Models are in [src/database/models/](src/database/models/), organized by domain:
- `core/`: Player, Maiden, GameConfig
- `economy/`: Transactions, Shrines, Tokens
- `combat/`, `progression/`, etc.

Use SQLAlchemy async patterns with session management from `DatabaseService`.

## Redis and Caching

Redis is **optional** - the bot gracefully degrades if Redis is unavailable:
- Rate limiting falls back to allowing requests
- Caching falls back to database queries
- Locks fall back to database-level locking

## Discord Command Prefixes

The bot supports flexible prefixes defined in [src/core/bot/lumen_bot.py](src/core/bot/lumen_bot.py):
- `r`, `r `, `r  `, `r   ` (with 0-3 spaces)
- `lumen`, `lumen `, `lumen  `, `lumen   `
- Mention-based (`@LUMEN`)

## Rate Limiting

Rate limits are configured in [config/rate_limits.yaml](config/rate_limits.yaml):

```yaml
# Format: uses (number of times) per period (seconds)
feature:
  command:
    uses: 10
    period: 60  # 10 uses per 60 seconds
```

The `@ratelimit` decorator reads from this configuration file (hot-reloadable via ConfigManager).

## Error Handling

Use domain exceptions from [src/core/exceptions.py](src/core/exceptions.py):
- `InsufficientResourcesError` - not enough resources
- `InvalidOperationError` - business rule violation
- `CooldownError` - rate limit or cooldown active
- `NotFoundError` - entity not found
- `ValidationError` - invalid input

Cogs should catch these and convert to embeds via `BaseCog.send_error()` or `EmbedBuilder`.

## Logging and Observability

Use `LogContext` for structured logging with Discord context:

```python
from src.core.logging.logger import get_logger, LogContext

logger = get_logger(__name__)

async with LogContext(
    user_id=ctx.author.id,
    guild_id=ctx.guild.id,
    command=ctx.command.name
):
    logger.info("Processing command")
```

The bot includes health monitoring, startup metrics, and service degradation detection.

## Important Notes

- **Never hardcode game values** - always use `ConfigManager`
- **Never put business logic in cogs or views** - always use services
- **Always use pessimistic locking** for state-modifying commands and view interactions
- **Always log transactions** for audit trail
- **Always use `EmbedBuilder`** for consistent Discord UI
- **Always validate users in view interactions** - check `interaction.user.id`
- **Always use Redis locks for button handlers** that modify state
- **Read LUMEN LAW** ([docs/lumen_law.md](docs/lumen_law.md)) before making architectural changes

## Configuration Files

- `.env` - Environment variables (DISCORD_TOKEN, DATABASE_URL, REDIS_URL)
- `config/rate_limits.yaml` - Rate limits for all commands (hot-reloadable)
- `config/*.yaml` - Game configuration (monsters, rewards, etc.)
- Database `game_config` table - Runtime-editable game balance values

## Documentation Reference

### Core Standards
- **[docs/lumen_law.md](docs/lumen_law.md)** - Architectural constitution (13 commandments)
- **[docs/ERROR_HANDLING_STANDARD.md](docs/ERROR_HANDLING_STANDARD.md)** - Error handling patterns (100% compliance)
- **[docs/TYPE_HINTS_DOCSTRINGS_STANDARD.md](docs/TYPE_HINTS_DOCSTRINGS_STANDARD.md)** - Type hints & docstrings guide
- **[docs/DEVELOPER_GUIDE_NEW_FEATURES.md](docs/DEVELOPER_GUIDE_NEW_FEATURES.md)** - Quick reference for common patterns

### Technical Guides
- **[docs/DATABASE_INDEXES.md](docs/DATABASE_INDEXES.md)** - Database performance optimization
- **[docs/code_refractor.md](docs/code_refractor.md)** - Refactoring guidelines

### Project Status
- **[docs/100_PERCENT_COMPLETION_SUMMARY.md](docs/100_PERCENT_COMPLETION_SUMMARY.md)** - Production readiness achievement (10/10)

**Last Updated**: 2025-01-08
