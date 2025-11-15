"""
Infrastructure Services for Lumen RPG (2025).

Purpose
-------
Provides core infrastructure services for database, caching, health monitoring,
and audit trail logging. These are the foundational components that all other
modules depend on.

Module Contents
---------------
**Audit Logging**:
    - AuditLogger: Event-driven audit trail logger for all transactions
    - TransactionLogger: Backward-compatible alias to AuditLogger (DEPRECATED)
    - AuditMetrics: Metrics dataclass for audit production observability

**Health Monitoring**:
    - UnifiedHealthCheck: Aggregates health status from all components
    - HealthStatus: Enum for system health states (HEALTHY/DEGRADED/UNHEALTHY)

Architecture Compliance
-----------------------
Lumen 2025 Engineering Standard compliance:
- **Separation of Responsibilities**: Pure infrastructure, no business logic
- **Event-Driven Architecture**: Audit logger publishes to EventBus
- **Observability First**: Comprehensive health checks and metrics
- **Config-Driven**: All behavior configurable via ConfigManager
- **Error Isolation**: Component failures don't cascade
- **Graceful Degradation**: Health checks return partial results on failure

Dependencies
------------
This package depends on:
- src.core.event (EventBus for audit events)
- src.core.database (DatabaseService and health monitor)
- src.core.redis (RedisHealthMonitor)
- src.core.config (ConfigManager)
- src.core.logging (Structured logging)
- src.core.validation (TransactionValidator)
- src.core.exceptions (Domain exceptions)

Usage Examples
--------------
Audit logging (recommended):
    from src.core.infra import AuditLogger
    
    await AuditLogger.log(
        player_id=123,
        transaction_type="fusion_attempt",
        details={"success": True, "tier": 4},
        context="/fuse",
    )
    
    metrics = AuditLogger.get_metrics()
    print(f"Error rate: {metrics['error_rate_percent']}%")

Audit logging (backward compatible):
    from src.core.infra import TransactionLogger
    
    # Still works but deprecated - use AuditLogger instead
    await TransactionLogger.log_transaction(
        player_id=123,
        transaction_type="fusion_attempt",
        details={"success": True, "tier": 4},
        context="/fuse",
    )

Health checking:
    from src.core.infra import UnifiedHealthCheck, HealthStatus
    
    # Initialize with monitors (at startup)
    UnifiedHealthCheck.initialize(
        database_monitor=db_monitor,
        redis_monitor=redis_monitor,
    )
    
    # Perform health check
    report = await UnifiedHealthCheck.check()
    
    if report["status"] == HealthStatus.UNHEALTHY.value:
        logger.error("System unhealthy!", extra={"report": report})

Design Notes
------------
**Event-Driven Audit**:
    AuditLogger publishes events to the EventBus instead of writing directly
    to the database. This enables:
    - Decoupled persistence (separate audit consumer service)
    - Non-blocking audit logging
    - Event-driven analytics
    - Flexible audit sinks (database, files, external systems)

**Unified Health**:
    UnifiedHealthCheck aggregates component health rather than exposing
    individual health checks. This provides:
    - Single source of truth for system health
    - Consistent health report format
    - Easy monitoring integration
    - Graceful degradation on component failures

**Backward Compatibility**:
    TransactionLogger is maintained as an alias to AuditLogger for backward
    compatibility with existing code (e.g., ConfigManager). New code should
    use AuditLogger directly.
    
    The main API difference:
    - TransactionLogger.log_transaction() → AuditLogger.log()
    - All other methods have identical names
"""

from src.core.infra.audit_logger import AuditLogger, AuditMetrics
from src.core.infra.health import HealthStatus, UnifiedHealthCheck
from src.core.infra.transaction_logger import TransactionLogger

__all__ = [
    # Audit Logging
    "AuditLogger",
    "AuditMetrics",
    "TransactionLogger",  # Backward compatibility alias
    # Health Monitoring
    "UnifiedHealthCheck",
    "HealthStatus",
]