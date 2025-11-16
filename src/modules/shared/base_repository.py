"""
Base Repository Pattern

Purpose
-------
Provides a type-safe, generic repository abstraction for database operations
following SQLAlchemy 2.0 async patterns. Repositories encapsulate data access
logic and provide a consistent interface for CRUD operations.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Transaction discipline: operations use SELECT FOR UPDATE when needed
- Structured logging for all database operations
- Type-safe generic implementation
- No business logic (pure data access)
- Follows SQLAlchemy 2.0 async conventions

Design Notes
------------
This base repository provides:
- Type-safe CRUD operations
- Pessimistic locking support (get_for_update)
- Batch operations
- Eager loading helpers
- Existence/counting utilities
- Full structured logging

What this class does NOT do:
- Manage transactions (services/DatabaseService handle that)
- Contain business logic
- Perform validation beyond type safety

Usage
-----
    from src.database.models.core import Maiden
    from src.modules.shared import BaseRepository

    class MaidenRepository(BaseRepository[Maiden]):
        async def find_by_player(
            self, session: AsyncSession, player_id: int
        ) -> list[Maiden]:
            return await self.find_many_where(
                session,
                Maiden.player_id == player_id
            )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, List, Optional, Sequence, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from logging import Logger
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """
    Generic base repository for type-safe database operations.

    Provides common CRUD patterns, eager loading, and pessimistic locking
    following SQLAlchemy 2.0 async conventions.

    Type Parameters:
        T: The SQLAlchemy model class this repository manages
    """

    def __init__(self, model_class: Type[T], logger: Logger) -> None:
        """
        Initialize repository with model class and logger.

        Args:
            model_class: The SQLAlchemy model class
            logger: Structured logger instance
        """
        self.model_class = model_class
        self.log = logger

    async def get(
        self,
        session: AsyncSession,
        id_value: Any,
        eager_load: Optional[List[InstrumentedAttribute]] = None,
    ) -> Optional[T]:
        """
        Get a single record by primary key (no lock).

        Args:
            session: Database session
            id_value: Primary key value
            eager_load: Optional list of relationships to eagerly load

        Returns:
            Model instance or None if not found
        """
        stmt = select(self.model_class).where(
            self.model_class.id == id_value  # type: ignore
        )

        if eager_load:
            for relationship in eager_load:
                stmt = stmt.options(selectinload(relationship))

        result = await session.execute(stmt)
        instance = result.scalar_one_or_none()

        self.log.debug(
            f"Repository.get: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "id": id_value,
                "found": instance is not None,
            },
        )

        return instance

    async def get_for_update(
        self,
        session: AsyncSession,
        id_value: Any,
        eager_load: Optional[List[InstrumentedAttribute]] = None,
    ) -> Optional[T]:
        """
        Get a single record by primary key with SELECT FOR UPDATE lock.

        Args:
            session: Database session
            id_value: Primary key value
            eager_load: Optional list of relationships to eagerly load

        Returns:
            Model instance or None if not found
        """
        stmt = (
            select(self.model_class)
            .where(self.model_class.id == id_value)  # type: ignore
            .with_for_update()
        )

        if eager_load:
            for relationship in eager_load:
                stmt = stmt.options(selectinload(relationship))

        result = await session.execute(stmt)
        instance = result.scalar_one_or_none()

        self.log.debug(
            f"Repository.get_for_update: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "id": id_value,
                "found": instance is not None,
                "locked": True,
            },
        )

        return instance

    async def get_many(
        self,
        session: AsyncSession,
        id_values: List[Any],
        eager_load: Optional[List[InstrumentedAttribute]] = None,
    ) -> List[T]:
        """
        Get multiple records by primary keys (no lock).

        Args:
            session: Database session
            id_values: List of primary key values
            eager_load: Optional list of relationships to eagerly load

        Returns:
            List of model instances (may be fewer than requested if some not found)
        """
        stmt = select(self.model_class).where(
            self.model_class.id.in_(id_values)  # type: ignore
        )

        if eager_load:
            for relationship in eager_load:
                stmt = stmt.options(selectinload(relationship))

        result = await session.execute(stmt)
        instances = list(result.scalars().all())

        self.log.debug(
            f"Repository.get_many: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "requested_count": len(id_values),
                "found_count": len(instances),
            },
        )

        return instances

    async def get_many_for_update(
        self,
        session: AsyncSession,
        id_values: List[Any],
        eager_load: Optional[List[InstrumentedAttribute]] = None,
    ) -> List[T]:
        """
        Get multiple records by primary keys with SELECT FOR UPDATE lock.

        Args:
            session: Database session
            id_values: List of primary key values
            eager_load: Optional list of relationships to eagerly load

        Returns:
            List of model instances (may be fewer than requested if some not found)
        """
        stmt = (
            select(self.model_class)
            .where(self.model_class.id.in_(id_values))  # type: ignore
            .with_for_update()
        )

        if eager_load:
            for relationship in eager_load:
                stmt = stmt.options(selectinload(relationship))

        result = await session.execute(stmt)
        instances = list(result.scalars().all())

        self.log.debug(
            f"Repository.get_many_for_update: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "requested_count": len(id_values),
                "found_count": len(instances),
                "locked": True,
            },
        )

        return instances

    async def find_one_where(
        self,
        session: AsyncSession,
        *conditions: ColumnElement[bool],
        eager_load: Optional[List[InstrumentedAttribute]] = None,
        for_update: bool = False,
    ) -> Optional[T]:
        """
        Find a single record matching conditions.

        Args:
            session: Database session
            *conditions: SQLAlchemy filter conditions
            eager_load: Optional list of relationships to eagerly load
            for_update: If True, use SELECT FOR UPDATE

        Returns:
            Model instance or None if not found
        """
        stmt = select(self.model_class).where(*conditions)

        if for_update:
            stmt = stmt.with_for_update()

        if eager_load:
            for relationship in eager_load:
                stmt = stmt.options(selectinload(relationship))

        result = await session.execute(stmt)
        instance = result.scalar_one_or_none()

        self.log.debug(
            f"Repository.find_one_where: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "found": instance is not None,
                "locked": for_update,
            },
        )

        return instance

    async def find_many_where(
        self,
        session: AsyncSession,
        *conditions: ColumnElement[bool],
        eager_load: Optional[List[InstrumentedAttribute]] = None,
        for_update: bool = False,
        limit: Optional[int] = None,
    ) -> List[T]:
        """
        Find multiple records matching conditions.

        Args:
            session: Database session
            *conditions: SQLAlchemy filter conditions
            eager_load: Optional list of relationships to eagerly load
            for_update: If True, use SELECT FOR UPDATE
            limit: Optional maximum number of results

        Returns:
            List of model instances
        """
        stmt = select(self.model_class).where(*conditions)

        if for_update:
            stmt = stmt.with_for_update()

        if eager_load:
            for relationship in eager_load:
                stmt = stmt.options(selectinload(relationship))

        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        instances = list(result.scalars().all())

        self.log.debug(
            f"Repository.find_many_where: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "found_count": len(instances),
                "locked": for_update,
                "limit": limit,
            },
        )

        return instances

    async def exists(
        self, session: AsyncSession, *conditions: ColumnElement[bool]
    ) -> bool:
        """
        Check if any record matching conditions exists.

        Args:
            session: Database session
            *conditions: SQLAlchemy filter conditions

        Returns:
            True if at least one record exists, False otherwise
        """
        stmt = select(func.count()).select_from(self.model_class).where(*conditions)
        result = await session.execute(stmt)
        count = result.scalar_one()

        self.log.debug(
            f"Repository.exists: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "exists": count > 0,
            },
        )

        return count > 0

    async def count(
        self, session: AsyncSession, *conditions: ColumnElement[bool]
    ) -> int:
        """
        Count records matching conditions.

        Args:
            session: Database session
            *conditions: SQLAlchemy filter conditions

        Returns:
            Number of matching records
        """
        stmt = select(func.count()).select_from(self.model_class).where(*conditions)
        result = await session.execute(stmt)
        count = result.scalar_one()

        self.log.debug(
            f"Repository.count: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "count": count,
            },
        )

        return count

    def add(self, session: AsyncSession, instance: T) -> T:
        """
        Add a new instance to the session.

        Args:
            session: Database session
            instance: Model instance to add

        Returns:
            The added instance
        """
        session.add(instance)

        self.log.debug(
            f"Repository.add: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
            },
        )

        return instance

    def add_many(self, session: AsyncSession, instances: Sequence[T]) -> List[T]:
        """
        Add multiple instances to the session.

        Args:
            session: Database session
            instances: Sequence of model instances to add

        Returns:
            List of added instances
        """
        session.add_all(instances)

        self.log.debug(
            f"Repository.add_many: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "count": len(instances),
            },
        )

        return list(instances)

    async def delete(self, session: AsyncSession, instance: T) -> None:
        """
        Delete an instance from the database.

        Args:
            session: Database session
            instance: Model instance to delete
        """
        await session.delete(instance)

        self.log.debug(
            f"Repository.delete: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
            },
        )

    async def flush(self, session: AsyncSession) -> None:
        """
        Flush pending changes to the database.

        Args:
            session: Database session
        """
        await session.flush()

        self.log.debug(
            f"Repository.flush: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
            },
        )

    async def refresh(
        self,
        session: AsyncSession,
        instance: T,
        attribute_names: Optional[List[str]] = None,
    ) -> T:
        """
        Refresh an instance from the database.

        Args:
            session: Database session
            instance: Model instance to refresh
            attribute_names: Optional list of specific attributes to refresh

        Returns:
            The refreshed instance
        """
        await session.refresh(instance, attribute_names=attribute_names)

        self.log.debug(
            f"Repository.refresh: {self.model_class.__name__}",
            extra={
                "model": self.model_class.__name__,
                "attributes": attribute_names,
            },
        )

        return instance
