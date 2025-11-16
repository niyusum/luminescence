# AI Service Generation Prompt for Lumen

Use this prompt when you need an AI to generate LES 2025-compliant services for your database models.

---

## System Context

You are tasked with generating domain services for the **Lumen Discord RPG Bot** following the **Lumen Engineering Standard (LES) 2025**.

### Available Infrastructure

I have a complete service generation infrastructure with the following files:

1. **[docs/lumen_engineering_standards.md](../docs/lumen_engineering_standards.md)**
   - Authoritative engineering standards governing all code
   - Defines architectural principles, transaction discipline, concurrency safety
   - Must be followed strictly for all generated code

2. **[docs/service_implementation_guide.md](../docs/service_implementation_guide.md)**
   - Complete step-by-step guide for building services
   - Transaction patterns, common examples, troubleshooting
   - Reference this for implementation patterns

3. **[src/modules/shared/reference_service.py](../src/modules/shared/reference_service.py)**
   - Complete working example: `ResourceService`
   - Shows all LES 2025 patterns in action:
     - Read operations with `get_session()`
     - Write operations with `get_transaction()` and pessimistic locking
     - Multi-entity transfers with deadlock prevention
     - Input validation, audit logging, event emission
   - Use this as the canonical example

4. **[src/modules/shared/service_template.py](../src/modules/shared/service_template.py)**
   - Copy-paste skeleton with inline documentation
   - TODOs and step-by-step operation templates
   - Start here when generating new services

5. **[src/modules/shared/base_service.py](../src/modules/shared/base_service.py)**
   - Base class providing: logging, config access, event emission
   - All services must inherit from `BaseService`

6. **[src/modules/shared/base_repository.py](../src/modules/shared/base_repository.py)**
   - Base repository providing CRUD operations with pessimistic locking
   - Generic `BaseRepository[T]` pattern for type safety

7. **[src/core/database/service.py](../src/core/database/service.py)**
   - `DatabaseService.get_session()` - Read-only operations
   - `DatabaseService.get_transaction()` - Write operations (auto-commit/rollback)
   - Never manually call `session.commit()`

8. **[src/core/validation/input_validator.py](../src/core/validation/input_validator.py)**
   - `InputValidator` class with comprehensive validation methods
   - Validates Discord IDs, positive integers, strings, choices, etc.

9. **[src/core/infra/audit_logger.py](../src/core/infra/audit_logger.py)**
   - `AuditLogger` for transaction audit trails
   - Use for all critical state changes

10. **[src/modules/shared/exceptions.py](../src/modules/shared/exceptions.py)**
    - Domain exceptions: `NotFoundError`, `InsufficientResourcesError`, `ValidationError`, etc.
    - Services raise domain exceptions, cogs translate to embeds

11. **[docs/logic_to_be_routed.md/](../docs/logic_to_be_routed.md/)** ⚠️ **CRITICAL**
    - Business logic extracted from database models during refactoring
    - Organized by domain: `core.md`, `economy.md`, `progression.md`, `social.md`
    - Each file lists missing logic that needs to be implemented in services
    - **ALWAYS check this folder** when generating services to ensure you implement all required business logic
    - Example entries:
      - Fusion eligibility checks → `FusionService`
      - Shrine yield calculation → `ShrineService`
      - Guild member management → `GuildMemberService`

---

## Service Generation Workflow

When I provide you with a **database model**, you should:

### Step 1: Analyze the Model & Check Business Logic Manifests
- Identify all fields and relationships
- Understand the domain (what does this model represent?)
- **⚠️ CHECK `docs/logic_to_be_routed.md/` folder** for orphaned business logic
  - Find the relevant domain file (`core.md`, `economy.md`, `progression.md`, `social.md`)
  - Look for logic related to your model
  - This logic was removed during refactoring and MUST be implemented in the service
- Determine what operations are needed (CRUD + business logic from manifest)

### Step 2: Design the Service
- List all public methods (reads vs writes)
- Identify config values needed (costs, limits, rates, etc.)
- Determine events to emit (state changes, achievements, etc.)
- Define business rules and constraints

### Step 3: Generate the Service
Using the **service_template.py** as the starting point:

1. **Name the service** (e.g., `FusionService`, `InventoryService`, `GuildService`)
2. **Create repository** if custom queries needed, otherwise use `BaseRepository` directly
3. **Implement read operations** using `DatabaseService.get_session()`
4. **Implement write operations** using `DatabaseService.get_transaction()` with `for_update=True`
5. **Add input validation** with `InputValidator`
6. **Add audit logging** for critical operations with `AuditLogger`
7. **Emit events** for state changes with `self.emit_event()`
8. **Use config values** with `self.get_config()` - NO hardcoded game balance
9. **Handle multi-entity operations** with deterministic locking order (sorted IDs)
10. **Add structured logging** with `self.log_operation()` and `self.log.info(..., extra={})`

### Step 4: Follow LES 2025 Compliance Checklist

Every generated service MUST:
- ✅ Inherit from `BaseService`
- ✅ Use `DatabaseService.get_transaction()` for all writes
- ✅ Use pessimistic locking (`for_update=True`) for all state mutations
- ✅ Never call `session.commit()` manually (transactions auto-commit)
- ✅ Validate all inputs with `InputValidator`
- ✅ Raise domain exceptions (not generic `Exception`)
- ✅ Load config values from `ConfigManager` (not hardcoded)
- ✅ Emit events for state changes via `EventBus`
- ✅ Log operations with structured logging
- ✅ Provide audit trails for critical operations
- ✅ Be pure business logic (no Discord dependencies)
- ✅ Use type hints throughout (`Dict[str, Any]`, `Optional[str]`, etc.)

---

## Example Prompts

### Prompt 1: Simple CRUD Service
```
Generate a service for this model:

[paste PlayerInventory model]

I need:
- get_inventory(player_id) -> Get all items
- add_item(player_id, item_id, quantity) -> Add items with validation
- remove_item(player_id, item_id, quantity) -> Remove with sufficiency check
- has_item(player_id, item_id, quantity) -> Check ownership

Config values:
- MAX_INVENTORY_SIZE
- MAX_STACK_SIZE

Events:
- inventory.item_added
- inventory.item_removed
```

### Prompt 2: Complex Service with Business Logic
```
Generate a FusionService for this Maiden model:

[paste Maiden model]

Domain: Fuse two maidens of the same tier to create a higher tier maiden

⚠️ CHECK docs/logic_to_be_routed.md/core.md for fusion-related business logic!

Operations (based on model + logic manifest):
- attempt_fusion(player_id, maiden_id_1, maiden_id_2) -> Fuse two maidens
  - Validate: Both maidens exist, owned by player, same tier, tier < 12
  - Check fusion eligibility (from logic manifest)
  - Tier & element fusion compatibility (from logic manifest)
  - Lock both maidens (sorted order to prevent deadlocks)
  - Check config: FUSION_COST_TIER_X
  - Deduct lumees from player
  - Roll success: FUSION_SUCCESS_RATE_TIER_X (from logic manifest)
  - On success: Create tier+1 maiden, delete source maidens, update times_fused
  - On failure: Award shards (consume fusion shards logic), delete source maidens
  - Update fusion success/failure counters (from logic manifest)
  - Handle locked/frozen maidens (from logic manifest)
  - Audit log the fusion attempt
  - Emit events: maiden.fused or fusion.failed

- get_fusion_cost(tier) -> Calculate cost for tier
- get_fusion_success_rate(tier) -> Get success rate for tier
- check_fusion_eligibility(maiden1, maiden2) -> Validate fusion compatibility
- determine_fusable_stacks() -> Get fusable maiden groups (from logic manifest)

Follow reference_service.py patterns for multi-entity locking.
```

### Prompt 3: Refactoring Existing Service
```
Refactor this existing service to be LES 2025 compliant:

[paste old service code]

Current issues:
- Uses manual session.commit()
- No pessimistic locking
- Hardcoded values instead of config
- No audit logging
- No event emission

Apply all patterns from reference_service.py.
```

---

## Key Patterns to Remember

### Read-Only Pattern
```python
async def get_something(self, player_id: int) -> Dict[str, Any]:
    player_id = InputValidator.validate_discord_id(player_id)
    self.log_operation("get_something", player_id=player_id)

    async with DatabaseService.get_session() as session:
        entity = await self._repo.find_one_where(
            session,
            Model.player_id == player_id,
        )
        if not entity:
            raise NotFoundError("ModelName", player_id)
        return {"data": entity.field}
```

### Write Pattern
```python
async def update_something(
    self, player_id: int, amount: int, reason: str, context: Optional[str] = None
) -> Dict[str, Any]:
    player_id = InputValidator.validate_discord_id(player_id)
    amount = InputValidator.validate_positive_integer(amount, "amount")
    self.log_operation("update_something", player_id=player_id, amount=amount)

    max_limit = self.get_config("MAX_SOMETHING", default=999_999)

    async with DatabaseService.get_transaction() as session:
        entity = await self._repo.find_one_where(
            session,
            Model.player_id == player_id,
            for_update=True,  # SELECT FOR UPDATE
        )
        if not entity:
            raise NotFoundError("ModelName", player_id)

        old_value = entity.field
        new_value = min(old_value + amount, max_limit)
        entity.field = new_value

        await AuditLogger.log(...) # Audit trail
        await self.emit_event("domain.updated", {...})  # Event

        self.log.info(f"Updated: +{amount}", extra={"player_id": player_id})

        return {"old_value": old_value, "new_value": new_value}
```

### Multi-Entity Pattern
```python
async def transfer_between_players(
    self, from_id: int, to_id: int, amount: int
) -> Dict[str, Any]:
    # Lock in deterministic order to prevent deadlocks
    player_ids = sorted([from_id, to_id])

    async with DatabaseService.get_transaction() as session:
        from_entity = await self._repo.find_one_where(
            session, Model.player_id == from_id, for_update=True
        )
        to_entity = await self._repo.find_one_where(
            session, Model.player_id == to_id, for_update=True
        )

        # Validate both exist
        # Check sufficiency
        # Perform transfer
        # Audit + events
```

---

## Output Format

When generating a service, provide:

1. **Complete service file** with:
   - Module docstring explaining purpose, domain, and compliance
   - Repository class (if needed)
   - Service class with all methods
   - Full type hints and documentation

2. **Brief explanation** of:
   - What operations were implemented
   - What config values are needed (add to config file)
   - What events are emitted (for other modules to subscribe)
   - Any business rules enforced

3. **Usage example** showing:
   - How to instantiate the service
   - How to call it from a cog
   - How to handle exceptions in the cog

---

## Ready to Generate

I'm now ready to generate LES 2025-compliant services. When you provide a database model, I will:
1. Analyze the model structure
2. **Check `docs/logic_to_be_routed.md/` for related business logic** (CRITICAL - don't skip!)
3. Design appropriate operations (combining model structure + orphaned logic)
4. Generate a complete, production-ready service following all patterns
5. Provide usage examples

**Provide the database model and describe what operations you need, and I'll generate the service!**

---

## Important Reminders

⚠️ **ALWAYS check `docs/logic_to_be_routed.md/` before generating services!**
- This folder contains critical business logic removed during model refactoring
- Missing this logic means generating incomplete services
- Each domain file maps logic to specific services

✅ **Every service must follow LES 2025 compliance checklist** (see above)

📚 **Use `reference_service.py` as the canonical example** for all patterns

🎯 **Services are pure business logic** - no Discord, no UI, no presentation logic
