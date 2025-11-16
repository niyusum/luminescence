# Lumen Service Implementation Guide (2025)

> **Complete guide for building domain services that comply with LES 2025 standards**

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Service Architecture](#service-architecture)
3. [Step-by-Step Implementation](#step-by-step-implementation)
4. [Transaction Patterns](#transaction-patterns)
5. [Common Patterns & Examples](#common-patterns--examples)
6. [Testing Services](#testing-services)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

### What You Need

Before creating a service, ensure you have:

- ✅ **Database models** defined in `src/database/models/`
- ✅ **BaseService** available at `src/modules/shared/base_service.py`
- ✅ **BaseRepository** available at `src/modules/shared/base_repository.py`
- ✅ **DatabaseService** initialized for transactions
- ✅ **ConfigManager** configured with your game values
- ✅ **EventBus** initialized for event emission

### Reference Files

- **Complete Example**: `src/modules/shared/reference_service.py`
- **Template**: `src/modules/shared/service_template.py`
- **LES Standards**: `docs/lumen_engineering_standards.md`

---

## Service Architecture

### What is a Service?

A **service** in Lumen is a class that:
- Contains **pure business logic** (no Discord, no UI)
- Manages **transactions** and **database operations**
- Enforces **game rules** and **domain constraints**
- Emits **events** for cross-module communication
- Provides **audit trails** for important operations
- Is **config-driven** (no hardcoded game balance)

### Service Responsibilities

```
┌──────────────────────────────────────┐
│          Discord Cog (UI)            │
│  ├─ Parse user input                 │
│  ├─ Call service methods             │
│  └─ Build embeds from results        │
└────────────────┬─────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────┐
│         Domain Service               │
│  ├─ Validate inputs                  │
│  ├─ Manage transactions              │
│  ├─ Enforce business rules           │
│  ├─ Lock database rows               │
│  ├─ Emit events                      │
│  └─ Log audit trail                  │
└────────────────┬─────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────┐
│         Repository                   │
│  ├─ CRUD operations                  │
│  ├─ Query builders                   │
│  └─ Entity loading                   │
└────────────────┬─────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────┐
│         Database                     │
└──────────────────────────────────────┘
```

### LES 2025 Compliance Checklist

Every service must:

- ✅ **Inherit from BaseService**
- ✅ **Use DatabaseService.get_transaction() for all writes**
- ✅ **Use pessimistic locking (SELECT FOR UPDATE)**
- ✅ **Never call session.commit() manually**
- ✅ **Validate all inputs with InputValidator**
- ✅ **Raise domain exceptions (not generic exceptions)**
- ✅ **Load config values from ConfigManager (not hardcoded)**
- ✅ **Emit events for state changes**
- ✅ **Log operations with structured logging**
- ✅ **Provide audit trails for critical operations**

---

## Step-by-Step Implementation

### Step 1: Define Your Service Structure

```python
# src/modules/your_module/service.py

from typing import TYPE_CHECKING, Dict, Optional
from src.core.database.service import DatabaseService
from src.core.logging.logger import get_logger
from src.modules.shared.base_service import BaseService
from src.modules.shared.base_repository import BaseRepository

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.your_model import YourModel


class YourModelRepository(BaseRepository["YourModel"]):
    """Repository for YourModel."""
    pass


class YourModuleService(BaseService):
    """Service for managing [your domain]."""

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        super().__init__(config_manager, event_bus, logger)

        from src.database.models.your_model import YourModel

        self._your_repo = YourModelRepository(
            model_class=YourModel,
            logger=get_logger(f"{__name__}.YourModelRepository"),
        )
```

### Step 2: Implement Read Operations

**Pattern: Read-only operations use `get_session()`**

```python
async def get_something(self, player_id: int) -> Dict[str, any]:
    """Get data without modifying anything."""

    # 1. Validate inputs
    player_id = InputValidator.validate_discord_id(player_id)

    # 2. Log operation
    self.log_operation("get_something", player_id=player_id)

    # 3. Read-only session (no transaction needed)
    async with DatabaseService.get_session() as session:
        entity = await self._your_repo.find_one_where(
            session,
            YourModel.player_id == player_id,
        )

        if not entity:
            raise NotFoundError("YourModel", player_id)

        # 4. Return data
        return {
            "player_id": player_id,
            "data": entity.some_field,
        }
```

### Step 3: Implement Write Operations

**Pattern: Write operations use `get_transaction()` with locking**

```python
async def update_something(
    self,
    player_id: int,
    amount: int,
    reason: str,
    context: Optional[str] = None,
) -> Dict[str, any]:
    """Update data with transaction safety."""

    # 1. Validate inputs
    player_id = InputValidator.validate_discord_id(player_id)
    amount = InputValidator.validate_positive_integer(amount, "amount")

    # 2. Log operation
    self.log_operation(
        "update_something",
        player_id=player_id,
        amount=amount,
    )

    # 3. Get config values
    max_limit = self.get_config("MAX_SOMETHING", default=999_999)

    # 4. Atomic transaction with locking
    async with DatabaseService.get_transaction() as session:
        # Lock the row
        entity = await self._your_repo.find_one_where(
            session,
            YourModel.player_id == player_id,
            for_update=True,  # SELECT FOR UPDATE
        )

        if not entity:
            raise NotFoundError("YourModel", player_id)

        # Save old value
        old_value = entity.some_field

        # Apply business logic
        new_value = min(old_value + amount, max_limit)
        entity.some_field = new_value

        # Audit logging (optional but recommended)
        await AuditLogger.log(
            player_id=player_id,
            transaction_type="something_updated",
            details={
                "old_value": old_value,
                "new_value": new_value,
                "amount": amount,
            },
            context=context,
        )

        # Emit event
        await self.emit_event(
            event_type="your_module.updated",
            data={
                "player_id": player_id,
                "old_value": old_value,
                "new_value": new_value,
            },
        )

        # Structured logging
        self.log.info(
            f"Updated: +{amount}",
            extra={
                "player_id": player_id,
                "old_value": old_value,
                "new_value": new_value,
            },
        )

        # Transaction auto-commits on exit
        return {
            "player_id": player_id,
            "old_value": old_value,
            "new_value": new_value,
        }
```

### Step 4: Add Custom Validation

```python
def _validate_custom_type(self, value: str) -> str:
    """Validate domain-specific values."""
    valid_choices = ("type_a", "type_b", "type_c")
    return InputValidator.validate_choice(
        value,
        field_name="custom_type",
        valid_choices=valid_choices,
    )
```

### Step 5: Instantiate Your Service

```python
# In your module's __init__.py or cog

from src.core.config.manager import ConfigManager
from src.core.event.bus import event_bus
from src.core.logging.logger import get_logger
from src.modules.your_module.service import YourModuleService

# Create service instance
your_service = YourModuleService(
    config_manager=ConfigManager(),
    event_bus=event_bus,
    logger=get_logger("your_module.service"),
)
```

---

## Transaction Patterns

### Pattern 1: Simple Single-Entity Update

```python
async with DatabaseService.get_transaction() as session:
    entity = await repo.find_one_where(
        session,
        Model.id == entity_id,
        for_update=True,
    )

    entity.field = new_value
    # Auto-commits
```

### Pattern 2: Multi-Entity Update (with Deadlock Prevention)

```python
async with DatabaseService.get_transaction() as session:
    # Lock in deterministic order to prevent deadlocks
    ids = sorted([id1, id2])

    entity1 = await repo.get_for_update(session, ids[0])
    entity2 = await repo.get_for_update(session, ids[1])

    # Perform updates
    entity1.field -= amount
    entity2.field += amount
    # Auto-commits
```

### Pattern 3: Conditional Business Logic

```python
async with DatabaseService.get_transaction() as session:
    player = await player_repo.find_one_where(
        session,
        Player.id == player_id,
        for_update=True,
    )

    # Business rule check
    if player.level < required_level:
        raise InvalidOperationError(
            "action",
            f"Requires level {required_level}"
        )

    # Proceed with operation
    player.some_field += 1
    # Auto-commits
```

### Pattern 4: Resource Deduction with Sufficiency Check

```python
async with DatabaseService.get_transaction() as session:
    currencies = await currencies_repo.find_one_where(
        session,
        Currencies.player_id == player_id,
        for_update=True,
    )

    if currencies.lumees < cost:
        raise InsufficientResourcesError(
            resource="lumees",
            required=cost,
            current=currencies.lumees,
        )

    currencies.lumees -= cost
    # Auto-commits
```

---

## Common Patterns & Examples

### Config-Driven Values

```python
# ❌ BAD: Hardcoded values
FUSION_COST = 2500

# ✅ GOOD: Config-driven
fusion_cost = self.get_config("FUSION_COST_TIER_3", default=2500)
```

### Exception Handling

```python
# In service:
if player.energy < required_energy:
    raise InsufficientResourcesError(
        resource="energy",
        required=required_energy,
        current=player.energy,
    )

# In cog:
try:
    result = await service.do_something(player_id)
    embed = build_success_embed(result)
except InsufficientResourcesError as e:
    embed = build_error_embed(
        f"Not enough {e.resource}!",
        f"Need {e.required:,}, have {e.current:,}"
    )
```

### Event Emission

```python
# Emit events for downstream systems
await self.emit_event(
    event_type="player.leveled_up",
    data={
        "player_id": player_id,
        "old_level": old_level,
        "new_level": new_level,
        "stat_points_gained": 5,
    },
)
```

### Audit Logging

```python
# Log important state changes
await AuditLogger.log_resource_change(
    player_id=player_id,
    resource_type="lumees",
    old_value=old_balance,
    new_value=new_balance,
    reason="fusion_cost",
    context="/fuse",
)
```

### Repository Custom Queries

```python
class YourModelRepository(BaseRepository["YourModel"]):
    """Repository with custom queries."""

    async def find_active_by_player(
        self,
        session: AsyncSession,
        player_id: int,
    ) -> List[YourModel]:
        """Find all active entities for a player."""
        return await self.find_many_where(
            session,
            YourModel.player_id == player_id,
            YourModel.is_active == True,
            limit=100,
        )
```

---

## Testing Services

### Unit Test Structure

```python
import pytest
from src.modules.your_module.service import YourModuleService

@pytest.fixture
async def service(mock_config, mock_event_bus, mock_logger):
    """Create service instance for testing."""
    return YourModuleService(
        config_manager=mock_config,
        event_bus=mock_event_bus,
        logger=mock_logger,
    )

@pytest.mark.asyncio
async def test_update_something_success(service, db_session):
    """Test successful update operation."""
    # Arrange
    player_id = 123
    amount = 100

    # Act
    result = await service.update_something(
        player_id=player_id,
        amount=amount,
        reason="test",
    )

    # Assert
    assert result["new_value"] == result["old_value"] + amount
```

### Integration Test with Database

```python
@pytest.mark.asyncio
async def test_update_with_transaction(service):
    """Test update with real transaction."""
    async with DatabaseService.get_transaction() as session:
        # Setup test data
        player = Player(discord_id=123, level=1)
        session.add(player)
        await session.flush()

        # Test service method
        result = await service.update_something(
            player_id=123,
            amount=100,
            reason="test",
        )

        # Verify result
        assert result["player_id"] == 123
```

---

## Troubleshooting

### Common Issues

#### ❌ "DatabaseNotInitializedError"

**Cause**: Trying to use DatabaseService before initialization

**Solution**: Call `await DatabaseService.initialize()` during startup

```python
# In your bot startup
await DatabaseService.initialize()
```

#### ❌ "Transaction auto-commits but data not persisted"

**Cause**: Not using `for_update=True` or not modifying entity within transaction

**Solution**: Always lock entities you're modifying

```python
# ❌ BAD
entity = await repo.find_one_where(session, Model.id == id)

# ✅ GOOD
entity = await repo.find_one_where(
    session,
    Model.id == id,
    for_update=True,  # Lock the row
)
```

#### ❌ "ValidationError is unknown import symbol"

**Cause**: Importing from wrong exceptions module

**Solution**: Import from `src.modules.shared.exceptions`

```python
# ❌ BAD
from src.core.exceptions import ValidationError

# ✅ GOOD
from src.modules.shared.exceptions import ValidationError
```

#### ❌ "Deadlocks when updating multiple entities"

**Cause**: Locking entities in different order across transactions

**Solution**: Always lock in deterministic (sorted) order

```python
# ✅ GOOD: Lock in sorted order
ids = sorted([player1_id, player2_id])
entity1 = await repo.get_for_update(session, ids[0])
entity2 = await repo.get_for_update(session, ids[1])
```

---

## AI Prompting Guide

### Generating a New Service

When asking an AI to generate a service, provide:

1. **Domain Description**: What the service manages
2. **Operations**: List of operations (read/write)
3. **Database Models**: Which models it uses
4. **Config Values**: What config keys it needs
5. **Events**: What events it should emit
6. **Business Rules**: Domain constraints

**Example Prompt**:

```
Create a FusionService following the Lumen service template.

Domain: Manage maiden fusion operations
Models: Maiden (src/database/models/core/maiden.py)
Config: FUSION_COST_TIER_X, FUSION_SUCCESS_RATE_TIER_X
Events: maiden.fused, fusion.failed

Operations:
- attempt_fusion(player_id, maiden_ids) -> Fuse two maidens
  - Lock both maidens
  - Check tier requirements
  - Deduct fusion cost
  - Roll success/failure
  - Update or create resulting maiden
  - Emit events

Business Rules:
- Requires exactly 2 maidens of same tier
- Cannot fuse tier 12+
- On failure, award shards

Reference: src/modules/shared/reference_service.py
Template: src/modules/shared/service_template.py
```

---

## Summary

You now have everything needed to build LES 2025-compliant services:

✅ **Reference Implementation**: [reference_service.py](../src/modules/shared/reference_service.py)
✅ **Template**: [service_template.py](../src/modules/shared/service_template.py)
✅ **DatabaseService**: Transaction management
✅ **BaseService**: Logging, config, events
✅ **BaseRepository**: CRUD operations
✅ **Validators**: Input validation
✅ **Exceptions**: Domain exceptions
✅ **AuditLogger**: Audit trails

**Next Steps**:
1. Read the reference implementation
2. Copy the template for your new service
3. Fill in your domain logic
4. Test with your database
5. Integrate with your cog

Happy coding! 🚀
