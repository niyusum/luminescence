📘 Progression Models — Missing Logic Manifest (Grouped by Domain)
🔥 1. Ascension Tower Logic (AscensionProgress)

Missing logic includes:

Calculating win rate

Determining next floor

Updating attempts, victories, defeats

Deciding floor rewards (XP, lumees)

Floor scaling formulas

Eligibility checks to attempt new floor

Record updates (highest_floor logic)

Leaderboard submission triggers

➡️ New home: AscensionService, AscensionCombatService

🔥 2. Daily Quest Logic (DailyQuest)

Missing logic includes:

Updating quest completion state

Updating progress counters

Determining daily completion

Reward distribution

Tracking streak logic

Resetting quests at UTC midnight

Auto-generating quest sets

Anti-repeat / double-claim logic

➡️ New home: DailyQuestService

🔥 3. Exploration Mastery Logic (ExplorationMastery)

Missing logic includes:

Checking rank unlock eligibility

Sequential rank validation

Awarding mastery items

Calculating mastery bonuses

Display formatting (rank badge, rank display, etc.)

Time-to-complete calculations

Updating timestamps on completion

Sector-based score aggregation for leaderboards

➡️ New home:
ExplorationMasteryService,
MasteryRewardService,
ui/mastery_display.py

🔥 4. Leaderboard Snapshot Logic (LeaderboardSnapshot)

Missing logic includes:

Generating leaderboard snapshots

Ranking computation

Sorting and rank-change calculation

Expiration & cleanup of old entries

Category-specific ranking algorithms

Formatting rank display

Formatting rank change

➡️ New home:
LeaderboardService,
LeaderboardSnapshotGenerator

🔥 5. Sector Exploration Logic (SectorProgress)

Missing logic includes:

Exploration progression formulas

XP/lumee reward calculation

Miniboss unlock & defeat rules

Determining 100% completion

Purified-maiden rewards

Updating sector unlock flow

Progress bar formatting

➡️ New home:
ExplorationService,
SectorProgressionService

🔥 6. Tutorial Logic (TutorialProgress)

Missing logic includes:

Completing tutorial steps

Validating step order

Unlocking tutorial rewards

Determining next tutorial step

Detecting full completion

Display formatting of tutorial status

Awarding onboarding rewards

➡️ New home: TutorialService