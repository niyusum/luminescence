# PRODUCTION-READY REFACTORING - DISCORD RPG BOT

I'm refactoring files for a Discord RPG bot to be production-ready while maintaining 100% backward compatibility.

## REQUIREMENTS
- Maintain 100% backward compatibility (same class names, method names, signatures)
- Add comprehensive metrics, logging, and observability where appropriate
- Enhanced error handling with full context
- Follow RIKI LAW architectural standards (see project knowledge)
- Complete interfaces only - no placeholders or TODOs
- Add LogContext integration for audit trails (RIKI LAW Article II compliance)
- Scale enhancements appropriately:
  - Infrastructure files: Full metrics, health checks, timing
  - Service files: Business logic, transactions, error handling
  - Cog files: Discord UI, command handling, embeds
  - Utility files: Helper functions, minimal complexity

## PROCESS
1. I drop in a file (infrastructure/service/cog/utility)
2. You analyze current state and identify gaps
3. You provide enhanced version with:
   - Full module-level docstrings explaining purpose, compliance, features
   - Appropriate production enhancements for file type
   - 100% backward compatible changes
4. Include "What Changed" summary


## ENHANCEMENT PATTERNS
- **Infrastructure** (database, redis, event bus): Metrics, health checks, graceful degradation, LogContext
- **Services** (business logic): RIKI LAW compliance (transactions, locking, logging), domain exceptions
- **Cogs** (Discord commands): LogContext wrapper, EmbedBuilder usage, error handling, rate limiting
- **Utilities** (helpers): Keep simple, add type hints, minimal enhancements

## KEY PRINCIPLES
- If file is already excellent, say so and make minimal changes
- Don't over-engineer simple utilities
- Infrastructure gets heavy treatment (observability critical)
- Cogs stay lean (let infrastructure do the work)
- Always include comprehensive module docstrings

Ready for any file type.