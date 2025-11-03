# Tutorial Events Implementation Summary

**Date:** 2025-11-03
**Status:** 🔄 2/6 Existing Events Implemented | 🎯 5 New Events Identified

---

## Overview

The tutorial system uses EventBus to trigger first-time completion rewards. This document tracks which events are implemented and which remain to be added.

---

## Current Tutorial System (6 Events)

### Tutorial Steps Configuration
Location: `src/features/tutorial/service.py` - `TUTORIAL_STEPS`

| Step Key | Trigger Event | Reward | Status |
|----------|--------------|--------|---------|
| tos_agreed | `tos_agreed` | 0 rikis, 0 grace | ✅ DONE |
| first_pray | `prayer_completed` | 250 rikis, 1 grace | ✅ DONE |
| first_summon | `summons_completed` | 0 rikis, 1 grace | ✅ DONE |
| first_fusion | `fusion_completed` | 500 rikis, 0 grace | ✅ DONE |
| view_collection | `collection_viewed` | 0 rikis, 1 grace | ✅ **DONE** (just added) |
| set_leader | `leader_set` | 0 rikis, 1 grace | ✅ **DONE** (just added) |

### Event Listener Registration
Location: `src/features/tutorial/listener.py` - `register_tutorial_listeners()`

All 6 events are registered in the EventBus listener.

---

## Implementation Status

### ✅ COMPLETED (6/6 Tutorial Events)

1. **tos_agreed** ✅
   - File: `src/features/player/register_cog.py`
   - Line: 183
   - Trigger: User accepts ToS during registration
   - Implementation: Fully working

2. **prayer_completed** ✅
   - File: `src/features/prayer/cog.py`
   - Line: 94
   - Trigger: Player uses `/pray` command
   - Implementation: Fully working

3. **summons_completed** ✅
   - File: `src/features/summon/cog.py`
   - Line: 96
   - Trigger: Player uses `/summon` command
   - Implementation: Fully working

4. **fusion_completed** ✅
   - File: `src/features/fusion/cog.py`
   - Line: 337
   - Trigger: Player completes fusion (success or fail)
   - Implementation: Fully working

5. **collection_viewed** ✅ **JUST ADDED**
   - File: `src/features/maiden/cog.py`
   - Line: 87
   - Trigger: Player uses `/maidens` command
   - Implementation: **NEW** - Added during refactoring
   - Also migrated cog to use BaseCog ✅

6. **leader_set** ✅ **JUST ADDED**
   - File: `src/features/leader/cog.py`
   - Line: 275
   - Trigger: Player sets a leader via dropdown
   - Implementation: **NEW** - Added during refactoring

---

## New Tutorial Opportunities (HIGH PRIORITY)

These are meaningful first-time events that should be added to enhance onboarding:

### 🎯 Recommended for Implementation

#### 1. First Ascension Attack
- **Event Name:** `first_ascension_attack`
- **Priority:** HIGH (Core progression loop)
- **Reward:** 100 rikis + 1 grace
- **Trigger:** First time attacking in ascension tower
- **Implementation Location:**
  - File: `src/features/ascension/cog.py`
  - Class: `AscensionCombatView`
  - Function: `_execute_attack()`
  - Line: ~261 (after player loaded)
  - Condition: `player.stats.get("ascension_attacks_total", 0) == 0`

**Add to TUTORIAL_STEPS:**
```python
{
    "key": "first_ascension_attack",
    "title": "First Ascension Attack",
    "trigger": "first_ascension_attack",
    "reward": {"rikis": 100, "grace": 1},
    "congrats": "The ascension tower tests your strongest maidens in turn-based combat."
},
```

**EventBus.publish call:**
```python
# In AscensionCombatView._execute_attack()
if player.stats.get("ascension_attacks_total", 0) == 0:
    try:
        await EventBus.publish("first_ascension_attack", {
            "player_id": self.user_id,
            "channel_id": self.message.channel.id,
            "bot": self.bot,
            "floor": progress.current_floor,
            "__topic__": "first_ascension_attack",
            "timestamp": discord.utils.utcnow()
        })
    except Exception as e:
        logger.warning(f"Failed to publish first_ascension_attack: {e}")
```

---

#### 2. First Ascension Victory
- **Event Name:** `first_ascension_victory`
- **Priority:** HIGH (Core progression loop)
- **Reward:** 250 rikis + 2 grace
- **Trigger:** First time defeating a floor boss
- **Implementation Location:**
  - File: `src/features/ascension/service.py`
  - Function: `resolve_victory()`
  - Line: ~473 (after progress.last_victory set)
  - Condition: `player.stats.get("ascension_victories_total", 0) == 0`

**Add to TUTORIAL_STEPS:**
```python
{
    "key": "first_ascension_victory",
    "title": "First Floor Cleared",
    "trigger": "first_ascension_victory",
    "reward": {"rikis": 250, "grace": 2},
    "congrats": "Victory! Each floor grants rewards and tokens for maiden redemption."
},
```

**EventBus.publish call:**
```python
# In AscensionService.resolve_victory()
if player.stats.get("ascension_victories_total", 0) == 0:
    try:
        from src.core.event_bus import EventBus
        await EventBus.publish("first_ascension_victory", {
            "player_id": player_id,
            "floor": progress.current_floor,
            "__topic__": "first_ascension_victory",
            "timestamp": datetime.utcnow()
        })
    except Exception as e:
        logger.warning(f"Failed to publish first_ascension_victory: {e}")
```

---

#### 3. First Matron Victory
- **Event Name:** `first_matron_victory`
- **Priority:** HIGH (Major feature)
- **Reward:** 200 rikis + 1 grace
- **Trigger:** First time defeating matron in exploration
- **Implementation Location:**
  - File: `src/features/exploration/matron_service.py`
  - Function: `attack_matron()`
  - Line: ~258 (after victory determined)
  - Condition: Victory AND `player.stats.get("matron_victories_total", 0) == 0`

**Add to TUTORIAL_STEPS:**
```python
{
    "key": "first_matron_victory",
    "title": "First Matron Defeated",
    "trigger": "first_matron_victory",
    "reward": {"rikis": 200, "grace": 1},
    "congrats": "Matrons guard exploration sectors and grant mastery progress when defeated."
},
```

---

#### 4. First Token Redemption
- **Event Name:** `first_token_redemption`
- **Priority:** MEDIUM (Economy loop)
- **Reward:** 100 rikis + 1 grace
- **Trigger:** First time redeeming a token for maiden
- **Implementation Location:**
  - File: `src/features/ascension/token_service.py`
  - Function: `redeem_token()`
  - Line: ~200 (after redemption success)
  - Condition: `player.stats.get("tokens_redeemed_total", 0) == 0`

**Add to TUTORIAL_STEPS:**
```python
{
    "key": "first_token_redemption",
    "title": "First Token Redeemed",
    "trigger": "first_token_redemption",
    "reward": {"rikis": 100, "grace": 1},
    "congrats": "Tokens guarantee specific tier ranges — save them for targeted upgrades!"
},
```

---

#### 5. First Daily Quest Claimed
- **Event Name:** `first_daily_claimed`
- **Priority:** MEDIUM (Engagement loop)
- **Reward:** 150 rikis + 1 grace
- **Trigger:** First time claiming daily rewards
- **Implementation Location:**
  - File: `src/features/daily/cog.py`
  - Line: ~78 (already has daily_claimed event)
  - Condition: Check if first time

**Add to TUTORIAL_STEPS:**
```python
{
    "key": "first_daily_claimed",
    "title": "First Daily Claimed",
    "trigger": "first_daily_claimed",
    "reward": {"rikis": 150, "grace": 1},
    "congrats": "Daily quests provide consistent rewards — claim them every day for streaks!"
},
```

**Modify existing EventBus call:**
```python
# Change event name from "daily_claimed" to "first_daily_claimed"
# Only publish on FIRST claim ever
if player.stats.get("daily_claims_total", 0) == 0:
    event_name = "first_daily_claimed"
else:
    event_name = "daily_claimed"

await EventBus.publish(event_name, { ... })
```

---

## Implementation Priority

### Phase 1: CRITICAL - Tutorial Completion (✅ DONE)
- [x] `collection_viewed` - Maiden cog
- [x] `leader_set` - Leader cog

### Phase 2: HIGH PRIORITY - Core Gameplay
- [ ] `first_ascension_attack` - Introduce tower combat
- [ ] `first_ascension_victory` - Reinforce progression
- [ ] `first_matron_victory` - Introduce exploration

### Phase 3: MEDIUM PRIORITY - Economy & Engagement
- [ ] `first_token_redemption` - Token system education
- [ ] `first_daily_claimed` - Daily engagement hook

### Phase 4: LOW PRIORITY - Milestones
- [ ] `first_tier_5_obtained` - Collection milestone
- [ ] `first_guild_joined` - Social feature
- [ ] `first_milestone_floor` - Achievement (floor 10, 25, etc.)

---

## Statistics Tracking

For new events to work, ensure player stats track counts:

### Required Stats (Add if missing):
```python
# In player model or service:
player.stats["ascension_attacks_total"] = 0
player.stats["ascension_victories_total"] = 0
player.stats["matron_victories_total"] = 0
player.stats["tokens_redeemed_total"] = 0
player.stats["daily_claims_total"] = 0
```

### Update on Actions:
```python
# Increment counters when actions occur:
player.stats["ascension_attacks_total"] = player.stats.get("ascension_attacks_total", 0) + 1
```

---

## Testing Checklist

For each new tutorial event:

1. ✅ Add step to `TUTORIAL_STEPS` in tutorial/service.py
2. ✅ Add trigger to listener in tutorial/listener.py (line 40)
3. ✅ Add EventBus.publish() call in feature cog/service
4. ✅ Ensure stat counter is incremented
5. ✅ Test: Create new account and trigger event
6. ✅ Verify: Tutorial completion message appears
7. ✅ Verify: Rewards are granted (rikis/grace)
8. ✅ Verify: Event only fires once (idempotent)

---

## Current State Summary

### ✅ What's Working Now:
- All 6 original tutorial events implemented
- Tutorial listener registered and active
- Rewards system integrated with ResourceService
- Idempotent completion (won't reward twice)

### 🚀 What's Next:
1. Add 3 HIGH priority events (ascension attack/victory, matron victory)
2. Add 2 MEDIUM priority events (token redemption, daily claimed)
3. Test full tutorial flow with new player account
4. Monitor EventBus logs for any issues

### 📊 Total Tutorial Steps:
- **Current:** 6 steps
- **After Phase 2:** 9 steps
- **After Phase 3:** 11 steps

---

## Files Modified

### ✅ Completed Today:
1. `src/features/maiden/cog.py` - Added collection_viewed event + BaseCog migration
2. `src/features/leader/cog.py` - Added leader_set event

### 📋 Requires Modification:
1. `src/features/ascension/cog.py` - Add first_ascension_attack
2. `src/features/ascension/service.py` - Add first_ascension_victory
3. `src/features/exploration/matron_service.py` - Add first_matron_victory
4. `src/features/ascension/token_service.py` - Add first_token_redemption
5. `src/features/daily/cog.py` - Modify to support first_daily_claimed
6. `src/features/tutorial/service.py` - Add new steps to TUTORIAL_STEPS
7. `src/features/tutorial/listener.py` - Add new triggers to registration

---

**Status:** Tutorial system foundational events complete. Ready for Phase 2 implementation.
