📘 Core Models — Missing Logic Manifest (Grouped by Domain)
(database/models/core)
🔥 1. Fusion Domain

Removed from: Player, Maiden, MaidenBase
Missing logic includes:

Fusion eligibility checks

Tier & element fusion compatibility

Fusion success-rate calculation

Consuming fusion shards

Updating fusion success/failure counters

Updating times_fused

Determining fusable stacks

Result-tier computation

Handling locked/frozen maidens

New Home: FusionService

🔥 2. Combat & Power Domain

Removed from: Player, Maiden, MaidenBase
Missing logic includes:

Maiden combat power (atk/def tier scaling)

Player total_power aggregation

Class-based combat bonuses

Leader-maiden power contribution

Win-rate calculations

Damage modifiers / mitigation

Elemental combat influence

New Homes:
CombatService, PlayerPowerService, MaidenCombatService

🔥 3. Player Progression Domain (Leveling & XP)

Removed from: Player
Missing logic includes:

XP → level rules

Level-up side-effects

Adding stat points

Updating last_level_up

Unlocking progression milestones (sector, floor, tier)

New Home: PlayerProgressionService

🔥 4. Player Stat Allocation Domain

Removed from: Player
Missing logic includes:

Spending stat points

Validating stat distributions

Deriving max_energy / max_stamina / max_hp

Stat-based boosts and formulas

New Home: PlayerStatService

🔥 5. Player Resource Domain (Regeneration & Timers)

Removed from: Player
Missing logic includes:

Drop regeneration timer logic

Time-left calculations

Activity updates (last_active)

Overflow energy/stamina behavior

Safe-spending logic for auric_coin

New Home: PlayerResourceService

🔥 6. Inventory / Maiden Ownership Domain

Removed from: Maiden, Player
Missing logic includes:

Adding/removing quantities from maiden stacks

Stack merging/splitting logic

Updating collection totals

Leader-maiden selection effects

New Homes:
MaidenInventoryService, PlayerCollectionService

🔥 7. Template / Archetype Domain (MaidenBase Static Data)

Removed from: MaidenBase
Missing logic includes:

Base power computation

Tier-scaling references

Leader-effect parsing & validation

Element → emoji/color mapping

Rarity weighting logic

Display-formatting helpers

New Homes:
MaidenTemplateService, LeaderSkillService, ui/element_display.py

🔥 8. Gacha & Summoning Domain

Removed from: Player, MaidenBase
Missing logic includes:

Pity counter logic

Summon counting

Rarity-weight roll formulas

Guaranteed pull rules

Summon stats updates

New Home: GachaService

🔥 9. Analytics / Statistics Domain

Removed from: Player
Missing logic includes:

Win/loss rate computation

Drop statistics

Shard usage & earnings

Completion metrics

Combat attempt counters

Lifetime-stats summaries

New Home: PlayerAnalyticsService

🔥 10. UI / Formatting Domain

Removed from: Player, Maiden, MaidenBase
Missing logic includes:

Tier label formatting (T1/T12 etc.)

Power display formatting

Element emoji & color

Inventory display naming

Gacha result formatting

Leader-effect text formatting

New Homes:
ui/player_display.py
ui/maiden_display.py
ui/element_display.py
ui/gacha_display.py

🔥 11. Config / Game Balance Domain

Removed from: GameConfig
Missing logic includes:

Config JSON → runtime object conversion

Validation of config structure

Default fallback logic

Safe casting of config values

Balance-related parsing

New Homes:
ConfigManager, GameBalanceService