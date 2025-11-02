"""
Production-grade logging system for RIKI RPG Bot.

Features:
- Rotating file handlers (size + time based)
- Structured JSON logging for production
- Context propagation (user_id, guild_id, command)
- Colored console output for development
- Automatic log cleanup (30-day retention)
- Environment-based configuration

RIKI LAW Compliance:
- Audit logging for all state changes (Article II)
- Discord context in all logs (Article II)
- Graceful degradation (Article IX)
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any

from src.core.config import Config


# Context variables for request tracing
_request_context: ContextVar[Dict[str, Any]] = ContextVar('request_context', default={})


class ContextFilter(logging.Filter):
    """
    Inject context variables into log records.
    
    Adds user_id, guild_id, command, request_id from async context
    to every log record for distributed tracing.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        context = _request_context.get({})
        
        # Add context fields to record
        record.user_id = context.get('user_id', 'N/A')
        record.guild_id = context.get('guild_id', 'N/A')
        record.command = context.get('command', 'N/A')
        record.request_id = context.get('request_id', 'N/A')
        
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
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[90m',      # Gray
        'INFO': '\033[94m',       # Blue
        'WARNING': '\033[93m',    # Yellow
        'ERROR': '\033[91m',      # Red
        'CRITICAL': '\033[91m\033[1m',  # Red + Bold
        'RESET': '\033[0m'
    }
    
    def format(self, record: logging.LogRecord) -> str:
        # Add color to levelname
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        
        # Format with parent formatter
        result = super().format(record)
        
        # Reset levelname for other handlers
        record.levelname = levelname
        
        return result


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging in production.
    
    Outputs logs as JSON for easy parsing by log aggregators
    (Datadog, Splunk, CloudWatch, etc.)
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add context fields if present
        if hasattr(record, 'user_id') and record.user_id != 'N/A':
            log_data['user_id'] = record.user_id
        if hasattr(record, 'guild_id') and record.guild_id != 'N/A':
            log_data['guild_id'] = record.guild_id
        if hasattr(record, 'command') and record.command != 'N/A':
            log_data['command'] = record.command
        if hasattr(record, 'request_id') and record.request_id != 'N/A':
            log_data['request_id'] = record.request_id
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields from logger.info("msg", extra={...})
        if hasattr(record, 'extra'):
            log_data['extra'] = record.extra
        
        return json.dumps(log_data)


class LoggerConfig:
    """Configuration for logging system."""
    
    # Rotation settings
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file
    BACKUP_COUNT = 5  # Keep 5 backup files
    RETENTION_DAYS = 30  # Delete logs older than 30 days
    
    # Format strings
    CONSOLE_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s'
    FILE_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-25s | [%(user_id)s:%(guild_id)s] | %(message)s'
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
    
    # Environment detection
    IS_PRODUCTION = Config.ENVIRONMENT == 'production'
    USE_JSON = IS_PRODUCTION or Config.get('LOG_JSON', False)
    USE_COLORS = not IS_PRODUCTION and sys.stdout.isatty()


def setup_logging() -> None:
    """
    Configure application-wide logging with production features.
    
    Features:
    - Rotating file handlers (10MB per file, 5 backups)
    - Daily log files with automatic cleanup (30-day retention)
    - Structured JSON logging in production
    - Colored console output in development
    - Context injection for distributed tracing
    
    Called automatically on module import.
    """
    log_level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
    
    # Create logs directory
    Config.LOGS_DIR.mkdir(exist_ok=True)
    
    # Clean up old logs
    _cleanup_old_logs()
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers to prevent duplicates
    root_logger.handlers.clear()
    
    # Add context filter to all logs
    context_filter = ContextFilter()
    root_logger.addFilter(context_filter)
    
    # === CONSOLE HANDLER ===
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    if LoggerConfig.USE_COLORS:
        console_formatter = ColoredFormatter(
            fmt=LoggerConfig.CONSOLE_FORMAT,
            datefmt=LoggerConfig.DATE_FORMAT
        )
    else:
        console_formatter = logging.Formatter(
            fmt=LoggerConfig.CONSOLE_FORMAT,
            datefmt=LoggerConfig.DATE_FORMAT
        )
    
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # === FILE HANDLER (Rotating by size) ===
    log_file = Config.LOGS_DIR / "riki.log"
    
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=LoggerConfig.MAX_FILE_SIZE,
        backupCount=LoggerConfig.BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    
    if LoggerConfig.USE_JSON:
        file_formatter = JSONFormatter()
    else:
        file_formatter = logging.Formatter(
            fmt=LoggerConfig.FILE_FORMAT,
            datefmt=LoggerConfig.DATE_FORMAT
        )
    
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # === DAILY FILE HANDLER (Rotating by time) ===
    daily_log_file = Config.LOGS_DIR / "riki_daily.log"
    
    daily_handler = TimedRotatingFileHandler(
        daily_log_file,
        when='midnight',
        interval=1,
        backupCount=LoggerConfig.RETENTION_DAYS,
        encoding='utf-8'
    )
    daily_handler.setLevel(log_level)
    daily_handler.setFormatter(file_formatter)
    daily_handler.suffix = "%Y%m%d"  # Format: riki_daily.log.20250102
    root_logger.addHandler(daily_handler)
    
    # === ERROR-ONLY FILE HANDLER ===
    error_log_file = Config.LOGS_DIR / "errors.log"
    
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=LoggerConfig.MAX_FILE_SIZE,
        backupCount=LoggerConfig.BACKUP_COUNT,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)
    
    # === SUPPRESS NOISY LOGGERS ===
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
    logging.getLogger('discord.gateway').setLevel(logging.WARNING)
    logging.getLogger('discord.client').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    # Log initialization
    logger = logging.getLogger(__name__)
    logger.info(
        f"🎯 Logging initialized: level={Config.LOG_LEVEL}, "
        f"json={LoggerConfig.USE_JSON}, colors={LoggerConfig.USE_COLORS}"
    )


def _cleanup_old_logs() -> None:
    """
    Remove log files older than RETENTION_DAYS.
    
    Prevents disk space issues from log accumulation.
    Runs on every bot startup.
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=LoggerConfig.RETENTION_DAYS)
        deleted_count = 0
        
        for log_file in Config.LOGS_DIR.glob("*.log*"):
            # Skip current log files
            if log_file.name in ['riki.log', 'riki_daily.log', 'errors.log']:
                continue
            
            # Check file modification time
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff_date:
                log_file.unlink()
                deleted_count += 1
        
        if deleted_count > 0:
            logger = logging.getLogger(__name__)
            logger.info(f"🗑️  Cleaned up {deleted_count} old log file(s)")
    
    except Exception as e:
        # Don't fail startup if cleanup fails
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to cleanup old logs: {e}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the given module name.
    
    Args:
        name: Module name (typically __name__)
    
    Returns:
        Configured logger instance
    
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Service initialized")
    """
    return logging.getLogger(name)


class LogContext:
    """
    Context manager for setting request context in logs.
    
    Allows tracing requests across multiple log statements
    by injecting user_id, guild_id, command into every log.
    
    Example:
        >>> async with LogContext(user_id=123, guild_id=456, command="/fuse"):
        ...     logger.info("Starting fusion")  # Includes user_id, guild_id, command
        ...     await fusion_service.execute()
        ...     logger.info("Fusion complete")  # Also includes context
    """
    
    def __init__(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        command: Optional[str] = None,
        request_id: Optional[str] = None,
        **extra: Any
    ):
        self.context = {
            'user_id': str(user_id) if user_id else 'N/A',
            'guild_id': str(guild_id) if guild_id else 'N/A',
            'command': command or 'N/A',
            'request_id': request_id or self._generate_request_id(),
            **extra
        }
        self.token = None
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID for tracing."""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def __enter__(self):
        self.token = _request_context.set(self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            _request_context.reset(self.token)
    
    async def __aenter__(self):
        return self.__enter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)


def set_log_context(
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    command: Optional[str] = None,
    **extra: Any
) -> None:
    """
    Set context for current async task (alternative to LogContext manager).
    
    Useful when you can't use context manager but need context
    throughout function execution.
    
    Args:
        user_id: Discord user ID
        guild_id: Discord guild ID
        command: Command name (e.g., "/fuse")
        **extra: Additional context fields
    
    Example:
        >>> set_log_context(user_id=123, guild_id=456, command="/fuse")
        >>> logger.info("Processing command")  # Includes context
    """
    context = _request_context.get({}).copy()
    
    if user_id:
        context['user_id'] = str(user_id)
    if guild_id:
        context['guild_id'] = str(guild_id)
    if command:
        context['command'] = command
    
    context.update(extra)
    _request_context.set(context)


def clear_log_context() -> None:
    """Clear log context for current async task."""
    _request_context.set({})


# Initialize logging on module import
setup_logging()