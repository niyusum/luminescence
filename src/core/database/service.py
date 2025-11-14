"""
Database subsystem: centralized async engine & session management (Lumen 2025)

Purpose
-------
This module provides the core database infrastructure for Lumen:

- A single shared SQLAlchemy AsyncEngine instance.
- A session factory for creating isolated AsyncSession instances.
- Context managers for:
  - read-only sessions (`get_session`)
  - atomic write transactions (`get_transaction`)
- A simple health check for infra-level probes.

Responsibilities
----------------
- Initialize and dispose the database engine (idempotent).
- Provide async context managers for read and write access.
- Enforce atomic transactions with automatic rollback-on-exception.
- Support pessimistic locking via SQLAlchemy's `with_for_update=True` pattern.
- Emit structured logs and database metrics for key lifecycle events.
- Expose a fast health check for readiness/liveness probes.
- Provide connection pool metrics for monitoring and capacity planning.

Non-Responsibilities
--------------------
This module is intentionally infra-pure and does NOT:

- Run background health monitors or schedulers.
- Perform query-level observability (handled by `query_observer.py`).
- Apply retry policies for domain operations (handled by callers / `retry_policy.py`).
- Perform migrations, table creation, or destructive operations.
- Know anything about domain models, SQLModel, or feature modules.
- Contain any business logic or Discord-related code.

Lumen 2025 Compliance
---------------------
- **Strict layering**: Infra-only; no domain, service, or Discord imports.
- **Transaction discipline**:
  - `get_transaction()` wraps all writes in a single atomic transaction.
  - Automatic `commit` on success, `rollback` on any exception.
  - Callers should NOT manually commit except in exceptional cases.
- **Pessimistic locking**:
  - Services must use:
    `await session.get(Player, player_id, with_for_update=True)`
    inside `get_transaction()` contexts.
- **Observability**:
  - Structured logs on initialization, shutdown, errors, and transaction outcomes.
  - Metrics emitted via `src.core.database.metrics.DatabaseMetrics`.
  - Health check for infra-level probes (`health_check()`).
- **Config-driven**:
  - All tunable parameters (timeouts, pool sizes) sourced from config.
- **Safety**:
  - Idempotent initialization guarded by an async lock.
  - Clear, domain-specific infra exceptions for initialization and usage errors.

Design Notes
------------
- Uses `QueuePool` in normal environments and `NullPool` in tests.
- Supports PostgreSQL `statement_timeout` when using a Postgres URL.
- `get_session()` is for read-only or advanced cases; `get_transaction()`
  is the standard entry-point for **all state mutations**.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional, Type

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, Pool, QueuePool

from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.database.metrics import DatabaseMetrics

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class DatabaseInitializationError(RuntimeError):
    """Raised when the database engine fails to initialize."""


class DatabaseNotInitializedError(RuntimeError):
    """Raised when the database engine or session factory is used before init."""


# --------------------------------------------------------------------------- #
# Configuration snapshot
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _DatabaseConfigSnapshot:
    """Simple immutable snapshot of DB-related configuration values.

    This prevents repeated Config lookups and gives a stable view for the
    lifetime of the process (or until re-initialization).
    """

    url: str
    echo: bool
    pool_class: Type[Pool]
    pool_size: int
    max_overflow: int
    pool_recycle: int
    pool_timeout: int
    statement_timeout_ms: int

    @property
    def is_postgres(self) -> bool:
        return self.url.startswith(("postgresql://", "postgresql+asyncpg://"))


class DatabaseService:
    """
    Centralized async database engine & session management.

    Public API
    ----------
    - initialize() -> None
    - shutdown() -> None
    - get_session() -> Async context manager for read-only or manual control.
    - get_transaction() -> Async context manager for atomic write transactions.
    - health_check() -> bool indicating DB reachability.
    - get_pool_metrics() -> dict with current connection pool metrics.
    - record_pool_metrics() -> Record pool metrics to monitoring backend.
    - get_locked_entity() -> helper for pessimistic row locking.

    Usage
    -----
    # Writes (preferred)
    >>> async with DatabaseService.get_transaction() as session:
    ...     player = await session.get(Player, player_id, with_for_update=True)
    ...     player.lumees += 1000

    # Reads
    >>> async with DatabaseService.get_session() as session:
    ...     result = await session.execute(select(Player))

    Notes
    -----
    - You must call `DatabaseService.initialize()` once during application
      startup before using sessions.
    - `get_transaction()` is designed for *single-unit-of-work* flows. Avoid
      nesting or long-lived transactions.
    """

    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker[AsyncSession]] = None
    _config_snapshot: Optional[_DatabaseConfigSnapshot] = None
    _init_lock: asyncio.Lock = asyncio.Lock()

    # --------------------------------------------------------------------- #
    # Initialization & Shutdown
    # --------------------------------------------------------------------- #

    @classmethod
    def _build_config_snapshot(cls) -> _DatabaseConfigSnapshot:
        """Create an immutable snapshot of DB configuration values."""
        database_url = getattr(Config, "DATABASE_URL", None)
        if not database_url or not isinstance(database_url, str):
            raise DatabaseInitializationError("DATABASE_URL is not configured")

        is_testing = bool(getattr(Config, "TESTING", False)) or (
            hasattr(Config, "is_testing") and Config.is_testing()
        )

        pool_class: Type[Pool] = NullPool if is_testing else QueuePool

        # All tunable values sourced from config with sensible defaults.
        pool_size = int(getattr(Config, "DATABASE_POOL_SIZE", 5))
        max_overflow = int(getattr(Config, "DATABASE_MAX_OVERFLOW", 10))
        pool_recycle = int(getattr(Config, "DATABASE_POOL_RECYCLE", 1800))
        pool_timeout = int(getattr(Config, "DATABASE_POOL_TIMEOUT", 30))
        statement_timeout_ms = int(
            getattr(Config, "DATABASE_STATEMENT_TIMEOUT_MS", 30_000)
        )

        echo = bool(getattr(Config, "DATABASE_ECHO", False))

        snapshot = _DatabaseConfigSnapshot(
            url=database_url,
            echo=echo,
            pool_class=pool_class,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
            statement_timeout_ms=statement_timeout_ms,
        )

        logger.debug(
            "Database configuration snapshot created",
            extra={
                "url_scheme": database_url.split(":", 1)[0],
                "pool_class": pool_class.__name__,
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_recycle": pool_recycle,
                "pool_timeout": pool_timeout,
                "statement_timeout_ms": statement_timeout_ms,
            },
        )

        return snapshot

    @classmethod
    async def initialize(cls) -> None:
        """
        Initialize the async engine and session factory (idempotent).

        Raises
        ------
        DatabaseInitializationError
            If configuration is missing/invalid or engine creation fails.
        """
        if cls._engine is not None and cls._session_factory is not None:
            # Already initialized; nothing to do.
            return

        async with cls._init_lock:
            if cls._engine is not None and cls._session_factory is not None:
                return

            try:
                config = cls._build_config_snapshot()
                cls._config_snapshot = config

                pool_kwargs = {}
                if config.pool_class is QueuePool:
                    pool_kwargs = {
                        "pool_size": config.pool_size,
                        "max_overflow": config.max_overflow,
                        "pool_recycle": config.pool_recycle,
                        "pool_timeout": config.pool_timeout,
                    }

                engine = create_async_engine(
                    config.url,
                    echo=config.echo,
                    poolclass=config.pool_class,
                    pool_pre_ping=True,
                    **pool_kwargs,
                )

                session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
                    engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                    autocommit=False,
                )

                cls._engine = engine
                cls._session_factory = session_factory

                DatabaseMetrics.record_engine_initialized(
                    url_scheme=config.url.split(":", 1)[0],
                    pool_class=config.pool_class.__name__,
                    pool_size=config.pool_size,
                    max_overflow=config.max_overflow,
                )

                logger.info(
                    "DatabaseService initialized",
                    extra={
                        "url_scheme": config.url.split(":", 1)[0],
                        "pool_class": config.pool_class.__name__,
                        "pool_size": config.pool_size,
                        "max_overflow": config.max_overflow,
                        "pool_recycle": config.pool_recycle,
                        "pool_timeout": config.pool_timeout,
                        "echo": config.echo,
                    },
                )

            except DatabaseInitializationError:
                # Bubble up after logging; this is a configuration error.
                logger.critical(
                    "DatabaseService initialization failed due to configuration error",
                    exc_info=True,
                )
                cls._engine = None
                cls._session_factory = None
                cls._config_snapshot = None
                DatabaseMetrics.record_engine_initialization_failed(config_error=True)
                raise
            except Exception as exc:
                # Unknown engine creation failure.
                logger.critical(
                    "Failed to initialize DatabaseService",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                    exc_info=True,
                )
                cls._engine = None
                cls._session_factory = None
                cls._config_snapshot = None
                DatabaseMetrics.record_engine_initialization_failed(config_error=False)
                raise DatabaseInitializationError(
                    "Failed to initialize DatabaseService"
                ) from exc

    @classmethod
    async def shutdown(cls) -> None:
        """
        Dispose the engine and clear the session factory.

        Safe to call multiple times.
        """
        engine = cls._engine
        cls._engine = None
        cls._session_factory = None
        cls._config_snapshot = None

        if engine is None:
            logger.info("DatabaseService shutdown requested; no active engine")
            return

        try:
            await engine.dispose()
            logger.info("DatabaseService shutdown complete")
            DatabaseMetrics.record_engine_shutdown()
        except Exception as exc:
            logger.error(
                "Error during DatabaseService shutdown",
                extra={"error": str(exc), "error_type": type(exc).__name__},
                exc_info=True,
            )

    @classmethod
    async def close(cls) -> None:
        """
        Backwards-compatible alias for `shutdown()`.
        """
        await cls.shutdown()

    # --------------------------------------------------------------------- #
    # Health Check
    # --------------------------------------------------------------------- #

    @classmethod
    async def health_check(cls) -> bool:
        """
        Perform a simple health check against the database.

        Returns
        -------
        bool
            True if the database is reachable and responds to a simple query;
            False otherwise.
        """
        engine = cls._engine
        if engine is None:
            logger.warning(
                "Database health check requested but engine is not initialized"
            )
            DatabaseMetrics.record_health_check(success=False, duration_ms=0.0)
            return False

        start = time.perf_counter()
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            duration_ms = (time.perf_counter() - start) * 1000.0
            DatabaseMetrics.record_health_check(success=True, duration_ms=duration_ms)
            logger.debug(
                "Database health check succeeded",
                extra={"duration_ms": duration_ms},
            )
            return True
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            DatabaseMetrics.record_health_check(success=False, duration_ms=duration_ms)
            logger.error(
                "Database health check failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                },
                exc_info=True,
            )
            return False

    # --------------------------------------------------------------------- #
    # Connection Pool Metrics
    # --------------------------------------------------------------------- #

    @classmethod
    def get_pool_metrics(cls) -> Optional[dict[str, int]]:
        """
        Get current connection pool metrics.

        Returns
        -------
        Optional[dict[str, int]]
            Dictionary with pool metrics:
            - pool_size: Configured pool size
            - checked_out: Connections currently in use
            - checked_in: Connections available
            - overflow: Overflow connections beyond pool_size
            - total_connections: Total connections
            Returns None if engine not initialized or using NullPool.
        """
        engine = cls._engine
        config = cls._config_snapshot

        if engine is None or config is None:
            logger.warning("Pool metrics requested but engine not initialized")
            return None

        # NullPool doesn't have pool metrics
        if config.pool_class.__name__ == "NullPool":
            return None

        try:
            pool = engine.pool
            # QueuePool provides size(), checkedout(), overflow()
            pool_size = pool.size()
            checked_out = pool.checkedout()
            overflow_count = pool.overflow()
            total = pool_size + overflow_count
            checked_in = pool_size - checked_out

            return {
                "pool_size": config.pool_size,
                "checked_out": checked_out,
                "checked_in": checked_in,
                "overflow": overflow_count,
                "total_connections": total,
            }

        except Exception as exc:
            logger.error(
                "Failed to retrieve pool metrics",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return None

    @classmethod
    def record_pool_metrics(cls) -> None:
        """
        Retrieve and record current connection pool metrics.

        This method queries the connection pool status and emits metrics
        for monitoring and capacity planning. Safe to call periodically.

        Notes
        -----
        - Does nothing if engine not initialized or using NullPool
        - Emits metrics via DatabaseMetrics.record_pool_metrics()
        - Logs warning if metrics retrieval fails
        """
        metrics = cls.get_pool_metrics()

        if metrics is None:
            return

        DatabaseMetrics.record_pool_metrics(
            pool_size=metrics["pool_size"],
            checked_out=metrics["checked_out"],
            checked_in=metrics["checked_in"],
            overflow=metrics["overflow"],
            total_connections=metrics["total_connections"],
        )

        logger.debug(
            "Pool metrics recorded",
            extra={
                "pool_size": metrics["pool_size"],
                "checked_out": metrics["checked_out"],
                "checked_in": metrics["checked_in"],
                "overflow": metrics["overflow"],
                "total_connections": metrics["total_connections"],
            },
        )

    # --------------------------------------------------------------------- #
    # Session & Transaction Context Managers
    # --------------------------------------------------------------------- #

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._session_factory is None or cls._engine is None:
            raise DatabaseNotInitializedError("DatabaseService is not initialized")

    @classmethod
    def _get_config_snapshot(cls) -> _DatabaseConfigSnapshot:
        if cls._config_snapshot is None:
            raise DatabaseNotInitializedError("DatabaseService is not initialized")
        return cls._config_snapshot

    @classmethod
    @asynccontextmanager
    async def get_session(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Yield a database session without automatic commit.

        Use this for:
        - Read-only operations.
        - Rare advanced cases where manual transaction control is required.

        The session is always closed at the end of the context.

        Raises
        ------
        DatabaseNotInitializedError
            If DatabaseService has not been initialized.
        """
        cls._ensure_initialized()
        assert cls._session_factory is not None  # for type-checkers

        start = time.perf_counter()
        async with cls._session_factory() as session:
            config = cls._get_config_snapshot()
            try:
                if config.is_postgres:
                    await session.execute(
                        text(
                            f"SET LOCAL statement_timeout = "
                            f"{config.statement_timeout_ms}"
                        )
                    )
                logger.debug("Database session opened (read-only/manual)")

                yield session
            finally:
                await session.close()
                duration_ms = (time.perf_counter() - start) * 1000.0
                logger.debug(
                    "Database session closed",
                    extra={"duration_ms": duration_ms},
                )

    @classmethod
    @asynccontextmanager
    async def get_transaction(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Yield a database session wrapped in a single atomic transaction.

        Behavior
        --------
        - On normal exit:
            - Commits the transaction.
        - On any exception:
            - Rolls back the transaction.
            - Logs the error and re-raises.

        This is the **standard entry point for all state mutations** in Lumen.

        Raises
        ------
        DatabaseNotInitializedError
            If DatabaseService has not been initialized.
        """
        cls._ensure_initialized()
        assert cls._session_factory is not None  # for type-checkers

        start = time.perf_counter()
        async with cls._session_factory() as session:
            config = cls._get_config_snapshot()
            committed = False
            DatabaseMetrics.record_transaction_started()

            try:
                if config.is_postgres:
                    await session.execute(
                        text(
                            f"SET LOCAL statement_timeout = "
                            f"{config.statement_timeout_ms}"
                        )
                    )

                logger.debug("Database transaction started")
                yield session

                await session.commit()
                committed = True
                duration_ms = (time.perf_counter() - start) * 1000.0
                DatabaseMetrics.record_transaction_committed(duration_ms=duration_ms)
                logger.debug(
                    "Database transaction committed",
                    extra={"duration_ms": duration_ms},
                )
            except OperationalError as exc:
                await session.rollback()
                duration_ms = (time.perf_counter() - start) * 1000.0
                DatabaseMetrics.record_transaction_rolled_back(
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                )
                logger.error(
                    "OperationalError in database transaction; rolled back",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "committed": committed,
                        "duration_ms": duration_ms,
                    },
                    exc_info=True,
                )
                raise
            except DBAPIError as exc:
                await session.rollback()
                duration_ms = (time.perf_counter() - start) * 1000.0
                DatabaseMetrics.record_transaction_rolled_back(
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                )
                logger.error(
                    "DBAPIError in database transaction; rolled back",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "committed": committed,
                        "duration_ms": duration_ms,
                    },
                    exc_info=True,
                )
                raise
            except Exception as exc:
                await session.rollback()
                duration_ms = (time.perf_counter() - start) * 1000.0
                DatabaseMetrics.record_transaction_rolled_back(
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                )
                logger.error(
                    "Error in database transaction; rolled back",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "committed": committed,
                        "duration_ms": duration_ms,
                    },
                    exc_info=True,
                )
                raise
            finally:
                await session.close()
                logger.debug("Database transaction session closed")

    # --------------------------------------------------------------------- #
    # Optional helper for pessimistic locking (syntactic sugar)
    # --------------------------------------------------------------------- #

    @classmethod
    async def get_locked_entity(
        cls,
        session: AsyncSession,
        model: type,
        primary_key: Any,
    ) -> Any:
        """
        Helper to fetch an entity with a pessimistic row lock.

        This is syntactic sugar over:
            await session.get(Model, pk, with_for_update=True)

        Parameters
        ----------
        session:
            Active AsyncSession (typically from `get_transaction()`).
        model:
            ORM model class.
        primary_key:
            Primary key value.

        Returns
        -------
        Any
            The locked entity instance or None if not found.
        """
        return await session.get(model, primary_key, with_for_update=True)
