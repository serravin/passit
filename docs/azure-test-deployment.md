# Deploy to your own Azure test environment

You choose the Azure subscription, region, resource names, network and service sizes. Create and configure the resources yourself in Azure Portal. The workflow publishes images, runs migrations and updates **existing** apps. It creates no resource groups, networks, databases, registries, identities or applications. There is no production deployment job.

## 1. Create the initial Azure resources

Use a dedicated test resource group containing:

- An Azure Container Registry, typically Basic, with the admin account disabled. These instructions use the **RBAC Registry Permissions** mode.
- An Azure Container Apps environment and its logging configuration.
- Azure Database for PostgreSQL Flexible Server with a database named `passit`. Give the Container Apps environment network access to it. For private networking, configure a shared virtual network, separate service subnets and the PostgreSQL private DNS link yourself. GitHub's runner does not need database access; migrations run inside Azure.
- A user-assigned managed identity with **AcrPull** on the registry. Assign it to each app and the migration job you create later, and select it for registry authentication.

Choose your sizes and region in Portal. The API/web can scale down; the worker needs at least one running replica for deadlines, so it incurs ongoing cost. Keep test data and permissions separate from production.

## 2. Configure GitHub and Azure authentication

In GitHub, create an **Environment** with your preferred name, such as `test`. Restrict its deployment branches to `main`; add required reviewers if you want manual approval.

In your Azure subscription's Entra tenant, create an application/service principal for GitHub deployments. Add a federated credential with:

| Field | Value |
|---|---|
| Issuer | `https://token.actions.githubusercontent.com` |
| Subject | `repo:serravin/passit:environment:YOUR_ENVIRONMENT_NAME` |
| Audience | `api://AzureADTokenExchange` |

Use the exact GitHub Environment name in the subject. Grant this deployment identity **Contributor** on the test resource group and **AcrPush** on the registry. It needs no subscription-wide role, long-lived client secret or access to application secret values. This deployment identity is separate from the Entra External ID tenant used by your players.

Add these **repository-level Actions variables**:

| Variable | Value |
|---|---|
| `AZURE_TEST_ENVIRONMENT` | Your GitHub Environment name; defaults to `test` |
| `AZURE_TEST_DEPLOY_ENABLED` | Leave unset/`false` during setup; later set to `true` |
| `VITE_OIDC_AUTHORITY` | Your Entra customer-sign-in authority URL, using HTTPS |
| `VITE_OIDC_CLIENT_ID` | The SPA application's client ID |
| `VITE_OIDC_SCOPE` | `openid profile` plus your exposed API scope, e.g. `api://YOUR_API_ID/access_as_user` |

The `VITE_*` values are public and compiled into the web image. Keep them at **repository scope**, because the image build runs before entering the deployment environment. Never put keys, passwords or client secrets in `VITE_*`.

These values require your customer sign-in setup: an Entra External ID SPA registration and API registration, an exposed delegated API scope, and consent for the SPA to call it. You create those registrations yourself too.

Add these **variables on your GitHub Environment**:

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | Deployment service principal's client ID |
| `AZURE_TENANT_ID` | Azure subscription's tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Your subscription ID |
| `AZURE_RESOURCE_GROUP` | Your existing test resource group |
| `AZURE_CONTAINER_REGISTRY` | Your registry name, without `.azurecr.io` |

## 3. Publish images for first-time manual setup

Once this workflow is merged into `main`, open **Actions → Checks and Azure test deployment → Run workflow**. Select `main` and enable **Publish scanned images…**. Lint, tests and all Trivy scans must pass before anything is published.

This mode needs only the initial resources and variables above. It publishes the API and web images to your registry, without creating or updating apps or running migrations. Copy their digest references from the workflow summary to use when creating your apps in Portal. The API image also runs the worker and migration job.

## 4. Create and configure the apps and migration job

Create three distinct, single-container Container Apps in the same environment. Use **Single revision mode**, the registry's managed identity, and these settings:

| Service | Image | Ingress | Command | Scale |
|---|---|---|---|---|
| Web | Published web image | External, target port `8080`, HTTPS only | Image default | Your chosen range |
| API | Published API image | Internal, target port `8000` | Image default | Your chosen range |
| Worker | Published API image | Disabled | `python -m passit.worker` | Minimum `1`; start with maximum `1` |

For the worker's command override, use command `python` and arguments `-m`, `passit.worker`. The initial worker may report missing tables until the first migration runs. The API's `/api/health` checks database connectivity and does not require those tables.

Create a **Container Apps Job** in the same environment with:

- The API image and registry managed identity.
- **Manual** trigger, parallelism `1`, completion count `1`, retry limit `0`, and timeout `600` seconds.
- Command `/bin/sh` and arguments `-c`, `alembic upgrade head && python -m passit.manage seed`.

Set these environment variables on **API, worker and migration job**:

| Variable | Value |
|---|---|
| `PASSIT_MODE` | `production` |
| `PASSIT_ORIGIN` | `https://YOUR_WEB_APP_FQDN` |
| `PASSIT_DATABASE_URL` | **Secret reference**, using the same database for all three services |
| `PASSIT_OIDC_ISSUER` | Actual issuer from your Entra API token/discovery metadata |
| `PASSIT_OIDC_AUDIENCE` | Your API audience |
| `PASSIT_OIDC_JWKS_URL` | HTTPS `jwks_uri` from Entra discovery metadata |

A database secret has this form; URL-encode the username/password when necessary:

```text
postgresql+psycopg://USER:ENCODED_PASSWORD@SERVER.postgres.database.azure.com:5432/passit?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt
```

Store database credentials and any `PASSIT_AI_API_KEY` in Azure secrets or Key Vault references. Configure `PASSIT_AI_ALLOWED_HOSTS` on API and worker, and grant managed-identity access to Azure OpenAI if using it instead of a key. For a user-assigned AI identity, set `AZURE_CLIENT_ID` in the API/worker to that runtime identity's client ID, which is separate from GitHub's deployment identity. This workflow preserves your Azure environment variables and secrets; it does not populate them from GitHub.

After the first deployment/sign-in, set `PASSIT_ADMIN_SUBJECTS` on the API to the comma-separated **`sub` claims from your administrators' API tokens**. Display names and Entra object IDs are not substitutes for that claim. An empty allowlist grants no administrator access. Use the dashboard to validate and activate creative and guardrail profiles before testing story creation.

Set these variables on the **web** app:

| Variable | Value |
|---|---|
| `PASSIT_API_UPSTREAM` | `https://YOUR_INTERNAL_API_FQDN`, using the API's actual ingress FQDN |
| `PASSIT_CONNECT_SOURCES` | `'self' https://YOUR_TENANT.ciamlogin.com`, using the origin of your `VITE_OIDC_AUTHORITY` |

Include any additional exact origins used by your provider's discovery/token endpoints if needed. Nginx verifies the upstream HTTPS certificate. The image creates its runtime configuration under `/tmp`, so it also works with the local Compose read-only filesystem.

In the Entra SPA registration, add `https://YOUR_WEB_APP_FQDN/auth/callback` as a SPA redirect URI and the web origin as the logout return URL. Grant consent for the exposed API scope. Configure readiness/startup probes for the web's `/healthz` on `8080` and API's `/api/health` on `8000` in Portal.

Finally, add these variables on the **GitHub Environment**:

| Variable | Value |
|---|---|
| `AZURE_WEB_APP` | Web Container App name |
| `AZURE_API_APP` | API Container App name |
| `AZURE_WORKER_APP` | Worker Container App name |
| `AZURE_MIGRATION_JOB` | Manual migration job name |

## 5. Enable test deployment

Set repository variable `AZURE_TEST_DEPLOY_ENABLED=true`. Run the workflow on `main` with **Publish images only unchecked**, or push a change to `main`.

The workflow:

1. Runs Ruff lint/format checks, ESLint, Prettier, SQLite/PostgreSQL tests, the frontend build and five browser workflows.
2. Scans source dependencies (including dev dependencies), secrets and configuration with Trivy. Builds both images, tests web startup, and scans the exact images for vulnerabilities and secrets.
3. Stops on any HIGH/CRITICAL finding or scanner failure. Reports are retained as workflow artifacts for seven days; scanned image artifacts for one day.
4. Authenticates to Azure through OIDC, validates the existing resource settings, and publishes scanned images. Deployment uses registry **digests**, not mutable tags.
5. Runs the migration job and waits for success before updating API, worker and web. A failed/timed-out migration prevents app image updates. Deployments to this environment are serialized.
6. Checks production mode, database readiness, HTTPS routing, disabled demo accounts, required authentication, SPA callback/CSP and active healthy revisions for all three deployed images.

The summary links to the test app. Test real Entra sign-in, admin access and Azure AI yourself afterward; automated unauthenticated probes do not establish that those external credentials/permissions work. Existing app revisions run during migration, so use backwards-compatible schema changes. A post-migration deployment failure does not automatically roll back schema changes.

Pull requests and other branches receive checks and scans without Azure login or deployment. This workflow currently deploys only to the test resources you designate. Turning the flag off pauses subsequent deployments; it does not stop or delete existing Azure resources or their charges.

## Validation limits in the coding environment

Workflow syntax, linting, application/deployment tests, the client build and native Nginx routing were checked locally. Docker Hub rate-limited the container build, and the network policy blocked Trivy's vulnerability-database registry. An offline Trivy secrets/configuration scan passed; full dependency/image scans remain required on GitHub and are not bypassed. No Azure resources were created or deployed from this coding environment.
