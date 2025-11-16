📘 Economy Models — Missing Logic Manifest (Grouped by Domain)
(database/models/economy)
🔥 1. Shrine Yield Logic (GuildShrine & PlayerShrine)

Missing business logic includes:

Yield amount computation

Yield rate modifiers (level, shrine type, guild perks)

Cooldown timer enforcement

Calculating next collectible time

Updating yield ring buffer

Upgrading shrine levels

Determining max shrine slots (per type)

Reset rules / activation toggles

Treasury routing (for guild shrines)

Anti-cheat checks (duplicate collection, early collection)

➡️ New home:
ShrineService, GuildShrineService, ShrineYieldCalculator

🔥 2. Token Economy Logic (Token model)

Missing logic includes:

Token redemption flow

Determining maiden tier range per token type

Safe decrement of token quantity

Awarding tokens from ascension/quests

Token rarity categories

Mass-redeem rules (multi pulls)

Validation of player ownership

➡️ New home:
TokenService

🔥 3. Transaction Logging Domain

(For TransactionLog)

Missing logic includes:

Automatic transaction log creation

Categorization of transaction types

Sensitive field filtering

Log retention / cleanup

Anti-spam batching (optional)

Context derivation (command, view, passive system)

Resolving human-readable log entries

➡️ New home:
EconomyAuditService, TransactionLogService

🔥 4. Economy Balancing / Config Integration

Relevant to all economy models.

Missing logic includes:

Shrine level scaling tables

Shrine yield curves (config-driven)

Token rarity → tier mapping

Guild collective yield multipliers

Shrine unlock rules

Shrine slot limits per type

Pricing and upgrade costs

➡️ New home:
GameBalanceService, ConfigManager

🔥 5. UI / Display Formatting (illegal in model layer)

Removed logic includes:

Shrine display names

Yield history presentation

Token icon / rarity color

Guild shrine UI formatting

Cooldown display formatting ("3h 22m left")

➡️ New home:
ui/economy_display.py, ui/shrine_display.py