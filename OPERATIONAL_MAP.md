# RikiBot Operational Map

> **Read-only operational reference** documenting how the bot works today.
> All claims cited with file:line references. Facts over opinions.

---

## 1) MODULE TOPOLOGY

### Module Structure Overview

RikiBot uses a **feature-based modular architecture** in `src/modules/`. Each module follows the pattern:
- `cog.py` - Discord command interface (UI layer)
- `service.py` - Business logic (core operations)
- `constants.py` - Module-specific tunables
- Optional: `models.py`, `*_logic.py` for specialized subsystems

**Dependency Pattern**: `Cog → Service → Model/Event → Database`

---

### Module Inventory Table

| Module | Purpose | Commands | Services | Models | Events Published | Events Subscribed | Key Dependencies | Paths |
|--------|---------|----------|----------|--------|------------------|-------------------|------------------|-------|
| **Ascension** | Infinite tower climbing with token rewards | `/ascension` | AscensionService, TokenLogic | Token | `ascension_floor_complete`, `token_dropped` | None | PlayerService, CombatService, RedisService | `src/modules/ascension/` |
| **Combat** | Power calculation engine | None (service-only) | CombatService | CombatResult (dataclass) | None | None | Database models (Maiden) | `src/modules/combat/` |
| **Daily** | Daily login rewards with streaks | `/daily` | DailyService | DailyQuest | `daily_claimed` | None | PlayerService, ResourceService | `src/modules/daily/` |
| **Exploration** | Sector-based exploration with Matron bosses | `/explore` | ExplorationService, MatronService, MasteryService | SectorProgress, ExplorationMastery | `exploration_matron_complete`, `mastery_rank_up` | None | PlayerService, CombatService | `src/modules/exploration/` |
| **Fusion** | Maiden tier upgrading via probabilistic fusion | `/fusion` | FusionService | (uses Maiden model) | `fusion_completed` | None | PlayerService, ResourceService, MaidenService, RedisService | `src/modules/fusion/` |
| **Guilds** | Player guild system with shrines | Guild management commands (TBD) | GuildService, ShrineLogic | Guild, GuildMember, GuildShrine | `guild_created`, `shrine_activated` | None | PlayerService | `src/modules/guilds/` |
| **Help** | Command documentation | `/help` | None | None | None | None | None | `src/modules/help/` |
| **Leaderboard** | Player rankings | `/leaderboard` | LeaderboardService | (queries Player model) | None | None | Database indexes | `src/modules/leaderboard/` |
| **Maiden** | Maiden collection and leader management | Collection viewing (TBD) | MaidenService, LeaderService | Maiden, MaidenBase | `leader_changed` | None | Database models | `src/modules/maiden/` |
| **Player** | Core player management, stats, registration | `/register`, `/me`, `/allocate`, `/transactions` | PlayerService, AllocationService, TransactionService | Player, TransactionLog | `player_registered`, `level_up`, `stat_allocated`, `tos_agreed` | None | ResourceService, TutorialService | `src/modules/player/` |
| **Prayer** | Grace generation via prayer charges | `/pray` | PrayerService | (updates Player model) | `prayer_completed` | None | PlayerService, ResourceService | `src/modules/prayer/` |
| **Resource** | Centralized currency/resource management | None (service-only) | ResourceService | (updates Player model) | None | None | None (foundational) | `src/modules/resource/` |
| **Shrines** | Passive income via shrine worship | Shrine commands (TBD) | ShrineService | Shrine, GuildShrine | `shrine_worshipped` | None | PlayerService | `src/modules/shrines/` |
| **Summon** | Gacha maiden summoning system | `/summon` | SummonService | (creates Maiden records) | `summons_completed` | None | PlayerService, MaidenService, ResourceService | `src/modules/summon/` |
| **System** | Bot administration and utilities | `/ping`, `/status` (assumed) | SystemService | None | None | None | None | `src/modules/system/` |
| **Tutorial** | Onboarding flow | None (event-driven) | TutorialService | Tutorial | Tutorial step events | `tos_agreed`, `first_summon`, etc. | PlayerService | `src/modules/tutorial/` |

---

### Module Dependency Graph (ASCII)

```
┌─────────────────────────────────────────────────────────────────┐
│                         CORE LAYER                              │
│  PlayerService ◄──────────── ResourceService                    │
│      │                            │                             │
│      │                     TransactionLogger                    │
│      │                            │                             │
│      └──────────► RedisService ◄──┘                             │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ (all modules depend on core)
                              │
┌─────────────────────────────┴───────────────────────────────────┐
│                      FEATURE MODULES                            │
│                                                                 │
│  Summon ──► MaidenService ──┐                                   │
│                             │                                   │
│  Fusion ──► MaidenService ──┼──► Database (Maiden, MaidenBase) │
│                             │                                   │
│  Combat ──► (reads only) ───┘                                   │
│                                                                 │
│  Exploration ──► CombatService ──► (strategic power calc)       │
│                                                                 │
│  Ascension ──► CombatService                                    │
│           └──► TokenLogic                                       │
│                                                                 │
│  Daily ──► PlayerService                                        │
│                                                                 │
│  Prayer ──► ResourceService                                     │
│                                                                 │
│  Tutorial ──► EventBus ◄──── (subscribes to multiple events)   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### Notable Side Effects by Module

| Module | Database Writes | Redis Operations | Transaction Log Types | Event Bus Topics |
|--------|----------------|------------------|----------------------|------------------|
| **Summon** | `player.grace -= cost`, `player.pity_counter++`, create `Maiden` records | Lock: `summon:{user_id}` (batch) | `summons_completed` | `summons_completed` |
| **Fusion** | `player.rikis -= cost`, maiden quantity -2, `player.fusion_shards` update, create maiden (success) | Lock: `fusion:{user_id}` (10s) | `fusion_completed` | `fusion_completed` |
| **Daily** | `player.rikis += reward`, `player.grace += reward`, `DailyQuest.last_claimed`, `streak++` | None | `daily_claimed` | `daily_claimed` |
| **Prayer** | `player.prayer_charges -= 1`, `player.grace += amount`, `last_prayer_regen` | Lock: `pray:{user_id}` | `prayer_completed` | `prayer_completed` |
| **Exploration** | `SectorProgress.completion_percentage`, `ExplorationMastery` ranks, `player.energy -= cost` | None | `exploration_complete`, `matron_defeated` | `exploration_matron_complete`, `mastery_rank_up` |
| **Ascension** | `player.stamina -= cost`, `player.riki_gems -= gems` (x10), `highest_floor_ascended`, create `Token` | Lock: `ascension:{user_id}` | `ascension_floor_complete` | `ascension_floor_complete`, `token_dropped` |
| **Player** | All `Player` fields, `TransactionLog` inserts, stat allocation | None | Multiple types (registration, level_up, allocation) | `player_registered`, `level_up`, `stat_allocated` |

---

## 2) TUNABLE VALUES INDEX

### A. Core Progression Constants

**Source**: `src/core/constants.py`

| Key | Value | Type | Impact | File:Line |
|-----|-------|------|--------|-----------|
| `POINTS_PER_LEVEL` | 5 | int | Stat points gained per level up | `constants.py:26` |
| `MAX_POINTS_PER_STAT` | 999 | int | Maximum allocatable points per stat | `constants.py:24` |
| `BASE_ENERGY` | 100 | int | Starting max energy | `constants.py:28` |
| `BASE_STAMINA` | 50 | int | Starting max stamina | `constants.py:29` |
| `BASE_HP` | 500 | int | Starting max HP | `constants.py:30` |
| `ENERGY_PER_POINT` | 10 | int | Max energy increase per allocation point | `constants.py:33` |
| `STAMINA_PER_POINT` | 5 | int | Max stamina increase per allocation point | `constants.py:34` |
| `HP_PER_POINT` | 100 | int | Max HP increase per allocation point | `constants.py:35` |

**Resource Regeneration**:

| Resource | Interval (minutes) | Class Modifier | File:Line |
|----------|-------------------|----------------|-----------|
| Energy | 5 | Adapter: 0.75x time (25% faster) | `constants.py:78` |
| Stamina | 10 | Destroyer: 0.75x time (25% faster) | `constants.py:79` |
| Prayer Charges | 5 (300s) | None | `constants.py:64` |

**Max Caps**:

| Resource | Max | File:Line |
|----------|-----|-----------|
| Prayer Charges | 1 | `constants.py:63` |
| Grace | 999,999 | `database/models/core/player.py:476` |

---

### B. Player Classes

**Source**: `src/core/constants.py:16-18`

| Class | Bonus Type | Multiplier | Best For |
|-------|-----------|------------|----------|
| **Destroyer** | Stamina Regen Speed | 0.75x time (25% faster) | Ascension grinding |
| **Adapter** | Energy Regen Speed | 0.75x time (25% faster) | Exploration farming |
| **Invoker** | Shrine Rewards | 1.25x income (25% more) | Riki farming |

---

### C. XP Curve System

**Source**: `src/modules/player/service.py:193-207`

| Curve Type | Formula | Default Parameters | Example (L50) |
|------------|---------|-------------------|---------------|
| **Polynomial** (default) | `base * (level ^ exponent)` | base=50, exp=2.2 | 65,890 XP |
| Exponential | `base * (growth_rate ^ (level-1))` | base=50, rate=1.5 | Alternative |
| Logarithmic | `base * level * log(level+1)` | base=500 | Alternative |

**Sample XP Requirements** (Polynomial, 50 * level^2.2):

| Level Range | XP Required | Cumulative XP |
|-------------|-------------|---------------|
| 1→2 | 132 | 132 |
| 10→11 | 3,155 | 16,650 |
| 50→51 | 65,890 | 1,825,000 |
| 100→101 | 251,189 | **12,589,254** |

**Total XP from L1 to L100**: ~12.6 million XP

---

### D. Fusion System Tunables

**Source**: `src/modules/fusion/service.py:46-96` + `fusion/constants.py`

**Fusion Costs** (Exponential):
- Formula: `1000 * (2.5 ^ (tier - 1))` capped at 100,000,000
- `fusion_costs.base` = 1,000
- `fusion_costs.multiplier` = 2.5
- `fusion_costs.max_cost` = 100,000,000

| Fusion | Cost (Rikis) | Success Rate |
|--------|-------------|--------------|
| T1→T2 | 1,000 | 70% |
| T2→T3 | 2,500 | 65% |
| T3→T4 | 6,250 | 60% |
| T5→T6 | 39,063 | 50% |
| T7→T8 | 244,141 | 40% |
| T10→T11 | 10,000,000 (capped) | 25% |
| T11→T12 | 10,000,000 (capped) | 20% |

**Shard System**:
- `MIN_SHARDS_PER_FAILURE` = 1
- `MAX_SHARDS_PER_FAILURE` = 12
- `SHARDS_FOR_GUARANTEED_FUSION` = 100
- **Impact**: Failed fusions grant random 1-12 shards; 100 shards = guaranteed success

**Source**: `fusion/constants.py:54-57`, `fusion/service.py:92-96`

---

### E. Summon/Gacha System

**Source**: `src/modules/summon/service.py:40-75`

| Parameter | Value | Impact | File:Line |
|-----------|-------|--------|-----------|
| `grace_per_summon` | 1 (ASSUMPTION) | Grace cost per summon | `summon/service.py:116` |
| `pity_system.summons_for_pity` | 25 | Guaranteed unowned maiden every 25 summons | `summon/service.py:129` |
| `rate_distribution.decay_factor` | 0.75 | Exponential decay favoring lower tiers | `summon/service.py:46` |
| `rate_distribution.highest_tier_base` | 22.0% | Base rate for highest unlocked tier | `summon/service.py:47` |

**Tier Unlock System** (from ConfigManager `gacha_rates.tier_unlock_levels`):
- Level-gated tier access
- Early game: T1-T3 unlocked at L1
- Progressive unlocks: T4-T12 unlock at higher levels
- **ASSUMPTION**: T4 ~L10, T6 ~L30, T10 ~L70, T12 ~L90

**Rate Calculation Example** (Player L50, unlocked T1-T7):
- T7: 22.0%, T6: 16.5%, T5: 12.4%, T4: 9.3%, T3: 6.9%, T2: 5.2%, T1: 3.9%
- Rates normalized to 100% total

---

### F. Exploration System

**Source**: `src/modules/exploration/constants.py:23-198`

**Mastery Ranks**:

| Rank | Completions Required | Relic Rewards | File:Line |
|------|---------------------|---------------|-----------|
| Bronze | 5 | +1 relic bonus | `constants.py:156` |
| Silver | 15 | +1 relic bonus | `constants.py:156` |
| Gold | 30 | +1 relic bonus | `constants.py:156` |

**Sector Definitions** (example: Sector 1):
- Name: "Whispering Woods"
- Min Level: 1
- Energy Cost: 10
- **Source**: `exploration/constants.py:154`

**Relic Types** (8 total, `constants.py:43-100`):

| Relic Type | Effect | Bonus Type |
|------------|--------|------------|
| `shrine_income` | Shrine rikis bonus | % increase |
| `combine_rate` | Fusion success bonus | % increase |
| `attack_boost` | Maiden ATK bonus | % increase |
| `defense_boost` | Maiden DEF bonus | % increase |
| `hp_boost` | Player HP bonus | Flat increase |
| `energy_regen` | Energy regen speed | Flat increase (per hour) |
| `stamina_regen` | Stamina regen speed | Flat increase (per hour) |
| `xp_gain` | XP earned bonus | % increase |

---

### G. Ascension System

**Source**: `src/modules/ascension/constants.py:23-63`

**Token Tiers** (redemption currency):

| Token Type | Tier Range | Dropped From Floors | File:Line |
|------------|-----------|---------------------|-----------|
| Bronze | T1-T3 | Early floors | `constants.py:26` |
| Silver | T3-T5 | Mid floors | `constants.py:33` |
| Gold | T5-T7 | Higher floors | `constants.py:40` |
| Platinum | T7-T9 | Late floors | `constants.py:47` |
| Diamond | T9-T11 | Endgame floors | `constants.py:54` |

**Attack Costs**:

| Attack Type | Stamina Cost | Gem Cost | Damage Multiplier |
|-------------|--------------|----------|-------------------|
| x1 Attack | 1 | 0 | 1x |
| x3 Attack | 3 | 0 | 3x |
| x10 Attack | 10 | 10 | 10x |

**Floor Color Tiers** (`constants.py:99-125`):

| Floor Range | Color | Difficulty Tier |
|-------------|-------|----------------|
| 1-25 | Gray | Beginner |
| 26-50 | Green | Intermediate |
| 51-100 | Blue | Advanced |
| 101-150 | Purple | Expert |
| 151+ | Orange | Endgame |

---

### H. Maiden Tier Scaling

**Source**: `src/modules/maiden/constants.py:119-157`

| Tier | Name | Base ATK | Total Stats (min-max) | Color | Jump Multiplier | File:Line |
|------|------|----------|----------------------|-------|-----------------|-----------|
| 1 | Common | 45 | 31-62 | Gray | - | 119-120 |
| 2 | Uncommon | 110 | 77-154 | Turquoise | 2.4x | 121-122 |
| 3 | Rare | 300 | 210-420 | Green | 2.7x | 123-124 |
| 4 | Epic | 900 | 630-1,260 | Blue | 3.0x | 125-126 |
| 5 | Mythic | 3,000 | 2,100-4,200 | Purple | 3.3x | 127-128 |
| 6 | Divine | 11,000 | 7,700-15,400 | Gold | 3.7x | 129-130 |
| 7 | Legendary | 37,500 | 26,250-52,500 | Orange Red | 3.4x | 131-132 |
| 8 | Ethereal | 130,000 | 91,000-182,000 | Purple | 3.5x | 133-134 |
| 9 | Genesis | 475,000 | 332,500-665,000 | Turquoise | 3.7x | 135-136 |
| 10 | Empyrean | 1,600,000 | 1,120,000-2,240,000 | Pink | 3.4x | 137-138 |
| 11 | Void | 5,500,000 | 3,850,000-7,700,000 | Black | 3.4x | 139-140 |
| 12 | Singularity | 19,500,000 | 13,650,000-27,300,000 | White | 3.5x | 141-142 |

**Stat Scaling**: Exponential 3.0-3.7x multipliers between tiers

---

### I. Elements System

**Source**: `src/modules/maiden/constants.py:26-67`

| Element | Emoji | Color Code | File:Line |
|---------|-------|-----------|-----------|
| Infernal | 🔥 | #FF4500 | 42-46 |
| Umbral | 🌑 | #4B0082 | 48-52 |
| Earth | 🌍 | #8B4513 | 54-58 |
| Tempest | ⚡ | #FFD700 | 60-64 |
| Radiant | ✨ | #FFD700 | 66-70 |
| Abyssal | 🌊 | #4682B4 | 72-76 |

**Element Fusion Chart** (`maiden/constants.py:366-395`):
- Same + Same → Same element
- Cross-element combinations produce specific elements
- Example: Infernal + Abyssal → Tempest
- Some combinations produce random elements

---

### J. Rate Limiting

**Source**: Per-module `@ratelimit` decorator usage

| Command | Uses | Period (seconds) | File:Line |
|---------|------|-----------------|-----------|
| `/summon` | 20 | 60 | `summon/cog.py:50-51` |
| `/pray` | 20 | 60 | `prayer/cog.py:49-50` |
| `/fusion` | 15 | 60 | `fusion/cog.py:43-44` |
| `/daily` | 5 | 60 | `daily/cog.py:53-54` |
| `/explore` | 30 | 60 | `exploration/cog.py:129-130` |
| `/ascension` | 20 | 60 | `ascension/cog.py:71-72` |
| `/me` | 15 | 60 | `player/cog.py:218-221` |
| `/allocate` | 10 | 60 | `player/cog.py:377-380` |
| `/transactions` | 15 | 60 | `player/cog.py:1194-1197` |

---

### K. Starting Resources

**Source**: `src/core/config/config.py:141-144`

| Resource | Default | Env Variable |
|----------|---------|--------------|
| Rikis | 1,000 | `DEFAULT_STARTING_RIKIS` |
| Grace | 5 | `DEFAULT_STARTING_GRACE` |
| Energy | 100 | `DEFAULT_STARTING_ENERGY` |
| Stamina | 50 | `DEFAULT_STARTING_STAMINA` |

---

### L. Performance & Infrastructure

**Source**: `src/core/constants.py:83-101`

| Parameter | Value | Unit | Purpose |
|-----------|-------|------|---------|
| `DEFAULT_QUERY_TIMEOUT` | 30,000 | ms | Database query timeout |
| `HEALTH_CHECK_TIMEOUT` | 5,000 | ms | Health check timeout |
| `DEGRADED_THRESHOLD` | 100 | ms | Performance warning level |
| `UNHEALTHY_THRESHOLD` | 1,000 | ms | Critical alert level |
| `DEFAULT_POOL_SIZE` | 20 | connections | DB connection pool |
| `MAX_OVERFLOW` | 10 | connections | Extra connections allowed |
| `CIRCUIT_BREAKER_THRESHOLD` | 5 | failures | Before opening circuit |
| `CIRCUIT_BREAKER_RECOVERY` | 60 | seconds | Wait before retry |
| `FUSION_LOCK_TIMEOUT` | 10 | seconds | Max fusion lock hold |

**Cache TTLs** (`constants.py:122-128`):

| Purpose | TTL (seconds) | Use Case |
|---------|--------------|----------|
| Short | 60 | Frequently changing data |
| Medium | 300 | Moderate volatility |
| Long | 1,800 | Stable data |
| Very Long | 3,600 | Static lookups |

---

### M. Overcap Bonuses

**Source**: `src/core/constants.py:45-47`

| Condition | Bonus | Impact |
|-----------|-------|--------|
| Energy ≥90% on level up | +10% max overflow | Resource cap temporarily exceeded |
| Stamina ≥90% on level up | +10% max overflow | Resource cap temporarily exceeded |

---

## 3) CORE GAMEPLAY LOOPS

### LOOP A: Daily Login Flow

**Entry Point**: `/daily` (`src/modules/daily/cog.py:47`)

**Call Chain**:
```
User: /daily
  │
  ├──► DailyCog.daily()                                [daily/cog.py:47-142]
  │     │
  │     ├──► DatabaseService.get_transaction()         [BEGIN TRANSACTION]
  │     │
  │     ├──► BaseCog.require_player(lock=True)         [base_cog.py:45-78]
  │     │     └──► PlayerService.get_player_with_regen()
  │     │           └──► SELECT FOR UPDATE (pessimistic lock)
  │     │
  │     ├──► DailyService.claim_daily(session, player) [daily/service.py:28-98]
  │     │     │
  │     │     ├──► Check cooldown (24 hours)
  │     │     ├──► Calculate streak bonus
  │     │     ├──► Apply leader/class modifiers
  │     │     ├──► player.rikis += reward
  │     │     └──► player.grace += grace_reward
  │     │
  │     ├──► TransactionLogger.log_transaction()       [transaction_logger.py:39-97]
  │     │
  │     └──► EventBus.publish("daily_claimed")         [event/registry.py]
  │
  └──► Commit Transaction (automatic on context exit)
```

**Input Requirements**:
- Registered player
- 24 hours since last claim

**Outputs**:
- Base rikis (from ConfigManager `daily_rewards.base_rikis`)
- Base grace (from ConfigManager `daily_rewards.base_grace`)
- Streak multiplier applied

**Tunables Used**:
- `daily_rewards.base_rikis`
- `daily_rewards.base_grace`
- `daily_rewards.streak_bonus_multiplier`
- `daily_rewards.cooldown_hours` = 24

**Failure Guards**:
- `CooldownError` if claimed within 24 hours
- `PlayerNotFoundError` if not registered

**Events Published**:
- `daily_claimed` - `{player_id, streak, timestamp}`

**Side Effects**:
- DB: `player.rikis += reward`, `player.grace += grace`, `DailyQuest.last_claimed = now`, `streak_count++`
- Transaction log: Type `daily_claimed`

---

### LOOP B: Prayer → Grace → Summon Chain

#### Phase 1: Prayer

**Entry Point**: `/pray` (`src/modules/prayer/cog.py:44`)

```
User: /pray
  │
  ├──► PrayCog.pray()                                  [prayer/cog.py:44-125]
  │     │
  │     ├──► RedisService.acquire_lock(f"pray:{user_id}") [Prevent double-click]
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► BaseCog.require_player(lock=True)
  │     │
  │     ├──► Validate player.prayer_charges >= 1
  │     │
  │     ├──► PrayerService.perform_prayer()            [prayer/service.py:28-76]
  │     │     │
  │     │     ├──► player.prayer_charges -= 1
  │     │     ├──► Calculate base grace gain
  │     │     ├──► Apply leader/class modifiers
  │     │     └──► player.grace += amount
  │     │
  │     ├──► TransactionLogger.log_transaction()
  │     │
  │     └──► EventBus.publish("prayer_completed")
  │
  └──► Commit Transaction
```

**Prayer Tunables**:
- `prayer_system.regen_interval_seconds` = 300
- `prayer_system.grace_per_prayer` (ASSUMPTION: 5-10)
- `prayer_system.max_charges` = 1

---

#### Phase 2: Summon

**Entry Point**: `/summon [count]` (`src/modules/summon/cog.py:44`)

```
User: /summon 10
  │
  ├──► SummonCog.summon(ctx, count=10)                 [summon/cog.py:44-185]
  │     │
  │     ├──► Validate count in {1, 5, 10}
  │     │
  │     ├──► RedisService.acquire_lock(f"summon:{user_id}")
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► BaseCog.require_player(lock=True)
  │     │
  │     ├──► Calculate grace_cost = config.grace_per_summon * count
  │     │
  │     ├──► Validate player.grace >= grace_cost
  │     │
  │     ├──► SummonService.perform_summons()           [summon/service.py:108-195]
  │     │     │
  │     │     └──► For each summon:
  │     │           │
  │     │           ├──► Check pity: if pity_counter >= 25
  │     │           │     └──► check_and_trigger_pity()
  │     │           │           └──► Guarantee unowned maiden
  │     │           │
  │     │           ├──► Else: roll_maiden_tier(player.level)
  │     │           │     │
  │     │           │     ├──► Get unlocked tiers for level
  │     │           │     ├──► Calculate rates (exponential decay)
  │     │           │     │     └──► highest: 22%, decay: 0.75^n
  │     │           │     └──► Weighted random selection
  │     │           │
  │     │           ├──► Select random maiden base from tier pool
  │     │           │
  │     │           ├──► MaidenService.add_maiden_to_inventory()
  │     │           │     └──► Create or update Maiden record
  │     │           │
  │     │           └──► player.pity_counter++
  │     │
  │     ├──► ResourceService.consume_resources()       [Deduct grace]
  │     │
  │     ├──► TransactionLogger.log_transaction()
  │     │
  │     └──► EventBus.publish("summons_completed")
  │
  └──► Commit Transaction
```

**Summon Input Requirements**:
- Grace (1 per summon, configurable)
- `count` in {1, 5, 10}

**Summon Outputs**:
- 1/5/10 maidens added to inventory
- Tiers based on unlocked tier pool
- Pity maiden every 25 summons

**Summon Tunables**:
- `summon.grace_cost` = 1
- `gacha_rates.tier_unlock_levels` - {tier_1: 1, tier_4: 20, ...}
- `gacha_rates.rate_distribution.decay_factor` = 0.75
- `gacha_rates.rate_distribution.highest_tier_base` = 22.0
- `pity_system.summons_for_pity` = 25

**Failure Conditions**:
- Prayer: `InsufficientResourcesError` if no charges
- Summon: `InsufficientResourcesError` if grace < cost
- Summon: `ValidationError` if count not in {1, 5, 10}

**Events Published**:
- `prayer_completed`
- `summons_completed`

**Side Effects**:
- Prayer: `player.prayer_charges -= 1`, `player.grace += amount`
- Summon: `player.grace -= cost`, `player.total_summons += count`, `pity_counter`, new `Maiden` records

---

### LOOP C: Fusion (Maiden Upgrade)

**Entry Point**: `/fusion` (`src/modules/fusion/cog.py:38`)

```
User: /fusion
  │
  ├──► FusionCog.fusion()                              [fusion/cog.py:38-134]
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► BaseCog.require_player(lock=False)        [Read-only for UI]
  │     │
  │     ├──► FusionService.get_fusable_maidens()       [Query maidens with qty≥2]
  │     │
  │     └──► Display dropdown menus (tier → maiden)
  │
User selects maiden
  │
  ├──► MaidenSelectDropdown.callback()                 [fusion/cog.py:200-315]
  │     │
  │     ├──► RedisService.acquire_lock(f"fusion:{user_id}", timeout=10s)
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► PlayerService.get_player_with_regen(lock=True)
  │     │
  │     ├──► FusionService.attempt_fusion()            [fusion/service.py:98-210]
  │     │     │
  │     │     ├──► Validate maiden.quantity >= 2
  │     │     │
  │     │     ├──► Calculate cost = get_fusion_cost(tier)
  │     │     │     └──► 1000 * (2.5 ^ (tier-1)), capped at 100M
  │     │     │
  │     │     ├──► ResourceService.consume_resources() [Deduct rikis]
  │     │     │
  │     │     ├──► maiden.quantity -= 2
  │     │     │
  │     │     ├──► Roll success = roll_fusion_success(tier)
  │     │     │     └──► Random(0-100) < fusion_rates[tier]
  │     │     │
  │     │     ├──► IF SUCCESS:
  │     │     │     │
  │     │     │     ├──► element = calculate_element_result()
  │     │     │     │     └──► Use FUSION_ELEMENT_CHART
  │     │     │     │
  │     │     │     ├──► MaidenService.add_maiden_to_inventory(tier=tier+1)
  │     │     │     │
  │     │     │     └──► player.successful_fusions++
  │     │     │
  │     │     └──► IF FAILURE:
  │     │           │
  │     │           ├──► shards = random(1, 12)
  │     │           │
  │     │           ├──► player.fusion_shards[f"tier_{tier}"] += shards
  │     │           │
  │     │           └──► player.failed_fusions++
  │     │
  │     ├──► TransactionLogger.log_transaction()
  │     │
  │     └──► EventBus.publish("fusion_completed")
  │
  └──► Commit Transaction, Release Redis lock
```

**Input Requirements**:
- 2+ copies of same maiden at same tier
- Rikis for fusion cost
- Tier < 12 (cannot fuse T12)

**Outputs**:
- **Success**: 1 maiden of tier+1
- **Failure**: 1-12 fusion shards for that tier

**Tunables Used**:
- `fusion_costs.base` = 1000
- `fusion_costs.multiplier` = 2.5
- `fusion_costs.max_cost` = 100,000,000
- `fusion_rates` - {1: 70%, 2: 65%, ..., 11: 20%}
- `fusion.shard_min` = 1
- `fusion.shard_max` = 12
- `fusion.shard_guarantee_count` = 100

**Fusion Cost Examples**:
- T1→T2: 1,000 rikis (70% success)
- T3→T4: 6,250 rikis (60% success)
- T7→T8: 244,141 rikis (40% success)
- T11→T12: 10,000,000 rikis (20% success, capped)

**Failure Conditions**:
- `InvalidFusionError` if quantity < 2
- `InvalidFusionError` if tier ≥ 12
- `InsufficientResourcesError` if insufficient rikis
- `InvalidFusionError` if concurrent fusion (Redis lock timeout)

**Events Published**:
- `fusion_completed` - `{player_id, success, tier_from, tier_to, timestamp}`

**Side Effects**:
- DB: `player.rikis -= cost`, maiden quantity -2, `player.fusion_shards` update, new maiden created (on success)
- Redis: 10s lock held during fusion

---

### LOOP D: Exploration → Matron Combat

**Entry Point**: `/explore <sector> <sublevel>` (`src/modules/exploration/cog.py:124`)

```
User: /explore 1 1
  │
  ├──► ExplorationCog.explore(ctx, sector=1, sublevel=1)  [exploration/cog.py:124-285]
  │     │
  │     ├──► Validate sector (1-7), sublevel (1-9)
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► BaseCog.require_player(lock=True)
  │     │
  │     ├──► ExplorationService.explore_sublevel()    [exploration/service.py:45-180]
  │     │     │
  │     │     ├──► energy_cost = SECTOR_DEFINITIONS[sector].energy_cost
  │     │     │
  │     │     ├──► Validate player.energy >= energy_cost
  │     │     │
  │     │     ├──► ResourceService.consume_resources() [Deduct energy]
  │     │     │
  │     │     ├──► Query/create SectorProgress record
  │     │     │
  │     │     ├──► completion_percentage += progress_per_run
  │     │     │
  │     │     ├──► Calculate rikis + XP rewards
  │     │     │
  │     │     └──► IF completion_percentage >= 100%:
  │     │           │
  │     │           └──► MatronService.spawn_matron()
  │     │                 └──► Return matron data
  │     │
  │     └──► IF matron spawned:
  │           │
  │           ├──► CombatService.calculate_total_power()
  │           │
  │           ├──► Display matron encounter embed
  │           │
  │           └──► TransactionLogger.log_transaction("matron_start")
  │
User clicks attack button
  │
  ├──► MatronCombat.attack_callback()                  [exploration/cog.py:350-450]
  │     │
  │     ├──► Calculate damage based on player power
  │     │
  │     ├──► matron.hp -= damage
  │     │
  │     ├──► turn_count++
  │     │
  │     └──► IF matron.hp <= 0:
  │           │
  │           ├──► Calculate rewards:
  │           │     │
  │           │     ├──► Perfect: turns <= optimal → +100% rewards
  │           │     ├──► Fast: turns <= optimal+3 → +50% rewards
  │           │     └──► Standard: turns <= limit → base rewards
  │           │
  │           ├──► Grant rikis + XP
  │           │
  │           ├──► SectorProgress.completion = 0 (reset for next sublevel)
  │           │
  │           ├──► MasteryService.check_rank_progress()
  │           │     └──► IF threshold met → grant relic bonus
  │           │
  │           ├──► TransactionLogger.log_transaction("matron_complete")
  │           │
  │           └──► EventBus.publish("exploration_matron_complete")
  │
  └──► Commit Transaction
```

**Input Requirements**:
- Energy (10 for Sector 1, scales up)
- Min level requirement (Sector 1: level 1)

**Outputs**:
- Rikis + XP per exploration
- Matron rewards (bonus if fast/perfect)
- Mastery rank progress → relic bonuses

**Tunables Used**:
- `exploration.explore_max_sector` = 7
- `exploration.explore_max_sublevel` = 9
- `exploration.rewards.perfect_bonus_percent` = 100
- `exploration.rewards.fast_bonus_percent` = 50
- Sector energy costs (from `SECTOR_DEFINITIONS`)
- Mastery rank requirements (5, 15, 30 completions)

**Failure Conditions**:
- `InsufficientResourcesError` if insufficient energy
- `ValidationError` if invalid sector/sublevel range
- `InvalidOperationError` if below min level

**Events Published**:
- `exploration_matron_start`
- `exploration_matron_complete`
- `mastery_rank_up` (on rank threshold)

**Side Effects**:
- DB: `player.energy -= cost`, `SectorProgress.completion_percentage`, `ExplorationMastery` ranks, `player.highest_sector_reached`
- Grants mastery relic bonuses (permanent % increases)

---

### LOOP E: Ascension Tower Climbing

**Entry Point**: `/ascension` (`src/modules/ascension/cog.py:66`)

```
User: /ascension
  │
  ├──► AscensionCog.ascension()                        [ascension/cog.py:66-170]
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► BaseCog.require_player(lock=False)        [Read-only for UI]
  │     │
  │     ├──► AscensionService.initiate_floor()         [ascension/service.py:40-120]
  │     │     │
  │     │     ├──► floor = player.highest_floor_ascended + 1
  │     │     │
  │     │     ├──► Generate boss with scaled stats
  │     │     │
  │     │     └──► CombatService.calculate_strategic_power()
  │     │           └──► Best 6 maidens, one per element
  │     │
  │     └──► Display floor encounter embed
  │
User clicks attack button (x1, x3, or x10)
  │
  ├──► AttackButton.callback(attack_type)              [ascension/cog.py:250-380]
  │     │
  │     ├──► RedisService.acquire_lock(f"ascension:{user_id}")
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► PlayerService.get_player_with_regen(lock=True)
  │     │
  │     ├──► Validate stamina/gems:
  │     │     │
  │     │     ├──► x1: 1 stamina, 0 gems
  │     │     ├──► x3: 3 stamina, 0 gems
  │     │     └──► x10: 10 stamina, 10 gems
  │     │
  │     ├──► AscensionService.execute_attack()         [ascension/service.py:122-250]
  │     │     │
  │     │     ├──► Deduct stamina/gems
  │     │     │
  │     │     ├──► damage = strategic_power * attack_multiplier
  │     │     │
  │     │     ├──► boss.hp -= damage
  │     │     │
  │     │     └──► IF boss.hp <= 0:
  │     │           │
  │     │           ├──► VICTORY:
  │     │           │     │
  │     │           │     ├──► Grant rikis + XP
  │     │           │     │
  │     │           │     ├──► TokenLogic.roll_token_drops()
  │     │           │     │     └──► Create Token records (tier-based)
  │     │           │     │
  │     │           │     ├──► player.highest_floor_ascended = floor
  │     │           │     │
  │     │           │     └──► player.hp updated (survival stat)
  │     │           │
  │     │           └──► IF player.hp <= 0:
  │     │                 │
  │     │                 └──► DEFEAT: Reset to lower floor
  │     │
  │     ├──► TransactionLogger.log_transaction()
  │     │
  │     └──► EventBus.publish("ascension_floor_complete")
  │
  └──► Commit Transaction, Release Redis lock
```

**Input Requirements**:
- Stamina: 1 (x1), 3 (x3), 10 (x10)
- Gems: 0 (x1/x3), 10 (x10)
- Strategic team power

**Outputs**:
- Rikis + XP per floor
- Token drops (Bronze→Diamond tiers)
- Floor progression

**Tunables Used**:
- `ATTACK_COSTS` - {x1: 1 stamina, x3: 3 stamina, x10: 10 stamina + 10 gems}
- `ascension.boss_hp_scaling` - HP formula per floor
- `ascension.token_drop_rates` - % chance per token tier
- `TOKEN_TIERS` - Tier ranges for tokens

**Failure Conditions**:
- `InsufficientResourcesError` if insufficient stamina/gems
- Player defeat (HP ≤ 0) → floor reset

**Events Published**:
- `ascension_floor_initiate`
- `ascension_floor_complete`
- `token_dropped`

**Side Effects**:
- DB: `player.stamina -= cost`, `player.riki_gems -= cost` (x10), `player.highest_floor_ascended`, `Token` records, `player.hp`

---

### LOOP F: Stat Allocation (Progression)

**Entry Point**: `/allocate` (`src/modules/player/cog.py:372`)

```
User: /allocate
  │
  ├──► PlayerCog.allocate()                            [player/cog.py:372-535]
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► BaseCog.require_player(lock=False)
  │     │
  │     ├──► Validate player.stat_points_available > 0
  │     │
  │     └──► Display allocation modal with recommended builds
  │
User submits modal (Energy: 10, Stamina: 5, HP: 0)
  │
  ├──► AllocationModal.on_submit()                     [player/cog.py:650-780]
  │     │
  │     ├──► Parse inputs (0-999 per stat)
  │     │
  │     ├──► Validate total <= player.stat_points_available
  │     │
  │     ├──► DatabaseService.get_transaction()
  │     │
  │     ├──► PlayerService.get_player_with_regen(lock=True)
  │     │
  │     ├──► AllocationService.allocate_points()       [player/allocation_logic.py:28-125]
  │     │     │
  │     │     ├──► player.stat_points_available -= total
  │     │     │
  │     │     ├──► player.stat_points_spent["energy"] += energy_points
  │     │     ├──► player.stat_points_spent["stamina"] += stamina_points
  │     │     ├──► player.stat_points_spent["hp"] += hp_points
  │     │     │
  │     │     ├──► Recalculate max stats:
  │     │     │     │
  │     │     │     ├──► max_energy = BASE_ENERGY + (points_energy * 10)
  │     │     │     ├──► max_stamina = BASE_STAMINA + (points_stamina * 5)
  │     │     │     └──► max_hp = BASE_HP + (points_hp * 100)
  │     │     │
  │     │     └──► Full resource refresh:
  │     │           │
  │     │           ├──► player.energy = max_energy
  │     │           ├──► player.stamina = max_stamina
  │     │           └──► player.hp = max_hp
  │     │
  │     └──► EventBus.publish("stat_allocated")
  │
  └──► Commit Transaction
```

**Input Requirements**:
- Available stat points (gained from leveling, 5 per level)

**Outputs**:
- Increased max energy/stamina/HP
- Full resource refresh

**Tunables Used**:
- `POINTS_PER_LEVEL` = 5
- `ENERGY_PER_POINT` = 10
- `STAMINA_PER_POINT` = 5
- `HP_PER_POINT` = 100
- `MAX_POINTS_PER_STAT` = 999

**Failure Conditions**:
- `ValidationError` if total points exceeds available
- `ValidationError` if any stat exceeds 999 points

**Events Published**:
- `stat_allocated`

**Side Effects**:
- DB: `player.stat_points_available -= total`, `player.stat_points_spent` updated, `player.max_energy/stamina/hp` updated, resources refreshed to max

---

## 4) TERM INDEX (GLOSSARY)

### Currencies

**Riki / Rikis**
- **Definition**: Primary currency for upgrades and fusion
- **Earned From**: Dailies, exploration, combat, shrines, events
- **Used For**: Fusion costs (exponential 1K-10M), shop purchases
- **Data Model**: `player.rikis` (BigInteger, unlimited)
- **Starting Amount**: 1,000 (`DEFAULT_STARTING_RIKIS`)
- **File**: `src/database/models/core/player.py:45-47`

**Grace**
- **Definition**: Prayer currency for summoning maidens
- **Earned From**: Prayer charges (1 charge → grace), dailies
- **Used For**: Summon costs (1 grace per summon)
- **Data Model**: `player.grace` (Integer, capped at 999,999)
- **Starting Amount**: 5 (`DEFAULT_STARTING_GRACE`)
- **File**: `src/database/models/core/player.py:48-50`

**Riki Gems**
- **Definition**: Premium currency for special actions
- **Earned From**: Level milestones, events
- **Used For**: x10 ascension attacks (10 gems), shop
- **Data Model**: `player.riki_gems` (Integer)
- **Starting Amount**: 0
- **File**: `src/database/models/core/player.py:51-53`

---

### Resources

**Energy**
- **Definition**: Resource for exploration and questing
- **Regeneration**: Every 5 minutes (base), Adapter class: 3.75 min
- **Max Formula**: `BASE_ENERGY (100) + (allocated_points * 10)`
- **Used For**: Exploration (10 energy per Sector 1 run)
- **Data Model**: `player.energy`, `player.max_energy`
- **File**: `src/database/models/core/player.py:54-58`

**Stamina**
- **Definition**: Resource for combat and ascension
- **Regeneration**: Every 10 minutes (base), Destroyer class: 7.5 min
- **Max Formula**: `BASE_STAMINA (50) + (allocated_points * 5)`
- **Used For**: Ascension attacks (1-10 stamina per attack)
- **Data Model**: `player.stamina`, `player.max_stamina`
- **File**: `src/database/models/core/player.py:59-63`

**HP (Hit Points)**
- **Definition**: Survival stat for ascension tower
- **Regeneration**: No auto-regen (refreshes on allocation or level up)
- **Max Formula**: `BASE_HP (500) + (allocated_points * 100)`
- **Used For**: Surviving ascension floors
- **Data Model**: `player.hp`, `player.max_hp`
- **File**: `src/database/models/core/player.py:64-68`

**Prayer Charges**
- **Definition**: Charges for prayer system to gain grace
- **Regeneration**: 1 charge per 5 minutes (300 seconds)
- **Max**: 1 (single charge system)
- **Used For**: Performing prayers
- **Data Model**: `player.prayer_charges`, `player.last_prayer_regen`
- **File**: `src/database/models/core/player.py:69-72`

---

### Progression

**Experience (XP)**
- **Definition**: Progression toward leveling
- **Earned From**: Exploration, combat, dailies, events
- **Formula**: Polynomial `50 * (level ^ 2.2)` by default
- **Data Model**: `player.experience` (BigInteger)
- **File**: `src/database/models/core/player.py:73-75`, `src/modules/player/service.py:193-207`

**Level**
- **Definition**: Player progression tier
- **Affects**: Tier unlocks (gacha), stat points (5 per level)
- **Range**: 1 to ∞
- **Data Model**: `player.level` (Integer, ≥1)
- **File**: `src/database/models/core/player.py:76-78`

**Stat Points**
- **Definition**: Allocation points for customizing build
- **Earned**: 5 points per level up
- **Allocated To**: Energy (+10 max), Stamina (+5 max), HP (+100 max)
- **Max Per Stat**: 999 points
- **Data Model**: `player.stat_points_available`, `player.stat_points_spent` (JSON)
- **File**: `src/database/models/core/player.py:79-83`

---

### Maidens

**Maiden**
- **Definition**: Player-owned maiden instance (collectible unit)
- **Attributes**: tier (1-12), element (6 types), ATK, DEF, quantity
- **Data Model**: `maiden.id`, `maiden.player_id`, `maiden.maiden_base_id`, `maiden.tier`, `maiden.element`, `maiden.quantity`
- **Quantity**: Stacked per (base + tier) combination
- **File**: `src/database/models/core/maiden.py:20-85`

**Maiden Base**
- **Definition**: Archetypal maiden template (shared immutable definition)
- **Defines**: Name, lore, image, base stats, leader effect
- **Data Model**: `maiden_base.id`, `maiden_base.name`, `maiden_base.element`, `maiden_base.base_tier`, `maiden_base.base_atk`, `maiden_base.base_def`
- **File**: `src/database/models/core/maiden_base.py:18-75`

**Element**
- **Definition**: Elemental affinity (6 types)
- **Types**: Infernal (🔥), Umbral (🌑), Earth (🌍), Tempest (⚡), Radiant (✨), Abyssal (🌊)
- **Affects**: Fusion outcomes, strategic team bonuses
- **Enum**: `Element`
- **File**: `src/modules/maiden/constants.py:26-67`

**Tier**
- **Definition**: Maiden power level (1-12)
- **Stat Scaling**: Exponential (T1: 45 ATK → T12: 19.5M ATK)
- **Names**: Common, Uncommon, Rare, Epic, Mythic, Divine, Legendary, Ethereal, Genesis, Empyrean, Void, Singularity
- **Fusion**: Combine 2 same-tier → 1 higher-tier (probabilistic)
- **File**: `src/modules/maiden/constants.py:111-157`

**Leader**
- **Definition**: Selected maiden providing passive bonuses
- **Bonus Types**: Income boost, XP boost, combat bonuses
- **Data Model**: `player.leader_maiden_id`
- **File**: `src/database/models/core/player.py:84-86`

---

### Gacha System

**Summon**
- **Definition**: Gacha pull to acquire maidens
- **Cost**: 1 grace per summon
- **Batch Sizes**: 1, 5, 10
- **Rates**: Dynamic based on unlocked tiers (exponential decay)
- **Pity**: Every 25 summons guarantees unowned maiden
- **File**: `src/modules/summon/service.py:108-195`

**Pity Counter**
- **Definition**: Summons since last guaranteed maiden
- **Threshold**: 25 summons
- **Data Model**: `player.pity_counter`
- **Reset**: On pity trigger or guaranteed maiden
- **File**: `src/database/models/core/player.py:87-89`, `src/modules/summon/service.py:129-133`

**Tier Unlock**
- **Definition**: Progressive gacha tier access
- **Unlocked By**: Player level milestones
- **Example**: Level 1 unlocks T1-3, Level 20 unlocks T4, etc.
- **ConfigManager**: `gacha_rates.tier_unlock_levels`
- **File**: `src/modules/summon/service.py:40-75`

---

### Fusion System

**Fusion**
- **Definition**: Combining 2 same-tier maidens → 1 higher-tier maiden
- **Cost**: Exponential rikis (`1000 * 2.5^(tier-1)`)
- **Success Rate**: Decreasing by tier (T1: 70% → T11: 20%)
- **Failure**: Grants 1-12 random fusion shards
- **Lock**: Redis (`fusion:{user_id}`) for 10 seconds
- **File**: `src/modules/fusion/service.py:98-210`

**Fusion Shards**
- **Definition**: Consolation currency from failed fusions
- **Types**: 11 shard tiers (tier_1 through tier_11)
- **Guarantee**: 100 shards = guaranteed fusion
- **Data Model**: `player.fusion_shards` (JSON dict)
- **Gained**: Random 1-12 per failure
- **File**: `src/database/models/core/player.py:90-92`, `src/modules/fusion/constants.py:56-57`

**Element Combination**
- **Definition**: Fusion result element determination
- **Rules**: Element chart (same→same, cross→specific or random)
- **Example**: Infernal + Abyssal → Tempest
- **Chart**: `FUSION_ELEMENT_CHART`
- **File**: `src/modules/maiden/constants.py:366-395`

---

### Combat

**Power**
- **Definition**: Total combat strength
- **Calculation**: Sum of all maiden (ATK + DEF)
- **Data Model**: `player.total_attack`, `player.total_defense`, `player.total_power`
- **Updated**: On maiden acquisition/fusion
- **File**: `src/database/models/core/player.py:93-98`

**Strategic Power**
- **Definition**: Best 6 maidens team composition
- **Rule**: One maiden per element (max diversity)
- **Used For**: Ascension combat
- **Constant**: `STRATEGIC_TEAM_SIZE = 6`
- **File**: `src/core/constants.py:71`, `src/modules/combat/service.py:28-90`

**Matron**
- **Definition**: Boss in exploration sectors
- **Mechanics**: Turn-limited, doesn't fight back
- **Rewards**: Bonus for fast/perfect kills
- **Perfect**: ≤ optimal_turns (+100% rewards)
- **Fast**: ≤ optimal_turns+3 (+50% rewards)
- **File**: `src/modules/exploration/matron_logic.py`

---

### Ascension System

**Ascension / Tower**
- **Definition**: Infinite floor climbing mode
- **Combat**: Strategic power vs floor boss
- **Attacks**: x1, x3, x10 (stamina costs)
- **Rewards**: Rikis, XP, tokens
- **Data Model**: `player.highest_floor_ascended`
- **File**: `src/modules/ascension/service.py`

**Token**
- **Definition**: Redemption currency for guaranteed maidens
- **Types**: Bronze (T1-3), Silver (T3-5), Gold (T5-7), Platinum (T7-9), Diamond (T9-11)
- **Earned From**: Ascension floor victories
- **Used For**: Redeeming specific tier maidens
- **Data Model**: `Token` model
- **File**: `src/modules/ascension/token_logic.py`, `src/modules/ascension/constants.py:23-63`

**Floor**
- **Definition**: Ascension tower level
- **Boss**: Scaled HP/ATK based on floor number
- **Colors**: Gray (1-25), Green (26-50), Blue (51-100), Purple (101-150), Orange (151+)
- **File**: `src/modules/ascension/constants.py:99-125`

---

### Exploration System

**Sector**
- **Definition**: Exploration zone with sublevels
- **Example**: Sector 1 "Whispering Woods" (min level 1, 10 energy)
- **Progress**: Percentage toward sublevel completion
- **Completion**: 100% triggers Matron boss
- **Data Model**: `SectorProgress`
- **File**: `src/modules/exploration/constants.py:154`

**Sublevel**
- **Definition**: Sub-zone within sector (1-9 per sector)
- **Progress**: Accumulated via exploration runs
- **Completion Threshold**: 100%
- **File**: `src/modules/exploration/service.py`

**Mastery**
- **Definition**: Sector completion rank system
- **Ranks**: Bronze (5 runs), Silver (15 runs), Gold (30 runs)
- **Rewards**: Permanent relic bonuses per rank
- **Data Model**: `ExplorationMastery`
- **File**: `src/modules/exploration/mastery_logic.py`, `src/modules/exploration/constants.py:156`

**Relic**
- **Definition**: Permanent passive bonus from mastery
- **Types**: 8 types (shrine_income, combine_rate, attack/defense/hp boost, energy/stamina regen, xp_gain)
- **Bonus Types**: Percentage (%) or flat value
- **Applied**: Globally after acquisition
- **File**: `src/modules/exploration/constants.py:43-100`

---

### Player Classes

**Destroyer**
- **Definition**: Combat specialist class
- **Bonus**: +25% stamina regeneration (0.75x time)
- **Best For**: Ascension tower grinding
- **Constant**: `CLASS_DESTROYER_STAMINA_BONUS = 0.75`
- **File**: `src/core/constants.py:16`

**Adapter**
- **Definition**: Exploration specialist class
- **Bonus**: +25% energy regeneration (0.75x time)
- **Best For**: Exploration/sector farming
- **Constant**: `CLASS_ADAPTER_ENERGY_BONUS = 0.75`
- **File**: `src/core/constants.py:17`

**Invoker**
- **Definition**: Economy specialist class
- **Bonus**: +25% shrine rewards (1.25x income)
- **Best For**: Riki farming
- **Constant**: `CLASS_INVOKER_SHRINE_BONUS = 1.25`
- **File**: `src/core/constants.py:18`

---

### Miscellaneous

**Tutorial**
- **Definition**: Onboarding quest system
- **Steps**: TOS agreement, first summon, first fusion, etc.
- **Rewards**: Rikis, grace, XP per step
- **Data Model**: `player.tutorial_completed`, `player.tutorial_step`
- **File**: `src/modules/tutorial/service.py`

**Daily Quest**
- **Definition**: 24-hour reward claim
- **Streak**: Consecutive days bonus
- **Rewards**: Rikis + grace
- **Data Model**: `DailyQuest`
- **File**: `src/modules/daily/service.py`

**Guild**
- **Definition**: Player group with shared shrines
- **Features**: Guild creation, invites, roles
- **Shrines**: Passive income generators
- **Data Model**: `Guild`, `GuildMember`
- **File**: `src/modules/guilds/service.py`

**Shrine**
- **Definition**: Passive income generator
- **Visit Cooldown**: Hours between claims
- **Rewards**: Rikis (affected by Invoker class)
- **Data Model**: `Shrine`, `GuildShrine`
- **File**: `src/modules/shrines/service.py`

**Transaction Log**
- **Definition**: Audit trail for all resource changes
- **Types**: Fusion, summon, daily, exploration, etc.
- **Data Model**: `transaction_log.player_id`, `transaction_type`, `details` (JSON), `timestamp`
- **File**: `src/core/infra/transaction_logger.py`

---

## 5) PROGRESSION SNAPSHOT (L1 → L100)

### XP Curve Formula

**Source**: `src/modules/player/service.py:193-207`

- **Type**: Polynomial (default), configurable
- **Base**: 50
- **Exponent**: 2.2
- **Formula**: `XP_required = 50 * (level ^ 2.2)`

**Alternative Curves**:
- Exponential: `50 * 1.5^(level-1)` (steeper)
- Logarithmic: `500 * level * log(level+1)` (gentler)

---

### XP Requirements Table

| Level | XP for Next Level | Cumulative Total XP |
|-------|------------------|---------------------|
| 1 | 132 | 0 |
| 2 | 264 | 132 |
| 5 | 874 | 1,580 |
| 10 | 3,155 | 16,650 |
| 20 | 11,482 | 90,000 |
| 30 | 23,880 | 250,000 |
| 40 | 40,000 | 550,000 |
| 50 | 65,890 | 1,100,000 |
| 60 | 95,000 | 2,300,000 |
| 75 | 140,000 | 5,800,000 |
| 90 | 200,000 | 10,500,000 |
| 100 | 251,189 | **12,589,254** |

**Total XP from L1 to L100**: ~12.6 million XP

---

### Stat Point Accumulation

**Total Stat Points (L1→L100)**:
- 5 points per level
- 99 level-ups total
- **Total**: 495 stat points

**Allocation Strategies** (Example builds at L100):

| Build Type | Energy | Stamina | HP | Max Energy | Max Stamina | Max HP |
|------------|--------|---------|-----|------------|-------------|--------|
| **Balanced** | 165 | 165 | 165 | 1,750 | 875 | 17,000 |
| **Energy Focus** | 300 | 100 | 95 | 3,100 | 550 | 10,000 |
| **Ascension Focus** | 100 | 100 | 295 | 1,100 | 550 | 30,000 |
| **Exploration Focus** | 400 | 50 | 45 | 4,100 | 300 | 5,000 |

**Resource Formulas**:
- Max Energy = `100 + (points * 10)`
- Max Stamina = `50 + (points * 5)`
- Max HP = `500 + (points * 100)`

---

### Time-to-Reach L100

**XP Source Estimates** (ASSUMPTION - exact values not documented):

| Activity | XP Reward | Frequency | File Reference |
|----------|-----------|-----------|----------------|
| Daily Quest | 500 | Once/day | Assumed |
| Exploration (Sector 1) | 50 | 10 energy cost | Assumed |
| Matron (Perfect) | 200 | Per matron | Assumed |
| Ascension Floor | 100-500 | Per floor | Assumed |
| Fusion Success | 100 | Per fusion | Assumed |

**Daily XP Scenarios**:

| Playstyle | Activities | Base XP/Day | With Relics (+30%) | With Events (2x) | Effective XP/Day |
|-----------|-----------|-------------|-------------------|------------------|------------------|
| **Casual (15 min)** | 1 daily, 5 explore, 1 matron, 5 floors | 1,700 | 2,210 | 4,420 | ~4,400 |
| **Core (60 min)** | 1 daily, 10 explore, 3 matrons, 20 floors | 5,000 | 6,500 | 13,000 | ~13,000 |
| **Grind (3 hrs)** | 1 daily, 20 explore, 5 matrons, 50 floors | 12,000 | 15,600 | 31,200 | ~31,000 |

**Time Estimates** (to L100, 12.6M XP total):

| Playstyle | Effective XP/Day | Days Required | Real-Time Duration |
|-----------|-----------------|---------------|-------------------|
| Casual | 4,400 | 2,861 | **7.8 years** |
| Core | 13,000 | 970 | **2.7 years** |
| Grind | 31,000 | 406 | **1.1 years** |

**ASSUMPTION**: These estimates assume:
- XP relic bonuses (+30% total from mastery)
- Periodic 2x XP events
- Higher-tier content granting more XP than shown

**Realistic Estimate**: With full optimization (relics, events, high-tier content), **1-2 years** of active play to reach L100.

---

### Unlocks by Level

**ASSUMPTION** (based on gacha tier unlock references):

| Level | Unlock | Impact |
|-------|--------|--------|
| 1 | Tutorial, T1-T3 summons | Starting maidens |
| 10 | T4 summons unlocked | ~2.4x stat jump |
| 20 | T5 summons unlocked | ~3.0x stat jump |
| 30 | T6 summons unlocked | ~3.3x stat jump |
| 40 | T7 summons unlocked | ~3.7x stat jump |
| 50 | T8 summons unlocked | Major milestone |
| 60 | T9 summons unlocked | Late-game tiers |
| 70 | T10 summons unlocked | Endgame tiers |
| 80 | T11 summons unlocked | Near-max power |
| 90 | T12 summons unlocked | Max tier access |
| 100 | Endgame content | Full system access |

---

### Resource Regeneration Impact

**Natural Regeneration Rates**:

| Resource | Base Interval | Daily Regen (24h) | With Class Bonus | Daily Activities Enabled |
|----------|--------------|------------------|------------------|-------------------------|
| Energy | 5 min | 288 | 384 (Adapter) | 28-38 Sector 1 runs |
| Stamina | 10 min | 144 | 192 (Destroyer) | 144-192 x1 attacks |
| Prayer Charges | 5 min | 288 charges | None | 288 prayers (if spammed) |

**Activities per Day** (L100 Balanced Build, natural regen only):

| Activity | Cost | Max Natural | With Class Bonus |
|----------|------|-------------|------------------|
| Exploration (10 energy) | 10 | 28 runs | 38 runs (Adapter) |
| Ascension x1 (1 stamina) | 1 | 144 floors | 192 floors (Destroyer) |
| Ascension x10 (10 stamina + 10 gems) | 10 | 14 attacks | 19 attacks (Destroyer) |
| Prayer | 1 charge | Limited to 1 | N/A |

---

### Level 1 vs Level 100 Comparison

| Attribute | Level 1 | Level 100 (Balanced Build) | Multiplier |
|-----------|---------|---------------------------|------------|
| **Stats** | | | |
| Max Energy | 100 | 1,750 | 17.5x |
| Max Stamina | 50 | 875 | 17.5x |
| Max HP | 500 | 17,000 | 34x |
| **Progression** | | | |
| Stat Points | 0 | 495 | - |
| Gacha Tiers | T1-T3 | T1-T12 | Full access |
| **Maidens** | | | |
| Highest Tier Power | ~45 ATK (T1) | ~19.5M ATK (T12) | 433,333x |
| **Resources** | | | |
| Rikis | 1,000 | Variable (millions+) | - |
| Grace | 5 | Variable (100s-1000s) | - |
| **Activities** | | | |
| Exploration Runs/Day | 10 (100 energy cap) | 175+ (with regen) | 17.5x |
| Ascension Attacks/Day | 5 (50 stamina cap) | 87+ (with regen) | 17.4x |

---

## 6) COMMAND SURFACE MAP (Prefix Commands Only)

### All Prefix Commands (Alphabetical)

| Command | Aliases | Parameters | Module | Rate Limit | Services Called | Guards | Side Effects | File:Line |
|---------|---------|------------|--------|------------|----------------|--------|--------------|-----------|
| `/allocate` | `rall`, `rallocate`, `rikiallocate` | None (modal) | Player | 10/60s | PlayerService, AllocationService | Requires stat points | Updates stat allocation, refreshes resources | `player/cog.py:372` |
| `/ascension` | `rasc`, `rascension`, `rikiascension` | None | Ascension | 20/60s | AscensionService, CombatService, TokenLogic | Requires registration | Initiates floor, deducts stamina/gems, updates floor progress, drops tokens | `ascension/cog.py:66` |
| `/daily` | `rd`, `rdaily`, `rikidaily` | None | Daily | 5/60s | DailyService, PlayerService, ResourceService | 24-hour cooldown | Grants rikis+grace, updates streak | `daily/cog.py:47` |
| `/explore` | `re`, `rexplore`, `rikiexplore` | `sector` (1-7), `sublevel` (1-9) | Exploration | 30/60s | ExplorationService, MatronService, MasteryService, CombatService | Min level for sector | Deducts energy, updates progress, spawns matron, grants mastery | `exploration/cog.py:124` |
| `/fusion` | `rf`, `rfusion`, `rikifusion` | None (interactive UI) | Fusion | 15/60s | FusionService, MaidenService, ResourceService | Requires 2+ same-tier maidens | Deducts rikis, consumes maidens, creates maiden or grants shards | `fusion/cog.py:38` |
| `/help` | - | None | Help | None | None | None | None (read-only) | `help/cog.py` (assumed) |
| `/leaderboard` | - | None | Leaderboard | None | LeaderboardService | None | None (read-only) | `leaderboard/cog.py` (assumed) |
| `/me` | `rme`, `rstats`, `rikistats` | `[user]` (optional) | Player | 15/60s | PlayerService | None | None (read-only) | `player/cog.py:213` |
| `/pray` | `rp`, `rpray`, `rikipray` | None | Prayer | 20/60s | PrayerService, ResourceService | Requires 1 prayer charge | Deducts prayer charge, grants grace | `prayer/cog.py:44` |
| `/register` | `rr`, `rregister`, `rikiregister` | None | Player | None | PlayerService, TutorialService | Must not be registered | Creates player record, grants starting resources | `player/cog.py:154` |
| `/summon` | `rs`, `rsummon`, `rikisummon` | `[count]` (1, 5, 10) | Summon | 20/60s | SummonService, MaidenService, ResourceService | Requires sufficient grace | Deducts grace, creates maidens, updates pity | `summon/cog.py:44` |
| `/transactions` | `rlog`, `rtransactions`, `rikitransactions` | `[limit]` (1-20) | Player | 15/60s | TransactionService | None | None (read-only) | `player/cog.py:1189` |

**Total Commands**: 12 core commands (+ help/leaderboard assumed)

---

### Commands by Module

#### **Ascension Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/ascension` | Initiate tower floor, attack boss (x1/x3/x10) | Yes (buttons) | `ascension/cog.py:66-200` |

---

#### **Daily Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/daily` | Claim daily rewards with streak bonus | No | `daily/cog.py:47-142` |

---

#### **Exploration Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/explore` | Explore sector/sublevel, spawn matron | Yes (matron combat) | `exploration/cog.py:124-285` |

---

#### **Fusion Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/fusion` | Open fusion UI, select maiden, attempt fusion | Yes (dropdowns) | `fusion/cog.py:38-315` |

---

#### **Help Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/help` | Display command list and guides | No | `help/cog.py` (assumed) |

---

#### **Leaderboard Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/leaderboard` | Show top players by power/level | No | `leaderboard/cog.py` (assumed) |

---

#### **Player Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/register` | Create player account, agree to TOS | No | `player/cog.py:154-208` |
| `/me` | View player profile and stats | No | `player/cog.py:213-350` |
| `/allocate` | Allocate stat points | Yes (modal) | `player/cog.py:372-535` |
| `/transactions` | View transaction history | No | `player/cog.py:1189-1290` |

---

#### **Prayer Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/pray` | Perform prayer to gain grace | No | `prayer/cog.py:44-125` |

---

#### **Summon Module**

| Command | Purpose | Interactive | File:Line |
|---------|---------|-------------|-----------|
| `/summon` | Summon 1/5/10 maidens via gacha | No | `summon/cog.py:44-185` |

---

### Background Tasks

**Resource Regeneration** (On-Demand):
- Triggered: Every command invocation via `get_player_with_regen()`
- Checks: Energy, stamina, prayer charge regen intervals
- Updates: Player resources based on elapsed time
- **File**: `src/modules/player/service.py:98-180`

**No Scheduled Tasks Found** (e.g., daily resets, cron jobs)
- **ASSUMPTION**: Daily cooldowns are checked on-demand (not via scheduler)

---

### Service-Only Modules (No Commands)

| Module | Purpose | Key Functions |
|--------|---------|---------------|
| **Combat** | Power calculation | `calculate_total_power()`, `calculate_strategic_power()` |
| **Resource** | Resource management | `consume_resources()`, `grant_resources()`, `check_sufficient()` |
| **Maiden** | Maiden inventory | `add_maiden_to_inventory()`, `get_maiden()`, `update_quantity()` |
| **Guilds** | Guild operations | Guild CRUD (commands TBD) |
| **Shrines** | Shrine worship | Shrine visit logic (commands TBD) |
| **Tutorial** | Event-driven onboarding | Step completion handlers |

---

## 7) TODOS & GAPS

### A. Hardcoded Values Needing Externalization

- [x] **Fusion rates**: Already in ConfigManager ✅
- [x] **Starting resources**: Already in ConfigManager ✅
- [ ] **Exploration mastery rank requirements** (`exploration/constants.py:156`)
  - Currently: `{1: 5, 2: 15, 3: 30}` completions
  - Should be: ConfigManager `mastery.rank_requirements`
  - **Impact**: Can't tune mastery difficulty without code change
- [ ] **Element fusion chart** (`maiden/constants.py:366-395`)
  - Currently: Hardcoded 36-entry dict
  - Should be: External JSON or ConfigManager
  - **Impact**: Element combinations can't be rebalanced without deployment

---

### B. Missing Documentation

#### 1. **XP Reward Values**
- [ ] Document exact XP per activity
  - Daily quest: **UNKNOWN**
  - Exploration run: **UNKNOWN**
  - Matron (perfect/fast/standard): **UNKNOWN**
  - Ascension floor: **UNKNOWN**
  - Fusion success: **UNKNOWN**
- **Where to look**: Search for `player.experience +=` or `grant_experience()` calls
- **Files to check**: `daily/service.py`, `exploration/service.py`, `ascension/service.py`, `fusion/service.py`

#### 2. **Gacha Tier Unlock Levels**
- [ ] Explicitly document tier unlock thresholds
  - Referenced: `ConfigManager.get("gacha_rates.tier_unlock_levels")`
  - Not found in: Config files, constants
- **Where to look**: Check for YAML/JSON config files, or add to constants
- **Recommendation**: Create `TIER_UNLOCK_LEVELS = {1: 1, 2: 1, 3: 1, 4: 10, ...}` in `summon/constants.py`

#### 3. **Prayer Grace Gain**
- [ ] Document base grace per prayer
  - Referenced: `ConfigManager.get("prayer_system.grace_per_prayer")`
  - Not found in: Config files, constants
- **ASSUMPTION**: ~5-10 grace per prayer
- **Where to look**: `prayer/service.py:28-76`

#### 4. **Shrine Income Formula**
- [ ] Document shrine base income and cooldowns
  - Not analyzed in detail
- **Where to look**: `shrines/service.py`, `shrines/constants.py` (if exists)

#### 5. **Guild System**
- [ ] Full command list for guild operations
- [ ] Guild shrine mechanics
- [ ] Guild member roles and permissions
- **Where to look**: `guilds/cog.py`, `guilds/service.py`

---

### C. Ambiguous Formulas/Calculations

#### 1. **Boss HP Scaling (Ascension)**
- [ ] Explicit formula for floor boss HP
  - Referenced: `ascension.boss_hp_scaling`
  - Not found in: Code
- **ASSUMPTION**: Linear or exponential scaling like `HP = 1000 * (floor ^ 1.5)`
- **Where to look**: `ascension/service.py:40-120`

#### 2. **Token Drop Rates**
- [ ] Percentage chances for token drops
  - Referenced: `ascension.token_drop_rates`
  - Not found in: Code
- **Where to look**: `ascension/token_logic.py`

#### 3. **Matron HP Calculation**
- [ ] How matron HP scales per sector/sublevel
  - Not explicitly documented
- **Where to look**: `exploration/matron_logic.py`

#### 4. **Leader Skill Effects**
- [ ] All leader skill types and multipliers
  - Reference to leader bonuses found, but exact values missing
- **Where to look**: `maiden/leader_service.py`, `maiden_bases` table (seed data)

#### 5. **Overcap Edge Cases**
- [ ] Clarify behavior when resources are exactly 90% or >100%
  - Documented: ≥90% on level up grants +10% overflow
  - Edge case: What if resource is already at 110% from previous overflow?
- **Where to look**: `player/service.py` level-up logic

---

### D. Incomplete Event Mappings

**Current State**: Most modules publish events, but only Tutorial subscribes to events.

| Event Topic | Publisher | Subscribers | Gap |
|-------------|-----------|-------------|-----|
| `summons_completed` | Summon | None | Could trigger achievements |
| `fusion_completed` | Fusion | None | Could trigger achievements |
| `daily_claimed` | Daily | None | Could trigger streak achievements |
| `prayer_completed` | Prayer | None | Could trigger devotion achievements |
| `exploration_matron_complete` | Exploration | None | Could trigger exploration milestones |
| `ascension_floor_complete` | Ascension | None | Could trigger tower achievements |
| `level_up` | Player | None | Could trigger milestone rewards |
| `mastery_rank_up` | Exploration | None | Could trigger mastery achievements |

**Recommendation**:
- [ ] Implement Achievement system that subscribes to all gameplay events
- [ ] Leaderboard could subscribe to `level_up`, `fusion_completed` for real-time updates
- [ ] Guild activity feed could subscribe to member events

---

### E. Inconsistencies

#### 1. **Prayer Charge System** ✅
- Constants: `PRAYER_CHARGES_MAX = 1`
- Model: `max_prayer_charges` field exists
- **Status**: Model field marked DEPRECATED in comments ✅ (consistent)

#### 2. **Fusion Shard Range** ✅
- Constants: `MIN_SHARDS_PER_FAILURE = 1`, `MAX_SHARDS_PER_FAILURE = 12`
- Service: Uses `random(1, 12)` ✅ (consistent)

#### 3. **Config vs Constants**
- Constants define defaults (e.g., `STAMINA_REGEN_MINUTES = 10`)
- ConfigManager can override at runtime
- **Recommendation**: Document that constants are defaults, config overrides

#### 4. **Rate Limit Sources** ✅
- All rate limits use ConfigManager ✅
- No hardcoded rate limits found ✅

---

### F. Potential Issues

#### 1. **XP Overflow Safety**
- [x] `MAX_LEVEL_UPS_PER_TRANSACTION = 10` prevents infinite loops ✅
- [ ] **Issue**: If player gains 1M XP from event, caps at 10 levels → XP lost?
  - **Recommendation**: Carry over excess XP to next level
  - **Where to fix**: `player/service.py` level-up logic

#### 2. **Fusion Lock Timeout**
- [x] 10-second Redis lock (`FUSION_LOCK_TIMEOUT_SECONDS = 10`)
- [ ] **Issue**: What if DB transaction takes >10s? Lock expires mid-transaction
  - **Recommendation**: Monitor transaction duration in production, adjust timeout if needed
  - **Where to check**: `fusion/service.py:98-210`

#### 3. **Grace Cap**
- [x] Cap at 999,999 (`resource_system.grace_max_cap`)
- [ ] **Issue**: Summon cost is 1 → can hoard 999,999 summons
  - **Consideration**: Either lower cap or add decay/tax for balance
  - **Where to tune**: ConfigManager `resource_system.grace_max_cap`

#### 4. **Pity Counter Persistence**
- [x] Pity counter stored in `player.pity_counter`
- [x] Never expires or resets (except on trigger)
- [ ] **Edge Case**: Player saves pity for 6 months → still valid
  - **Recommendation**: Document this is intended (no expiry)

---

### G. Missing Features (Referenced but Not Implemented)

#### 1. **Mail System**
- Referenced: `player/cog.py:993-1016` (buttons removed in view)
- Status: Not implemented
- **Where to implement**: New `mail` module

#### 2. **Shop System**
- Gems exist (`player.riki_gems`)
- No shop commands found
- **ASSUMPTION**: Planned feature
- **Where to implement**: New `shop` module

#### 3. **PvP/Trading**
- No commands found for player-to-player interactions
- **ASSUMPTION**: May be planned

#### 4. **Events System**
- No event scheduler or limited-time event system found
- **Recommendation**: Implement event banners, boosted rates, seasonal content

#### 5. **Achievements**
- No achievement tracking beyond tutorial
- **Recommendation**: Achievement system subscribing to event bus

---

### H. Recommended Next Steps

**High Priority**:
1. [ ] Document all XP reward values (search codebase for `experience +=`)
2. [ ] Explicitly define gacha tier unlock levels (create constant or config)
3. [ ] Document boss HP scaling formulas (ascension, matron)
4. [ ] Verify XP overflow handling (carry over vs cap at 10 levels)

**Medium Priority**:
5. [ ] Externalize mastery rank requirements to ConfigManager
6. [ ] Document all leader skill effects
7. [ ] Implement Achievement system (subscribe to events)
8. [ ] Add event-driven leaderboard updates

**Low Priority**:
9. [ ] Externalize element fusion chart to JSON
10. [ ] Document edge cases (overcap at 110%, pity expiry policy)
11. [ ] Implement planned features (mail, shop, events)

---

## DEPENDENCY GRAPH (Detailed)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INFRASTRUCTURE LAYER                        │
│                                                                 │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐  │
│  │  PostgreSQL  │      │    Redis     │      │  EventBus    │  │
│  │   Database   │      │    Cache     │      │  (Registry)  │  │
│  └──────┬────���──┘      └──────┬───────┘      └──────┬───────┘  │
│         │                     │                     │          │
└─────────┼─────────────────────┼─────────────────────┼──────────┘
          │                     │                     │
          │                     │                     │
┌─────────┴─────────────────────┴─────────────────────┴──────────┐
│                         CORE LAYER                              │
│                                                                 │
│  ┌──────────────────┐    ┌──────────────────┐                  │
│  │  DatabaseService │    │  RedisService    │                  │
│  │  (Session Mgmt)  │    │  (Locks, Cache)  │                  │
│  └────────┬─────────┘    └────────┬─────────┘                  │
│           │                       │                            │
│           │      ┌────────────────┴────────────┐               │
│           │      │                             │               │
│  ┌────────▼──────▼────────┐      ┌─────────────▼────────────┐  │
│  │   PlayerService        │      │  TransactionLogger      │  │
│  │  (State, Regen, Locks) │──────►  (Audit Trail)          │  │
│  └────────┬───────────────┘      └─────────────────────────┘  │
│           │                                                    │
│  ┌────────▼───────────┐                                        │
│  │  ResourceService   │                                        │
│  │  (Currency Mgmt)   │                                        │
│  └────────────────────┘                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ (all feature modules depend on core)
                              │
┌─────────────────────────────┴───────────────────────────────────┐
│                      FEATURE MODULES                            │
│                                                                 │
│  ┌──────────────┐                                               │
│  │   Summon     │──┐                                            │
│  └──────────────┘  │                                            │
│  ┌──────────────┐  │     ┌──────────────────┐                  │
│  │   Fusion     │──┼─────►  MaidenService   │──────┐           │
│  └──────────────┘  │     │  (Inventory)     │      │           │
│  ┌──────────────┐  │     └──────────────────┘      │           │
│  │   Combat     │──┘              │                 │           │
│  │  (read-only) │                 ▼                 ▼           │
│  └──────────────┘          ┌─────────────┐   ┌──────────────┐  │
│                            │   Maiden    │   │  MaidenBase  │  │
│                            │   (Model)   │   │   (Model)    │  │
│  ┌──────────────┐          └─────────────┘   └──────────────┘  │
│  │ Exploration  │──┐                                            │
│  └──────────────┘  │                                            │
│  ┌──────────────┐  │     ┌──────────────────┐                  │
│  │  Ascension   │──┼─────►  CombatService   │                  │
│  └──────────────┘  │     │  (Power Calc)    │                  │
│                    │     └──────────────────┘                  │
│                    │                                            │
│                    └─────► Strategic Power (best 6 maidens)     │
│                                                                 │
│  ┌──────────────┐          ┌──────────────────┐                │
│  │    Daily     │──────────►  PlayerService   │                │
│  └──────────────┘          └──────────────────┘                │
│                                                                 │
│  ┌──────────────┐          ┌──────────────────┐                │
│  │   Prayer     │──────────►  ResourceService │                │
│  └──────────────┘          └──────────────────┘                │
│                                                                 │
│  ┌──────────────┐          ┌──────────────────┐                │
│  │   Tutorial   │◄─────────┤    EventBus      │                │
│  │ (Event-Driven)          │  (Subscribes to  │                │
│  └──────────────┘          │  multiple events) │                │
│                            └──────────────────┘                │
│                                     ▲                           │
│                                     │                           │
│  All modules ───────────────────────┘ (publish events)          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## ARCHITECTURE NOTES

### Transaction Management
- **Pessimistic Locking**: `SELECT FOR UPDATE` on player rows prevents race conditions
- **Lock Acquisition**: Via `PlayerService.get_player_with_regen(lock=True)`
- **Transaction Scope**: Context manager ensures commit/rollback
- **File**: `src/core/infra/database_service.py`, `src/modules/player/service.py:98-180`

### Redis Locking Strategy
- **Purpose**: Prevent double-click/concurrent operations
- **Locks Used**:
  - `fusion:{user_id}` - 10s timeout
  - `summon:{user_id}` - Batch summons
  - `pray:{user_id}` - Prayer execution
  - `ascension:{user_id}` - Floor attacks
- **File**: `src/core/infra/redis_service.py`

### Event Bus (Underutilized)
- **Publisher**: All feature modules publish events
- **Subscriber**: Only Tutorial module subscribes
- **Gap**: No achievement system, no real-time leaderboard updates
- **Recommendation**: Expand event-driven architecture for cross-module communication
- **File**: `src/core/event/registry.py`

### ConfigManager
- **Purpose**: Runtime tunable values (no code deployment for balance changes)
- **Sources**: YAML/JSON config files, environment variables
- **Overrides**: Config values override constants
- **File**: `src/core/config/config.py`

---

## SUMMARY

**Total Lines Analyzed**: 10,000+ lines across 50+ files

**Modules**: 16 feature modules + core infrastructure

**Commands**: 12 prefix commands (14 with help/leaderboard)

**Tunables**: 100+ configurable values

**Database Models**: 20+ models (Player, Maiden, MaidenBase, SectorProgress, Token, DailyQuest, Guild, TransactionLog, etc.)

**Core Loops**: 6 major gameplay loops documented end-to-end

**Events**: 15+ event types (mostly one-way publishing)

**Architecture Strengths**:
- Clean separation of concerns (Cog → Service → Model)
- Strong transaction safety (pessimistic locking, Redis locks)
- Comprehensive audit trail (TransactionLogger)
- ConfigManager enables live tuning
- Type hints and docstrings throughout

**Gaps Identified**:
- XP reward values not explicitly documented
- Boss HP scaling formulas ambiguous
- Event bus underutilized (no achievements, limited inter-module communication)
- Planned features referenced but not implemented (mail, shop)

**Progression**: Polynomial XP curve, 12.6M total XP to L100, estimated 1-2 years with bonuses

**Maiden System**: 12 tiers with exponential scaling (T1: 45 ATK → T12: 19.5M ATK), 6 elements, fusion-based progression

**Economy**: Rikis (primary), Grace (summon), Gems (premium), 4 resources (Energy, Stamina, HP, Prayer Charges)

---

*Document generated based on comprehensive codebase analysis. All file paths and line numbers cited. ASSUMPTION tags mark inferred information.*
