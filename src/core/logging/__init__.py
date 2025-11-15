"""
Lumen Logging Infrastructure

Exports the structured logging subsystem, log context helpers,
and configuration interface.

This module provides:
- Production-grade JSON logging
- ContextVar-based contextual logging (`LogContext`)
- Setup and teardown helpers for the global logging system
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
    "setup_logging",
    "shutdown_logging",
    "get_logger",
    "LogContext",
    "set_log_context",
    "clear_log_context",
    "LoggerConfig",
]

