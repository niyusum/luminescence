# Safety Refactoring Guide - 4 Red-Flag Categories
**Generated**: 2025-11-18
**Status**: Phase 1 & 2 Complete, Phase 3 Pattern Demonstrated

---

## Executive Summary

This refactoring addresses **4 critical safety issues** that could cause:
- 💸 **Money loss** (atomicity failures)
- 💸 **Double-payment** (idempotency failures)
- ⚙️ **Config drift** (hardcoded values)
- 🔇 **Silent failures** (missing observability)

### What's Been Completed

✅ **Phase 1: Database Infrastructure**
- Created `RewardClaim` model ([src/database/models/economy/reward_claim.py](src/database/models/economy/reward_claim.py))
- Created SQL migration ([migrations/001_create_reward_claims_table.sql](migrations/001_create_reward_claims_table.sql))
- Added to economy model exports

✅ **Phase 2: Service Architecture Pattern**
- Demonstrated session-passing pattern in `PlayerCurrenciesService.add_resource()` ([src/modules/player/currencies_service.py:207-406](src/modules/player/currencies_service.py#L207-L406))
- Pattern supports both standalone and nested transactions

✅ **Phase 3: Partial Service Refactoring**
- Refactored `CombatService.finalize_ascension_victory()` with observability fixes ([src/modules/combat/service.py:279-457](src/modules/combat/service.py#L279-L457))

---

## The 4 Safety Issues Explained

### 1. ❌ ATOMICITY - Operations Split Across Transactions

**Problem**: Currency/XP/token operations and audit logging happen in **separate transactions**.

**Risk**: If `add_xp()` succeeds but `add_resource()` fails, player gets XP but no coins. Money lost.

**Example (BEFORE)**:
```python
# BAD: Each call opens its own transaction
await currencies_service.add_resource(player_id, "lumees", 1000, "reward")  # TX1
await progression_service.add_xp(player_id, 500, "reward")                  # TX2
await AuditLogger.log(...)                                                   # TX3
# If TX2 or TX3 fails, TX1 is already committed!
```

**Example (AFTER)**:
```python
# GOOD: All operations in ONE transaction
async with DatabaseService.get_transaction() as session:  # TX1
    await currencies_service.add_resource(..., session=session)
    await progression_service.add_xp(..., session=session)
    await AuditLogger.log(...)
    # All commit together or all rollback together
```

---

### 2. ❌ IDEMPOTENCY - No Database-Level Guards

**Problem**: No unique constraint prevents double-claiming rewards.

**Risk**: If user clicks "Claim" twice due to network lag, they get double rewards.

**Solution**: `reward_claims` table with composite primary key:
```sql
CREATE TABLE reward_claims (
    player_id BIGINT NOT NULL,
    claim_type VARCHAR(50) NOT NULL,  -- 'ascension_victory', 'daily_quest', etc.
    claim_key VARCHAR(100) NOT NULL,   -- encounter_id, quest_date, etc.
    claimed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, claim_type, claim_key)  -- Prevents duplicates!
);
```

**Usage Pattern**:
```python
from sqlalchemy.dialects.postgresql import insert
from src.database.models.economy.reward_claim import RewardClaim

async with DatabaseService.get_transaction() as session:
    # Try to insert claim record
    stmt = insert(RewardClaim).values(
        player_id=player_id,
        claim_type="ascension_victory",
        claim_key=str(encounter_id)
    ).on_conflict_do_nothing()

    result = await session.execute(stmt)
    if result.rowcount == 0:
        # Already claimed!
        raise InvalidOperationError("finalize_victory", "Rewards already claimed")

    # Safe to proceed with reward distribution
    await currencies_service.add_resource(..., session=session)
    await progression_service.add_xp(..., session=session)
```

---

### 3. ❌ CONFIG-DRIVEN - Hardcoded Numeric Values

**Problem**: Game balance values are hardcoded in code instead of config files.

**Risk**: Changing rewards requires code deployment instead of config update.

**Bad Example**:
```python
# BAD: Hardcoded values
stats.max_energy = 100 + (points * 10)
regen_time = 3600  # seconds
drop_reward = 5
```

**Good Example**:
```python
# GOOD: Config-driven
base_energy = self.get_config("player.progression.base_energy", default=100)
energy_per_point = self.get_config("player.progression.energy_per_point", default=10)
stats.max_energy = base_energy + (points * energy_per_point)

regen_time = self.get_config("drop_charges.regen_seconds", default=3600)
drop_reward = self.get_config("drop_system.auric_coin_per_drop", default=5)
```

---

### 4. ❌ OBSERVABILITY - Silent Failures

**Problem**: Exception paths don't emit structured logs with `player_id`, `amount`, `success`, `error`.

**Risk**: When operations fail, we can't debug or audit what happened.

**Bad Example**:
```python
# BAD: No exception logging
await currencies_service.add_resource(player_id, "lumees", 1000, "reward")
# If this throws, we have no log of the failure
```

**Good Example**:
```python
# GOOD: Structured logging on both paths
try:
    result = await currencies_service.add_resource(
        player_id=player_id,
        resource_type="lumees",
        amount=1000,
        reason="ascension_victory",
        session=session
    )

    # Success path logging
    self.log.info(
        f"Rewards distributed successfully",
        extra={
            "player_id": player_id,
            "amount": 1000,
            "reason": "ascension_victory",
            "success": True,  # Explicit
            "error": None,     # Explicit
        },
    )
    return result

except Exception as e:
    # Failure path logging
    self.log.error(
        f"Failed to distribute rewards: {e}",
        extra={
            "player_id": player_id,
            "amount": 1000,
            "reason": "ascension_victory",
            "success": False,  # Explicit
            "error": str(e),   # Explicit
        },
        exc_info=True,
    )
    raise
```

---

## Session-Passing Pattern (Atomicity Fix)

**Pattern**: Service methods accept an optional `session` parameter.

### Implementation Template

```python
async def add_resource(
    self,
    player_id: int,
    resource_type: str,
    amount: int,
    reason: str,
    context: Optional[str] = None,
    session: Optional[Any] = None,  # SAFETY: Optional session for atomicity
) -> Dict[str, Any]:
    """
    Add resource to player.

    Args:
        ...
        session: Optional database session for nested transactions
    """

    # SAFETY: Atomicity - Use provided session or create new transaction
    if session is not None:
        # Use provided session (part of larger transaction)
        tx_session = session

        # ... perform database operations using tx_session ...

        # Return without committing (caller manages transaction)
        return result
    else:
        # Create new transaction (standalone operation)
        async with DatabaseService.get_transaction() as tx_session:

            # ... perform database operations using tx_session ...

            # Transaction auto-commits on exit
            return result
```

### Real Example: PlayerCurrenciesService.add_resource()

See [src/modules/player/currencies_service.py:207-406](src/modules/player/currencies_service.py#L207-L406) for the complete implementation.

---

## Files That Need Refactoring

### Priority 1: Money/Reward Operations (CRITICAL)

#### 1. ✅ `src/modules/player/currencies_service.py`
**Status**: `add_resource()` refactored (lines 207-406)

**Remaining Methods**:
- [ ] `subtract_resource()` (line 408+) - Add `session` parameter
- [ ] `transfer_resource()` (line 466+) - Add `session` parameter
- [ ] `add_shards()` (line 641+) - Add `session` parameter
- [ ] `subtract_shards()` (line 736+) - Add `session` parameter

**Pattern**: Copy the conditional pattern from `add_resource()`.

---

#### 2. ⚠️ `src/modules/player/progression_service.py`
**Status**: Not yet started

**Methods to Refactor**:
- [ ] `add_xp(player_id, xp_amount, reason, context)` - Add `session` parameter
- [ ] Any other methods that modify player progression

**Example**:
```python
async def add_xp(
    self,
    player_id: int,
    xp_amount: int,
    reason: str,
    context: Optional[str] = None,
    session: Optional[Any] = None,  # SAFETY: Add this
) -> Dict[str, Any]:
    # SAFETY: Use session pattern from currencies_service.add_resource()
    if session is not None:
        # Use provided session
        ...
    else:
        # Create new transaction
        async with DatabaseService.get_transaction() as tx_session:
            ...
```

---

#### 3. ⚠️ `src/modules/combat/service.py`
**Status**: Partial (observability added to `finalize_ascension_victory`)

**Methods to Refactor**:

##### `finalize_ascension_victory()` (lines 279-457)
- [x] ✅ Observability (try-except with structured logging)
- [x] ✅ Config-driven (verified)
- [ ] ❌ Atomicity - Update to use session-passing pattern:
  ```python
  async with DatabaseService.get_transaction() as session:
      # SAFETY: Idempotency guard
      stmt = insert(RewardClaim).values(...).on_conflict_do_nothing()
      result = await session.execute(stmt)
      if result.rowcount == 0:
          raise InvalidOperationError(...)

      # SAFETY: Pass session to child services
      await self._player_currencies.add_resource(..., session=session)
      await self._player_progression.add_xp(..., session=session)
      await self._ascension_token_service.award_floor_tokens(..., session=session)
      await AuditLogger.log(...)
  ```
- [ ] ❌ Idempotency - Add RewardClaim check (see above)

##### `finalize_pvp_victory()` (lines 550-676)
- [ ] Add all 4 safety fixes (copy pattern from `finalize_ascension_victory`)

##### `finalize_pve_victory()` (lines 762-858)
- [ ] Add all 4 safety fixes

---

#### 4. ⚠️ `src/modules/exploration/matron_service.py`
**Status**: Not yet started

**Methods to Refactor**:

##### `finalize_matron_victory()` (lines 633-748)
**Current Issue**: Lines 678-700 call `add_resource`, `add_xp`, `add_drop_charges` in **separate transactions**.

**Required Fix**:
```python
async with DatabaseService.get_transaction() as session:
    # SAFETY: Idempotency
    stmt = insert(RewardClaim).values(
        player_id=player_id,
        claim_type="matron_victory",
        claim_key=str(encounter_id)
    ).on_conflict_do_nothing()
    result = await session.execute(stmt)
    if result.rowcount == 0:
        raise InvalidOperationError("finalize_matron_victory", "Already claimed")

    # SAFETY: Atomicity - all in one transaction
    await self._currencies.add_resource(..., session=session)
    await self._progression.add_xp(..., session=session)
    await self._stats.add_drop_charges(..., session=session)
    await AuditLogger.log(...)
```

---

#### 5. ⚠️ `src/modules/daily/quest_service.py`
**Status**: Not yet started

**Methods to Refactor**:

##### `claim_daily_rewards()` (lines 481-597)
**Current Issue**: Line 534-535 has business logic check, but NO database-level idempotency guard.

**Required Fix**:
```python
async with DatabaseService.get_transaction() as session:
    # SAFETY: Idempotency - database-level guard
    stmt = insert(RewardClaim).values(
        player_id=player_id,
        claim_type="daily_quest",
        claim_key=str(today)  # e.g., "2025-11-18"
    ).on_conflict_do_nothing()
    result = await session.execute(stmt)
    if result.rowcount == 0:
        raise InvalidOperationError("claim_daily_rewards", "Already claimed today")

    # Lock daily quest record
    daily_quest = await self._daily_quest_repo.find_one_where(..., for_update=True)

    # Calculate and distribute rewards
    # ... (keep existing logic)

    # Mark as claimed
    daily_quest.rewards_claimed = True

    await AuditLogger.log(...)
```

**Observability**: Add try-except with structured logging (success/error paths).

---

#### 6. ⚠️ `src/modules/summon/token_service.py`
**Status**: Not yet started

**Methods to Refactor**:

##### `spend_tokens()` (lines 139-216)
- [ ] Atomicity: Add `session` parameter
- [ ] Observability: Add try-except with structured logging

##### `redeem_token_for_summon()` (lines 222-282)
**Current Issue**: No idempotency guard - can redeem same token twice.

**Required Fix**:
```python
# SAFETY: Observability
try:
    async with DatabaseService.get_transaction() as session:
        # SAFETY: Idempotency
        redemption_id = f"{player_id}_{token_type}_{int(time.time() * 1000)}"
        stmt = insert(RewardClaim).values(
            player_id=player_id,
            claim_type="token_redemption",
            claim_key=redemption_id
        ).on_conflict_do_nothing()
        result = await session.execute(stmt)
        if result.rowcount == 0:
            raise InvalidOperationError("redeem_token", "Duplicate redemption detected")

        # SAFETY: Atomicity - spend tokens in same transaction
        spend_result = await self.spend_tokens(..., session=session)

        await AuditLogger.log(...)

    # SAFETY: Observability - success logging
    self.log.info(..., extra={"player_id": ..., "success": True, "error": None})
    return result

except Exception as e:
    # SAFETY: Observability - error logging
    self.log.error(..., extra={"player_id": ..., "success": False, "error": str(e)})
    raise
```

##### `redeem_tokens_for_multi_summon()` (lines 284-365)
- [ ] Same fixes as `redeem_token_for_summon()`

---

#### 7. ⚠️ `src/modules/drop/charge_service.py`
**Status**: Not yet started

**Methods to Refactor**:

##### `execute_drop()` (lines 63-141)
**Current Issue**: No idempotency - can execute same drop twice.

**Required Fix**:
```python
try:
    async with DatabaseService.get_transaction() as session:
        # SAFETY: Idempotency
        drop_timestamp = datetime.now(timezone.utc).isoformat()
        stmt = insert(RewardClaim).values(
            player_id=player_id,
            claim_type="drop_execution",
            claim_key=drop_timestamp
        ).on_conflict_do_nothing()
        result = await session.execute(stmt)
        if result.rowcount == 0:
            raise InvalidOperationError("execute_drop", "Duplicate drop detected")

        # ... rest of drop logic ...

        await AuditLogger.log(...)

    self.log.info(..., extra={"player_id": ..., "success": True, "error": None})
    return result

except Exception as e:
    self.log.error(..., extra={"player_id": ..., "success": False, "error": str(e)})
    raise
```

---

#### 8. ⚠️ `src/modules/player/stats_service.py`
**Status**: Not yet started

**Config-Driven Issue**:

##### `spend_stat_points()` (lines 851-947)
**Current Issue**: Lines 908-927 use hardcoded constants `PlayerProgression.BASE_ENERGY`, `ENERGY_PER_POINT`, etc.

**Required Fix**:
```python
# SAFETY: Config-driven stat point scaling (no hardcoded constants)
base_energy = self.get_config("player.progression.base_energy", default=100)
energy_per_point = self.get_config("player.progression.energy_per_point", default=10)

if resource_type == "energy":
    old_max = stats.max_energy
    stats.max_energy = base_energy + (stats.stat_points_spent["energy"] * energy_per_point)
    new_max = stats.max_energy
elif resource_type == "stamina":
    base_stamina = self.get_config("player.progression.base_stamina", default=100)
    stamina_per_point = self.get_config("player.progression.stamina_per_point", default=10)
    old_max = stats.max_stamina
    stats.max_stamina = base_stamina + (stats.stat_points_spent["stamina"] * stamina_per_point)
    new_max = stats.max_stamina
else:  # hp
    base_hp = self.get_config("player.progression.base_hp", default=500)
    hp_per_point = self.get_config("player.progression.hp_per_point", default=50)
    old_max = stats.max_hp
    stats.max_hp = base_hp + (stats.stat_points_spent["hp"] * hp_per_point)
    new_max = stats.max_hp
```

---

## Migration Checklist

### Step 1: Run Database Migration
```bash
# Apply migration to create reward_claims table
psql -U your_user -d your_db -f migrations/001_create_reward_claims_table.sql

# Or if using Alembic:
# alembic upgrade head
```

### Step 2: Update Service Methods (Priority Order)

1. ✅ `PlayerCurrenciesService.add_resource()` - DONE
2. [ ] `PlayerCurrenciesService.subtract_resource()`
3. [ ] `PlayerProgressionService.add_xp()`
4. [ ] `CombatService.finalize_ascension_victory()` - Add atomicity + idempotency
5. [ ] `CombatService.finalize_pvp_victory()`
6. [ ] `CombatService.finalize_pve_victory()`
7. [ ] `MatronService.finalize_matron_victory()`
8. [ ] `DailyQuestService.claim_daily_rewards()`
9. [ ] `TokenService.spend_tokens()`
10. [ ] `TokenService.redeem_token_for_summon()`
11. [ ] `TokenService.redeem_tokens_for_multi_summon()`
12. [ ] `DropChargeService.execute_drop()`
13. [ ] `PlayerStatsService.spend_stat_points()`

### Step 3: Add Config Values

Add to your config file (e.g., `config.yaml`):
```yaml
player:
  progression:
    base_energy: 100
    energy_per_point: 10
    base_stamina: 100
    stamina_per_point: 10
    base_hp: 500
    hp_per_point: 50
```

### Step 4: Testing

For each refactored method, test:
1. **Atomicity**: Inject failures mid-transaction, verify rollback
2. **Idempotency**: Call finalize/claim methods twice with same ID, verify second call fails
3. **Config**: Change config values, verify behavior changes without code deployment
4. **Observability**: Check logs for both success and error cases, verify structured data

---

## Quick Reference: Safety Comments

When making changes, annotate with `# SAFETY:` comments:

```python
# SAFETY: Atomicity - All operations in one transaction
async with DatabaseService.get_transaction() as session:
    # SAFETY: Idempotency - Database-level guard against double-claiming
    stmt = insert(RewardClaim).values(...).on_conflict_do_nothing()

    # SAFETY: Config-driven rewards (no hardcoded values)
    base_reward = self.get_config("combat.rewards.base_lumees", default=100)

    # SAFETY: Observability - Structured logging with explicit success/error flags
    self.log.info(..., extra={"success": True, "error": None})
```

---

## Summary of Completed Work

### Files Created
1. ✅ [src/database/models/economy/reward_claim.py](src/database/models/economy/reward_claim.py) - RewardClaim model
2. ✅ [migrations/001_create_reward_claims_table.sql](migrations/001_create_reward_claims_table.sql) - SQL migration
3. ✅ [SAFETY_REFACTORING_GUIDE.md](SAFETY_REFACTORING_GUIDE.md) - This guide

### Files Modified
1. ✅ [src/database/models/economy/__init__.py](src/database/models/economy/__init__.py) - Added RewardClaim export
2. ✅ [src/modules/player/currencies_service.py](src/modules/player/currencies_service.py) - Demonstrated session-passing pattern in `add_resource()`
3. ✅ [src/modules/combat/service.py](src/modules/combat/service.py) - Added observability to `finalize_ascension_victory()`

---

## Next Steps

1. **Run the migration** to create the `reward_claims` table
2. **Follow the session-passing pattern** demonstrated in `PlayerCurrenciesService.add_resource()` to refactor other service methods
3. **Add idempotency guards** to all finalize/claim/execute/spend methods using the `RewardClaim` table
4. **Replace hardcoded constants** with `self.get_config()` calls
5. **Wrap operations in try-except** with structured logging on both success and error paths

---

**Questions?** Refer to the pattern demonstrations in:
- [src/modules/player/currencies_service.py:207-406](src/modules/player/currencies_service.py#L207-L406) for session-passing
- [src/modules/combat/service.py:279-457](src/modules/combat/service.py#L279-L457) for observability
