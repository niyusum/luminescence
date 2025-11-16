"""
Daily Module - LES 2025 Compliant
==================================

Domain: Daily quest system with streaks and resets

Services:
- QuestService: Daily quest management, progress tracking, and rewards
"""

from .quest_service import DailyQuestService

__all__ = [
    "DailyQuestService",
]
