"""
Configuration management subsystem for Lumen (2025).

Purpose
-------
Provides comprehensive configuration management with both static (environment-based)
and dynamic (database-backed) configuration support. Designed for production-grade
configuration handling with validation, caching, and observability.

Features
--------
- Static configuration from environment variables (.env support)
- Dynamic configuration with database backing and caching
- Recursive schema validation for nested configurations
- Comprehensive metrics tracking and health monitoring
- Hot-reload support for runtime configuration changes
- Transaction logging and optional EventBus integration
- Config-driven TTLs and self-tuning cache behavior

Architecture
------------
The config subsystem is organized into specialized modules:

- **config.py**: Static configuration from environment variables
- **manager.py**: Dynamic configuration with database backing
- **validator.py**: Schema-based configuration validation
- **metrics.py**: Performance metrics and health monitoring
- **errors.py**: Domain-specific exception hierarchy

All modules follow LES 2025 standards with proper separation of concerns,
comprehensive observability, and production-grade error handling.

LES 2025 Compliance
-------------------
- **Article I**: Strict separation - infrastructure layer only
- **Article V**: Config-driven everything (even cache TTLs)
- **Article VI**: Comprehensive observability and metrics
- **Article IX**: Graceful degradation on failures
- **Article X**: Structured logging throughout

Static vs Dynamic Configuration
--------------------------------
**Static (Config):**
- Loaded from environment variables at startup
- Includes: Discord token, database URLs, pool sizes, Redis config
- Validated on application start
- Changes require application restart (except safe reload)

**Dynamic (ConfigManager):**
- Loaded from YAML defaults + database overrides
- Includes: Game balance, fusion costs, exploration config
- Hot-reload support for runtime changes
- Background refresh with configurable TTL

Usage Examples
--------------
### Static Configuration
```python
from src.core.config import Config

# Access static values
token = Config.DISCORD_TOKEN
db_url = Config.DATABASE_URL
pool_size = Config.DATABASE_POOL_SIZE

# Check environment
if Config.is_production():
    logger.info("Running in production mode")

# Get config summary
summary = Config.get_config_summary()
```

### Dynamic Configuration
```python
from src.core.config import ConfigManager

# Initialize (once at startup)
await ConfigManager.initialize()

# Read configuration
fusion_base_cost = ConfigManager.get("fusion_costs.base", default=100)
fusion_curve_a = ConfigManager.get("fusion_costs.curve.a", default=1.5)

# Write configuration (hot-reload)
await ConfigManager.set(
    key="fusion_costs.base",
    value=150,
    modified_by="admin"
)

# Get metrics
metrics = ConfigManager.get_metrics()
print(f"Cache hit rate: {metrics['cache_hit_rate']}%")

# Health check
health = ConfigManager.health_snapshot()
if not health["initialized"]:
    logger.error("ConfigManager not initialized!")
```

### Schema Validation
```python
from src.core.config import ConfigSchema, register_schema

# Define custom schema
schema = ConfigSchema(
    fields={
        "enabled": bool,
        "rate": float,
        "nested": ConfigSchema(
            fields={"value": int}
        )
    }
)

# Register for validation
register_schema("my_feature", schema)

# Now writes are validated
await ConfigManager.set("my_feature", {
    "enabled": True,
    "rate": 1.5,
    "nested": {"value": 100}
})
```

### Metrics Monitoring
```python
from src.core.config import ConfigManager

# Get comprehensive metrics
metrics = await ConfigManager.get_metrics()
logger.info("Config metrics", extra=metrics)

# Check health
health = ConfigManager.health_snapshot()
if health["status"] == "degraded":
    send_alert("config_degraded", health)

# Reset metrics (testing/monitoring)
ConfigManager.reset_metrics()
```

Dependencies
------------
- Config: python-dotenv, pathlib, enum
- ConfigManager: asyncio, sqlalchemy, yaml (optional)
- Validator: dataclasses, typing
- Metrics: dataclasses, asyncio
- Errors: Standard library only

Performance Characteristics
---------------------------
- Static config: O(1) access, loaded once at startup
- Dynamic config: O(1) cache access, periodic DB refresh
- Validation: O(n) where n = total fields in config tree
- Typical cache hit rate: 95-99%
- Average GET latency: <5ms (cached)
- Average SET latency: <100ms (DB write)
"""

# Static configuration (environment-based)
from src.core.config.config import Config, Environment

# Dynamic configuration management (database-backed)
from src.core.config.manager import ConfigManager

# Error hierarchy
from src.core.config.errors import (
    ConfigError,
    ConfigInitializationError,
    ConfigValidationError,
    ConfigWriteError,
)

# Validation and schema management
from src.core.config.validator import (
    ConfigSchema,
    SchemaField,
    get_schema_for_top_key,
    register_schema,
    unregister_schema,
    validate_config_value,
)

# Metrics and monitoring
from src.core.config.metrics import (
    ConfigMetrics,
    get_health_snapshot,
    get_metrics_snapshot,
)

__all__ = [
    # Static configuration
    "Config",
    "Environment",
    # Dynamic configuration manager
    "ConfigManager",
    # Error hierarchy
    "ConfigError",
    "ConfigInitializationError",
    "ConfigValidationError",
    "ConfigWriteError",
    # Validation
    "ConfigSchema",
    "SchemaField",
    "get_schema_for_top_key",
    "register_schema",
    "unregister_schema",
    "validate_config_value",
    # Metrics
    "ConfigMetrics",
    "get_health_snapshot",
    "get_metrics_snapshot",
]

