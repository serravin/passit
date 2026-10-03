# Build images and deploy to your own Azure environments

You choose the Azure subscription, region, resource names, network and service sizes. Create and configure the resources yourself in Azure Portal. The build workflow publishes images to Azure Container Registry (ACR). The separate deployment workflow runs migrations and updates **existing** apps in the environment you select. It creates no resource groups, networks, databases, registries, identities or applications. Start with an isolated test environment; add further environments when you choose.

## 1. Create the initial Azure resources

Use a dedicated test resource group containing:

- An Azure Container Registry, typically Basic, with the admin account disabled. These instructions use the **RBAC Registry Permissions** mode.
- An Azure Container Apps environment and its logging configuration.
- Azure Database for PostgreSQL Flexible Server with a database named `passit`. Give the Container Apps environment network access to it. For private networking, configure a shared virtual network, separate service subnets and the PostgreSQL private DNS link yourself. GitHub's runner does not need database access; migrations run inside Azure.
- A user-assigned managed identity with **AcrPull** on the registry. Assign it to each app and the migration job you create later, and select it for registry authentication.

Choose your sizes and region in Portal. The API/web can scale down; the worker needs at least one running replica for deadlines, so it incurs ongoing cost. Keep test data and permissions separate from production.

## 2. Configure image publication

Create a GitHub **Environment** called `registry`, or choose another name and set the repository Actions variable `AZURE_REGISTRY_ENVIRONMENT` to it. Permit `main` and your feature branches in its deployment branch policy. Publication is automatic after checks pass; required reviewers on this environment will pause publication until approved.

In the Azure subscription's Entra tenant, create an application/service principal for **publishing images only**. Grant **AcrPush** and **Reader** on the registry. Do not grant this identity permissions to your application resource groups. These instructions use the registry's **RBAC Registry Permissions** mode.

Add a federated credential with:

| Field | Value |
|---|---|
| Issuer | `https://token.actions.githubusercontent.com` |
| Subject | `repo:serravin/passit:environment:YOUR_REGISTRY_ENVIRONMENT_NAME` |
| Audience | `api://AzureADTokenExchange` |

Set these Actions **variables on the registry GitHub Environment**:

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | Publisher service principal's client ID |
| `AZURE_TENANT_ID` | Azure subscription's tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing the registry |
| `AZURE_CONTAINER_REGISTRY` | Existing registry name, without `.azurecr.io` |

No client secret is needed. Only trusted repository collaborators should have feature-branch write access: their workflows can use the publishing identity. Fork pull requests never authenticate to Azure or publish images.

## 3. Publish snapshot and release images

**Build and publish images** runs the following stages in order. Both API and web must finish each image stage before the next stage starts:

```text
Linting → Testing → Source security scan → Image build → Image scan → Registry push
```

Lint includes Ruff, ESLint, formatting and shell syntax. Testing includes SQLite/PostgreSQL suites, the frontend build and all five browser workflows. Trivy checks source dependencies (including development dependencies), secrets and configuration, then scans the exact built images for vulnerabilities and secrets. HIGH/CRITICAL findings or scanner failures stop the pipeline. Reports remain available for seven days; built image artifacts for one day.

A branch push publishes the same version for API and web:

| Source | Image tag |
|---|---|
| Feature/other non-main branch | `snapshot-FULL_COMMIT_SHA-RUN_ID-ATTEMPT` |
| `main` (including a merged PR) | `release-FULL_COMMIT_SHA-RUN_ID-ATTEMPT` |

The complete references are `YOUR_REGISTRY.azurecr.io/passit-api:TAG` and `YOUR_REGISTRY.azurecr.io/passit-web:TAG`. The API image also runs the worker and migration job. There is no mutable `latest` tag. Publication refuses an existing version and locks both tags against overwrite/deletion after both pushes succeed. A failed partial publication cannot be deployed. Rerunning a build produces a different attempt tag.

Pull requests receive all checks, builds and scans without publication. A manual build also follows these gates and classifies its selected branch the same way. Merging to `main` publishes a release; it does not deploy automatically.

For first-time setup, create the registry and configure its GitHub Environment first, then push your feature branch or run the build workflow. Copy the resulting image references from the Actions summary and use them when manually creating your apps in Portal.

## 4. Configure a selectable deployment environment

Create a GitHub **Environment** with your preferred name, such as `test`. Restrict deployment branches to `main`; add required reviewers where appropriate. The deployment workflow itself accepts only `main`. Repeat this section and the resource setup for each additional environment you want to select.

Create a separate Azure deployment service principal. Grant **Contributor** on this environment's application resource group and **AcrPull** plus **Reader** on the registry. The registry can be shared and can live in another resource group, but must be in the selected subscription. The deployer needs no image-push role. Add a federated credential with the same issuer/audience as above and subject `repo:serravin/passit:environment:YOUR_DEPLOYMENT_ENVIRONMENT_NAME`.

Set these **variables on each deployment GitHub Environment**:

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | This environment's deployment service principal client ID |
| `AZURE_TENANT_ID` | Azure subscription's tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing the apps and registry |
| `AZURE_RESOURCE_GROUP` | Existing application resource group |
| `AZURE_CONTAINER_REGISTRY` | Registry containing the selected images |
| `VITE_OIDC_AUTHORITY` | HTTPS Entra customer-sign-in authority URL |
| `VITE_OIDC_CLIENT_ID` | SPA application client ID |
| `VITE_OIDC_SCOPE` | `openid profile` plus your exposed API scope, e.g. `api://YOUR_API_ID/access_as_user` |

Create the Entra External ID SPA/API registrations, expose a delegated API scope, and grant the SPA consent yourself. Customer sign-in uses a separate identity setup from GitHub's Azure deployment authentication.

### Create and configure the apps and migration job

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
| `VITE_OIDC_AUTHORITY` | Same public authority URL as this deployment GitHub Environment |
| `VITE_OIDC_CLIENT_ID` | Same SPA client ID as this deployment GitHub Environment |
| `VITE_OIDC_SCOPE` | Same scope string as this deployment GitHub Environment |

Include any additional exact origins used by your provider's discovery/token endpoints if needed. Nginx verifies the upstream HTTPS certificate. These public sign-in values are served as `/runtime-config.json` at startup; they are not compiled into the image. The same scanned image can therefore run with different settings in different environments. Never put secrets in these public values. Runtime configuration is written under `/tmp`, so the image also works with the local Compose read-only filesystem.

In the Entra SPA registration, add `https://YOUR_WEB_APP_FQDN/auth/callback` as a SPA redirect URI and the web origin as the logout return URL. Grant consent for the exposed API scope. Configure readiness/startup probes for the web's `/healthz` on `8080` and API's `/api/health` on `8000` in Portal.

Finally, add these variables on the **GitHub Environment**:

| Variable | Value |
|---|---|
| `AZURE_WEB_APP` | Web Container App name |
| `AZURE_API_APP` | API Container App name |
| `AZURE_WORKER_APP` | Worker Container App name |
| `AZURE_MIGRATION_JOB` | Manual migration job name |

## 5. Select an image and deploy

After merging these workflows through a PR, open **Actions → Deploy selected image → Run workflow**:

1. Choose branch **main**.
2. Choose image type **snapshot** or **release**.
3. Paste the **complete image tag**, including its type prefix, from a successful build summary or ACR's `passit-api`/`passit-web` tag lists.
4. Select your existing GitHub **Environment** from the dropdown.
5. Run the workflow; any environment-required reviewers apply before Azure access.

The image version is a text field because GitHub Actions cannot populate dispatch choices dynamically from ACR. To list available versions locally after your own Azure login:

```sh
az acr repository show-tags --name YOUR_REGISTRY --repository passit-api --orderby time_desc --output table
```

The workflow checks the selected type/tag, production resource settings and both locked image versions. It resolves registry digests before making changes; it does not rebuild or push images. It runs the migration job using the selected API digest and waits for success, then updates API, worker and web to those exact digests. Missing images, unfinished publications and failed migrations prevent application updates. Deployments to the same GitHub Environment are serialized, while separate environments can deploy independently.

Finally, it checks the new active healthy revisions, HTTPS routing, production mode, database readiness, disabled demo accounts, required authentication, SPA callback/CSP and runtime sign-in settings. The summary links to the deployed app. Test real Entra sign-in, admin access and Azure AI afterward; unauthenticated probes do not establish those external credentials/permissions work.

Existing revisions run during migration, so use backwards-compatible schema changes. Selecting an older image does not restore or downgrade the database; it may fail if its migration history cannot handle the current schema. A post-migration deployment failure does not automatically roll back schema changes.

No deployment starts merely from a branch push or merge. The old `AZURE_TEST_DEPLOY_ENABLED`, `AZURE_TEST_ENVIRONMENT` and `publish_images_only` controls are superseded by these two workflows. Existing Azure resources continue running until you stop/delete them yourself.

## Pull requests and main protection

[AGENTS.md](../AGENTS.md) requires coding agents to use feature branches and real GitHub PRs for every merge to `main`. For GitHub to enforce this for everyone, configure a branch ruleset targeting `main`: require a pull request and the lint, application/browser tests, Trivy source scan, API/web build and API/web image scan checks; block force pushes and branch deletion. Choose review/bypass rules yourself in GitHub settings. The repository file guides agents; it does not itself create a GitHub protection rule.

## Validation limits in the coding environment

Workflow syntax, linting, application/deployment tests, the client build and native Nginx routing were checked locally. Docker Hub rate-limited the container build, and the network policy blocked Trivy's vulnerability-database registry. An offline Trivy secrets/configuration scan passed; full dependency/image scans remain required on GitHub and are not bypassed. No Azure resources were created or deployed from this coding environment.
