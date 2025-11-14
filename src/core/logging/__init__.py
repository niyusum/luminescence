"""
Logging infrastructure and utilities.

Provides structured logging with context tracking and log management.
"""

from src.core.logging.logger import (
    LogContext,
    LoggerConfig,
    clear_log_context,
    get_logger,
    set_log_context,
    setup_logging,
    shutdown_logging,
)

__all__ = [
    # Logger setup
    "setup_logging",
    "shutdown_logging",
    "get_logger",
    # Context management
    "LogContext",
    "set_log_context",
    "clear_log_context",
    # Configuration
    "LoggerConfig",
]
