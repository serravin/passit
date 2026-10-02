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
- AI calls, failures, retries, median latency, tokens, estimated USD cost, and cost per completed story. Validation and demo calls are identified separately.

An **active player** creates a story or submits a human contribution; creator setup counts. Browsing, signing in, likes, and automatic fallback contributions do not count. Activation measures the selected signup cohort's first play by the period end. Retention groups players by first play in the selected period and checks for another play on the exact local day 1, 7, or 30 afterward, including returns after the selected period. Only fully elapsed return days enter the denominator. The funnel follows stories started in the selected period through its end; completed/published headline counts instead measure events occurring in that period. Zero-denominator rates are unavailable.

For AI cost estimates, enter both input/output USD prices per million tokens when creating an AI profile revision in **Configuration**. The server records the response token usage and those revision prices for each call, including billable responses whose generated content fails validation. This is a token-cost estimate, not an Azure invoice. Calls without reported usage or prices make the associated totals unavailable. Demo calls cost zero. Cost per completed story uses recorded game calls across each completed story's lifetime and requires complete coverage of its linked calls. Setup assistance happens before a story exists, so its cost appears in the total AI cost without being attributed to a completed story. Analytics records operational metadata only, without copying prompts, responses, names, or story text.

The migration preserves existing stories and backfills completion times from final submitted turns. Unknown historical signup, like, job, and setup-assistance information remains unknown; the dashboard explains missing history rather than inventing dates or costs. Dated like counts include likes still retained, and failed jobs reflect the current status of jobs created in the range. All-time account/story totals describe currently stored records. Revenue, paying users, paid conversion, MRR, and cancellations show **Unavailable** until a payment integration exists. Growth/acquisition metrics are excluded.

Reporting currently aggregates stored metadata in memory; a large production dataset will need indexed database aggregation or rollups. Deploy the new migration before starting the updated API and worker. Docker Compose runs migrations automatically for the local demo.

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22+.

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
npm --prefix frontend run build
```

All 39 backend tests have been run against SQLite and PostgreSQL 17, including concurrent human submissions, timeout races, duplicate jobs, expired leases, concurrent workers/reconcilers, publication decisions, private reads, production JWT validation, admin authorization, analytics periods/cohorts, AI usage/cost recording, and preservation of legacy data during migration. PostgreSQL tests require a **dedicated disposable database**: fixtures recreate its application tables. Set `PASSIT_TEST_DATABASE_URL` to its SQLAlchemy URL, then run the same pytest command.

To exercise the complete UI, leave the development API, worker and web server running, install a Playwright Chromium browser (or set `PLAYWRIGHT_CHROMIUM_PATH` to your existing Chromium), then run:

```sh
.venv/bin/playwright install chromium
.venv/bin/python backend/tests/browser_smoke.py
.venv/bin/python backend/tests/browser_languages.py
.venv/bin/python backend/tests/browser_statistics.py
```

The smoke test creates fictional demo stories and verifies creation, suggestion editing, draft retention, passing, separate publication approvals, discovery, outsider access, and the mobile layout. It saves screenshots under `/tmp`. The language smoke test checks all three translations, responsive layouts, saved preferences, account switching, draft retention, notifications, and error messages. The dashboard smoke test checks custom dates, presets, timezones, comparisons, charts, saved ranges, translations, mobile layouts, AI price controls, and administrator access restrictions. The CI workflow runs backend tests on both databases, a client build, and all three browser workflows; these checks have been validated locally.

## Implementation and deployment boundaries

The core includes friend selection, saved group snapshots, opted-in random matching, random recipient assignment, immutable per-turn Motives, private reads, prepared timeout fallback, asynchronous titles, separate Chain/turn likes, in-app notifications, explicit unanimous publication, and versioned admin AI profiles with validation and revision-pinned work.

The local durable job table acts as a transactional outbox and delivery transport. Workers claim leased jobs, retry with backoff, expose failures to admins, recover expired leases, and reconcile overdue turns. This implementation does **not** yet use Azure Service Bus. A broker transport and Azure infrastructure provisioning are separate deployment work. No Azure resources are created by running this application.

The demo uses sample creative text, rather than a live LLM. Real AI is provided through the Azure adapter once configured. Polling and deadline acceptance use server timestamps; the browser timer accounts for client clock differences. Suggestions are visible only to the assigned player and removed when the contribution is committed. Background payloads contain identifiers rather than story or suggestion text.

Production requires PostgreSQL and configured OIDC bearer authentication. See `.env.example`. Run migrations as a controlled step, then `python -m passit.manage seed` to initialize the Motive catalog and platform settings without demo accounts. The React client supports authorization-code login with PKCE using `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, and `VITE_OIDC_SCOPE` (include your API scope); `VITE_API_URL` selects a separate API origin. Configure the API's issuer, audience, JWKS URL, and explicit admin subjects. Serve the client over HTTPS and route `/auth/callback` to `index.html`.

For Azure AI, allow the resource host with `PASSIT_AI_ALLOWED_HOSTS`, create a profile in Admin, test its four task schemas, then activate it. The adapter supports Azure OpenAI chat completions with structured output, managed identity, or the server-side `PASSIT_AI_API_KEY` reference. Credentials never belong in a profile or client code. Models must support JSON-schema structured output and the configured generation parameters. Actual Azure connectivity needs your deployment and credentials; the local demo does not validate it.

Monetization is intentionally deferred as proposed in the rollout specification. Account deletion, paid features, export themes, push notifications, Azure messaging, infrastructure, backup/restore operations, and production load/security hardening remain follow-up work. SQLite is for local development; validate deployment concurrency against PostgreSQL.
