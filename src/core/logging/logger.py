"""
Lumen Logging Subsystem (2025)

Purpose
-------
Provide a production-grade, async-safe logging subsystem that is the single
source of truth for Lumen observability, offering:

- Structured JSON logs for aggregation and analysis.
- LogContext-based propagation of request/operation context via ContextVars.
- Correlation IDs and request IDs for end-to-end traceability.
- Component-aware metadata derived from logger names and explicit context.
- Async-safe logging via a QueueHandler + QueueListener architecture.
- Bounded, health-aware log queue with graceful degradation on overload.
- Hybrid output:
  - Console handler (JSON in production, colored human text in dev).
  - Minimal rotating file handler with ~24h retention for local backup.
- Lightweight internal metrics and health inspection for infra observability.

Responsibilities
----------------
- Initialize and configure the global logging stack.
- Enrich all log records with contextual fields:
  - user_id, guild_id, command
  - correlation_id, request_id
  - component, operation
- Emit structured logs in JSON format suitable for aggregation systems.
- Avoid blocking the asyncio event loop with synchronous file I/O.
- Provide simple helper APIs:
  - get_logger()
  - LogContext (sync + async context manager)
  - set_log_context() / clear_log_context()
  - get_logging_health() for infra-level health inspection.
- Degrade gracefully when the logging queue is overloaded or handlers fail.

Design Decisions
----------------
- Hybrid model:
  - Console logging is the primary sink (JSON in prod, colored in dev).
  - A TimedRotatingFileHandler maintains a small rolling window of logs
    as a local backup (configured for daily rotation with minimal history).
- JSONFormatter is the canonical representation.
- ContextFilter uses ContextVars to safely enrich logs in async code.
- Extra fields passed via `logger.info("msg", extra={...})` are merged into JSON.
- A bounded log queue provides graceful degradation during log storms.

Dependencies
------------
- src.core.config.config.Config
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger
from logging.handlers import (
    QueueHandler,
    QueueListener,
    TimedRotatingFileHandler,
)
from pathlib import Path
from typing import Any, Dict, Optional

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

    CONSOLE_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
    FILE_FORMAT: str = (
        "%(asctime)s | %(levelname)-8s | %(name)-30s "
        "| [%(user_id)s:%(guild_id)s] | %(message)s"
    )
    DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    DAILY_BASENAME: str = "lumen_daily.json.log"
    DAILY_BACKUP_COUNT: int = 1

    QUEUE_MAX_SIZE: int = 10_000

    @property
    def environment(self) -> str:
        env = getattr(Config, "ENVIRONMENT", "development")
        return str(env).lower()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def logs_dir(self) -> Path:
        return Path(Config.LOGS_DIR).resolve()

    @property
    def log_level(self) -> int:
        level_name = getattr(Config, "LOG_LEVEL", "INFO")
        if not isinstance(level_name, str):
            level_name = "INFO"
        return getattr(logging, level_name.upper(), logging.INFO)

    @property
    def use_json(self) -> bool:
        json_flag = getattr(Config, "LOG_JSON", None)
        if json_flag is None:
            return self.is_production
        return bool(json_flag)

    @property
    def use_colors(self) -> bool:
        if self.is_production or self.use_json:
            return False
        colors_flag = getattr(Config, "LOG_COLORS", True)
        return bool(colors_flag) and sys.stdout.isatty()


LOGGER_CONFIG = LoggerConfig()


# ============================================================================
# Logging Metrics / Health
# ============================================================================


@dataclass(slots=True)
class LoggingMetrics:
    records_enqueued: int = 0
    records_dropped: int = 0
    listener_errors: int = 0


@dataclass(frozen=True, slots=True)
class LoggingHealth:
    initialized: bool
    queue_size: int
    queue_max_size: int
    records_enqueued: int
    records_dropped: int
    listener_errors: int


_logging_metrics: LoggingMetrics = LoggingMetrics()
_log_queue: Optional["queue.Queue[logging.LogRecord]"] = None


# ============================================================================
# Filters & Formatters
# ============================================================================


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        context: Dict[str, Any] = _request_context.get({})

        record.user_id = context.get("user_id", "N/A")
        record.guild_id = context.get("guild_id", "N/A")
        record.command = context.get("command", "N/A")

        correlation_id = context.get("correlation_id") or context.get("request_id")
        if not correlation_id:
            correlation_id = "N/A"
        record.correlation_id = correlation_id
        record.request_id = context.get("request_id", correlation_id)

        record.component = context.get("component") or record.name.split(".", 1)[0]
        record.operation = context.get("operation", "N/A")

        return True


class ColoredFormatter(logging.Formatter):
    COLORS: Dict[str, str] = {
        "DEBUG": "\033[90m",
        "INFO": "\033[94m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "CRITICAL": "\033[91m\033[1m",
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        original = record.levelname
        prefix = self.COLORS.get(original, "")
        reset = self.COLORS["RESET"] if prefix else ""

        if prefix:
            record.levelname = f"{prefix}{original}{reset}"

        try:
            return super().format(record)
        finally:
            record.levelname = original


class JSONFormatter(logging.Formatter):
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
        created_dt = datetime.fromtimestamp(record.created, tz=timezone.utc)

        log_data: Dict[str, Any] = {
            "timestamp": created_dt.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        for attr in self.CONTEXT_ATTRS:
            value = getattr(record, attr, None)
            if value not in (None, "N/A"):
                log_data[attr] = value

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        extra: Dict[str, Any] = {}
        for key, val in record.__dict__.items():
            if key in self.STANDARD_ATTRS or key in self.CONTEXT_ATTRS:
                continue
            if key.startswith("_"):
                continue
            if key in {"levelname", "name", "message", "asctime"}:
                continue
            extra[key] = val

        if extra:
            log_data["extra"] = extra

        return json.dumps(log_data, ensure_ascii=False)


# ============================================================================
# Custom Queue Handler & Listener
# ============================================================================


class LumenQueueHandler(QueueHandler):
    def enqueue(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        global _logging_metrics
        _logging_metrics.records_enqueued += 1

        try:
            self.queue.put_nowait(record)
        except queue.Full:
            _logging_metrics.records_dropped += 1
            try:
                sys.stderr.write("Lumen logging queue full; dropping log record.\n")
            except Exception:
                pass


class LumenQueueListener(QueueListener):
    def handleError(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        global _logging_metrics
        _logging_metrics.listener_errors += 1
        try:
            sys.stderr.write("Lumen logging handler error while processing record.\n")
        except Exception:
            pass


# ============================================================================
# Global Setup
# ============================================================================

_queue_listener: Optional[QueueListener] = None


def _build_console_handler() -> logging.Handler:
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
    global _queue_listener, _logging_metrics, _log_queue

    root = logging.getLogger()

    if getattr(root, "_lumen_logging_initialized", False):
        return

    _logging_metrics = LoggingMetrics()

    root.setLevel(LOGGER_CONFIG.log_level)
    root.handlers.clear()
    root.filters.clear()

    root.addFilter(ContextFilter())

    console = _build_console_handler()
    file_handler = _build_daily_file_handler()

    _log_queue = queue.Queue(LOGGER_CONFIG.QUEUE_MAX_SIZE)

    _queue_listener = LumenQueueListener(
        _log_queue,
        console,
        file_handler,
        respect_handler_level=True,
    )
    _queue_listener.start()

    queue_handler = LumenQueueHandler(_log_queue)
    queue_handler.setLevel(LOGGER_CONFIG.log_level)

    root.addHandler(queue_handler)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    setattr(root, "_lumen_logging_initialized", True)

    log = logging.getLogger(__name__)
    log.info(
        "Logging initialized",
        extra={
            "environment": LOGGER_CONFIG.environment,
            "log_level": logging.getLevelName(LOGGER_CONFIG.log_level),
            "json": LOGGER_CONFIG.use_json,
            "colors": LOGGER_CONFIG.use_colors,
            "logs_dir": str(LOGGER_CONFIG.logs_dir),
            "queue_max_size": LOGGER_CONFIG.QUEUE_MAX_SIZE,
        },
    )


def shutdown_logging() -> None:
    global _queue_listener, _log_queue

    root = logging.getLogger()
    log = logging.getLogger(__name__)

    if not getattr(root, "_lumen_logging_initialized", False):
        return

    log.info("Shutting down logging subsystem.")

    if _queue_listener:
        try:
            _queue_listener.stop()
        except Exception:
            log.exception("Error while stopping logging queue listener.")
        finally:
            _queue_listener = None

    for handler in list(root.handlers):
        try:
            handler.flush()
        except Exception:
            log.exception("Error while flushing logging handler.")
        try:
            handler.close()
        except Exception:
            log.exception("Error while closing logging handler.")
        root.removeHandler(handler)

    root.filters.clear()
    setattr(root, "_lumen_logging_initialized", False)
    _log_queue = None


def get_logging_health() -> LoggingHealth:
    initialized = bool(getattr(logging.getLogger(), "_lumen_logging_initialized", False))

    queue_size = 0
    max_size = 0
    if _log_queue is not None:
        try:
            queue_size = _log_queue.qsize()
        except Exception:
            queue_size = -1
        max_size = _log_queue.maxsize

    return LoggingHealth(
        initialized=initialized,
        queue_size=queue_size,
        queue_max_size=max_size,
        records_enqueued=_logging_metrics.records_enqueued,
        records_dropped=_logging_metrics.records_dropped,
        listener_errors=_logging_metrics.listener_errors,
    )


# ============================================================================
# Public API
# ============================================================================


def get_logger(name: str) -> Logger:
    return logging.getLogger(name)


class LogContext:
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

        if not correlation_id and not request_id:
            correlation_id = self._generate_correlation_id()

        effective = correlation_id or request_id or self._generate_correlation_id()

        self.context: Dict[str, Any] = {
            "user_id": str(user_id) if user_id is not None else "N/A",
            "guild_id": str(guild_id) if guild_id is not None else "N/A",
            "command": command or "N/A",
            "component": component,
            "operation": operation,
            "correlation_id": effective,
            "request_id": request_id or effective,
            **extra,
        }

        self._token: Optional[Token[Dict[str, Any]]] = None

    @staticmethod
    def _generate_correlation_id() -> str:
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

    current = _request_context.get({}).copy()

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
    _request_context.set({})


# Initialize logging automatically
setup_logging()



