"""
Maiden Module - LES 2025 Compliant Services
============================================

This module provides all maiden-related services following the Lumen Engineering
Standard (LES) 2025.

Services
--------
- MaidenService: Player-owned maiden inventory and stack management
- MaidenBaseService: Maiden templates, gacha pools, power calculations

All services are transaction-safe, config-driven, and event-driven.
"""

from .base_service import MaidenBaseService
from .service import MaidenService

__all__ = [
    "MaidenService",
    "MaidenBaseService",
]
