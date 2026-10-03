# PassIt

Stories nobody writes alone. A responsive React client, FastAPI API, SQLAlchemy persistence, and a durable Python worker implement the comedy storytelling loop described in `spec/`.

## Test locally with Docker

The demo accepts both `http://localhost:8080` and `http://127.0.0.1:8080`. Origin checks require the configured scheme and port; production accepts only `PASSIT_ORIGIN`.

With Docker Desktop (or Docker Engine and Compose v2) running:

```sh
git clone https://github.com/serravin/passit.git
cd passit
docker compose up --build -d
```

Open `http://localhost:8080` on your computer. Choose a fictional player and switch players to play the other turns. No API keys are required: this setup uses sample AI text. View logs with `docker compose logs -f`; stop with `docker compose down`. Stories persist in the `stories` named volume. Removing that volume with `docker compose down -v` deletes the Docker demo stories. To change the port, set `PASSIT_DOCKER_PORT` before starting Compose.

The images contain the application dependencies; you do not need to install Python, Node or npm packages on your computer. Containers run as non-root users with read-only root filesystems, dropped capabilities and no elevated privileges. Only the web port is published, on loopback. The API and worker use an internal network; the web container also joins a bridge network so Docker can publish its localhost port. The application has no host-folder or Docker-socket mounts. Python installation uses the frozen uv lockfile and binary wheels; npm uses the lockfile and disables dependency install scripts. Base images are the official Python, Node and Nginx images. The optional `docker/compose.proxy.yaml` supplies CA trust for managed cloud builds and is unnecessary on a normal local machine.

On 1 October 2026, `npm audit` reported zero known advisories in the locked JavaScript dependencies, and `pip-audit` reported none in the 34 applicable Python runtime dependencies. These checks do not establish that all software is harmless, detect every malicious package, or audit the operating-system packages in the base images. Compose configuration was validated; the image build could not be executed in the cloud environment because Docker Hub downloads were rate-limited and the alternate registry was blocked. Keep Docker and base images updated; this Compose file is a local demo, not a production deployment.

## Languages

The interface supports English, German, French, and Italian. Use the language selector in the header for an immediate change, or choose a language in Settings and save preferences. Guests start with their browser’s supported language; explicit choices persist in the browser. Signed-in players save their choice to their account, which takes precedence at sign-in.

Navigation, game controls, forms, notifications, Motives, accessibility labels, and admin screens are translated. Story titles, contributions, rules, and group names retain their original text. Switching the interface language does not translate stored AI continuations; the local demo generator still supplies English samples. Translation catalogs are in `frontend/src/locales/`; English UI strings act as keys and fallbacks. No extra runtime dependencies are required.

## Admin statistics

Open **Settings → Admin dashboard**. In the local demo, Alex is the administrator. In production, set `PASSIT_ADMIN_SUBJECTS` to the comma-separated OIDC subject IDs allowed to administer the platform. Both the dashboard and `GET /api/admin/statistics` require an administrator; hiding the menu is not the access control.

Choose custom inclusive start/end dates or Today, This week, MTD, YTD, Last 7 days, Last 30 days, or All time. Select an IANA reporting timezone such as `Europe/Berlin`; the range is saved in your browser. Weeks start on Monday. Comparisons use the previous equivalent period, including the same elapsed local day for ranges ending today; MTD compares the previous month to the same day, and YTD the previous year. All time has no comparison. Refresh retrieves a new snapshot.

The dashboard includes:

- Activity, recorded signups, started/completed/published stories, contribution types, average cast size, and the started-story completion funnel.
- Activation rate and median time to first play, D1/D7/D30 retention, repeat players, repeated casts, and stories per active player.
- Median response/completion times, timeout rates by allowed turn duration, publication decisions, retained likes, and background failures.
- AI calls, guardrail checks, failures, retries, median latency, tokens, estimated USD cost, and cost per completed story. Validation and demo calls are identified separately.

An **active player** creates a story or submits a human contribution; creator setup counts. Browsing, signing in, likes, and automatic fallback contributions do not count. Activation measures the selected signup cohort's first play by the period end. Retention groups players by first play in the selected period and checks for another play on the exact local day 1, 7, or 30 afterward, including returns after the selected period. Only fully elapsed return days enter the denominator. The funnel follows stories started in the selected period through its end; completed/published headline counts instead measure events occurring in that period. Zero-denominator rates are unavailable.

For AI cost estimates, enter both input/output USD prices per million tokens when creating an AI profile revision in **Configuration**. The server records the response token usage and those revision prices for each call, including billable responses whose generated content fails validation. This is a token-cost estimate, not an Azure invoice. Calls without reported usage or prices make the associated totals unavailable. Demo calls cost zero. Cost per completed story uses recorded game and guardrail calls across each completed story's lifetime and requires complete coverage of its linked calls. Setup assistance and setup checks happen before a story exists, so their costs appear in the total AI cost without being attributed to a completed story. Analytics records operational metadata only, without copying prompts, responses, names, or story text.

The migration preserves existing stories and backfills completion times from final submitted turns. Unknown historical signup, like, job, and setup-assistance information remains unknown; the dashboard explains missing history rather than inventing dates or costs. Dated like counts include likes still retained, and failed jobs reflect the current status of jobs created in the range. All-time account/story totals describe currently stored records. Revenue, paying users, paid conversion, MRR, and cancellations show **Unavailable** until a payment integration exists. Growth/acquisition metrics are excluded.

Reporting currently aggregates stored metadata in memory; a large production dataset will need indexed database aggregation or rollups. Deploy the new migration before starting the updated API and worker. Docker Compose runs migrations automatically for the local demo.

## Blocking users

Open **Settings → Admin dashboard → Manage users** (Alex in the demo). Search by name or exact account ID, filter all/active/blocked accounts, and select **Block** or **Unblock**. Review the account in the confirmation dialog and optionally add a private reason of up to 500 characters. Administrators cannot block themselves or other administrators. Production uses the current `PASSIT_ADMIN_SUBJECTS` allowlist to protect administrator accounts.

Each authenticated request checks the stored account block, so existing demo sessions and valid OIDC tokens cannot bypass it. A blocked session sees an account-blocked screen when its next request is denied; the client checks notifications every five seconds while signed in. A request already admitted before the block may finish. Sign out remains available, and public stories can still be viewed anonymously. Identity provider authentication remains managed by Entra; the block denies access to PassIt. Unblocking restores access, including an otherwise valid existing session; reload or sign in again to leave the blocked screen.

Blocked accounts are excluded from user search, friend selection, and new random casts. New stories or groups cannot include them; a saved group containing a blocked account needs an available subset. Existing stories and contributions remain stored. Their assigned turns use the normal deadline and prepared automatic fallback, and publication continues to require each participant's explicit consent. A blocked participant's pending approval stays pending until they are unblocked and can decide.

Block/unblock changes are recorded with the administrator, target account, timestamp, and private reason. Repeated identical requests create one action. The admin screen shows the latest 20 actions; the database retains the complete history. Only administrators can access this history, reasons, or the management API (`GET /api/admin/users`, `PUT /api/admin/users/{id}/block`, and `GET /api/admin/moderation`). The new migration leaves existing accounts unblocked and preserves their stories. No additional dependencies are required.

## Story safety guardrail

The guardrail checks setup text, rules and human contributions before acceptance; generated setups, suggestions, timeout fallbacks and titles before delivery; and complete stories before publication. It assesses each candidate using bounded context for bullying/harassment, hate, threats, sexual exploitation/abuse, private personal information and encouragement of self-harm. Its instructions support English, German, French and Italian and allow ordinary fictional comedy and profanity alone.

**Every flagged human submission blocks its author immediately**, without a confidence threshold. Rejected text never enters the story. Flagged existing stories are withheld from participant views and discovery. Other authors are not blamed for earlier text, and unsafe AI output is withheld without blocking its recipient. Server records establish the origin of unchanged AI text; a request claiming AI assistance does not exempt human text. Administrator accounts remain protected from account blocks, while their flagged text is withheld for review. Missing configuration, outages and malformed model responses hold content without banning users.

Users receive a persistent **in-app notice** containing the category and instructions to contact an administrator; no email is sent. Blocked identities can read and acknowledge their own notices through `/api/account-status` and `/api/account-notices/{id}/read`. Administrator reasons and evidence stay private. Open **Settings → Admin dashboard → Safety reviews** to inspect evidence and allow a false positive or confirm a flag. Allowing restores an automatic block only after all that user's human flags are cleared; independent administrator blocks remain in place. The worker rechecks approved flagged stories, rejected submissions can be resubmitted, and publication still needs unanimous consent. Decisions record the reviewer and time. Flagged text and bounded context are retained for administrators; allowed checks retain metadata and hashes without copying private text.

For production, create and validate an Azure OpenAI profile in **Configuration**, then activate it for **guardrail** explicitly. The creative default does not supply production safety checks automatically. The guardrail can use a separate model, deployment and credential reference. Configure `PASSIT_AI_ALLOWED_HOSTS`, use a model supporting JSON-schema structured output, and give both API and worker access through managed identity or a server-side environment secret such as `PASSIT_AI_API_KEY`. On Azure Container Apps, reference the secret in each service's environment. Validation exercises all five task schemas plus harmless and abusive guardrail samples. Live Azure moderation was not tested here because deployment credentials are unavailable. Model errors remain possible; use administrator review to correct false positives.

Run the migration before starting the updated API and worker. Existing stories become pending and leave public discovery until checked. Unfinished suggestions are regenerated with original deadlines preserved; hashes identify copied older AI drafts. Changing the guardrail profile also rechecks approved stories and regenerates unfinished suggestions, preserving completed text and assigned Motives. Keep the worker running and retry failed safety jobs through Configuration after resolving their cause. Guardrail usage and estimated costs appear in statistics; cost per completed story includes linked game and guardrail calls. Setup checks occur before a story exists and contribute only to total AI cost.

The local demo recognizes only the explicit fictional marker `[[demo:bullying]]` to exercise blocking and review. It **does not detect real inappropriate text**. No new runtime libraries were added.

## Azure image publication and deployment

Create your Azure resources manually and follow [the Azure/GitHub setup guide](docs/azure-test-deployment.md). The build pipeline runs **linting → testing → source security scan → image build → image scan → registry push**, stopping on failed checks or HIGH/CRITICAL Trivy findings. Feature branch pushes publish `snapshot-YYYYMMDD-SHORT_SHA-rRUN_ID-aATTEMPT` versions to your configured **Azure Container Registry**; `main` publishes `release-YYYYMMDD-SHORT_SHA-rRUN_ID-aATTEMPT`. Pull requests receive checks without publication.

Use **Actions → Deploy selected image → Run workflow** on `main` to choose snapshot/release, paste an existing image tag and select a GitHub Environment. Deployment uses locked registry digests, waits for migration success, updates existing apps and verifies the new revisions and runtime sign-in configuration. No deployment starts automatically from a merge. Each environment supplies its own Azure resources and public Entra settings; the same web image works across environments without rebuilding.

[AGENTS.md](AGENTS.md) requires feature branches and PRs for all agent changes to `main`. Configure GitHub branch protection to enforce this for all contributors. The registry publishing identity and per-environment deployment identities use separate OIDC permissions, as described in the guide.

Local workflow/configuration checks, backend/deployment tests, frontend checks and browser startup passed. The Docker web image also builds and passes its read-only container startup check. Full image/dependency scans still need to pass on GitHub; the cloud network policy blocked Trivy's vulnerability database during earlier validation. No Azure deployment was performed here.

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22.13+ (CI uses Node 24).

```sh
bash scripts/install.sh
bash scripts/dev.sh
```

The startup helper runs all three components and shuts them down together. Alternatively, run these in separate terminals from the repository root:

```sh
.venv/bin/uvicorn passit.api:app --host 127.0.0.1 --port 8000
.venv/bin/python -m passit.worker
npm --prefix frontend run dev
```

Open the frontend on port 5173. The default is an explicitly labeled local demo: five fictional accounts, pre-established friendships, and sample creative continuations. Use “Choose a player” / “Switch player” to play each participant's turn and approve publication separately. Demo identity and AI are for local development only. Data persists in the ignored `passit.db`; the background worker must run for handoffs and timeouts.

The creator's setup counts as their one contribution. Human submission and passing are a single **Submit & Pass** command. These resolve the two open product decisions in the specifications.

## Validation

```sh
.venv/bin/pytest -q
.venv/bin/ruff check backend
npm --prefix frontend run lint
npm --prefix frontend run format:check
npm --prefix frontend run build
```

All 94 backend/deployment tests have been run against SQLite and PostgreSQL 17, including concurrent human submissions, timeout races, duplicate jobs, expired leases, concurrent workers/reconcilers, publication decisions, private reads, production JWT validation, admin authorization, blocking with existing sessions and tokens, concurrent blocks, analytics, AI usage/cost recording, and legacy migrations. Guardrail tests cover automatic bans, notices, false-positive reversal, human/AI attribution, outages, malformed responses, profile changes during inference and deadline enforcement. Deployment tests cover migration failure/concurrency, image digest pinning, production/authentication checks, unhealthy revisions, secret-safe errors, existing resource validation, snapshot/release selection, locked paired publications, overwrite prevention, registry-only bootstrap, readable/legacy tags and isolated GitHub summaries. Container smoke regression tests cover transient connection resets, exited containers, readiness timeouts and failed callback checks. PostgreSQL tests require a **dedicated disposable database**: fixtures recreate its application tables. Set `PASSIT_TEST_DATABASE_URL` to its SQLAlchemy URL, then run the same pytest command.

To exercise the complete UI, leave the development API, worker and web server running, install a Playwright Chromium browser (or set `PLAYWRIGHT_CHROMIUM_PATH` to your existing Chromium), then run:

```sh
.venv/bin/playwright install chromium
.venv/bin/python backend/tests/browser_smoke.py
.venv/bin/python backend/tests/browser_languages.py
.venv/bin/python backend/tests/browser_statistics.py
.venv/bin/python backend/tests/browser_user_blocking.py
.venv/bin/python backend/tests/browser_guardrails.py
```

The smoke test creates fictional demo stories and verifies creation, suggestion editing, draft retention, passing, separate publication approvals, discovery, outsider access, and the mobile layout. It saves screenshots under `/tmp`. The language smoke test checks all three translations, responsive layouts, saved preferences, account switching, draft retention, notifications, and error messages. The dashboard smoke test checks custom dates, presets, timezones, comparisons, charts, saved ranges, translations, mobile layouts, AI price controls, and administrator access restrictions. The moderation smoke test checks search, confirmation, private action history, live blocked sessions, login denial, unblocking, translations, mobile layouts, and administrator-only controls. The guardrail smoke test checks automatic blocks, persistent notices, administrator reversal, notice acknowledgement, translations, mobile layouts and private review access. The CI workflow runs backend tests on both databases, a client build, and all five browser workflows; these checks have been validated locally.

## Implementation and deployment boundaries

The core includes friend selection, saved group snapshots, opted-in random matching, random recipient assignment, immutable per-turn Motives, private reads, prepared timeout fallback, asynchronous titles, separate Chain/turn likes, in-app notifications, explicit unanimous publication, and versioned admin AI profiles with validation and revision-pinned work.

The local durable job table acts as a transactional outbox and delivery transport. Workers claim leased jobs, retry with backoff, expose failures to admins, recover expired leases, and reconcile overdue turns. This implementation does **not** yet use Azure Service Bus. A broker transport and Azure infrastructure provisioning are separate deployment work. No Azure resources are created by running this application.

The demo uses sample creative text, rather than a live LLM. Real AI is provided through the Azure adapter once configured. Polling and deadline acceptance use server timestamps; the browser timer accounts for client clock differences. Suggestions are visible only to the assigned player and removed when the contribution is committed. Background payloads contain identifiers rather than story or suggestion text.

Production requires PostgreSQL and configured OIDC bearer authentication. See `.env.example`. Run migrations as a controlled step, then `python -m passit.manage seed` to initialize the Motive catalog and platform settings without demo accounts. The React client supports authorization-code login with PKCE using `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, and `VITE_OIDC_SCOPE` (include your API scope); `VITE_API_URL` selects a separate API origin. Configure the API's issuer, audience, JWKS URL, and explicit admin subjects. Serve the client over HTTPS and route `/auth/callback` to `index.html`.

For Azure AI, allow the resource host with `PASSIT_AI_ALLOWED_HOSTS`, create a profile in Admin, validate its five task schemas, then activate the creative default and an explicit guardrail assignment. The adapter supports Azure OpenAI chat completions with structured output, managed identity, or the server-side `PASSIT_AI_API_KEY` reference. Credentials never belong in a profile or client code. Models must support JSON-schema structured output and the configured generation parameters. Actual Azure connectivity needs your deployment and credentials; the local demo does not validate it.

Monetization is intentionally deferred as proposed in the rollout specification. Account deletion, paid features, export themes, push notifications, Azure messaging, infrastructure, backup/restore operations, and production load/security hardening remain follow-up work. SQLite is for local development; validate deployment concurrency against PostgreSQL.
