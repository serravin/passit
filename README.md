# PassIt

Stories nobody writes alone. A responsive React client, FastAPI API, SQLAlchemy persistence, and a durable Python worker implement the comedy storytelling loop described in `spec/`.

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22+.

```sh
uv sync --frozen --extra dev
cd frontend
npm ci
cd ..
.venv/bin/alembic upgrade head
.venv/bin/python -m passit.manage seed
```

Run these in separate terminals from the repository root:

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

## Implementation and deployment boundaries

The core includes friend selection, saved group snapshots, opted-in random matching, random recipient assignment, immutable per-turn Motives, private reads, prepared timeout fallback, asynchronous titles, separate Chain/turn likes, in-app notifications, explicit unanimous publication, and versioned admin AI profiles with validation and revision-pinned work.

The local durable job table acts as a transactional outbox and delivery transport. Workers claim leased jobs, retry with backoff, expose failures to admins, recover expired leases, and reconcile overdue turns. This implementation does **not** yet use Azure Service Bus. A broker transport and Azure infrastructure provisioning are separate deployment work. No Azure resources are created by running this application.

Production requires PostgreSQL and configured OIDC bearer authentication. See `.env.example`. Run migrations as a controlled step, then `python -m passit.manage seed` to initialize the Motive catalog and platform settings without demo accounts. The React client supports authorization-code login with PKCE using `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, and `VITE_OIDC_SCOPE` (include your API scope); `VITE_API_URL` selects a separate API origin. Configure the API's issuer, audience, JWKS URL, and explicit admin subjects. Serve the client over HTTPS and route `/auth/callback` to `index.html`.

For Azure AI, allow the resource host with `PASSIT_AI_ALLOWED_HOSTS`, create a profile in Admin, test its four task schemas, then activate it. The adapter supports Azure OpenAI chat completions with structured output, managed identity, or the server-side `PASSIT_AI_API_KEY` reference. Credentials never belong in a profile or client code. Models must support JSON-schema structured output and the configured generation parameters. Actual Azure connectivity needs your deployment and credentials; the local demo does not validate it.

Monetization is intentionally deferred as proposed in the rollout specification. Account deletion, paid features, export themes, push notifications, Azure messaging, infrastructure, backup/restore operations, and production load/security hardening remain follow-up work. SQLite is for local development; validate deployment concurrency against PostgreSQL.
