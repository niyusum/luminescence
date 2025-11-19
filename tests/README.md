# Lumen RPG Test Suite (LES 2025)

Comprehensive test infrastructure for the Lumen RPG bot following LES 2025 standards.

## Overview

The test suite uses **pytest** with **testcontainers** for integration testing. Tests are organized into:

- **Unit Tests** (`tests/unit/`): Fast, isolated tests with mocks (no external dependencies)
- **Integration Tests** (`tests/integration/`): Tests with real infrastructure (PostgreSQL, Redis via testcontainers)
- **Fixtures** (`tests/fixtures/`): Shared test data and factories

## Quick Start

### Installation

Install test dependencies:

```bash
pip install -r requirements-dev.txt
```

### Running Tests

```bash
# Run all tests
pytest

# Run only unit tests (fast)
pytest tests/unit

# Run only integration tests
pytest tests/integration

# Run with coverage report
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/domain/test_player.py

# Run tests matching a pattern
pytest -k "test_player"

# Run tests with specific marker
pytest -m unit
pytest -m integration
```

## Test Organization

### Directory Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures and configuration
├── README.md                # This file
│
├── unit/                    # Unit tests (fast, mocked)
│   ├── domain/              # Domain model tests
│   │   └── test_player.py
│   ├── services/            # Service layer tests
│   └── repositories/        # Repository tests
│
├── integration/             # Integration tests (slower, real infra)
│   ├── test_database_service.py
│   └── test_redis_service.py
│
└── fixtures/                # Test data factories
    └── __init__.py
```

### Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit         # Fast unit test with mocks
@pytest.mark.integration  # Integration test with real infrastructure
@pytest.mark.slow         # Tests that take > 1 second
@pytest.mark.smoke        # Critical smoke tests
@pytest.mark.domain       # Domain model tests
@pytest.mark.service      # Service layer tests
@pytest.mark.database     # Requires database
@pytest.mark.redis        # Requires Redis
```

Run tests by marker:

```bash
pytest -m unit            # Only unit tests
pytest -m "not slow"      # Skip slow tests
pytest -m "integration and database"  # Integration tests that need DB
```

## Writing Tests

### Unit Test Example

Unit tests should be fast and isolated using mocks:

```python
import pytest
from src.domain.models import Player, PlayerIdentity, PlayerProgression, PlayerCurrencies

@pytest.mark.unit
@pytest.mark.domain
def test_player_add_experience():
    """Test adding experience to a player."""
    # Arrange
    player = Player(
        identity=PlayerIdentity(discord_id=123, username="Test"),
        progression=PlayerProgression(level=1, experience=0, experience_to_next_level=100),
        currencies=PlayerCurrencies(lumens=0, gems=0),
    )

    # Act
    player.add_experience(50)

    # Assert
    assert player.progression.experience == 50
    assert player.progression.level == 1
```

### Integration Test Example

Integration tests use real infrastructure via testcontainers:

```python
import pytest
from src.database.models.core.player import PlayerCore

@pytest.mark.integration
@pytest.mark.database
async def test_create_player(db_session):
    """Test creating a player in the database."""
    # Arrange
    player = PlayerCore(
        discord_id=123456789,
        username="TestUser",
    )

    # Act
    db_session.add(player)
    await db_session.flush()
    await db_session.refresh(player)

    # Assert
    assert player.id is not None
    assert player.created_at is not None
```

## Available Fixtures

### Database Fixtures (Integration Tests)

```python
@pytest.mark.integration
async def test_something(db_session):
    """db_session: Clean database session with automatic rollback."""
    # Each test gets fresh database state
    pass

async def test_something_else(database_engine):
    """database_engine: Direct access to SQLAlchemy engine."""
    pass
```

### Mock Fixtures (Unit Tests)

```python
def test_something(mock_service_container):
    """mock_service_container: Mocked ServiceContainer."""
    pass

def test_something_else(mock_database_service):
    """mock_database_service: Mocked DatabaseService."""
    pass

async def test_command(mock_context):
    """mock_context: Mocked Discord command context."""
    pass
```

### Testcontainers Fixtures

```python
@pytest.mark.integration
def test_postgres(postgres_container):
    """postgres_container: PostgreSQL testcontainer."""
    url = postgres_container.get_connection_url()
    pass

def test_redis(redis_container):
    """redis_container: Redis testcontainer."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    pass
```

## Best Practices

### 1. Follow AAA Pattern

Organize tests with **Arrange**, **Act**, **Assert**:

```python
def test_example():
    # Arrange - Set up test data
    player = create_player()

    # Act - Perform the operation
    player.add_experience(100)

    # Assert - Verify the result
    assert player.progression.level == 2
```

### 2. Test One Behavior Per Test

Each test should verify a single behavior:

```python
# Good - Tests one thing
def test_add_experience_emits_event():
    player.add_experience(100)
    assert len(player.get_pending_events()) == 1

# Bad - Tests multiple things
def test_player_everything():
    player.add_experience(100)
    assert player.progression.level == 2
    player.add_currency("lumens", 500)
    assert player.currencies.lumens == 500
```

### 3. Use Descriptive Test Names

Test names should describe what they test:

```python
# Good
def test_add_experience_triggers_level_up_when_threshold_reached():
    pass

# Bad
def test_experience():
    pass
```

### 4. Use Fixtures for Common Setup

Extract common setup into fixtures:

```python
@pytest.fixture
def sample_player():
    return Player(
        identity=PlayerIdentity(discord_id=123, username="Test"),
        progression=PlayerProgression(level=1, experience=0, experience_to_next_level=100),
        currencies=PlayerCurrencies(lumens=0, gems=0),
    )

def test_something(sample_player):
    # Use sample_player directly
    pass
```

### 5. Keep Unit Tests Fast

Unit tests should run in milliseconds:

- Use mocks for external dependencies
- Don't use real database, network, or file I/O
- Keep test data minimal

### 6. Integration Tests Test Real Behavior

Integration tests should use real infrastructure:

- Use testcontainers for database/Redis
- Test actual database queries and transactions
- Verify schema and constraints
- Test error handling with real errors

## Coverage Reports

Generate HTML coverage report:

```bash
pytest --cov=src --cov-report=html
```

View report:

```bash
# Open htmlcov/index.html in browser
start htmlcov/index.html  # Windows
```

## Continuous Integration

The test suite is designed to run in CI/CD pipelines:

- Testcontainers automatically manages infrastructure
- Tests are isolated and can run in parallel
- Coverage reports can be uploaded to services like Codecov

Example GitHub Actions workflow:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest --cov=src --cov-report=xml
      - uses: codecov/codecov-action@v3
```

## Troubleshooting

### Testcontainers Issues

If testcontainers fail to start:

1. Ensure Docker is running
2. Check Docker daemon is accessible
3. Verify network connectivity

### Slow Tests

If tests are slow:

1. Run only unit tests: `pytest tests/unit`
2. Skip slow tests: `pytest -m "not slow"`
3. Use `-n auto` for parallel execution (requires `pytest-xdist`)

### Import Errors

If imports fail:

1. Ensure project root is in PYTHONPATH
2. Run pytest from project root directory
3. Check virtual environment is activated

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [testcontainers-python](https://testcontainers-python.readthedocs.io/)
- [SQLAlchemy async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
