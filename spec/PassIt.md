# PassIt

**PassIt is a multiplayer comedy storytelling game where a group builds a funny story one turn at a time, with AI suggesting the next comic direction and the system randomly choosing who continues.**

## Core Concept

A round is called a **Chain**. Someone writes a short setup and brings together friends, a reusable saved group or randomly matched users who have opted in. Selected users become participants immediately, without invitations or acceptance. The round starts as soon as the initiator launches it with a valid group that meets the minimum participant count.

Each participant gets **one contribution** to the story. They read what came before, add their part and **Pass**. Passing asks the system to randomly select the next eligible member of the round group; players never choose the recipient. Every contribution becomes a permanent part of the story.

Before each pass, an LLM reads the story so far and assigns a **Motive for the next turn** from an available list, such as *Make it worse*, *Make it awkward* or *Add a plot twist*. It chooses the direction it judges most likely to produce a funny continuation. The assigned Motive is fixed: neither the passing player nor the receiving player can change it. There is no overall Chain Motive, and none is required when writing the initial setup.

For example:

> **Setup:** “I woke up in a hotel room and had no idea how I got there.”
>
> **Motive for the next turn:** 💀 Make it worse
>
> **Next contribution:** “The receptionist called to ask why I had checked in as the hotel's new owner.”
>
> **Motive assigned for the following turn:** 😂 Make it awkward

AI prepares suggestions for each turn. Players can use one, adapt it or write independently. If someone misses their turn deadline, the system submits one of those prepared suggestions as a clearly labeled AI contribution and passes the Chain on automatically. AI also creates a short, crisp title after the first pass, so the initiator only needs to supply the setup.

**Setup → Select group → Add → System assigns next Motive → Random pass → … → Finale**

Each round has configurable participation limits and deadlines. Defaults are **2 minimum / 5 maximum participants**, including the initiator, **15 minutes per turn**. An admin-controlled global maximum defaults to **20 participants**.

All Chains are **participants-only while being played**, including those formed through open matching. Once the story is finished, it can be published only if **every participant explicitly approves**. Published Chains appear in Discover, where people can enjoy the full story and like either the Chain or individual turns.

**Play with a group. Build a comedy together. Share it only when everyone agrees.**

## Motives

Each turn has a creative rule selected from the available Motive list:

- 💀 Make it worse
- 🤯 Add a plot twist
- 😂 Make it awkward
- 🌀 Make it absurd
- ❤️ Make it wholesome
- 😈 Ruin the situation
- 🦸 Save the situation
- 👤 Introduce a new character
- 🎬 End the story

### System-Assigned Motives

The system assigns every turn's Motive. An LLM reads the **setup, complete story so far, previously used Motives and remaining turns**, then selects one valid Motive from the available list that it judges most likely to create a funny continuation. It aims for comic escalation, surprise, callbacks and variety while keeping the story coherent.

- **Initial selection:** the setup requires no Motive. Before completing the first pass, the system reads the setup and assigns the receiving participant's Motive.
- **After each contribution:** the system reads the updated story and assigns the next turn's Motive before completing the handoff.
- **On pass:** the system randomly selects the next eligible participant, who receives the story and its assigned Motive. No player approval or manual Motive selection is required.
- **On an AI timeout contribution:** the same system assignment applies, and the Chain passes automatically.
- **Finale:** “End the story” is eligible only for the final remaining turn, so Motive selection cannot bypass other participants. No next Motive is needed after the last turn.

A Motive belongs to one turn and cannot be changed, rerolled or overridden by a player, including the initiator. A valid next-turn Motive must be assigned before the pass completes. The LLM must select from the supplied list, not invent a new Motive. Future themed packs may extend that list but do not allow players to choose or change an assigned Motive.

Store the assigned **motive_id** on each turn.

## AI Assistance

The LLM is centrally configurable by administrators, with a default model deployment and optional task-specific configurations. Players do not choose the model. Configuration details are defined in [PassIt-Data.md](PassIt-Data.md) and [PassIt-Architecture.md](PassIt-Architecture.md).

AI helps users participate through optional suggestions and automatically fills a turn when its participant misses the submission deadline.

When a turn is assigned, AI automatically prepares suggestions based on the **story so far + current Motive**, even if the participant never opens the app. Those suggestions are available to the participant during their turn. The system designates one of them as the timeout fallback.

For example:

**Current Motive: Make it worse**

AI suggestions:

- “Your boss walks into the room.”
- “You realize you're live-streaming.”
- “Your phone starts ringing. It's your ex.”

The user can use a suggestion, modify it or write something completely independently.

AI suggestions are retained temporarily on the server for the active turn, together with the designated fallback, so the same text can be submitted if the participant does not respond. On completion, keep only the final contribution and discard unused suggestions. There is no permanent suggestion history. Each human-submitted turn records an **ai_assisted** flag indicating whether the participant used an AI suggestion, including a suggestion they edited. Merely requesting suggestions does not set this flag. The final submitted text is stored as part of the turn. A separate **ai_generated** flag identifies automatic timeout contributions; these are stored as final story content, not as suggestions.

AI can also help users create funny Chain setups. System-led Motive selection and automatic title generation are part of the core game, separate from optional writing suggestions.

### Automatic Chain Titles

The initiator does **not** create or enter a title. After the **first successful pass** (the initial handoff from the initiator), AI generates a **short, crisp comedy title** based on the setup and story content available at that point. The title should capture the premise without inventing story events.

Before generation completes, the interface uses a temporary label such as **“Untitled Chain”**. The generated title is stored on the Chain and used in its story view, discovery card and sharing presentation. It is generated once after the first pass, not regenerated after every contribution. Retries must not overwrite an already saved title or block the next participant's turn.

## Creating & Publishing Chains

Any user can create a Chain.

The creator defines:

**Setup + Chain Rules + Participant Group + Turn Timeout + Minimum Participants (default: 2) + Maximum Participants (default: 5)**

The creation form has neither a title input nor an overall Motive setting. The system assigns the first next-turn Motive when preparing the initial pass; the initiator cannot change it. AI creates the Chain's title after that first pass.

Recruitment and publication are independent concepts. Avoid using **public/private** to describe how players are recruited.

| Dimension | Options |
| --- | --- |
| **Recruitment** | **Friends / saved group:** directly selected participants. **Open matching:** randomly selected users who opted in to automatic random-group participation. |
| **Visibility** | **Participants-only** by default. **Published:** visible in Discover and shareable publicly, only after unanimous approval. |
| **Publication status** | **Not requested**, **awaiting approvals**, **approved** or **rejected**. |

Open matching does not make a story publicly visible or let spectators join freely. Every active Chain is participants-only, regardless of recruitment mode. A finished Chain also stays participants-only unless the publication process succeeds.

### Publication & Unanimous Approval

After a Chain finishes, any participant may request publication. Each participant must explicitly approve publication of the finished story, including the initiator and any participant whose turn was completed automatically by AI. Requesting publication records the requester's explicit approval; other participants approve separately.

- Publication starts as **not requested** and becomes **awaiting approvals** when requested.
- Only approval from **every participant** changes publication status to **approved** and visibility to **published**.
- No response is not consent. While any approval is missing, the Chain stays participants-only.
- If anyone declines, publication status becomes **rejected** and the Chain stays participants-only.

Approvals apply to the completed, immutable story. Being added to a round, random-matching opt-in and saved-group membership never count as publication consent. Only published Chains appear in public discovery or provide publicly accessible story links.

## Participant Groups & Round Start

Every Chain is played within a **group defined before play begins**. Selected users are added directly to the round: there are **no invitations, acceptance steps or acceptance deadlines**. All recruitment modes remain participants-only during play.

The initiator forms the group in one of three ways:

- **Friends:** selects people from their friends list.
- **Saved group:** selects a reusable group to add its members to a new Chain.
- **Random group:** the system selects users who have explicitly enabled **“Allow random group participation”**. This opt-in allows automatic inclusion in randomly formed rounds, without a separate acceptance step.

The minimum defaults to **2 participants** and the per-Chain maximum to **5**, both including the initiator. The admin-controlled global maximum defaults to **20**. Validate **2 ≤ minimum participants ≤ Chain maximum ≤ global maximum** and the actual selected group size before launch. The initiator occupies one place and cannot be added twice.

Friend and saved-group selection must fit the configured maximum. If a saved group is larger, the initiator must choose a subset or increase the maximum within the admin cap; the system must not silently truncate it. Random matching fills up to the configured maximum from eligible users. If too few users are available to meet the minimum, the round cannot start until a valid group is formed.

Once the initiator launches a round with a valid group, it starts immediately, with no acceptance waiting period. Membership and settings are fixed for that round. Users receive round and turn notifications according to their notification preferences; notifications do not require acceptance. When a participant is assigned a turn, its timeout begins. If they do not contribute in time, AI completes that turn and the round continues automatically.

### Reusable Groups & Quickstart

Users can create named, reusable groups by selecting friends. The group owner can rename a group and add or remove members. Members can leave a saved group.

**Quickstart:** select a saved group, enter a setup, review settings and launch. Defaults are 15 minutes per turn, a minimum of 2 and a maximum of 5 participants, including the initiator, subject to the global cap of 20 by default. No title or Chain-wide Motive is required.

Each round is a **new Chain** with its own participants, turns, story and likes. A saved group is a selection shortcut, not shared game state. At launch, membership is copied into the Chain's participant records. Later group changes do not alter an existing round.

## Playing a Chain

Each participant:

1. is added to the round and receives the Chain when assigned their turn,
2. sees the story so far,
3. sees the current Motive,
4. gets one contribution,
5. can optionally use AI suggestions,
6. submits their contribution,
7. passes the Chain, prompting the system to assign the next turn’s Motive and randomly select the next eligible person within the round group.

**Pass** means handing the turn back to the system: the user does not choose the recipient. The system randomly selects the next participant from round group members who have not yet used their turn. This applies to friend-selected, saved and randomly formed groups. Each participant gets one contribution per Chain; once no eligible participants remain, the Chain ends.

Previous contributions cannot be changed.

### Timeouts & AI-Generated Turns

Each Chain has one **turn timeout**, defaulting to **15 minutes**. The initiator may configure a positive duration before launch; it stays fixed once the round starts. There is no participation-acceptance timeout.

The timer starts when the system assigns a participant their turn. The participant sees the deadline and the automatic AI fallback rule. If no contribution has been submitted by that deadline, the system submits the designated suggestion already prepared for that turn, then passes the Chain automatically. It does not generate a new continuation at timeout.

An **AI-generated turn** uses the exact text of one of the AI suggestions prepared for that participant, based on the story so far and the assigned Motive. It occupies the timed-out participant's existing turn, is clearly labeled **“AI-generated · participant timed out”**, and is not presented as text written by that participant. It can be liked like any other completed turn.

The automatic contribution consumes that participant's turn. They cannot submit late, replace the generated text or receive another turn in that Chain. After the AI contribution is saved, the system randomly selects the next eligible participant. If none remain, the Chain ends.

Each turn stores **assigned_at**, **deadline_at**, **submitted_at**, contribution text, **ai_assisted**, **ai_generated** and a status such as **pending**, **generating** or **submitted**. Human submissions have `ai_generated = false`; timeout contributions have `ai_generated = true` and `ai_assisted = false`, distinguishing automatic authorship from human use of suggestions.

The system accepts at most one final contribution per turn. When the deadline expires, it closes human submission and commits the designated prepared suggestion. Retries must not create duplicate contributions or pass the Chain more than once; the Chain advances only after that contribution is saved. Suggestion preparation runs independently of user activity and is retried on failure. If no prepared suggestion is available at expiry, the turn remains awaiting preparation; once the set is available, the designated suggestion is committed automatically.

## Discover

PassIt has a public discovery feed for **finished, published Chains with unanimous participant approval**. Active Chains and unpublished finished Chains do not appear in this feed.

Users can browse:

**🔥 Trending · ✨ New · 😂 Awkward · 🌀 Absurd · 🤯 Plot Twists**

All Chains are comedy-focused; these categories highlight different styles of funny stories. Discovery cards show finished, published stories. The chronological story shows the Motive used for each turn. There is no overall Chain Motive.

A Chain card could look like:

**The Worst First Date Ever**

😂 Awkward comedy

> “Everything was going perfectly until he said…”

👥 27 contributors\
❤️ 12.4K likes\
🔗 26 passes

Users can open the Chain and experience the complete story chronologically.

They can **like the Chain as a whole** and **like individual submitted turns** without interfering with the active storytelling. Chain likes and turn likes are separate; liking a turn does not automatically like its Chain. Each user can like each Chain or submitted turn once and can remove their like.

## Finished Chains

Once a Chain ends, it becomes a finished story retained for its participants. It becomes public community content only after unanimous publication approval.

**The Worst First Date Ever**\
Comedy Chain\
👥 34 contributors · ❤️ 24K likes

Once published, the complete story remains discoverable and can continue spreading through likes and sharing even though no more turns can be added. Unpublished finished stories remain participants-only.

## Core Product Loop

**Discover → Create/Receive → Add → Pass → Discover**

There are therefore two ways to use PassIt:

**Player:** actively contributes to Chains.

**Viewer:** browses, reads/watches and likes entertaining Chains.

A viewer can become a player by creating a Chain or being added to a round through friends or a saved group. Enabling random group participation also makes them eligible for automatic inclusion in randomly formed rounds.

## Data Model & Architecture

See [PassIt-Data.md](PassIt-Data.md) for entities, relationships and typed settings. See [PassIt-Architecture.md](PassIt-Architecture.md) for the proposed Azure deployment and processing flows.

## Settings

User settings and admin configuration fields are defined in [PassIt-Data.md](PassIt-Data.md).

### Chain Settings

Store game-specific settings directly on **Chain**:

- **Recruitment mode:** friends / saved group or open matching. Every mode adds participants directly, without invitations.
- **Group selection mode:** friends, saved group or random; retain the source group reference when using a saved group.
- **Turn timeout:** positive duration, default **15 minutes**; determines each turn's deadline from assignment and triggers an automatic AI contribution on expiry. The initiator may change it before the round starts.
- **Minimum participants:** defaults to 2, including the initiator.
- **Maximum participants:** defaults to 5, including the initiator; configurable before the round starts, no lower than the minimum and no higher than the admin global cap.

There is no **Chain-level Motive** field or initial Motive setting. Each turn stores its own Motive, determined before the preceding pass: the system assigns one from the available list, and players cannot change it.

**Visibility** is a controlled publication outcome, not a creator toggle: every Chain starts participants-only and becomes published only after completion and unanimous approval. Store publication status separately from gameplay lifecycle status, together with the publication requester and request/publication timestamps.

Persist these values when creating the Chain. If user-level defaults are introduced later, changing those defaults must not change existing Chains. A generic **Settings** key-value entity is not needed.

## Monetization

See [PassIt-Monetization.md](PassIt-Monetization.md) for the monetization proposal and related entities.

## Positioning

**PassIt — Stories nobody writes alone.**

PassIt combines **social chains, improv comedy, collaborative storytelling, AI-directed Motives, optional AI writing assistance and entertainment discovery** into a lightweight multiplayer comedy game.
