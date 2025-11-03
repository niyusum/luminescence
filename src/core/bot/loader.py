"""
Dynamic feature cog loader for RIKI RPG Bot.

RIKI LAW Compliance:
- Dynamic discovery (Article I.8)
- Service modularity (Article I.2)
- Zero hardcoded paths
- Graceful degradation on failures

Production Enhancements:
- Load timing metrics per cog
- Timeout protection (30s per cog)
- Validation before loading
- Rich error context with suggestions
- Load performance tracking
"""

import asyncio
import importlib
import pkgutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

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
    - Parallel loading for speed
    - Timeout protection per cog
    - Validation before loading
    - Comprehensive metrics
    """
    
    # Configuration
    LOAD_TIMEOUT = 30.0  # seconds per cog
    BASE_PATH = Path(__file__).parent.parent / "features"
    BASE_PACKAGE = "features"
    COG_SUFFIX = "_cog"
    
    def __init__(self, bot):
        self.bot = bot
        self.load_results: List[LoadResult] = []
    
    async def load_all_features(self) -> dict:
        """
        Discover and load all feature cogs.
        
        Returns:
            Dictionary with load statistics and results
            
        Example:
            >>> loader = FeatureLoader(bot)
            >>> stats = await loader.load_all_features()
            >>> print(f"Loaded {stats['loaded']} cogs in {stats['total_time_ms']:.0f}ms")
        """
        start_time = time.perf_counter()
        
        logger.info(f"🔍 Discovering feature cogs in {self.BASE_PATH}")
        cog_names = self._discover_cogs()
        
        if not cog_names:
            logger.warning(f"⚠️  No *{self.COG_SUFFIX}.py files found in {self.BASE_PATH}")
            return self._build_stats(start_time)
        
        logger.info(f"📦 Found {len(cog_names)} cog(s): {', '.join(cog_names)}")
        
        # Load all cogs in parallel with timeout protection
        tasks = [self._load_cog_with_timeout(name) for name in cog_names]
        self.load_results = await asyncio.gather(*tasks, return_exceptions=False)
        
        stats = self._build_stats(start_time)
        self._log_summary(stats)
        
        return stats
    
    def _discover_cogs(self) -> List[str]:
        """
        Discover all *_cog.py files in features directory.
        
        Returns:
            List of fully qualified module names
        """
        cog_names = []
        
        try:
            for _, name, ispkg in pkgutil.walk_packages(
                [str(self.BASE_PATH)], 
                prefix=f"{self.BASE_PACKAGE}."
            ):
                if name.endswith(self.COG_SUFFIX):
                    cog_names.append(name)
        except Exception as e:
            logger.error(f"❌ Error discovering cogs: {e}", exc_info=True)
        
        return sorted(cog_names)  # Consistent ordering for logs
    
    async def _load_cog_with_timeout(self, extension_name: str) -> LoadResult:
        """
        Load a single cog with timeout protection.
        
        Args:
            extension_name: Full module path (e.g., "features.fusion.fusion_cog")
            
        Returns:
            LoadResult with timing and error info
        """
        start_time = time.perf_counter()
        
        try:
            # Validate cog before loading
            validation_error = self._validate_cog(extension_name)
            if validation_error:
                return LoadResult(
                    name=extension_name,
                    success=False,
                    duration_ms=0,
                    error=validation_error,
                    error_type="ValidationError"
                )
            
            # Load with timeout
            await asyncio.wait_for(
                self.bot.load_extension(extension_name),
                timeout=self.LOAD_TIMEOUT
            )
            
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"✅ Loaded {extension_name} ({duration_ms:.0f}ms)")
            
            return LoadResult(
                name=extension_name,
                success=True,
                duration_ms=duration_ms
            )
            
        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000
            error = TimeoutError(f"Cog loading exceeded {self.LOAD_TIMEOUT}s timeout")
            logger.error(
                f"⏱️  {extension_name} timed out after {self.LOAD_TIMEOUT}s",
                exc_info=False
            )
            
            return LoadResult(
                name=extension_name,
                success=False,
                duration_ms=duration_ms,
                error=error,
                error_type="TimeoutError"
            )
            
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            error_type = type(e).__name__
            
            # Enhanced error logging with suggestions
            logger.error(
                f"❌ Failed to load {extension_name} ({error_type}): {e}",
                exc_info=True,
                extra={
                    "cog_name": extension_name,
                    "error_type": error_type,
                    "duration_ms": duration_ms,
                    "suggestion": self._get_error_suggestion(e)
                }
            )
            
            return LoadResult(
                name=extension_name,
                success=False,
                duration_ms=duration_ms,
                error=e,
                error_type=error_type
            )
    
    def _validate_cog(self, extension_name: str) -> Optional[Exception]:
        """
        Validate that a cog module has required setup() function.
        
        Args:
            extension_name: Full module path
            
        Returns:
            Exception if validation fails, None if valid
        """
        try:
            # Import module to check for setup()
            module = importlib.import_module(extension_name)
            
            if not hasattr(module, 'setup'):
                return ValueError(
                    f"Missing required setup() function. "
                    f"Add: async def setup(bot): await bot.add_cog(YourCog(bot))"
                )
            
            if not callable(getattr(module, 'setup')):
                return ValueError("setup must be a callable function")
            
            return None
            
        except ImportError as e:
            return ImportError(f"Cannot import module: {e}")
        except Exception as e:
            return e
    
    def _get_error_suggestion(self, error: Exception) -> str:
        """
        Get actionable suggestion based on error type.
        
        Args:
            error: Exception that occurred
            
        Returns:
            Helpful suggestion string
        """
        error_type = type(error).__name__
        
        suggestions = {
            "ImportError": "Check that all dependencies are installed and module paths are correct",
            "AttributeError": "Verify all required attributes/methods exist in the cog",
            "SyntaxError": "Fix syntax errors in the cog file",
            "NameError": "Check for undefined variables or incorrect imports",
            "TypeError": "Verify function signatures and type usage",
            "TimeoutError": "Cog setup is taking too long - check for blocking operations",
            "ValueError": "Check configuration values and function arguments",
        }
        
        return suggestions.get(error_type, "Check cog implementation and logs for details")
    
    def _build_stats(self, start_time: float) -> dict:
        """
        Build statistics dictionary from load results.
        
        Args:
            start_time: When loading started (perf_counter)
            
        Returns:
            Dictionary with comprehensive statistics
        """
        total_time_ms = (time.perf_counter() - start_time) * 1000
        
        successful = [r for r in self.load_results if r.success]
        failed = [r for r in self.load_results if not r.success]
        
        stats = {
            "total_time_ms": total_time_ms,
            "discovered": len(self.load_results),
            "loaded": len(successful),
            "failed": len(failed),
            "success_rate": (len(successful) / len(self.load_results) * 100) if self.load_results else 0,
            "results": self.load_results,
        }
        
        # Add timing stats if any cogs loaded
        if successful:
            durations = [r.duration_ms for r in successful]
            stats["timing"] = {
                "slowest_cog": max(successful, key=lambda r: r.duration_ms).name,
                "slowest_time_ms": max(durations),
                "fastest_cog": min(successful, key=lambda r: r.duration_ms).name,
                "fastest_time_ms": min(durations),
                "average_time_ms": sum(durations) / len(durations),
            }
        
        # Add error breakdown if any failures
        if failed:
            error_types = {}
            for result in failed:
                error_type = result.error_type or "Unknown"
                error_types[error_type] = error_types.get(error_type, 0) + 1
            stats["error_breakdown"] = error_types
        
        return stats
    
    def _log_summary(self, stats: dict) -> None:
        """
        Log comprehensive loading summary.
        
        Args:
            stats: Statistics dictionary from _build_stats
        """
        logger.info("=" * 60)
        logger.info("🎯 FEATURE COG LOADING SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Time:     {stats['total_time_ms']:.0f}ms")
        logger.info(f"Discovered:     {stats['discovered']} cogs")
        logger.info(f"Loaded:         {stats['loaded']} cogs ✅")
        logger.info(f"Failed:         {stats['failed']} cogs ❌")
        logger.info(f"Success Rate:   {stats['success_rate']:.1f}%")
        
        # Log timing stats if available
        if "timing" in stats:
            timing = stats["timing"]
            logger.info(f"Fastest Load:   {timing['fastest_cog']} ({timing['fastest_time_ms']:.0f}ms)")
            logger.info(f"Slowest Load:   {timing['slowest_cog']} ({timing['slowest_time_ms']:.0f}ms)")
            logger.info(f"Average Load:   {timing['average_time_ms']:.0f}ms")
        
        # Log error breakdown if any failures
        if "error_breakdown" in stats:
            logger.warning("Error Breakdown:")
            for error_type, count in stats["error_breakdown"].items():
                logger.warning(f"  • {error_type}: {count}")
        
        logger.info("=" * 60)
        
        # Warning if success rate is low
        if stats["success_rate"] < 80 and stats["discovered"] > 0:
            logger.warning(
                f"⚠️  Low success rate ({stats['success_rate']:.1f}%). "
                "Review error logs above for details."
            )


# Backward-compatible API
async def load_all_features(bot):
    """
    Legacy function for backward compatibility.
    
    Dynamically discover and load all feature cogs from src/features.
    
    This is the original API maintained for backward compatibility.
    New code should use FeatureLoader directly for access to stats.
    
    RIKI LAW:
        • Dynamic discovery (Article I.8)
        • Service modularity (Article I.2)
        • No hard-coded paths
    
    Returns:
        Dictionary with load statistics
    """
    loader = FeatureLoader(bot)
    return await loader.load_all_features()




