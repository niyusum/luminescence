"""
Database metrics for Lumen 2025.

Purpose
-------
Provide a centralized, infra-pure metrics façade for all database-related
telemetry:

- Engine lifecycle (init / failure / shutdown).
- Health checks.
- Transactions (start / commit / rollback).
- Queries (latency, errors).
- Retries (attempts, give-ups).
- Connection pool (size, checked out/in, overflow).

Responsibilities
----------------
- Define a stable metrics API (`DatabaseMetrics`) that other database modules
  can call without depending on a specific metrics backend.
- Optionally delegate to a pluggable backend implementing
  `AbstractDatabaseMetricsBackend`.
- Emit structured logs whenever no backend is configured to ensure some
  observability in all environments.
- Track connection pool utilization for capacity planning.

Non-Responsibilities
--------------------
- Does not perform any database IO.
- Does not manage the engine or sessions.
- Does not run background tasks or schedulers.
- Does not depend on domain or Discord code.

Design Notes
------------
- Uses an optional backend to avoid hard-coupling to Prometheus/StatsD/etc.
- When no backend is configured, falls back to debug-level logging only.
- Connection pool metrics support capacity planning and connection leak detection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class AbstractDatabaseMetricsBackend(ABC):
    """Interface for pluggable database metrics backends."""

    # ------------------------------------------------------------------ #
    # Engine lifecycle
    # ------------------------------------------------------------------ #

    @abstractmethod
    def record_engine_initialized(
        self,
        *,
        url_scheme: str,
        pool_class: str,
        pool_size: int,
        max_overflow: int,
    ) -> None:
        ...

    @abstractmethod
    def record_engine_initialization_failed(self, *, config_error: bool) -> None:
        ...

    @abstractmethod
    def record_engine_shutdown(self) -> None:
        ...

    # ------------------------------------------------------------------ #
    # Health checks
    # ------------------------------------------------------------------ #

    @abstractmethod
    def record_health_check(self, *, success: bool, duration_ms: float) -> None:
        ...

    # ------------------------------------------------------------------ #
    # Transactions
    # ------------------------------------------------------------------ #

    @abstractmethod
    def record_transaction_started(self) -> None:
        ...

    @abstractmethod
    def record_transaction_committed(self, *, duration_ms: float) -> None:
        ...

    @abstractmethod
    def record_transaction_rolled_back(
        self,
        *,
        duration_ms: float,
        error_type: str,
    ) -> None:
        ...

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    @abstractmethod
    def record_query(
        self,
        *,
        operation: str,
        duration_ms: float,
        success: bool,
        error_type: Optional[str],
        extra_tags: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...

    # ------------------------------------------------------------------ #
    # Retries
    # ------------------------------------------------------------------ #

    @abstractmethod
    def record_retry_attempt(
        self,
        *,
        operation: str,
        attempt: int,
        will_retry: bool,
        error_type: str,
    ) -> None:
        ...

    @abstractmethod
    def record_retry_give_up(
        self,
        *,
        operation: str,
        attempt: int,
        error_type: str,
    ) -> None:
        ...

    # ------------------------------------------------------------------ #
    # Connection Pool
    # ------------------------------------------------------------------ #

    @abstractmethod
    def record_pool_metrics(
        self,
        *,
        pool_size: int,
        checked_out: int,
        checked_in: int,
        overflow: int,
        total_connections: int,
    ) -> None:
        """
        Record current connection pool metrics.

        Parameters
        ----------
        pool_size : int
            Configured pool size
        checked_out : int
            Number of connections currently checked out (in use)
        checked_in : int
            Number of connections checked in (available)
        overflow : int
            Number of overflow connections (beyond pool_size)
        total_connections : int
            Total connections (checked_out + checked_in + overflow)
        """
        ...


class DatabaseMetrics:
    """
    Static façade for database metrics.

    Other infra and service layers should call these classmethods; a concrete
    backend can be configured at startup via `configure_backend`.
    """

    _backend: Optional[AbstractDatabaseMetricsBackend] = None

    # ------------------------------------------------------------------ #
    # Backend configuration
    # ------------------------------------------------------------------ #

    @classmethod
    def configure_backend(cls, backend: AbstractDatabaseMetricsBackend) -> None:
        cls._backend = backend
        logger.info(
            "Database metrics backend configured",
            extra={"backend_class": type(backend).__name__},
        )

    @classmethod
    def _log_fallback(cls, message: str, **extra: Any) -> None:
        """Fallback logging when no backend is configured."""
        logger.debug(
            f"[DatabaseMetrics fallback] {message}",
            extra=extra or None,
        )

    # ------------------------------------------------------------------ #
    # Engine lifecycle
    # ------------------------------------------------------------------ #

    @classmethod
    def record_engine_initialized(
        cls,
        *,
        url_scheme: str,
        pool_class: str,
        pool_size: int,
        max_overflow: int,
    ) -> None:
        if cls._backend:
            cls._backend.record_engine_initialized(
                url_scheme=url_scheme,
                pool_class=pool_class,
                pool_size=pool_size,
                max_overflow=max_overflow,
            )
        else:
            cls._log_fallback(
                "engine_initialized",
                url_scheme=url_scheme,
                pool_class=pool_class,
                pool_size=pool_size,
                max_overflow=max_overflow,
            )

    @classmethod
    def record_engine_initialization_failed(cls, *, config_error: bool) -> None:
        if cls._backend:
            cls._backend.record_engine_initialization_failed(config_error=config_error)
        else:
            cls._log_fallback(
                "engine_initialization_failed",
                config_error=config_error,
            )

    @classmethod
    def record_engine_shutdown(cls) -> None:
        if cls._backend:
            cls._backend.record_engine_shutdown()
        else:
            cls._log_fallback("engine_shutdown")

    # ------------------------------------------------------------------ #
    # Health checks
    # ------------------------------------------------------------------ #

    @classmethod
    def record_health_check(cls, *, success: bool, duration_ms: float) -> None:
        if cls._backend:
            cls._backend.record_health_check(success=success, duration_ms=duration_ms)
        else:
            cls._log_fallback(
                "health_check",
                success=success,
                duration_ms=duration_ms,
            )

    # ------------------------------------------------------------------ #
    # Transactions
    # ------------------------------------------------------------------ #

    @classmethod
    def record_transaction_started(cls) -> None:
        if cls._backend:
            cls._backend.record_transaction_started()
        else:
            cls._log_fallback("transaction_started")

    @classmethod
    def record_transaction_committed(cls, *, duration_ms: float) -> None:
        if cls._backend:
            cls._backend.record_transaction_committed(duration_ms=duration_ms)
        else:
            cls._log_fallback(
                "transaction_committed",
                duration_ms=duration_ms,
            )

    @classmethod
    def record_transaction_rolled_back(
        cls,
        *,
        duration_ms: float,
        error_type: str,
    ) -> None:
        if cls._backend:
            cls._backend.record_transaction_rolled_back(
                duration_ms=duration_ms,
                error_type=error_type,
            )
        else:
            cls._log_fallback(
                "transaction_rolled_back",
                duration_ms=duration_ms,
                error_type=error_type,
            )

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    @classmethod
    def record_query(
        cls,
        *,
        operation: str,
        duration_ms: float,
        success: bool,
        error_type: Optional[str],
        extra_tags: Optional[Dict[str, Any]] = None,
    ) -> None:
        if cls._backend:
            cls._backend.record_query(
                operation=operation,
                duration_ms=duration_ms,
                success=success,
                error_type=error_type,
                extra_tags=extra_tags,
            )
        else:
            cls._log_fallback(
                "query",
                operation=operation,
                duration_ms=duration_ms,
                success=success,
                error_type=error_type,
                extra_tags=extra_tags,
            )

    # ------------------------------------------------------------------ #
    # Retries
    # ------------------------------------------------------------------ #

    @classmethod
    def record_retry_attempt(
        cls,
        *,
        operation: str,
        attempt: int,
        will_retry: bool,
        error_type: str,
    ) -> None:
        if cls._backend:
            cls._backend.record_retry_attempt(
                operation=operation,
                attempt=attempt,
                will_retry=will_retry,
                error_type=error_type,
            )
        else:
            cls._log_fallback(
                "retry_attempt",
                operation=operation,
                attempt=attempt,
                will_retry=will_retry,
                error_type=error_type,
            )

    @classmethod
    def record_retry_give_up(
        cls,
        *,
        operation: str,
        attempt: int,
        error_type: str,
    ) -> None:
        if cls._backend:
            cls._backend.record_retry_give_up(
                operation=operation,
                attempt=attempt,
                error_type=error_type,
            )
        else:
            cls._log_fallback(
                "retry_give_up",
                operation=operation,
                attempt=attempt,
                error_type=error_type,
            )

    # ------------------------------------------------------------------ #
    # Connection Pool
    # ------------------------------------------------------------------ #

    @classmethod
    def record_pool_metrics(
        cls,
        *,
        pool_size: int,
        checked_out: int,
        checked_in: int,
        overflow: int,
        total_connections: int,
    ) -> None:
        """
        Record current connection pool metrics.

        Parameters
        ----------
        pool_size : int
            Configured pool size
        checked_out : int
            Number of connections currently checked out (in use)
        checked_in : int
            Number of connections checked in (available)
        overflow : int
            Number of overflow connections (beyond pool_size)
        total_connections : int
            Total connections (checked_out + checked_in + overflow)
        """
        if cls._backend:
            cls._backend.record_pool_metrics(
                pool_size=pool_size,
                checked_out=checked_out,
                checked_in=checked_in,
                overflow=overflow,
                total_connections=total_connections,
            )
        else:
            cls._log_fallback(
                "pool_metrics",
                pool_size=pool_size,
                checked_out=checked_out,
                checked_in=checked_in,
                overflow=overflow,
                total_connections=total_connections,
            )
