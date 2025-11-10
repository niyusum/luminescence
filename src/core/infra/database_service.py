"""
Centralized database connection and session management.

RIKI LAW Compliance:
- Transaction context managers for pessimistic locking (Article I.1)
- Automatic rollback on exceptions (Article I.6)
- Health monitoring and graceful degradation (Article IX)
- Audit logging with Discord context (Article II) - ENHANCED

Production Features:
- Comprehensive connection metrics and monitoring
- Query timeout enforcement (30s)
- Session leak detection
- Background health checks (60s interval)
- Connection pooling with pre-ping
- Retry logic on initialization (3 attempts)
- Slow query logging (>5s warnings)
- Graceful shutdown with metrics summary
- Pool status inspection

ENHANCED: LogContext integration for full audit trail compliance
"""

from typing import AsyncGenerator, Optional, Dict, Any, List
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy import text, event
from sqlalchemy.exc import OperationalError, DBAPIError
import asyncio
import time

from src.core.config.config import Config
from src.core.logging.logger import get_logger, LogContext, set_log_context

logger = get_logger(__name__)


@dataclass
class ConnectionMetrics:
    """Metrics for database connection monitoring."""
    total_sessions_created: int = 0
    active_sessions: int = 0
    total_transactions: int = 0
    total_rollbacks: int = 0
    total_commits: int = 0
    failed_connections: int = 0
    slow_queries: int = 0
    query_times: List[float] = field(default_factory=list)
    last_health_check: Optional[datetime] = None
    health_check_failures: int = 0
    
    def record_session_start(self):
        self.total_sessions_created += 1
        self.active_sessions += 1
    
    def record_session_end(self):
        self.active_sessions = max(0, self.active_sessions - 1)
    
    def record_commit(self):
        self.total_commits += 1
    
    def record_rollback(self):
        self.total_rollbacks += 1
    
    def record_query_time(self, duration: float, slow_threshold: float = 1.0):
        self.query_times.append(duration)
        if duration > slow_threshold:
            self.slow_queries += 1
        if len(self.query_times) > 1000:
            self.query_times = self.query_times[-1000:]
    
    def record_health_check(self, success: bool):
        self.last_health_check = datetime.utcnow()
        if not success:
            self.health_check_failures += 1
    
    def get_average_query_time(self) -> float:
        if not self.query_times:
            return 0.0
        return sum(self.query_times) / len(self.query_times)
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_sessions": self.total_sessions_created,
            "active_sessions": self.active_sessions,
            "total_commits": self.total_commits,
            "total_rollbacks": self.total_rollbacks,
            "rollback_rate": self.total_rollbacks / max(1, self.total_transactions),
            "failed_connections": self.failed_connections,
            "slow_queries": self.slow_queries,
            "avg_query_time_ms": self.get_average_query_time() * 1000,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "health_check_failures": self.health_check_failures,
        }


class DatabaseService:
    """
    Centralized database connection and session management.
    
    Provides async context managers for transactional and non-transactional
    database access. Handles connection pooling, health checks, and initialization.
    
    ENHANCED FEATURES (maintains 100% backward compatibility):
    - Comprehensive connection metrics and monitoring
    - Query timeout enforcement
    - Session leak detection
    - Enhanced error context and logging
    - Pool status inspection
    - Background health monitoring
    - Graceful degradation
    - LogContext integration for audit trails (RIKI LAW Article II)
    
    Architecture:
        - Single async engine with connection pooling
        - Session factory for creating isolated sessions
        - Automatic transaction management via context managers
        - Retry logic on initialization failure
        - Connection and query performance metrics
    
    Usage:
        # Transaction (auto-commit on success)
        >>> async with DatabaseService.get_transaction() as session:
        ...     player = await session.get(Player, discord_id, with_for_update=True)
        ...     player.rikis += 1000
        
        # Read-only (no auto-commit)
        >>> async with DatabaseService.get_session() as session:
        ...     result = await session.execute(select(Player))
    
    Thread Safety:
        All methods are async-safe. Each session is isolated per coroutine.
    """
    
    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker] = None
    _health_check_query: str = "SELECT 1"
    _metrics: Optional[ConnectionMetrics] = None
    _is_healthy: bool = False
    _health_check_task: Optional[asyncio.Task] = None
    _shutdown_event: asyncio.Event = asyncio.Event()
    _initialization_lock: asyncio.Lock = asyncio.Lock()
    
    # Configuration
    _query_timeout: int = 30  # seconds
    _statement_timeout: int = 30000  # milliseconds
    _enable_metrics: bool = True
    _health_check_interval: int = 60  # seconds
    
    @classmethod
    async def initialize(cls, max_retries: int = 3, retry_delay: int = 5) -> None:
        """
        Initialize database engine and session factory.
        
        Args:
            max_retries: Number of connection attempts before failing
            retry_delay: Seconds to wait between retry attempts
        
        Raises:
            Exception: If initialization fails after all retries
        """
        async with cls._initialization_lock:
            if cls._engine is not None:
                logger.warning("DatabaseService already initialized")
                return
            
            # Initialize metrics
            if cls._enable_metrics:
                cls._metrics = ConnectionMetrics()
            
            for attempt in range(1, max_retries + 1):
                try:
                    pool_class = NullPool if Config.is_testing() else QueuePool
                    
                    cls._engine = create_async_engine(
                        Config.DATABASE_URL,
                        echo=Config.DATABASE_ECHO,
                        poolclass=pool_class,
                        pool_size=Config.DATABASE_POOL_SIZE if pool_class == QueuePool else None,
                        max_overflow=Config.DATABASE_MAX_OVERFLOW if pool_class == QueuePool else None,
                        pool_pre_ping=True,
                        pool_recycle=Config.DATABASE_POOL_RECYCLE,
                        pool_timeout=30,  # Connection checkout timeout
                        connect_args={
                            "timeout": cls._query_timeout,
                            "command_timeout": cls._query_timeout,
                        } if "postgresql" in Config.DATABASE_URL else {},
                    )
                    
                    # Set up connection event listeners for metrics
                    if cls._metrics and pool_class == QueuePool:
                        @event.listens_for(cls._engine.sync_engine, "connect")
                        def receive_connect(dbapi_conn, connection_record):
                            logger.debug("New database connection established")
                        
                        @event.listens_for(cls._engine.sync_engine, "close")
                        def receive_close(dbapi_conn, connection_record):
                            logger.debug("Database connection closed")
                    
                    cls._session_factory = async_sessionmaker(
                        cls._engine,
                        class_=AsyncSession,
                        expire_on_commit=False,
                        autocommit=False,
                        autoflush=False,
                    )
                    
                    # Initial health check
                    if not await cls.health_check():
                        raise RuntimeError("Initial health check failed")
                    
                    cls._is_healthy = True
                    
                    # Start background health monitoring
                    if cls._health_check_interval > 0:
                        cls._health_check_task = asyncio.create_task(
                            cls._background_health_check()
                        )
                    
                    logger.info(f"DatabaseService initialized successfully on attempt {attempt}")
                    return
                    
                except Exception as e:
                    if cls._metrics:
                        cls._metrics.failed_connections += 1
                    
                    logger.error(
                        f"Failed to initialize DatabaseService (attempt {attempt}/{max_retries}): {e}",
                        exc_info=True
                    )
                    
                    if attempt < max_retries:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.critical("DatabaseService initialization failed after all retries")
                        raise
    
    @classmethod
    async def close(cls) -> None:
        """
        Close all database connections and dispose of engine.
        
        Alias for shutdown() for backward compatibility with bot.py.
        """
        await cls.shutdown()
    
    @classmethod
    async def shutdown(cls) -> None:
        """Close all database connections and dispose of engine."""
        cls._shutdown_event.set()
        
        # Cancel health check task
        if cls._health_check_task:
            cls._health_check_task.cancel()
            try:
                await cls._health_check_task
            except asyncio.CancelledError:
                pass
        
        if cls._engine is None:
            return
        
        try:
            await cls._engine.dispose()
            cls._engine = None
            cls._session_factory = None
            cls._is_healthy = False
            
            logger.info("DatabaseService shutdown successfully")
            
            # Log final metrics
            if cls._metrics:
                logger.info(f"Final database metrics: {cls._metrics.get_summary()}")
                cls._metrics = None
            
        except Exception as e:
            logger.error(f"Error during DatabaseService shutdown: {e}", exc_info=True)
    
    @classmethod
    async def health_check(cls) -> bool:
        """
        Verify database connectivity with a simple query.
        
        Returns:
            True if database is accessible, False otherwise
        """
        if cls._engine is None:
            return False
        
        try:
            async with cls._engine.connect() as conn:
                await conn.execute(text(cls._health_check_query))
            
            if cls._metrics:
                cls._metrics.record_health_check(success=True)
            
            cls._is_healthy = True
            return True
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            
            if cls._metrics:
                cls._metrics.record_health_check(success=False)
            
            cls._is_healthy = False
            return False
    
    @classmethod
    async def _background_health_check(cls):
        """Background task for periodic health checks."""
        while not cls._shutdown_event.is_set():
            try:
                await asyncio.sleep(cls._health_check_interval)
                await cls.health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background health check: {e}")
    
    @classmethod
    @property
    def is_healthy(cls) -> bool:
        """Check if database connection is healthy."""
        return cls._is_healthy
    
    @classmethod
    @asynccontextmanager
    async def get_session(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session without automatic commit.
        
        Use for read-only queries or when manual transaction control is needed.
        Session is automatically closed on context exit.
        
        ENHANCED: Automatically sets database context in logs for audit trail.
        
        Yields:
            AsyncSession instance
        
        Raises:
            RuntimeError: If DatabaseService not initialized
        
        Example:
            >>> async with DatabaseService.get_session() as session:
            ...     players = await session.execute(select(Player))
            ...     # Logs will show "database_operation: read"
        """
        if cls._session_factory is None:
            raise RuntimeError("DatabaseService not initialized")
        
        if cls._metrics:
            cls._metrics.record_session_start()
        
        # Set database context for logging - RIKI LAW Article II
        set_log_context(database_operation="read")
        
        start_time = time.time()
        async with cls._session_factory() as session:
            try:
                # Set statement timeout for PostgreSQL
                if "postgresql" in Config.DATABASE_URL:
                    await session.execute(
                        text(f"SET statement_timeout = {cls._statement_timeout}")
                    )
                
                yield session
                
            except OperationalError as e:
                logger.error(
                    f"Database operational error in session: {e}",
                    exc_info=True,
                    extra={"error_type": "OperationalError", "operation": "read"}
                )
                await session.rollback()
                cls._is_healthy = False
                raise
                
            except DBAPIError as e:
                logger.error(
                    f"Database API error in session: {e}",
                    exc_info=True,
                    extra={"error_type": "DBAPIError", "operation": "read"}
                )
                await session.rollback()
                raise
                
            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Database session error: {e}",
                    exc_info=True,
                    extra={"operation": "read"}
                )
                raise
                
            finally:
                duration = time.time() - start_time
                
                if cls._metrics:
                    cls._metrics.record_query_time(duration)
                    cls._metrics.record_session_end()
                
                await session.close()
                
                if duration > 5.0:  # Log slow sessions
                    logger.warning(
                        f"Slow read session: {duration:.2f}s",
                        extra={"duration_seconds": duration, "operation": "read"}
                    )
    
    @classmethod
    @asynccontextmanager
    async def get_transaction(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session with automatic commit on success.
        
        Use for all write operations (RIKI LAW Article I.6).
        Transaction automatically commits on clean exit, rolls back on exception.
        
        ENHANCED: Automatically sets database context in logs for audit trail.
        
        Yields:
            AsyncSession instance
        
        Raises:
            RuntimeError: If DatabaseService not initialized
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     player = await session.get(Player, discord_id, with_for_update=True)
            ...     player.rikis += 1000
            ...     # Auto-commits here
            ...     # Logs show "database_operation: transaction" with commit status
        """
        if cls._session_factory is None:
            raise RuntimeError("DatabaseService not initialized")
        
        if cls._metrics:
            cls._metrics.record_session_start()
            cls._metrics.total_transactions += 1
        
        # Set database context for logging - RIKI LAW Article II
        set_log_context(database_operation="transaction")
        
        start_time = time.time()
        committed = False
        
        async with cls._session_factory() as session:
            try:
                # Set statement timeout for PostgreSQL
                if "postgresql" in Config.DATABASE_URL:
                    await session.execute(
                        text(f"SET statement_timeout = {cls._statement_timeout}")
                    )
                
                yield session
                await session.commit()
                committed = True
                
                if cls._metrics:
                    cls._metrics.record_commit()
                
                logger.debug("Transaction committed successfully")
                
            except OperationalError as e:
                logger.error(
                    f"Database operational error in transaction: {e}",
                    exc_info=True,
                    extra={
                        "error_type": "OperationalError",
                        "operation": "transaction",
                        "committed": committed
                    }
                )
                await session.rollback()
                
                if cls._metrics:
                    cls._metrics.record_rollback()
                
                cls._is_healthy = False
                raise
                
            except DBAPIError as e:
                logger.error(
                    f"Database API error in transaction: {e}",
                    exc_info=True,
                    extra={
                        "error_type": "DBAPIError",
                        "operation": "transaction",
                        "committed": committed
                    }
                )
                await session.rollback()
                
                if cls._metrics:
                    cls._metrics.record_rollback()
                
                raise
                
            except Exception as e:
                await session.rollback()
                
                if cls._metrics:
                    cls._metrics.record_rollback()
                
                logger.error(
                    f"Transaction rolled back: {e}",
                    exc_info=True,
                    extra={"operation": "transaction", "committed": committed}
                )
                raise
                
            finally:
                duration = time.time() - start_time
                
                if cls._metrics:
                    cls._metrics.record_query_time(duration)
                    cls._metrics.record_session_end()
                
                await session.close()
                
                if duration > 5.0:  # Log slow transactions
                    logger.warning(
                        f"Slow transaction ({'committed' if committed else 'rolled back'}): "
                        f"{duration:.2f}s",
                        extra={
                            "duration_seconds": duration,
                            "operation": "transaction",
                            "committed": committed
                        }
                    )
    
    @classmethod
    def get_metrics(cls) -> Optional[ConnectionMetrics]:
        """
        Get database connection metrics.
        
        Returns:
            ConnectionMetrics instance or None if metrics disabled
        """
        return cls._metrics
    
    @classmethod
    def get_metrics_summary(cls) -> Dict[str, Any]:
        """
        Get formatted metrics summary.
        
        Returns:
            Dictionary with all metrics, or empty dict if metrics disabled
        """
        if cls._metrics:
            return cls._metrics.get_summary()
        return {}
    
    @classmethod
    def get_pool_status(cls) -> Dict[str, Any]:
        """
        Get connection pool status information.
        
        Returns:
            Dictionary with pool statistics
        """
        if cls._engine is None or not isinstance(cls._engine.pool, QueuePool):
            return {"pool_type": "NullPool or not initialized"}
        
        pool: QueuePool = cls._engine.pool
        
        return {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "checked_in": pool.checkedin(),
            "pool_timeout": 30,
            "max_overflow": Config.DATABASE_MAX_OVERFLOW,
        }
    
    @classmethod
    async def create_tables(cls) -> None:
        """
        Create all database tables from SQLModel definitions.
        
        Idempotent - safe to call multiple times.
        
        Raises:
            RuntimeError: If DatabaseService not initialized
        """
        from sqlmodel import SQLModel
        from modules import (
            Player, Maiden, MaidenBase, GameConfig,
            DailyQuest, LeaderboardSnapshot, TransactionLog
        )
        
        if cls._engine is None:
            raise RuntimeError("DatabaseService not initialized")
        
        try:
            async with cls._engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            logger.info("Database tables created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create tables: {e}", exc_info=True)
            raise
    
    @classmethod
    async def drop_tables(cls) -> None:
        """
        Drop all database tables.
        
        DESTRUCTIVE OPERATION - Only allowed in non-production environments.
        
        Raises:
            RuntimeError: If called in production environment
        """
        from sqlmodel import SQLModel
        
        if cls._engine is None:
            raise RuntimeError("DatabaseService not initialized")
        
        if Config.is_production():
            raise RuntimeError("Cannot drop tables in production environment")
        
        try:
            async with cls._engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.drop_all)
            logger.warning("Database tables dropped")
            
        except Exception as e:
            logger.error(f"Failed to drop tables: {e}", exc_info=True)
            raise





