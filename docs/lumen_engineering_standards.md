🏛️ LUMEN ENGINEERING STANDARD — 2025 EDITION

Pre-Launch Architecture & Refactoring Guide


---

0. PURPOSE

The Lumen Engineering Standard (LES) defines the authoritative technical rules, patterns, and expectations for building, refactoring, and extending the Lumen RPG system.

This document governs:

Code structure

Architecture

Observability

Refactoring standards

Domain separation

Concurrency safety

Consistency

Long-term maintainability


It is not a rigid constitution.
It is a professional engineering standard designed for:

Assistant alignment

Multi-module consistency

Pre-launch stability

Long-term evolution



---

1. CORE ARCHITECTURAL PRINCIPLES

These are non-negotiable engineering truths across the entire system.


---

1.1 Separation of Responsibilities

✔ Cogs

Discord UI surface only

No business logic

Parse inputs → call service → build embed

Handle Discord errors, timeouts, and validation


✔ Services

Pure business logic

Transactions, locking, domain rules

No Discord dependencies

Responsible for correctness, validation, and state mutation


✔ Models

Data structures only

No domain logic


✔ Views (discord.ui)

UI components (buttons, dropdowns, modals)

Must validate user

Must respect concurrency rules

Must be thin wrappers around service calls


✔ Infra

Database, Redis, config, logging, events

Highly observable, durable, and robust



---

1.2 Transaction Discipline

Every operation that mutates state must run inside a single atomic transaction.

Never manually call session.commit().

All writes use SELECT FOR UPDATE pessimistic locks.

Reads use no lock unless needed.


Rule:
If it changes the player, lock the player.


---

1.3 Concurrency Safety

Discord is concurrent by nature.
Lumen must guarantee correctness under stress.

Use Redis locks for:

Buttons that perform mutations

Multi-step workflows

Anything involving resource consumption


Use database row locks for:

Resource changes

Fusion

Summoning

Inventory changes

Guild operations



---

1.4 Config-Driven Game Balance

All values must be loaded from ConfigManager:

Costs

Rewards

Rates

Timers

Limits


No hardcoded game values. Ever.

This enables:

Hot balance patches

Scaling for events

A/B testing



---

1.5 Domain Exceptions

Services must raise domain exceptions, not generic errors.
Cogs translate these into user-friendly embeds.

Examples:

InsufficientResourcesError

ValidationError

NotFoundError

BusinessRuleViolation



---

1.6 Observability First

Every major operation must be measurable.

Required observability:

Structured logs

Latency measurements

Transaction logs

Event emissions

Operation context (user_id, guild_id, command)


Infra components must:

Expose health checks

Log degraded states

Fail gracefully



---

2. CODE STRUCTURE & FILE EXPECTATIONS

Directory style:

src/
 ├── core/           # infra, logging, config, redis, db, events
 ├── modules/        # feature vertical slices
 │    └── feature_x/
 │         ├── cog.py
 │         ├── service.py
 │         ├── views.py
 │         └── logic.py (optional)
 ├── utils/          # small helpers
 └── database/       # models

Module expectations:

Self-contained

No cross-imports (use EventBus)

Cogs only depend on services

Services only depend on infra + models

Views only depend on services



---

3. COG STANDARDS

Cogs must:

Defer early

Validate inputs

Convert exceptions into embeds

Log user + guild context

Apply rate limiting

Contain zero business logic


Cog checklist:

(Empty in source document)



---

4. SERVICE STANDARDS

Services are the backbone of Lumen. They must be:

Deterministic

Pure business logic

Discord-free

Config-driven

Transaction-safe


Service checklist:

(Empty in source document)



---

5. VIEW (BUTTON / MODAL) STANDARDS

Views must:

Validate the interacting user

Use Redis locks for mutation

Disable buttons after use

Handle timeouts gracefully

Avoid business logic


View checklist:

(Empty in source document)



---

6. INFRASTRUCTURE STANDARDS

Infrastructure must provide:

Maximum observability

Safety under failure

Performance under stress

Clear and consistent interfaces


Infra checklist:

(Empty in source document)



---

7. EMBED & UI STANDARDS

All UI uses EmbedBuilder.

Standards:

Primary embeds for normal workflows

Success embeds for completions

Error embeds for issues

Warning or info embeds as needed

Consistent color palette

Timestamp included

Fields for structured data only



---

8. EVENT-DRIVEN ARCHITECTURE

Events must be emitted for:

Achievements

Leaderboard updates

Analytics

Tutorials

Logs


Services publish events.
Cogs must not.

Event handlers must be:

Non-blocking

Idempotent

Independent



---

9. ERROR HANDLING & USER EXPERIENCE

Player-facing errors must always be:

Clear

Helpful

In-embed

Never raw exceptions


Engineering errors must be:

Fully logged

Wrapped with context

Identified by type



---

10. REFACTOR EXPECTATIONS

When refactoring a file:

Preserve behavior unless improvement requires change

Improve clarity and maintainability

Strengthen architecture

Remove dead logic

Add observability

Enforce LES boundaries


A refactor should make the system more stable, more readable, and more future-proof, not more complex.


---

11. PRE-LAUNCH QUALITY BAR

For this phase, every file must reach:

Zero hardcoded values (except small UI strings)

Zero duplicated logic

Correct locking patterns

Clean async flows

Full exception handling

Clean and readable embeds

Consistent naming

Predictable folder structure

Logging that makes sense in production


This is the gold standard — production-ready and evolution-ready.


---

CLOSING STATEMENT

The Lumen Engineering Standard 2025 is the foundation for:

Consistent code

Stable systems

Scalable architecture

Predictable refactors

Assistant alignment

A safe pre-launch environment


This is the standard.
This is the expectation.
This is Lumen.