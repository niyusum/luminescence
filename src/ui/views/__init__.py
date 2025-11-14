"""
UI Views package.

Exports all reusable view classes for Discord interactions.
"""

from src.ui.views.base import BaseView, BaseModalView
from src.ui.views.pagination import PaginatedView, PaginatedListView
from src.ui.views.combat import CombatActionView, CombatVictoryView
from src.ui.views.menu import DropdownMenuView, ButtonMenuView
from src.ui.views.confirmation import (
    ConfirmationView,
    AgreementView,
    DeletionConfirmationView
)
from src.ui.views.modals import (
    NumericInputModal,
    TextInputModal,
    MultiFieldModal
)

__all__ = [
    # Base
    "BaseView",
    "BaseModalView",

    # Pagination
    "PaginatedView",
    "PaginatedListView",

    # Combat
    "CombatActionView",
    "CombatVictoryView",

    # Menus
    "DropdownMenuView",
    "ButtonMenuView",

    # Confirmation
    "ConfirmationView",
    "AgreementView",
    "DeletionConfirmationView",

    # Modals
    "NumericInputModal",
    "TextInputModal",
    "MultiFieldModal",
]
