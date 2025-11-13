"""
Lumen Logging Subsystem (2025)

Purpose
-------
Provide a production-grade, hybrid logging system with:

- Structured JSON logs as the single source of truth.
- LogContext-based propagation of request context via ContextVars.
- Correlation IDs for traceability across services and events.
- Component-aware fields derived from logger names and context.
- Async-safe logging via a QueueHandler + QueueListener architecture.
- Hybrid output:
  - Console handler (JSON in production, colored human text in dev).
  - Minimal rotating file handler with ~24h retention for backup.

Responsibilities
----------------
- Initialize and configure the global logging stack.
- Enrich all log records with contextual fields:
  - user_id, guild_id, command, correlation_id, request_id, component, operation.
- Emit structured logs in JSON format suitable for aggregation systems.
- Avoid blocking the asyncio event loop with synchronous file I/O.
- Provide simple helper APIs:
  - get_logger()
  - LogContext (sync + async context manager)
  - set_log_context() / clear_log_context()

Lumen 2025 Compliance
---------------------
- Logs are structured, JSON-formatted, and environment-aware.
- Context propagation via LogContext + ContextVars.
- Correlation IDs attached to every contextualized request.
- Component-aware metadata derived from logger name and context.
- Async-safe logging using a log queue and background listener thread.
- Single source of truth for log schema; no duplicated formatter logic.
- Minimal, time-based file retention (~24h) to avoid disk bloat.

Design Decisions
----------------
- Hybrid model (Option C):
  - Console logging is the primary sink (JSON in prod, colored in dev).
  - A TimedRotatingFileHandler maintains a small rolling window of logs
    as a local backup (configured for daily rotation with minimal history).
- JSONFormatter is the canonical representation; console/dev formatter is
  a human-friendly view for developers only.
- ContextFilter uses ContextVars to safely enrich logs in async code.
- Extra fields passed via `logger.info("msg", extra={...})` are merged into
  the JSON payload while avoiding duplication of standard attributes.

Dependencies
------------
- src.core.config.config.Config: environment, log level, logs directory, and flags.
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger
from logging.handlers import (
    QueueHandler,
    QueueListener,
    TimedRotatingFileHandler,
)
from pathlib import Path
from typing import Any, Dict, Optional, Mapping

from src.core.config.config import Config


# ============================================================================
# Request / Operation Context (ContextVars)
# ============================================================================

_request_context: ContextVar[Dict[str, Any]] = ContextVar(
    "request_context",
    default={},
)


# ============================================================================
# Config / Environment
# ============================================================================


@dataclass(frozen=True, slots=True)
class LoggerConfig:
    """Configuration for the logging subsystem."""

    # Console + file format strings for non-JSON dev output.
    CONSOLE_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
    FILE_FORMAT: str = (
        "%(asctime)s | %(levelname)-8s | %(name)-30s "
        "| [%(user_id)s:%(guild_id)s] | %(message)s"
    )
    DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # Timed rotating file retention.
    # We use a daily rotation with minimal backup to approximate ~24h window.
    DAILY_BASENAME: str = "lumen_daily.json.log"
    DAILY_BACKUP_COUNT: int = 1  # keep only the most recent rolled file

    @property
    def environment(self) -> str:
        env = getattr(Config, "ENVIRONMENT", "development")
        return str(env).lower()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def logs_dir(self) -> Path:
        return Config.LOGS_DIR

    @property
    def log_level(self) -> int:
        level_name = getattr(Config, "LOG_LEVEL", "INFO")
        if not isinstance(level_name, str):
            level_name = "INFO"
        return getattr(logging, level_name.upper(), logging.INFO)

    @property
    def use_json(self) -> bool:
        # In production we always prefer JSON. In dev, Config may override.
        try:
            json_flag = Config.get("LOG_JSON", None)
        except Exception:
            json_flag = None

        if json_flag is None:
            return self.is_production
        return bool(json_flag)

    @property
    def use_colors(self) -> bool:
        # Colors only in non-production, TTY consoles, and when not using JSON.
        if self.is_production or self.use_json:
            return False
        try:
            colors_flag = Config.get("LOG_COLORS", True)
        except Exception:
            colors_flag = True
        return bool(colors_flag) and sys.stdout.isatty()


LOGGER_CONFIG = LoggerConfig()


# ============================================================================
# Filters & Formatters
# ============================================================================


class ContextFilter(logging.Filter):
    """
    Inject ContextVar-based context into log records.

    Fields added:
    - user_id
    - guild_id
    - command
    - correlation_id
    - request_id
    - component
    - operation

    Values default to "N/A" when absent.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        context: Dict[str, Any] = _request_context.get({})

        record.user_id = context.get("user_id", "N/A")
        record.guild_id = context.get("guild_id", "N/A")
        record.command = context.get("command", "N/A")

        # Correlation ID + request ID (aliases for traceability).
        correlation_id = context.get("correlation_id") or context.get("request_id")
        if not correlation_id:
            correlation_id = "N/A"
        record.correlation_id = correlation_id
        record.request_id = context.get("request_id", correlation_id)

        # Component / operation for better observability.
        # Component defaults to the top-level logger namespace.
        record.component = context.get("component") or record.name.split(".", 1)[0]
        record.operation = context.get("operation", "N/A")

        return True


class ColoredFormatter(logging.Formatter):
    """
    Colored console formatter for development readability.

    Colors:
        DEBUG    - Gray
        INFO     - Blue
        WARNING  - Yellow
        ERROR    - Red
        CRITICAL - Red + Bold
    """

    COLORS: Dict[str, str] = {
        "DEBUG": "\033[90m",         # Gray
        "INFO": "\033[94m",          # Blue
        "WARNING": "\033[93m",       # Yellow
        "ERROR": "\033[91m",         # Red
        "CRITICAL": "\033[91m\033[1m",  # Red + Bold
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        original_levelname = record.levelname
        color_prefix = self.COLORS.get(original_levelname, "")
        color_reset = self.COLORS["RESET"] if color_prefix else ""

        if color_prefix:
            record.levelname = f"{color_prefix}{original_levelname}{color_reset}"

        try:
            result = super().format(record)
        finally:
            record.levelname = original_levelname

        return result


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Output includes:
    - timestamp (UTC, ISO-8601)
    - level
    - logger
    - message
    - module, function, line
    - component, operation
    - user_id, guild_id, command
    - correlation_id, request_id
    - exception (if any)
    - extra fields (from `extra={...}` in logger calls)
    """

    # Attributes considered "standard" and removed from the `extra` payload.
    STANDARD_ATTRS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
    }

    CONTEXT_ATTRS = {
        "user_id",
        "guild_id",
        "command",
        "correlation_id",
        "request_id",
        "component",
        "operation",
    }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        timestamp = datetime.now(timezone.utc).isoformat()

        log_data: Dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Inject core context fields if present and meaningful.
        for attr in self.CONTEXT_ATTRS:
            value = getattr(record, attr, None)
            if value is not None and value != "N/A":
                log_data[attr] = value

        # Exception info.
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Collect all non-standard attributes as "extra".
        extra: Dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in self.STANDARD_ATTRS or key in self.CONTEXT_ATTRS:
                continue
            if key.startswith("_"):
                continue
            # Avoid duplicating fields we already included explicitly.
            if key in {"levelname", "name", "message", "asctime"}:
                continue
            extra[key] = value

        if extra:
            log_data["extra"] = extra

        return json.dumps(log_data, ensure_ascii=False)


# ============================================================================
# Global Queue Listener (async-safe logging)
# ============================================================================

_queue_listener: Optional[QueueListener] = None


def _build_console_handler() -> logging.Handler:
    """Create the console handler based on environment and configuration."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(LOGGER_CONFIG.log_level)

    if LOGGER_CONFIG.use_json:
        handler.setFormatter(JSONFormatter())
    elif LOGGER_CONFIG.use_colors:
        handler.setFormatter(
            ColoredFormatter(
                fmt=LOGGER_CONFIG.CONSOLE_FORMAT,
                datefmt=LOGGER_CONFIG.DATE_FORMAT,
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt=LOGGER_CONFIG.CONSOLE_FORMAT,
                datefmt=LOGGER_CONFIG.DATE_FORMAT,
            )
        )

    return handler


def _build_daily_file_handler() -> logging.Handler:
    """
    Create a daily rotating file handler with minimal retention.

    - Rotates at midnight (UTC).
    - Keeps only a small number of backups (configured as ~24h window).
    - Always uses JSONFormatter to keep file output structured.
    """
    LOGGER_CONFIG.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = LOGGER_CONFIG.logs_dir / LOGGER_CONFIG.DAILY_BASENAME

    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=LOGGER_CONFIG.DAILY_BACKUP_COUNT,
        encoding="utf-8",
        utc=True,
    )
    handler.setLevel(LOGGER_CONFIG.log_level)
    handler.setFormatter(JSONFormatter())
    return handler


def setup_logging() -> None:
    """
    Configure global logging for the Lumen application.

    Features
    --------
    - Async-safe logging via QueueHandler/QueueListener.
    - Console handler:
        - JSON in production for log aggregation.
        - Colored human-readable in development.
    - Minimal daily rotating file handler with ~24h retention.
    - ContextFilter for LogContext propagation.
    - Suppresses noisy third-party loggers at WARNING+.
    """
    global _queue_listener

    root_logger = logging.getLogger()
    # Avoid re-initialization if already configured.
    if getattr(root_logger, "_lumen_logging_initialized", False):
        return

    root_logger.setLevel(LOGGER_CONFIG.log_level)
    root_logger.handlers.clear()
    root_logger.filters.clear()

    # Context enrichment filter.
    root_logger.addFilter(ContextFilter())

    # Build actual output handlers.
    console_handler = _build_console_handler()
    daily_handler = _build_daily_file_handler()

    # Queue listener for async-safe logging.
    log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue(-1)
    _queue_listener = QueueListener(
        log_queue,
        console_handler,
        daily_handler,
        respect_handler_level=True,
    )
    _queue_listener.start()

    queue_handler = QueueHandler(log_queue)
    queue_handler.setLevel(LOGGER_CONFIG.log_level)

    root_logger.addHandler(queue_handler)

    # Suppress noisy third-party loggers.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Mark as initialized.
    setattr(root_logger, "_lumen_logging_initialized", True)

    # Log initialization summary using our own logger.
    init_logger = logging.getLogger(__name__)
    init_logger.info(
        "Logging initialized",
        extra={
            "environment": LOGGER_CONFIG.environment,
            "log_level": logging.getLevelName(LOGGER_CONFIG.log_level),
            "json": LOGGER_CONFIG.use_json,
            "colors": LOGGER_CONFIG.use_colors,
            "logs_dir": str(LOGGER_CONFIG.logs_dir),
            "daily_basename": LOGGER_CONFIG.DAILY_BASENAME,
            "daily_backup_count": LOGGER_CONFIG.DAILY_BACKUP_COUNT,
        },
    )


def shutdown_logging() -> None:
    """
    Stop the QueueListener and flush/close handlers.

    Should be called on graceful application shutdown, if possible.
    """
    global _queue_listener
    if _queue_listener is not None:
        _queue_listener.stop()
        _queue_listener = None


# ============================================================================
# Public Logger API
# ============================================================================


def get_logger(name: str) -> Logger:
    """
    Return a configured logger for the given module/component.

    Parameters
    ----------
    name:
        Module or component name (typically __name__).

    Returns
    -------
    logging.Logger
        Logger instance with full Config + LogContext integration.

    Examples
    --------
    >>> logger = get_logger(__name__)
    >>> logger.info("Service initialized", extra={"component": "player_service"})
    """
    return logging.getLogger(name)


# ============================================================================
# LogContext Helpers
# ============================================================================


class LogContext:
    """
    Context manager for setting request context in logs.

    Injects user, guild, command, component, operation and correlation_id
    into all log records created within its scope.

    Example
    -------
    >>> async with LogContext(
    ...     user_id=123,
    ...     guild_id=456,
    ...     command="/fuse",
    ...     component="fusion_service",
    ...     operation="execute_fusion",
    ... ):
    ...     logger.info("Starting fusion")
    ...     await fusion_service.execute()
    ...     logger.info("Fusion complete")
    """

    def __init__(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        command: Optional[str] = None,
        component: Optional[str] = None,
        operation: Optional[str] = None,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        **extra: Any,
    ) -> None:
        # Generate a short correlation ID if none is provided.
        if not correlation_id and not request_id:
            correlation_id = self._generate_correlation_id()

        effective_correlation_id = correlation_id or request_id or self._generate_correlation_id()

        self.context: Dict[str, Any] = {
            "user_id": str(user_id) if user_id is not None else "N/A",
            "guild_id": str(guild_id) if guild_id is not None else "N/A",
            "command": command or "N/A",
            "component": component,
            "operation": operation,
            "correlation_id": effective_correlation_id,
            "request_id": request_id or effective_correlation_id,
            **extra,
        }
        self._token: Optional[object] = None

    @staticmethod
    def _generate_correlation_id() -> str:
        """Generate a short correlation ID for tracing."""
        return str(uuid.uuid4())[:8]

    def __enter__(self) -> "LogContext":
        self._token = _request_context.set(self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._token is not None:
            _request_context.reset(self._token)

    async def __aenter__(self) -> "LogContext":
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)


def set_log_context(
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    command: Optional[str] = None,
    component: Optional[str] = None,
    operation: Optional[str] = None,
    correlation_id: Optional[str] = None,
    request_id: Optional[str] = None,
    **extra: Any,
) -> None:
    """
    Imperatively set log context for the current async task.

    Useful when a context manager cannot be used but contextual logging is still
    required.

    Parameters
    ----------
    user_id:
        Discord user ID.
    guild_id:
        Discord guild ID.
    command:
        Command name (e.g. "/fuse").
    component:
        Logical component or service name.
    operation:
        Operation or workflow name.
    correlation_id:
        Correlation ID for cross-service tracing.
    request_id:
        Request ID; if provided, will be mirrored to correlation_id if missing.
    extra:
        Additional key/value pairs to attach to the log context.
    """
    current: Dict[str, Any] = _request_context.get({}).copy()

    if user_id is not None:
        current["user_id"] = str(user_id)
    if guild_id is not None:
        current["guild_id"] = str(guild_id)
    if command is not None:
        current["command"] = command
    if component is not None:
        current["component"] = component
    if operation is not None:
        current["operation"] = operation

    if correlation_id:
        current["correlation_id"] = correlation_id
    if request_id:
        current["request_id"] = request_id
        if "correlation_id" not in current:
            current["correlation_id"] = request_id

    current.update(extra)
    _request_context.set(current)


def clear_log_context() -> None:
    """Clear log context for the current async task."""
    _request_context.set({})


# Initialize logging on module import.
setup_logging()
