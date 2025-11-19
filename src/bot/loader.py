"""
Dynamic Feature Cog Loader for Lumen (2025)

Purpose
-------
Automatically discover and load all feature cogs from the features directory
with production-grade observability, error handling, and performance tracking.

Responsibilities
----------------
- Discover all *_cog.py files in src/features/ directory
- Validate cog modules before loading (check for setup() function)
- Load cogs with timeout protection
- Track load timing and performance metrics per cog
- Provide detailed error context and suggestions
- Log a comprehensive loading summary

Non-Responsibilities
--------------------
- Cog implementation (handled by feature cogs)
- Bot lifecycle management (handled by BotLifecycle)
- Error handling within cogs (handled by BaseCog)

Lumen 2025 Compliance
---------------------
- Dynamic discovery, zero hardcoded cog lists
- Structured logging of timings and failures
- Graceful degradation on loading failures
- Config-driven timeouts
"""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.config import ConfigManager
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LoadResult:
    """Result of loading a single cog."""

    name: str
    success: bool
    duration_ms: float
    error: Optional[Exception] = None
    error_type: Optional[str] = None


class FeatureLoader:
    """
    Dynamic feature cog loader with production-grade observability.

    Discovers and loads all *_cog.py files from src/features/ with:
    - Timeout protection per cog
    - Validation before loading
    - Comprehensive metrics and structured logs
    """

    # Static configuration (config-driven where it matters)
    BASE_PATH: Path = Path(__file__).parent.parent / "features"
    BASE_PACKAGE: str = "features"
    COG_SUFFIX: str = "_cog"

    def __init__(self, bot, config_manager: ConfigManager) -> None:
        self.bot = bot
        self._config_manager = config_manager
        self.load_results: List[LoadResult] = []
        self.load_timeout_seconds: float = float(
            self._config_manager.get("bot.feature_load_timeout_seconds", 30.0)
        )

    async def load_all_features(self) -> Dict[str, object]:
        """
        Discover and load all feature cogs.

        Returns:
            Dictionary with load statistics and results.
        """
        start_time = time.perf_counter()

        logger.info(
            "Discovering feature cogs",
            extra={"base_path": str(self.BASE_PATH)},
        )
        cog_names = self._discover_cogs()

        if not cog_names:
            logger.warning(
                "No cog files discovered",
                extra={"pattern": f"*{self.COG_SUFFIX}.py"},
            )
            return self._build_stats(start_time)

        logger.info(
            "Discovered feature cogs",
            extra={"count": len(cog_names), "cogs": cog_names},
        )

        tasks = [self._load_cog_with_timeout(name) for name in cog_names]
        self.load_results = await asyncio.gather(*tasks, return_exceptions=False)

        stats = self._build_stats(start_time)
        self._log_summary(stats)
        return stats

    def _discover_cogs(self) -> List[str]:
        """
        Discover all *_cog.py files in the features directory.

        Returns:
            List of fully qualified module names.
        """
        cog_names: List[str] = []

        try:
            for _, name, ispkg in pkgutil.walk_packages(
                [str(self.BASE_PATH)],
                prefix=f"{self.BASE_PACKAGE}.",
            ):
                if ispkg:
                    continue
                if name.endswith(self.COG_SUFFIX):
                    cog_names.append(name)
        except Exception as exc:
            logger.error(
                "Error discovering cogs",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

        return sorted(cog_names)

    async def _load_cog_with_timeout(self, extension_name: str) -> LoadResult:
        """
        Load a single cog with timeout protection.

        Args:
            extension_name: Full module path (e.g., "features.fusion.fusion_cog")

        Returns:
            LoadResult with timing and error info.
        """
        start_time = time.perf_counter()

        try:
            validation_error = self._validate_cog(extension_name)
            if validation_error:
                logger.error(
                    "Cog validation failed",
                    extra={
                        "cog_name": extension_name,
                        "error": str(validation_error),
                        "error_type": type(validation_error).__name__,
                    },
                )
                return LoadResult(
                    name=extension_name,
                    success=False,
                    duration_ms=0.0,
                    error=validation_error,
                    error_type="ValidationError",
                )

            await asyncio.wait_for(
                self.bot.load_extension(extension_name),
                timeout=self.load_timeout_seconds,
            )

            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "Cog loaded successfully",
                extra={"cog_name": extension_name, "duration_ms": round(duration_ms, 2)},
            )

            return LoadResult(
                name=extension_name,
                success=True,
                duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000
            error = TimeoutError(
                f"Cog loading exceeded {self.load_timeout_seconds}s timeout"
            )
            logger.error(
                "Cog load timeout",
                extra={
                    "cog_name": extension_name,
                    "timeout_seconds": self.load_timeout_seconds,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return LoadResult(
                name=extension_name,
                success=False,
                duration_ms=duration_ms,
                error=error,
                error_type="TimeoutError",
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            error_type = type(exc).__name__

            logger.error(
                "Failed to load cog",
                extra={
                    "cog_name": extension_name,
                    "error": str(exc),
                    "error_type": error_type,
                    "duration_ms": round(duration_ms, 2),
                    "suggestion": self._get_error_suggestion(exc),
                },
                exc_info=True,
            )

            return LoadResult(
                name=extension_name,
                success=False,
                duration_ms=duration_ms,
                error=exc,
                error_type=error_type,
            )

    def _validate_cog(self, extension_name: str) -> Optional[Exception]:
        """
        Validate that a cog module has the required setup() function.

        Args:
            extension_name: Full module path.

        Returns:
            Exception if validation fails, None if valid.
        """
        try:
            module = importlib.import_module(extension_name)

            if not hasattr(module, "setup"):
                return ValueError(
                    "Missing required setup() function. "
                    "Expected: async def setup(bot): await bot.add_cog(YourCog(bot))"
                )

            setup_fn = getattr(module, "setup")
            if not callable(setup_fn):
                return ValueError("setup must be a callable function")

            return None

        except ImportError as exc:
            return ImportError(f"Cannot import module: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            return exc

    def _get_error_suggestion(self, error: Exception) -> str:
        """
        Get actionable suggestion based on error type.

        Args:
            error: Exception that occurred.

        Returns:
            Helpful suggestion string.
        """
        error_type = type(error).__name__

        suggestions = {
            "ImportError": "Check that all dependencies are installed and module paths are correct.",
            "AttributeError": "Verify all required attributes/methods exist in the cog.",
            "SyntaxError": "Fix syntax errors in the cog file.",
            "NameError": "Check for undefined variables or incorrect imports.",
            "TypeError": "Verify function signatures and type usage.",
            "TimeoutError": "Cog setup is taking too long; check for blocking operations.",
            "ValueError": "Check configuration values and function arguments.",
        }

        return suggestions.get(error_type, "Check cog implementation and logs for details.")

    def _build_stats(self, start_time: float) -> Dict[str, Any]:
        """
        Build statistics dictionary from load results.

        Args:
            start_time: When loading started (perf_counter).

        Returns:
            Dictionary with comprehensive statistics.
        """
        total_time_ms = (time.perf_counter() - start_time) * 1000

        successful = [r for r in self.load_results if r.success]
        failed = [r for r in self.load_results if not r.success]

        stats: Dict[str, object] = {
            "total_time_ms": total_time_ms,
            "discovered": len(self.load_results),
            "loaded": len(successful),
            "failed": len(failed),
            "success_rate": (
                len(successful) / len(self.load_results) * 100
                if self.load_results
                else 0.0
            ),
            "results": self.load_results,
        }

        if successful:
            durations = [r.duration_ms for r in successful]
            slowest = max(successful, key=lambda r: r.duration_ms)
            fastest = min(successful, key=lambda r: r.duration_ms)

            stats["timing"] = {
                "slowest_cog": slowest.name,
                "slowest_time_ms": max(durations),
                "fastest_cog": fastest.name,
                "fastest_time_ms": min(durations),
                "average_time_ms": sum(durations) / len(durations),
            }

        if failed:
            error_types: Dict[str, int] = {}
            for result in failed:
                etype = result.error_type or "Unknown"
                error_types[etype] = error_types.get(etype, 0) + 1
            stats["error_breakdown"] = error_types

        return stats

    def _log_summary(self, stats: Dict[str, Any]) -> None:
        """
        Log comprehensive loading summary.

        Args:
            stats: Statistics dictionary from _build_stats.
        """
        logger.info("=" * 60)
        logger.info("FEATURE COG LOADING SUMMARY")
        logger.info("=" * 60)
        logger.info("Total Time:     %.0fms", stats["total_time_ms"])
        logger.info("Discovered:     %d cogs", stats["discovered"])
        logger.info("Loaded:         %d cogs", stats["loaded"])
        logger.info("Failed:         %d cogs", stats["failed"])
        logger.info("Success Rate:   %.1f%%", stats["success_rate"])

        if "timing" in stats:
            timing = stats["timing"]
            logger.info(
                "Fastest Load:   %s (%.0fms)",
                timing["fastest_cog"],
                timing["fastest_time_ms"],
            )
            logger.info(
                "Slowest Load:   %s (%.0fms)",
                timing["slowest_cog"],
                timing["slowest_time_ms"],
            )
            logger.info(
                "Average Load:   %.0fms",
                timing["average_time_ms"],
            )

        if "error_breakdown" in stats:
            logger.warning("Error Breakdown:")
            for error_type, count in stats["error_breakdown"].items():
                logger.warning("  • %s: %d", error_type, count)

        logger.info("=" * 60)

        if stats["success_rate"] < 80.0 and stats["discovered"] > 0:
            logger.warning(
                "Low cog load success rate",
                extra={"success_rate": stats["success_rate"]},
            )


# Backward-compatible API
async def load_all_features(bot) -> Dict[str, object]:
    """
    Legacy function for backward compatibility.

    Dynamically discover and load all feature cogs from src/features.

    New code should prefer using FeatureLoader directly for access to stats.
    """
    # Get config_manager from bot (assumes bot has config_manager property)
    config_manager = bot.config_manager
    loader = FeatureLoader(bot, config_manager)
    return await loader.load_all_features()





