"""Publish scanned images or deploy an existing image pair to Azure Container Apps.

This script creates no infrastructure and never reads Azure secret values.
"""

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

MIGRATION = "alembic upgrade head && python -m passit.manage seed"
REQUIRED = (
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "AZURE_CONTAINER_REGISTRY",
    "AZURE_WEB_APP",
    "AZURE_API_APP",
    "AZURE_WORKER_APP",
    "AZURE_MIGRATION_JOB",
    "VITE_OIDC_AUTHORITY",
    "VITE_OIDC_CLIENT_ID",
    "VITE_OIDC_SCOPE",
)


class DeploymentError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise DeploymentError(message)


def settings(environ, publish_only=False):
    required = (
        list(REQUIRED)
        if not publish_only
        else [
            "AZURE_SUBSCRIPTION_ID",
            "AZURE_CONTAINER_REGISTRY",
            "COMMIT_SHA",
            "BUILD_NUMBER",
            "BUILD_ATTEMPT",
            "SOURCE_BRANCH",
        ]
    )
    missing = [name for name in required if not environ.get(name, "").strip()]
    require(not missing, "Configure these GitHub variables: " + ", ".join(missing))
    values = {name: environ[name].strip() for name in required}
    if publish_only:
        require(re.fullmatch(r"[0-9a-f]{40}", values["COMMIT_SHA"]), "COMMIT_SHA must identify a full commit")
        for name in ("BUILD_NUMBER", "BUILD_ATTEMPT"):
            require(re.fullmatch(r"[1-9][0-9]*", values[name]), f"{name} must be a positive number")
        values["IMAGE_TYPE"] = "release" if values["SOURCE_BRANCH"] == "main" else "snapshot"
        values["IMAGE_TAG"] = (
            f"{values['IMAGE_TYPE']}-{datetime.now(UTC):%Y%m%d}-{values['COMMIT_SHA'][:7]}"
            f"-r{values['BUILD_NUMBER']}-a{values['BUILD_ATTEMPT']}"
        )
        return values
    values["IMAGE_TYPE"] = environ.get("IMAGE_TYPE", "")
    values["IMAGE_TAG"] = environ.get("IMAGE_TAG", "")
    validate_selection(values["IMAGE_TYPE"], values["IMAGE_TAG"])
    authority = urlsplit(values["VITE_OIDC_AUTHORITY"])
    require(
        authority.scheme == "https"
        and authority.hostname
        and not authority.username
        and not authority.password,
        "VITE_OIDC_AUTHORITY must be an HTTPS authority URL",
    )
    scopes = set(values["VITE_OIDC_SCOPE"].split())
    require(
        "openid" in scopes and scopes - {"openid", "profile", "email", "offline_access"},
        "VITE_OIDC_SCOPE must include openid and your API scope",
    )
    if not publish_only:
        names = [values[f"AZURE_{kind}_APP"] for kind in ("WEB", "API", "WORKER")]
        require(len(set(names)) == 3, "Web, API and worker must be distinct Container Apps")
    values["authority_origin"] = f"https://{authority.netloc}"
    return values


def command(*args, json_output=False):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    # Azure responses can contain environment variables. Never print raw responses or errors.
    if result.returncode:
        raise DeploymentError(f"{args[0]} {args[1]} failed; inspect the resource in Azure")
    return json.loads(result.stdout) if json_output else result.stdout.strip()


def az(*args, json_output=True):
    return command(
        "az",
        *args,
        "--only-show-errors",
        "--output",
        "json" if json_output else "tsv",
        json_output=json_output,
    )


def container(resource, label):
    containers = resource["properties"]["template"]["containers"]
    require(len(containers) == 1, f"{label} must have exactly one application container")
    return containers[0]


def env_values(item):
    return {entry["name"]: entry.get("value", "") for entry in item.get("env", [])}


def backend_config(item, label, origin):
    env = env_values(item)
    require(env.get("PASSIT_MODE") == "production", f"{label}: set PASSIT_MODE=production")
    require(env.get("PASSIT_ORIGIN") == origin, f"{label}: set PASSIT_ORIGIN to the HTTPS web URL")
    db = next((entry for entry in item.get("env", []) if entry["name"] == "PASSIT_DATABASE_URL"), {})
    require(
        db.get("secretRef") and not db.get("value"), f"{label}: use a secret reference for the database URL"
    )
    for name in (
        "PASSIT_OIDC_ISSUER",
        "PASSIT_OIDC_AUDIENCE",
        "PASSIT_OIDC_JWKS_URL",
    ):
        require(env.get(name), f"{label}: configure {name}")
    require(env["PASSIT_OIDC_JWKS_URL"].startswith("https://"), f"{label}: JWKS must use HTTPS")


def registry_target(config):
    account = az("account", "show")
    require(account["id"] == config["AZURE_SUBSCRIPTION_ID"], "Azure login uses the wrong subscription")
    registry = az("acr", "show", "--name", config["AZURE_CONTAINER_REGISTRY"])
    require(
        not registry.get("adminUserEnabled"), "Disable the registry admin account and use managed identity"
    )
    return registry["loginServer"]


def preflight(config):
    group = config["AZURE_RESOURCE_GROUP"]
    server = registry_target(config)
    apps = {
        kind: az(
            "containerapp", "show", "--name", config[f"AZURE_{kind.upper()}_APP"], "--resource-group", group
        )
        for kind in ("web", "api", "worker")
    }
    job = az(
        "containerapp", "job", "show", "--name", config["AZURE_MIGRATION_JOB"], "--resource-group", group
    )
    environments = set()
    for label, resource in [*apps.items(), ("migration job", job)]:
        props = resource["properties"]
        environments.add((props.get("environmentId") or props.get("managedEnvironmentId") or "").lower())
        auth = props["configuration"].get("registries", [])
        require(
            any(entry.get("server") == server and entry.get("identity") for entry in auth),
            f"{label}: configure managed-identity access to the container registry",
        )
        container(resource, label)
    require(
        len(environments) == 1 and "" not in environments,
        "All services must use the same Container Apps environment",
    )
    for label, app in apps.items():
        require(
            app["properties"]["configuration"].get("activeRevisionsMode") == "Single",
            f"{label}: use Single revision mode",
        )
    api_ingress = apps["api"]["properties"]["configuration"].get("ingress") or {}
    web_ingress = apps["web"]["properties"]["configuration"].get("ingress") or {}
    require(
        api_ingress.get("external") is False and api_ingress.get("targetPort") == 8000,
        "API ingress must be internal on port 8000",
    )
    require(
        web_ingress.get("external") is True and web_ingress.get("targetPort") == 8080,
        "Web ingress must be external on port 8080",
    )
    require(not web_ingress.get("allowInsecure"), "Web ingress must require HTTPS")
    require(
        not apps["worker"]["properties"]["configuration"].get("ingress"), "The worker must have no ingress"
    )
    require(
        apps["worker"]["properties"]["template"].get("scale", {}).get("minReplicas", 0) >= 1,
        "Keep at least one worker replica running for deadlines",
    )
    worker = container(apps["worker"], "worker")
    require(
        worker.get("command", []) + worker.get("args", []) == ["python", "-m", "passit.worker"],
        "Configure the worker command as python -m passit.worker",
    )
    origin = "https://" + web_ingress["fqdn"]
    for label, resource in [("api", apps["api"]), ("worker", apps["worker"]), ("migration job", job)]:
        backend_config(container(resource, label), label, origin)
    web_env = env_values(container(apps["web"], "web"))
    require(
        web_env.get("PASSIT_API_UPSTREAM", "").rstrip("/") == "https://" + api_ingress["fqdn"],
        "Web PASSIT_API_UPSTREAM must be the internal API HTTPS URL",
    )
    for name in ("VITE_OIDC_AUTHORITY", "VITE_OIDC_CLIENT_ID", "VITE_OIDC_SCOPE"):
        require(web_env.get(name) == config[name], f"Web {name} must match the selected GitHub Environment")
    sources = web_env.get("PASSIT_CONNECT_SOURCES", "").split()
    require(
        "'self'" in sources and config["authority_origin"] in sources,
        "Web PASSIT_CONNECT_SOURCES must include 'self' and the Entra authority origin",
    )
    job_config = job["properties"]["configuration"]
    require(job_config.get("triggerType") == "Manual", "The migration job must have a Manual trigger")
    require(
        job_config.get("replicaRetryLimit") == 0
        and job_config.get("manualTriggerConfig", {}).get("parallelism") == 1
        and job_config.get("manualTriggerConfig", {}).get("replicaCompletionCount") == 1,
        "The migration job must run one replica with no automatic retries",
    )
    task = container(job, "migration job")
    require(
        task.get("command", []) + task.get("args", []) == ["/bin/sh", "-c", MIGRATION],
        "Set the migration command to /bin/sh -c 'alembic upgrade head && python -m passit.manage seed'",
    )
    return server, apps, job, origin


def validate_selection(image_type, tag):
    require(image_type in {"snapshot", "release"}, "Choose snapshot or release")
    require(
        re.fullmatch(
            rf"{image_type}-(?:[0-9]{{8}}-[0-9a-f]{{7}}-r[1-9][0-9]*-a[1-9][0-9]*"
            rf"|[0-9a-f]{{40}}-[1-9][0-9]*-[1-9][0-9]*)",
            tag,
        ),
        "Select a complete published tag matching the chosen image type",
    )


def resolve_images(config, server):
    validate_selection(config["IMAGE_TYPE"], config["IMAGE_TAG"])
    images = {}
    for component in ("api", "web"):
        metadata = az(
            "acr",
            "repository",
            "show",
            "--name",
            config["AZURE_CONTAINER_REGISTRY"],
            "--image",
            f"passit-{component}:{config['IMAGE_TAG']}",
        )
        digest = metadata.get("digest", "")
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest), f"Invalid {component} registry digest")
        require(
            metadata.get("changeableAttributes", {}).get("writeEnabled") is False,
            f"The {component} tag is not locked; select a completed publication",
        )
        images[component] = f"{server}/passit-{component}@{digest}"
    return images


def publish_images(config, images, server):
    for component in ("api", "web"):
        require((images / f"{component}.tar").is_file(), f"The scanned {component} image artifact is missing")
    registry = config["AZURE_CONTAINER_REGISTRY"]
    repositories = az("acr", "repository", "list", "--name", registry)
    for component in ("api", "web"):
        repo = f"passit-{component}"
        if repo in repositories:
            tags = az("acr", "repository", "show-tags", "--name", registry, "--repository", repo)
            require(
                config["IMAGE_TAG"] not in tags, "This build tag already exists; rerun with a new attempt"
            )
    az("acr", "login", "--name", registry, json_output=False)
    for component in ("api", "web"):
        local = f"passit-{component}:{config['COMMIT_SHA']}"
        remote = f"{server}/passit-{component}:{config['IMAGE_TAG']}"
        command("docker", "load", "--input", str(images / f"{component}.tar"))
        command("docker", "tag", local, remote)
        command("docker", "push", remote)
    # Lock both only after both pushes succeed. Deployment rejects incomplete publications.
    for component in ("api", "web"):
        az(
            "acr",
            "repository",
            "update",
            "--name",
            registry,
            "--image",
            f"passit-{component}:{config['IMAGE_TAG']}",
            "--write-enabled",
            "false",
            "--delete-enabled",
            "false",
        )
    published = resolve_images(config, server)
    summary = f"Image type: `{config['IMAGE_TYPE']}`\n\nImage tag: `{config['IMAGE_TAG']}`\n\n"
    for component, image in published.items():
        summary += f"- {component}: `{image}`\n"
    print(summary)
    if path := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as output:
            output.write(summary)
    return published


def migrate(config, image, job):
    group, name = config["AZURE_RESOURCE_GROUP"], config["AZURE_MIGRATION_JOB"]
    running = az("containerapp", "job", "execution", "list", "--name", name, "--resource-group", group)
    require(
        not any(item.get("properties", {}).get("status") == "Running" for item in running),
        "A migration is already running; wait before deploying again",
    )
    az(
        "containerapp",
        "job",
        "update",
        "--name",
        name,
        "--resource-group",
        group,
        "--container-name",
        container(job, "migration job")["name"],
        "--image",
        image,
    )
    execution = az("containerapp", "job", "start", "--name", name, "--resource-group", group)
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        result = az(
            "containerapp",
            "job",
            "execution",
            "show",
            "--name",
            name,
            "--resource-group",
            group,
            "--job-execution-name",
            execution["name"],
        )
        status = result["properties"]["status"]
        if status == "Succeeded":
            return
        require(
            status not in {"Failed", "Stopped", "Canceled"},
            "Migration failed; application images were not updated",
        )
        time.sleep(5)
    raise DeploymentError("Migration timed out; application images were not updated")


def probe(url):
    request = urllib.request.Request(url, headers={"User-Agent": "PassIt-deployment-check"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


def smoke(origin, authority_origin, public_config=None):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            status, body, _ = probe(origin + "/api/health")
            if status == 200 and json.loads(body) == {"status": "ok", "mode": "production"}:
                break
        except (OSError, ValueError):
            pass
        time.sleep(5)
    else:
        raise DeploymentError("The deployed API did not become healthy in production mode")
    status, _, _ = probe(origin + "/healthz")
    require(status == 200, "Web health check failed")
    status, body, _ = probe(origin + "/api/config")
    require(
        status == 200 and json.loads(body).get("mode") == "production",
        "Production configuration check failed",
    )
    require(probe(origin + "/api/demo/accounts")[0] == 404, "Demo accounts must be disabled in Azure")
    require(probe(origin + "/api/me")[0] == 401, "The API must require authentication")
    status, body, headers = probe(origin + "/auth/callback")
    require(status == 200 and b'<div id="root">' in body, "SPA callback routing failed")
    require(
        authority_origin in headers.get("Content-Security-Policy", ""), "Web CSP does not allow Entra sign-in"
    )
    if public_config:
        status, body, _ = probe(origin + "/runtime-config.json")
        require(status == 200, "Web runtime configuration is unavailable")
        expected = {
            "authority": public_config["VITE_OIDC_AUTHORITY"],
            "clientId": public_config["VITE_OIDC_CLIENT_ID"],
            "scope": public_config["VITE_OIDC_SCOPE"],
        }
        require(
            json.loads(body) == expected, "Web runtime sign-in settings do not match the selected environment"
        )


def wait_revision(config, kind, image):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        revisions = az(
            "containerapp",
            "revision",
            "list",
            "--name",
            config[f"AZURE_{kind.upper()}_APP"],
            "--resource-group",
            config["AZURE_RESOURCE_GROUP"],
        )
        for revision in revisions:
            props = revision["properties"]
            if props.get("active") and props.get("healthState") == "Healthy":
                images = [item["image"] for item in props["template"]["containers"]]
                if images == [image]:
                    return
        time.sleep(5)
    raise DeploymentError(f"The new {kind} image did not become an active, healthy revision")


def deploy(config):
    print("Checking the existing Azure resources...")
    server, apps, job, origin = preflight(config)
    print("Resolving the selected, locked image pair...")
    published = resolve_images(config, server)
    print("Running the database migration in the selected environment...")
    migrate(config, published["api"], job)
    for kind in ("api", "worker", "web"):
        print(f"Updating the {kind} image...")
        az(
            "containerapp",
            "update",
            "--name",
            config[f"AZURE_{kind.upper()}_APP"],
            "--resource-group",
            config["AZURE_RESOURCE_GROUP"],
            "--container-name",
            container(apps[kind], kind)["name"],
            "--image",
            published["web" if kind == "web" else "api"],
        )
    print("Checking HTTPS, database readiness, callback routing and authentication...")
    for kind in ("api", "worker", "web"):
        wait_revision(config, kind, published["web" if kind == "web" else "api"])
    smoke(origin, config["authority_origin"], config)
    if path := os.getenv("GITHUB_OUTPUT"):
        with open(path, "a") as output:
            output.write(f"web_url={origin}\n")
    if path := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as summary:
            summary.write(f"Azure deployment: [{origin}]({origin})\n\nImage tag: `{config['IMAGE_TAG']}`\n")
    print(f"Azure deployment checked: {origin}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    publish = subcommands.add_parser("publish", help="Publish scanned build artifacts, without deploying")
    publish.add_argument("--images", type=Path, required=True)
    subcommands.add_parser("deploy", help="Deploy the selected existing registry images")
    args = parser.parse_args()
    try:
        config = settings(os.environ, publish_only=args.action == "publish")
        if args.action == "publish":
            publish_images(config, args.images, registry_target(config))
        else:
            deploy(config)
    except (DeploymentError, KeyError, ValueError, OSError) as exc:
        # Generic parse/network errors must not disclose Azure response bodies or credentials.
        message = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
        print("Deployment failed: " + message)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
