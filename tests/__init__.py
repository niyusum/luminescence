"""
Lumen RPG Test Suite (LES 2025)
================================

Test Organization
-----------------
- tests/unit/          : Fast unit tests with mocks (no external dependencies)
- tests/integration/   : Integration tests with testcontainers (real infrastructure)
- tests/fixtures/      : Test data fixtures and factories

Testing Philosophy
------------------
- Unit tests: Fast, isolated, test business logic
- Integration tests: Slower, test real infrastructure interactions
- Use pytest markers to categorize and selectively run tests
- Follow AAA pattern: Arrange, Act, Assert
"""
