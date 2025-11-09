# 🏛️ RIKI LAW
### *The Architectural Constitution for Discord RPG Bots*

---

## 📜 PREAMBLE

This document represents the **supreme architectural authority** for Discord RPG bot development. Every implementation, decision, and line of code must comply with these principles.

**Platform:** Discord (API v10)  
**Framework:** discord.py  
**Database:** PostgreSQL + SQLModel  
**Cache:** Redis  
**Architecture:** Domain-Driven + Feature Modules + Service Layer + Event-Driven

The Architect enforces.  
The Implementer follows.  
The Code complies.

---

## ⚖️ PART I: THE THIRTEEN COMMANDMENTS

### Core Foundation (Non-Negotiable)

#### 1. **SELECT FOR UPDATE** — The Concurrency Safeguard

```python
# ✅ MANDATORY on ANY command that modifies player state
async with DatabaseService.get_transaction() as session:
    player = await session.get(Player, user_id, with_for_update=True)
    # Modify player state safely
```

**Rationale:** Discord commands execute concurrently. Two simultaneous `/fuse` commands must not corrupt maiden inventory.

**When to Use:**
- ANY command that changes resources (energy, stamina, rikis, grace)
- ANY command that modifies inventory (maidens, items, equipment)
- ANY button interaction that triggers state changes
- Trading, fusion, summoning, battling, economy transactions

---

#### 2. **Transaction Logging** — The Audit Trail

```python
# ✅ MANDATORY for all commands that change game state
await TransactionLogger.log_transaction(
    player_id=user_id,
    transaction_type="maiden_fused",
    details={"tier": 3, "cost": 5000, "result": "success"},
    context=f"command:/fuse guild:{guild_id}"
)
```

**Rationale:** When players report "I lost my maiden!", audit logs show exactly what happened.

**What to Log:**
- All resource consumption (energy, stamina, currencies)
- All inventory changes (maidens acquired, fused, consumed)
- All currency transactions (purchases, rewards, costs)
- Discord context (user_id, guild_id, channel_id, command_name)

---

#### 3. **Redis Locks** — The Coordination Mechanism

```python
# ✅ MANDATORY for button interactions that modify state
async with RedisService.acquire_lock(f"fusion:{user_id}", timeout=5):
    # User clicked fusion button
    # Ensure they can't click it twice simultaneously
    result = await FusionService.execute_fusion(user_id, maiden_ids)
```

**Rationale:** Discord buttons can be clicked multiple times before the first click completes processing.

**When to Use:**
- Button click handlers that modify state
- Modal submit handlers that consume resources
- Multi-step Discord interaction workflows
- Trading confirmations between two players

---

#### 4. **ConfigManager** — The Single Source of Truth

```python
# ✅ MANDATORY for ALL game balance values
fusion_cost = ConfigManager.get("maiden.fusion_cost_tier_3")
energy_per_zone = ConfigManager.get("exploration.energy_cost")
prayer_grace = ConfigManager.get("prayer.grace_amount")

# ❌ FORBIDDEN — hardcoded values
fusion_cost = 5000  # NEVER DO THIS
```

**Rationale:** Balance changes without redeploying the bot. Configuration changes propagate instantly.

**What Belongs in Config:**
- All costs (rikis, grace, energy, stamina)
- All rewards (XP, loot, currency amounts)
- All rates (fusion success, summon rates, drop chances)
- All cooldowns (prayer timer, daily reset times)
- All limits (max inventory, max energy, rate limits)

---

#### 5. **Specific Exception Handling** — The Safety Net

```python
# ✅ MANDATORY — Discord-friendly error handling
try:
    await FusionService.fuse_maidens(user_id, maiden_ids)

except InsufficientResourcesError as e:
    embed = EmbedBuilder.error(
        title="Insufficient Resources",
        description=f"Need {e.required:,} {e.resource}, have {e.current:,}",
        help_text="Use /daily or /explore to earn more"
    )
    await ctx.send(embed=embed)

except ValidationError as e:
    embed = EmbedBuilder.error(
        title="Invalid Input",
        description=f"{e.field}: {e.message}"
    )
    await ctx.send(embed=embed)

except Exception as e:
    logger.error(f"Fusion error for {user_id}: {e}", exc_info=True)
    embed = EmbedBuilder.error(
        title="Something Went Wrong",
        description="An unexpected error occurred. The team has been notified."
    )
    await ctx.send(embed=embed)
```

**Rationale:** Discord users see embeds, not Python tracebacks. Every exception must become a helpful message.

---

#### 6. **Single Commit Per Transaction** — The Integrity Guarantee

```python
# ✅ CORRECT — Single atomic transaction
async with DatabaseService.get_transaction() as session:
    player = await session.get(Player, user_id, with_for_update=True)
    await ResourceService.consume(session, player, cost, "fusion")
    # Commits automatically on context exit

# ❌ FORBIDDEN — Multiple commits
await session.commit()  # Don't call this manually
await do_something()
await session.commit()  # Especially not twice!
```

**Rationale:** Discord commands must be atomic — all changes succeed or all fail. No partial updates.

---

#### 7. **ALL Business Logic Through Services** — The Holy Separation

```python
# ✅ CORRECT — Cog calls service ONLY
@commands.slash_command(name="fuse")
async def fuse(self, ctx: commands.Context, maiden_name: str):
    await ctx.defer()
    
    # ALL game logic through service
    result = await FusionService.attempt_fusion(
        player_id=ctx.author.id,
        maiden_name=maiden_name
    )
    
    # Cog builds Discord embed from result
    embed = self._build_result_embed(result)
    await ctx.send(embed=embed)

# ❌ ABSOLUTELY FORBIDDEN — Game logic in cog
player.rikis -= 5000  # NEVER in cog files!
maiden.tier += 1  # NEVER in cog files!
```

**Rationale:** Cogs handle Discord UI only. Services handle game logic. Never mix them.

**The Separation:**
- **Cog:** Slash command, parse Discord input, defer response, build embeds
- **Service:** Game logic, validation, state changes, transactions
- **Model:** Data structure only, no business logic

---

#### 8. **Event-Driven Decoupling** — The Scalability Key

```python
# ✅ MANDATORY for complex workflows
# In fusion_service.py
async def execute_fusion(self, player_id: int, maiden_ids: list):
    result = await self._perform_fusion_logic(player_id, maiden_ids)
    
    # Publish event for other systems to react
    await EventBus.publish("maiden_fused", {
        "player_id": player_id,
        "result_tier": result.new_tier,
        "channel_id": channel_id
    })
    
    return result

# In tutorial_cog.py — Automatically reacts to event
async def cog_load(self):
    EventBus.subscribe("maiden_fused", self._handle_fusion_event)

async def _handle_fusion_event(self, data: dict):
    await TutorialService.complete_step(data["player_id"], "first_fusion")
```

**Rationale:** Achievement checks, tutorial completions, and analytics don't block Discord command responses.

**When to Use Events:**
- Achievement/milestone checking (async, non-blocking)
- Leaderboard updates (can happen in background)
- Discord role assignments (happens after command completes)
- Tutorial progression tracking
- Analytics and metrics
- Cross-system notifications

**When to Use Direct Calls:**
- Resource consumption (must be synchronous)
- Inventory changes (must be in same transaction)
- Validation (must block command if invalid)

---

#### 9. **Graceful Degradation** — The Resilience Principle

```python
# ✅ MANDATORY — Bot stays online even if Redis fails
try:
    cached_player = await RedisService.get_cached_player(user_id)
except RedisConnectionError:
    logger.warning(f"Redis degraded for user {user_id}, using database")
    # Command still works, just slower
    cached_player = await DatabaseService.query_player(user_id)
```

**Rationale:** Discord bot remains functional when components fail. Users experience degraded performance, not outages.

**Degradation Scenarios:**
- Redis down → Database fallback (slower but functional)
- Database slow → Show cached data with warning
- High load → Queue non-critical operations
- Rate limit hit → Inform user to wait

---

#### 10. **Value Object Encapsulation** — The Domain Model

```python
# ✅ MANDATORY — Game rules in value objects, not cogs
@dataclass(frozen=True)
class FusionCost:
    rikis: int
    tier: int
    
    def can_afford(self, player_rikis: int) -> bool:
        return player_rikis >= self.rikis
    
    def validate_tier(self) -> ValidationResult:
        if self.tier > 11:
            return ValidationResult(False, "Cannot fuse beyond tier 11")
        return ValidationResult(True, "Valid")

# Usage in Discord command
cost = FusionCost(rikis=5000, tier=3)
if not cost.can_afford(player.rikis):
    embed = EmbedBuilder.error("Insufficient Rikis", "...")
    await ctx.send(embed=embed)
```

**Rationale:** Game rules are testable independently of Discord API. Domain logic lives in domain objects.

---

#### 11. **Command/Query Separation** — The Performance Multiplier

```python
# ✅ MANDATORY — Optimize reads separately from writes

# Discord query command (read) — Aggressive caching allowed
@commands.slash_command(name="profile")
async def profile(self, ctx: commands.Context):
    # Can use read replica, cache aggressively, no locks
    player_data = await PlayerService.get_profile(ctx.author.id)
    embed = self._build_profile_embed(player_data)
    await ctx.send(embed=embed)

# Discord command (write) — Must use primary database with locks
@commands.slash_command(name="fuse")
async def fuse(self, ctx: commands.Context):
    await ctx.defer()
    async with DatabaseService.get_transaction() as session:
        player = await session.get(Player, ctx.author.id, with_for_update=True)
        # Modify state
```

**Rationale:** `/profile` is called 100× more than `/fuse`. Optimize each separately.

---

#### 12. **Complete Audit Trails** — The Time Machine

```python
# ✅ MANDATORY — Snapshot before commands that modify critical state
@commands.slash_command(name="fuse")
async def fuse(self, ctx: commands.Context):
    # Create snapshot BEFORE fusion attempt
    await StateSnapshotService.create_snapshot(
        player_id=ctx.author.id,
        snapshot_type="pre_fusion",
        state_data={
            "maidens": player.get_maidens_snapshot(),
            "rikis": player.rikis,
            "tier_attempting": tier
        },
        discord_context={
            "command": "/fuse",
            "guild_id": ctx.guild_id,
            "channel_id": ctx.channel_id
        }
    )
```

**Rationale:** When player reports "I lost my maiden!", restore from snapshot. Audit trail enables rollbacks.

---

#### 13. **Feature Flags Integration** — The Safe Experimentation

```python
# ✅ MANDATORY — A/B test Discord features safely
@commands.slash_command(name="fuse")
async def fuse(self, ctx: commands.Context):
    if await FeatureFlags.is_enabled("new_fusion_ui", ctx.author.id):
        # New Discord embed design with buttons
        await self._fuse_with_new_ui(ctx)
    else:
        # Old Discord embed design
        await self._fuse_with_old_ui(ctx)
```

**Rationale:** Test new Discord UI with 10% of users before full rollout. Instant rollback if issues arise.

---

## 📐 PART II: ARCHITECTURAL PATTERNS

### The Feature Module Architecture

**Structure:**
```
src/
├── modules/
│   ├── fusion/
│   │   ├── cog.py          # Discord UI layer
│   │   ├── service.py      # Business logic
│   │   └── views.py        # Button/Modal components
│   ├── guilds/
│   │   ├── cog.py
│   │   ├── service.py
│   │   └── views.py
│   └── summon/
│       ├── cog.py
│       ├── service.py
│       └── views.py
├── database/
│   └── models/
│       ├── core/           # Player, Maiden, Config
│       ├── progression/    # Ascension, Quests
│       ├── economy/        # Transactions, Shrines
│       └── social/         # Guilds, Trading
└── core/
    ├── database_service.py
    ├── event_bus.py
    ├── config_manager.py
    └── exceptions.py
```

**Principles:**

1. **Vertical Slices:** Each feature is self-contained (cog + service + views)
2. **Domain Segregation:** Models organized by domain (core, progression, economy, social)
3. **Dynamic Loading:** Features auto-discovered by `loader.py` at startup
4. **Zero Dependencies:** Features don't import each other (use EventBus instead)

---

### The Service Layer Pattern

```python
class FusionService:
    """
    Pure business logic, zero Discord dependencies.
    
    RIKI LAW Compliance:
        - All methods are @staticmethod (stateless)
        - No Discord imports (discord.py stays in cogs)
        - ConfigManager for all values
        - Raises domain exceptions only
    """
    
    @staticmethod
    async def attempt_fusion(
        session: AsyncSession,
        player_id: int,
        maiden_ids: List[int]
    ) -> FusionResult:
        """
        Complete fusion workflow with pessimistic locking.
        
        Returns:
            FusionResult with success/failure and rewards
        
        Raises:
            InsufficientResourcesError: Player can't afford fusion
            ValidationError: Invalid maiden selection
            FusionError: Business logic violation
        """
        # 1. Lock player
        player = await session.get(Player, player_id, with_for_update=True)
        
        # 2. Validate
        cost = ConfigManager.get(f"fusion.tier_{tier}_cost")
        if player.rikis < cost:
            raise InsufficientResourcesError("rikis", cost, player.rikis)
        
        # 3. Execute
        result = await FusionService._perform_fusion(session, player, maiden_ids)
        
        # 4. Log
        await TransactionLogger.log_transaction(
            player_id=player_id,
            transaction_type="fusion",
            details=result.to_dict()
        )
        
        # 5. Publish event
        await EventBus.publish("maiden_fused", {
            "player_id": player_id,
            "result": result.to_dict()
        })
        
        return result
```

**Service Rules:**

- Services are **stateless** (all methods `@staticmethod`)
- Services **never import discord.py** (cogs do that)
- Services **always raise domain exceptions** (cogs convert to embeds)
- Services **always use ConfigManager** (no hardcoded values)
- Services **always log transactions** (audit trail)
- Services **publish events for side effects** (decoupling)

---

### The View Layer Pattern

```python
class FusionConfirmView(discord.ui.View):
    """
    Discord button confirmation for fusion.
    
    RIKI LAW Compliance:
        - Timeout handling (Article I.13)
        - Redis locks on button clicks (Article I.3)
        - User validation (only command author can click)
        - Proper disabled state after use
    """
    
    def __init__(self, player_id: int, maiden_ids: list, cost: int):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.maiden_ids = maiden_ids
        self.cost = cost
    
    @discord.ui.button(
        label="✅ Confirm Fusion",
        style=discord.ButtonStyle.success
    )
    async def confirm(self, inter: discord.Interaction, button: discord.ui.Button):
        """Execute fusion on confirmation."""
        # Validate user
        if inter.user.id != self.player_id:
            await inter.response.send_message(
                "This button is not for you!",
                ephemeral=True
            )
            return
        
        await inter.response.defer()
        
        # Acquire lock to prevent double-click
        async with RedisService.acquire_lock(f"fusion:{self.player_id}", timeout=5):
            try:
                async with DatabaseService.get_transaction() as session:
                    result = await FusionService.attempt_fusion(
                        session,
                        self.player_id,
                        self.maiden_ids
                    )
                
                if result.success:
                    embed = EmbedBuilder.success(
                        title="Fusion Successful!",
                        description=f"Created Tier {result.new_tier} maiden!"
                    )
                else:
                    embed = EmbedBuilder.error(
                        title="Fusion Failed",
                        description="Better luck next time!",
                        help_text="+1 Fusion Shard as consolation"
                    )
                
                # Disable buttons after use
                for item in self.children:
                    item.disabled = True
                
                await inter.edit_original_response(embed=embed, view=self)
                
            except InsufficientResourcesError as e:
                embed = EmbedBuilder.error(
                    title="Cannot Fuse",
                    description=str(e)
                )
                await inter.edit_original_response(embed=embed, view=None)
    
    @discord.ui.button(
        label="❌ Cancel",
        style=discord.ButtonStyle.secondary
    )
    async def cancel(self, inter: discord.Interaction, button: discord.ui.Button):
        """Cancel fusion."""
        if inter.user.id != self.player_id:
            await inter.response.send_message(
                "This button is not for you!",
                ephemeral=True
            )
            return
        
        embed = EmbedBuilder.primary(
            title="Fusion Cancelled",
            description="No resources were consumed."
        )
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        
        await inter.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        """Handle timeout — disable all buttons."""
        for item in self.children:
            item.disabled = True
        
        # Note: Cannot edit message here (no reference)
        # Cog must handle timeout display
```

**View Rules:**

- Views **always validate user** (only command author can click)
- Views **always have timeout** (60 seconds recommended)
- Views **always implement on_timeout()** (disable buttons)
- Views **use Redis locks** for state-modifying operations
- Views **disable buttons after use** (prevent double-clicks)
- Views **never contain business logic** (call services only)

---

### The Cog Pattern

```python
class FusionCog(commands.Cog):
    """
    Discord UI layer for fusion feature.
    
    RIKI LAW Compliance:
        - Zero business logic (Article I.7)
        - All logic through FusionService
        - Specific exception handling (Article I.5)
        - Rate limiting decorator
        - Event publishing for side effects (Article I.8)
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.hybrid_command(
        name="fuse",
        aliases=["rf"],
        description="Fuse two maidens to create a higher tier"
    )
    @ratelimit(uses=10, per_seconds=60, command_name="fuse")
    async def fuse(
        self,
        ctx: commands.Context,
        maiden_1: str,
        maiden_2: str
    ):
        """Fuse two maidens together."""
        await ctx.defer()
        
        try:
            # Get maiden IDs (Discord UI concern)
            maiden_ids = await self._resolve_maiden_names(
                ctx.author.id,
                [maiden_1, maiden_2]
            )
            
            # Get cost (from config)
            cost = ConfigManager.get("fusion.base_cost")
            
            # Show confirmation view
            view = FusionConfirmView(
                player_id=ctx.author.id,
                maiden_ids=maiden_ids,
                cost=cost
            )
            
            embed = EmbedBuilder.primary(
                title="Confirm Fusion",
                description=f"Fuse **{maiden_1}** + **{maiden_2}**?"
            )
            embed.add_field(name="Cost", value=f"{cost:,} Rikis")
            
            await ctx.send(embed=embed, view=view)
            
        except ValidationError as e:
            embed = EmbedBuilder.error(
                title="Invalid Maidens",
                description=str(e),
                help_text="Use /maidens to view your collection"
            )
            await ctx.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Fusion error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Something Went Wrong",
                description="An unexpected error occurred."
            )
            await ctx.send(embed=embed, ephemeral=True)
    
    async def _resolve_maiden_names(
        self,
        player_id: int,
        names: list[str]
    ) -> list[int]:
        """
        Helper: Convert maiden names to IDs.
        
        This is Discord UI concern (name resolution), not business logic.
        """
        async with DatabaseService.get_session() as session:
            maiden_ids = []
            for name in names:
                maiden = await session.execute(
                    select(Maiden).where(
                        Maiden.player_id == player_id,
                        Maiden.name == name
                    )
                )
                maiden = maiden.scalar_one_or_none()
                
                if not maiden:
                    raise ValidationError("maiden_name", f"'{name}' not found")
                
                maiden_ids.append(maiden.id)
            
            return maiden_ids


async def setup(bot: commands.Bot):
    """Required for dynamic cog loading."""
    await bot.add_cog(FusionCog(bot))
```

**Cog Rules:**

- Cogs **contain zero business logic** (all logic in services)
- Cogs **handle Discord UI only** (commands, embeds, buttons)
- Cogs **always use @ratelimit** (prevent spam)
- Cogs **always defer long operations** (>3 seconds)
- Cogs **always use EmbedBuilder** (consistent colors)
- Cogs **always use specific exception handling** (friendly messages)
- Cogs **always implement setup() function** (dynamic loading)

---

## 🎨 PART III: DISCORD STANDARDS

### Embed Design Rules

**Official Color Palette:**

```python
class EmbedColors:
    PRIMARY = 0x2c2d31    # Main theme (90% of embeds)
    SUCCESS = 0x2d5016    # Dark green (victories, completions)
    ERROR = 0x8b0000      # Dark red (errors, failures)
    WARNING = 0x8b6914    # Dark gold (warnings, cautions)
    INFO = 0x1e3a8a       # Dark blue (informational)
```

**EmbedBuilder Service:**

```python
class EmbedBuilder:
    """Centralized Discord embed creation."""
    
    @staticmethod
    def primary(title: str, description: str, **kwargs) -> discord.Embed:
        """Standard embed for most commands."""
        return discord.Embed(
            title=title,
            description=description,
            color=EmbedColors.PRIMARY,
            timestamp=datetime.utcnow()
        )
    
    @staticmethod
    def success(title: str, description: str, **kwargs) -> discord.Embed:
        """Success embed for completed actions."""
        return discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=EmbedColors.SUCCESS,
            timestamp=datetime.utcnow()
        )
    
    @staticmethod
    def error(
        title: str,
        description: str,
        help_text: str = None
    ) -> discord.Embed:
        """Error embed for failures."""
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=EmbedColors.ERROR,
            timestamp=datetime.utcnow()
        )
        if help_text:
            embed.add_field(name="Help", value=help_text, inline=False)
        return embed
```

**Embed Structure Rules:**

```python
# ✅ CORRECT — Well-structured embed
embed = discord.Embed(
    title="Short Title (50 chars max)",
    description="Main content here...",
    color=EmbedColors.PRIMARY,
    timestamp=datetime.utcnow()
)

# Fields for structured data (max 25 fields)
embed.add_field(
    name="Stat Name",
    value="Value (1024 chars max)",
    inline=True
)

# Footer for meta information
embed.set_footer(
    text="Level 42 • Zone 12 • 50,000 Rikis",
    icon_url=user.display_avatar.url
)

# Thumbnail for visual interest
embed.set_thumbnail(url=maiden_image_url)
```

**Discord Embed Limits (MANDATORY):**

- Title: 256 characters
- Description: 4,096 characters
- Field name: 256 characters
- Field value: 1,024 characters
- Footer text: 2,048 characters
- Total embed: 6,000 characters
- Fields per embed: 25 maximum
- Embeds per message: 10 maximum

---

### Rate Limits & Constraints

**Discord API Constraints:**

```python
RATE_LIMITS = {
    "global": "50 requests per second",
    "per_channel": "5 messages per 5 seconds",
    "slash_commands": "1 response per command invocation",
    "interactions": "15 minute timeout if not responded"
}

INTERACTION_TIMING = {
    "initial_response": "3 seconds maximum",
    "followup_window": "15 minutes",
    "button_timeout": "Configurable (60s recommended)",
    "modal_timeout": "15 minutes"
}
```

**How to Handle:**

- Use `defer()` immediately for operations >3 seconds
- Set reasonable button timeouts (60 seconds)
- Disable buttons after use or timeout
- Handle timeout in `View.on_timeout()`
- Queue bulk operations (don't spam channels)
- Use webhooks for announcements (separate rate limit)

---

## 📋 PART IV: IMPLEMENTATION CHECKLIST

### For Every Discord Command

- [ ] **Slash command decorator** with clear description
- [ ] **Hybrid command** (works with both / and prefix)
- [ ] **Rate limiting** with `@ratelimit` decorator
- [ ] **Defer response** if operation >3 seconds
- [ ] **Pessimistic locking** with `with_for_update=True`
- [ ] **Service layer calls** (no direct model operations)
- [ ] **Specific exception handling** with Discord embeds
- [ ] **EmbedBuilder** for all embeds (consistent colors)
- [ ] **Button timeout** handling if using views
- [ ] **Redis locks** for button click handlers
- [ ] **Audit logging** with Discord context
- [ ] **Event publishing** for side effects
- [ ] **ConfigManager** for all configurable values
- [ ] **setup() function** in cog file for dynamic loading

---

### For Every Service Method

- [ ] **@staticmethod** (services are stateless)
- [ ] **Type hints** for all parameters and returns
- [ ] **Docstring** explaining purpose, args, returns, raises
- [ ] **Session parameter** first (for transactions)
- [ ] **ConfigManager** for all game values
- [ ] **Domain exceptions** only (no Discord imports)
- [ ] **Transaction logging** for state changes
- [ ] **Event publishing** for side effects
- [ ] **Validation** before state changes
- [ ] **Pessimistic locking** for writes

---

### For Every View Component

- [ ] **Timeout** set (60 seconds recommended)
- [ ] **on_timeout()** implementation (disable buttons)
- [ ] **User validation** (only command author can click)
- [ ] **Redis locks** for state-modifying buttons
- [ ] **Disable buttons** after use
- [ ] **Defer response** before long operations
- [ ] **Service calls only** (no business logic)
- [ ] **Specific exception handling**

---

## 🏛️ CLOSING STATEMENT

**RIKI LAW is not a suggestion. It is the supreme architectural constitution.**

Every Discord command, every button click, every embed, every service call must comply with these laws.

The Architect enforces.  
The Code complies.  
The System thrives.

---

*"Quality is not an act, it is a habit." — Aristotle*

**SO IT IS WRITTEN. SO IT SHALL BE CODED.**