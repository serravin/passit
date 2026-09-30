# PassIt — Data Model

Status: conceptual model; field names and constraints below guide implementation, not a completed database migration. Product behavior is defined in [PassIt.md](PassIt.md). Deployment is described in [PassIt-Architecture.md](PassIt-Architecture.md).

## Core Entities

| Entity | Purpose |
| --- | --- |
| **User** | User identity and profile. |
| **User Settings** | One-to-one settings record with typed columns for random-group opt-in, notifications and language. |
| **LLM Configuration** | Versioned, admin-managed connection and generation profiles, with a default profile and optional task-specific assignments. |
| **Platform Settings** | Admin-managed, typed global configuration, including the maximum participants allowed per Chain (default 20). |
| **Friendship** | Friendship relationship between two users. |
| **Group** | Named, reusable group with an owner, used to quickly add the same people to new rounds. |
| **Group Member** | Links a user to a reusable group; each user can appear only once per group. |
| **Chain** | AI-generated title (empty until generated after the first pass), setup, visibility, lifecycle status, turn timeout, minimum and maximum participants and rules. |
| **Motive** | Creative rule selected by the LLM from the available list and assigned immutably to a turn; players cannot change it. |
| **Chain Participant** | Links a user to a Chain and tracks round membership and participation status; no invitation or acceptance state. |
| **Publication Approval** | One decision per participant per Chain: pending, approved or rejected, with a decision timestamp. Publication requires unanimous approval. |
| **Turn** | Assigned participant, position, **motive_id**, status, assignment/deadline/submission timestamps, contribution text, **ai_assisted** and **ai_generated** flags, plus temporary suggestion data and a designated fallback for the active turn. The contribution is part of the turn, not a separate entity. |
| **Like** | A user's like on either a Chain or an individual submitted turn. Each like targets exactly one of these, with one like per user per target. |

An assigned turn can exist before submission, with no contribution text yet. Once submitted, its contribution cannot be changed. There is no separate **Contribution** or permanent **AI Suggestion** entity: each turn has at most one contribution. Suggestions and the designated fallback are temporary turn data, retained until completion and then removed; the chosen final contribution remains.

**Group** and **Group Member** store reusable membership. **Chain Participant** stores per-round membership and participation status. A Chain created from a saved group can retain a **source_group_id** reference, but its participant snapshot is independent of later group changes.

## Typed Settings

### User Settings

Store core user preferences in a **UserSettings** entity with explicit, typed columns rather than generic key-value pairs. Each user has one settings record.

| Field | Type | Default / Constraint |
| --- | --- | --- |
| **user_id** | UUID | Primary key and foreign key to User. |
| **allow_random_participation** | BOOLEAN | `false`; users must explicitly opt in to automatic participation in randomly formed rounds. |
| **notifications_enabled** | BOOLEAN | `true`. |
| **language** | VARCHAR | `'en'`; validate against supported language codes. |

Typed columns provide explicit defaults and validation and make it straightforward to query users eligible for random participation. An optional JSON field may be introduced later for less structured preferences; it is not required initially.

### Global Admin Settings

Store platform-wide limits as typed fields in **Platform Settings**, editable only by administrators:

| Field | Type | Default / Constraint |
| --- | --- | --- |
| **max_participants_per_chain** | INTEGER | `20`; at least 2. Caps the initiator's per-Chain maximum. |

The per-Chain **max_participants** default is `5`. If an administrator lowers the global cap below 5, new Chains use the lower cap as their effective default. Validate the current global cap again at launch. Changing the global cap does not remove participants or alter the fixed maximum of active Chains; the new cap applies to new and not-yet-started Chains.

### LLM Configuration

Administrators configure the LLM centrally; players do not select a model. Use typed, versioned **LLM Configuration** records and task-to-profile references. Start with one default profile, optionally assigning different profiles to Motive selection, turn suggestions, title generation and setup assistance.

| Field | Purpose |
| --- | --- |
| **id / revision / status** | Identify an immutable profile revision; draft, active or retired. |
| **provider** | Initially `azure_openai`; other providers require a supported adapter. |
| **endpoint** | Approved server-side service endpoint. |
| **deployment_name** | Azure deployment used for inference; not a hardcoded model name. |
| **model_reference** | Expected model/version metadata for compatibility checks and observability. |
| **api_version** | Optional, where the selected API requires it. |
| **auth_mode / credential_reference** | Managed identity or reference to a Key Vault secret; never the secret value. |
| **generation_parameters** | Validated model-supported options, such as output token limit and temperature where supported. |
| **request_timeout_seconds / max_retries** | Bounded inference timeout and retry policy, separate from the game's turn timeout. |
| **prompt_version** | Versioned prompt/template reference for the assigned task. |
| **updated_by / created_at** | Admin audit metadata. |

Validate a profile with a test call and task output-schema checks before activation. Record the selected configuration revision on each AI work item and retain non-content execution metadata. Existing queued jobs keep their resolved revision; changes apply to newly created work. Configuration changes never replace a turn's assigned Motive, prepared suggestions, designated fallback or submitted text. Do not delete revisions still referenced by pending work.

## Relationships & Integrity

Use PostgreSQL as the authoritative relational store. Use UUID identifiers and UTC timestamp fields (`timestamptz`).

| Relationship / record | Constraint |
| --- | --- |
| User → User Settings | One settings row per user; `user_id` is both PK and FK. |
| User → external identity | Unique identity-provider issuer and subject; never use email as the immutable identity key. |
| Friendship | One canonical user pair; no self-friendship. |
| Group → Group Member | Unique `(group_id, user_id)`; group has an owner. |
| Chain → Chain Participant | Unique `(chain_id, user_id)`; freeze membership at launch. |
| Chain → Turn | Unique `(chain_id, position)`; at most one active turn per Chain. |
| Chain Participant → Turn | At most one playable turn per participant, subject to the initiator/setup decision below. |
| Turn → Motive | FK to catalog item; immutable after assignment. No Chain-level Motive. |
| Publication Approval → Chain Participant | One decision per participant; default pending. |
| Like → Chain or Turn | Exactly one target FK populated; unique user per target using separate partial unique indexes. |

Use database constraints for local invariants and transactions for cross-record rules. Validate the global participant cap at launch and preserve existing active rounds when the cap changes. Reject human contributions at or after the stored deadline, using server time. Lock or conditionally update a turn so human submission and timeout completion cannot both win.

Chain configuration includes `turn_timeout_seconds` (default 900), `min_participants` (default 2), `max_participants` (default 5), group selection mode and optional source-group reference. Derive the broader recruitment label from group selection mode rather than maintaining contradictory values.

Store gameplay status separately from publication status. Publication must be granted in a transaction that verifies completion and approval by every member of the frozen participant set. All private reads must enforce membership, including reads of individual turns and their likes.

## Temporary Turn Data

Store the suggestion set and designated fallback on the active turn, for example as JSONB plus a fallback index. Persist this data server-side so worker restarts cannot lose the timeout contribution. Validate that the fallback refers to a member of the suggestion set. Only the assigned participant needs access to their suggestions.

At completion, save the final contribution and flags, then clear temporary suggestions in the same transaction. The timeout contribution must exactly match the prepared fallback. Removing active data does not instantly remove historical copies from database backups; account for the backup retention period and avoid suggestion content in logs.

## Supporting Technical Records

These are proposed implementation records, separate from product entities:

- **Outbox Event:** durable event ID, aggregate ID, event type, minimal payload, creation time and dispatch state. Written in the same transaction as the game change.
- **Processed Event:** consumer/event key for idempotent handling where conditional state transitions alone are insufficient.
- **Notification:** optional in-app delivery record with recipient, event reference and read state; never contains an invitation-acceptance workflow.

Index active turn deadlines, participant membership, publication state and published timestamps. Add indexes for likes and opted-in random participants based on measured queries. Start with PostgreSQL queries for Discover; avoid a separate search index until justified.

## Open Modeling Decisions

- Clarify whether the initiator's setup consumes their one contribution or whether they receive a later playable turn. The current product description does not settle this; do not silently encode either interpretation.
- Define whether human submission and Pass are one action. If separate, specify what advances a submitted turn when its author leaves before passing.
- Define the friendship request lifecycle and account deletion behavior separately; there is no round invitation lifecycle.

Monetization entities remain in [PassIt-Monetization.md](PassIt-Monetization.md).
