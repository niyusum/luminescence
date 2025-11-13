"""
Event log context helpers for Lumen EventBus.
"""

from __future__ import annotations

from typing import Any, Dict

from src.core.logging.logger import set_log_context


def apply_event_log_context(event_name: str, payload: Dict[str, Any]) -> None:
    """
    Apply event-related fields to LogContext for structured logging.

    This is best-effort; failures are swallowed to avoid breaking the bus.
    """
    try:
        set_log_context(
            event_name=event_name,
            event_keys=list(payload.keys()),
        )
    except Exception:
        # Never let logging context setup break event dispatch.
        return
