📘 Social Models — Missing Logic Manifest (Grouped by Domain)
🔥 1. Guild Core Logic (Guild Model)

Missing business logic includes:

Creating a guild (validation, treasury creation)

Disbanding a guild

Renaming / updating emblem

Managing level / experience curves

Treasury deposits / withdrawals

Guild upgrade tree logic

Calculating max_members from upgrades

Applying guild perks (xp_boost, income_boost, etc.)

Activity log management (capping, formatting, privacy rules)

Guild leaderboard participation

Permissions (owner/officer/member restrictions)

➡️ New Homes:
GuildService, GuildPerkService, GuildEconomyService

🔥 2. Guild Membership Logic (GuildMember)

Missing logic includes:

Joining a guild

Leaving a guild

Kicking a member

Role promotions/demotions

Calculating contribution value

Updating guild member_count

Synchronizing guild first-time join rewards

➡️ New Homes:
GuildMemberService, GuildPermissionService

🔥 3. Guild Invite Logic (GuildInvite)

Missing logic includes:

Creating invites

Auto-expiration

Revoking invites

Restricting duplicate invites

Maximum pending invites per guild/player

Validation (target already in guild, guild full, banned users)

Acceptance → member creation

Logging into audit table

➡️ New Home:
GuildInviteService

🔥 4. Guild Audit Logic (GuildAudit)

Missing logic includes:

Audit entry creation

Filtering and querying audit history

Rollback reconstruction rules

Security hashing or signature (if any)

Auto-clean of old audits

Display formatting for UI

➡️ New Home:
GuildAuditService

🔥 5. Guild Role / Permission Logic (GuildRole)

Missing logic includes:

Permission trees per role

Action gating (officers vs leader)

Config-driven permissions

Mapping role → allowed actions

Role validation on promotions/demotions

➡️ New Home:
GuildPermissionService