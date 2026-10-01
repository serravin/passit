# PassIt

Stories nobody writes alone. A responsive React client, FastAPI API, SQLAlchemy persistence, and a durable Python worker implement the comedy storytelling loop described in `spec/`.

## Test locally with Docker

With Docker Desktop (or Docker Engine and Compose v2) running:

```sh
git clone --branch work https://github.com/serravin/passit.git
cd passit
docker compose up --build -d
```

Open `http://localhost:8080` on your computer. Choose a fictional player and switch players to play the other turns. No API keys are required: this setup uses sample AI text. View logs with `docker compose logs -f`; stop with `docker compose down`. Stories persist in the `stories` named volume. Removing that volume with `docker compose down -v` deletes the Docker demo stories. To change the port, set `PASSIT_DOCKER_PORT` before starting Compose.

The images contain the application dependencies; you do not need to install Python, Node or npm packages on your computer. Containers run as non-root users with read-only root filesystems, dropped capabilities and no elevated privileges. Only the web port is published, on loopback. The API and worker use an internal network; the web container also joins a bridge network so Docker can publish its localhost port. The application has no host-folder or Docker-socket mounts. Python installation uses the frozen uv lockfile and binary wheels; npm uses the lockfile and disables dependency install scripts. Base images are the official Python, Node and Nginx images. The optional `docker/compose.proxy.yaml` supplies CA trust for managed cloud builds and is unnecessary on a normal local machine.

On 1 October 2026, `npm audit` reported zero known advisories in the locked JavaScript dependencies, and `pip-audit` reported none in the 34 applicable Python runtime dependencies. These checks do not establish that all software is harmless, detect every malicious package, or audit the operating-system packages in the base images. Compose configuration was validated; the image build could not be executed in the cloud environment because Docker Hub downloads were rate-limited and the alternate registry was blocked. Keep Docker and base images updated; this Compose file is a local demo, not a production deployment.

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

All 24 backend tests have been run against SQLite and PostgreSQL 17, including concurrent human submissions, timeout races, duplicate jobs, expired leases, concurrent workers/reconcilers, publication decisions, private reads, and production JWT validation. PostgreSQL tests require a **dedicated disposable database**: fixtures recreate its application tables. Set `PASSIT_TEST_DATABASE_URL` to its SQLAlchemy URL, then run the same pytest command.

To exercise the complete UI, leave the development API, worker and web server running, install a Playwright Chromium browser (or set `PLAYWRIGHT_CHROMIUM_PATH` to your existing Chromium), then run:

```sh
.venv/bin/playwright install chromium
.venv/bin/python backend/tests/browser_smoke.py
```

The smoke test creates fictional demo stories and verifies creation, suggestion editing, draft retention, passing, separate publication approvals, discovery, outsider access, and the mobile layout. It saves screenshots under `/tmp`. The CI workflow runs backend tests on both databases, a client build, and this browser workflow; the workflow itself has not run on GitHub yet.

## Implementation and deployment boundaries

The core includes friend selection, saved group snapshots, opted-in random matching, random recipient assignment, immutable per-turn Motives, private reads, prepared timeout fallback, asynchronous titles, separate Chain/turn likes, in-app notifications, explicit unanimous publication, and versioned admin AI profiles with validation and revision-pinned work.

The local durable job table acts as a transactional outbox and delivery transport. Workers claim leased jobs, retry with backoff, expose failures to admins, recover expired leases, and reconcile overdue turns. This implementation does **not** yet use Azure Service Bus. A broker transport and Azure infrastructure provisioning are separate deployment work. No Azure resources are created by running this application.

The demo uses sample creative text, rather than a live LLM. Real AI is provided through the Azure adapter once configured. Polling and deadline acceptance use server timestamps; the browser timer accounts for client clock differences. Suggestions are visible only to the assigned player and removed when the contribution is committed. Background payloads contain identifiers rather than story or suggestion text.

Production requires PostgreSQL and configured OIDC bearer authentication. See `.env.example`. Run migrations as a controlled step, then `python -m passit.manage seed` to initialize the Motive catalog and platform settings without demo accounts. The React client supports authorization-code login with PKCE using `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, and `VITE_OIDC_SCOPE` (include your API scope); `VITE_API_URL` selects a separate API origin. Configure the API's issuer, audience, JWKS URL, and explicit admin subjects. Serve the client over HTTPS and route `/auth/callback` to `index.html`.

For Azure AI, allow the resource host with `PASSIT_AI_ALLOWED_HOSTS`, create a profile in Admin, test its four task schemas, then activate it. The adapter supports Azure OpenAI chat completions with structured output, managed identity, or the server-side `PASSIT_AI_API_KEY` reference. Credentials never belong in a profile or client code. Models must support JSON-schema structured output and the configured generation parameters. Actual Azure connectivity needs your deployment and credentials; the local demo does not validate it.

Monetization is intentionally deferred as proposed in the rollout specification. Account deletion, paid features, export themes, push notifications, Azure messaging, infrastructure, backup/restore operations, and production load/security hardening remain follow-up work. SQLite is for local development; validate deployment concurrency against PostgreSQL.
