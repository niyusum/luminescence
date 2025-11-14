"""
Configuration management and settings.

Handles environment variables, YAML configuration files, and runtime settings.
"""

# Import from config module (static configuration)
from src.core.config.config import Config

# Import from manager module (dynamic configuration management)
from src.core.config.manager import (
    ConfigInitializationError,
    ConfigManager,
    ConfigManagerError,
    ConfigWriteError,
)

# Import from metrics module
from src.core.config.metrics import ConfigMetrics

# Import from validator module
from src.core.config.validator import ConfigSchema

__all__ = [
    # Static config
    "Config",
    # Dynamic config manager
    "ConfigManager",
    "ConfigManagerError",
    "ConfigInitializationError",
    "ConfigWriteError",
    # Metrics
    "ConfigMetrics",
    # Validator
    "ConfigSchema",
]
