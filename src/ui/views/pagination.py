"""
Reusable pagination views for Discord.

Provides generic pagination with next/previous buttons.
Supports custom page builders and automatic list slicing.

Usage:
    >>> # Generic pagination with custom page builder
    >>> async def build_page(page):
    ...     return await create_custom_embed(page)
    >>>
    >>> view = PaginatedView(user_id, total_pages=5, page_builder=build_page)
    >>>
    >>> # Automatic list pagination
    >>> items = ["Item 1", "Item 2", ..., "Item 100"]
    >>> view = PaginatedListView(user_id, items, items_per_page=10, title="My Items")
"""

import discord
from discord.ui import Button
from typing import List, Callable, Awaitable, Optional, cast

from src.ui.views.base import BaseView
from src.ui.emojis import Emojis


class PaginatedView(BaseView):
    """
    Generic paginated view with next/previous navigation.

    Calls custom page_builder function to generate embed for each page.
    """

    def __init__(
        self,
        user_id: int,
        total_pages: int,
        page_builder: Callable[[int], Awaitable[discord.Embed]],
        current_page: int = 1,
        timeout: float = 180
    ):
        """
        Initialize paginated view.

        Args:
            user_id: Discord user ID
            total_pages: Total number of pages
            page_builder: Async function that takes page number and returns embed
            current_page: Starting page (1-indexed)
            timeout: Timeout in seconds
        """
        super().__init__(user_id, timeout)
        self.current_page = current_page
        self.total_pages = total_pages
        self.page_builder = page_builder

        # Add navigation buttons
        self._setup_buttons()

    def _setup_buttons(self) -> None:
        """Setup pagination buttons."""
        # Previous button
        prev_button = Button(
            label="Previous",
            emoji=Emojis.PREVIOUS,
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page <= 1
        )
        prev_button.callback = self._previous_page
        self.add_item(prev_button)

        # Next button
        next_button = Button(
            label="Next",
            emoji=Emojis.NEXT,
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page >= self.total_pages
        )
        next_button.callback = self._next_page
        self.add_item(next_button)

    async def _previous_page(self, interaction: discord.Interaction) -> None:
        """Handle previous page button."""
        if not await self.check_user(interaction):
            return

        if self.current_page > 1:
            self.current_page -= 1
            await self._update_page(interaction)

    async def _next_page(self, interaction: discord.Interaction) -> None:
        """Handle next page button."""
        if not await self.check_user(interaction):
            return

        if self.current_page < self.total_pages:
            self.current_page += 1
            await self._update_page(interaction)

    async def _update_page(self, interaction: discord.Interaction) -> None:
        """Update page display."""
        # Build new embed
        embed = await self.page_builder(self.current_page)

        # Update button states
        if isinstance(self.children[0], discord.ui.Button):
            prev_button = cast(discord.ui.Button, self.children[0])
            prev_button.disabled = self.current_page <= 1
        if isinstance(self.children[1], discord.ui.Button):
            next_button = cast(discord.ui.Button, self.children[1])
            next_button.disabled = self.current_page >= self.total_pages

        # Update message
        await interaction.response.edit_message(embed=embed, view=self)

    async def get_initial_embed(self) -> discord.Embed:
        """Get initial embed for first page."""
        return await self.page_builder(self.current_page)


class PaginatedListView(BaseView):
    """
    Paginated list view with automatic item slicing.

    Automatically slices items list and formats for display.
    """

    def __init__(
        self,
        user_id: int,
        items: List[str],
        items_per_page: int = 10,
        title: str = "List",
        description: Optional[str] = None,
        timeout: float = 180
    ):
        """
        Initialize paginated list view.

        Args:
            user_id: Discord user ID
            items: List of formatted item strings
            items_per_page: Number of items per page
            title: Embed title
            description: Optional embed description
            timeout: Timeout in seconds
        """
        super().__init__(user_id, timeout)
        self.items = items
        self.items_per_page = items_per_page
        self.title = title
        self.description = description

        # Calculate pagination
        self.total_pages = max(1, (len(items) + items_per_page - 1) // items_per_page)
        self.current_page = 1

        # Add navigation buttons
        self._setup_buttons()

    def _setup_buttons(self) -> None:
        """Setup pagination buttons."""
        # Previous button
        prev_button = Button(
            label="Previous",
            emoji=Emojis.PREVIOUS,
            style=discord.ButtonStyle.secondary,
            disabled=True  # Start on page 1
        )
        prev_button.callback = self._previous_page
        self.add_item(prev_button)

        # Next button
        next_button = Button(
            label="Next",
            emoji=Emojis.NEXT,
            style=discord.ButtonStyle.secondary,
            disabled=self.total_pages <= 1
        )
        next_button.callback = self._next_page
        self.add_item(next_button)

    async def _previous_page(self, interaction: discord.Interaction) -> None:
        """Handle previous page button."""
        if not await self.check_user(interaction):
            return

        if self.current_page > 1:
            self.current_page -= 1
            await self._update_page(interaction)

    async def _next_page(self, interaction: discord.Interaction) -> None:
        """Handle next page button."""
        if not await self.check_user(interaction):
            return

        if self.current_page < self.total_pages:
            self.current_page += 1
            await self._update_page(interaction)

    async def _update_page(self, interaction: discord.Interaction) -> None:
        """Update page display."""
        embed = self.build_embed()

        # Update button states
        if isinstance(self.children[0], discord.ui.Button):
            prev_button = cast(discord.ui.Button, self.children[0])
            prev_button.disabled = self.current_page <= 1
        if isinstance(self.children[1], discord.ui.Button):
            next_button = cast(discord.ui.Button, self.children[1])
            next_button.disabled = self.current_page >= self.total_pages

        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        """
        Build embed for current page.

        Returns:
            Discord embed with current page items
        """
        from src.ui.embeds import EmbedFactory

        # Slice items for current page
        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.items[start_idx:end_idx]

        # Build embed using EmbedFactory
        embed = EmbedFactory.paginated_list(
            title=self.title,
            items=page_items,
            page=self.current_page,
            total_pages=self.total_pages,
            description=self.description
        )

        return embed

    def get_initial_embed(self) -> discord.Embed:
        """Get initial embed for first page."""
        return self.build_embed()
