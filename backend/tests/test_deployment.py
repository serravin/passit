"""Critical deployment guards, with no Azure credentials or external resources."""

import copy
import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "azure_deploy", Path(__file__).resolve().parents[2] / "scripts" / "azure_deploy.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_missing_configuration_and_signin_scope_fail_before_deployment():
    with pytest.raises(release.DeploymentError, match="GitHub variables"):
        release.settings({})
    values = dict.fromkeys(release.REQUIRED, "configured")
    values.update(COMMIT_SHA="a" * 40, VITE_OIDC_AUTHORITY="https://tenant.ciamlogin.com/tenant/v2.0")
    with pytest.raises(release.DeploymentError, match="API scope"):
        release.settings({**values, "VITE_OIDC_SCOPE": "openid profile"})
    with pytest.raises(release.DeploymentError, match="distinct"):
        release.settings({**values, "VITE_OIDC_SCOPE": "openid api://app/play"})


def test_migration_failure_leaves_application_images_untouched(tmp_path, monkeypatch):
    for component in ("api", "web"):
        (tmp_path / f"{component}.tar").touch()
    config = {"AZURE_RESOURCE_GROUP": "test-group", "AZURE_MIGRATION_JOB": "migrate"}
    job = {"properties": {"template": {"containers": [{"name": "migration"}]}}}
    monkeypatch.setattr(release, "preflight", lambda _: ("registry", {}, job, "https://test.example"))
    monkeypatch.setattr(
        release, "publish_images", lambda *args: {"api": "api@sha256:scanned", "web": "web@sha256:scanned"}
    )
    calls = []

    def fake_az(*args, **kwargs):
        calls.append(args)
        if args[:4] == ("containerapp", "job", "execution", "list"):
            return []
        if args[:3] == ("containerapp", "job", "start"):
            return {"name": "execution"}
        if args[:4] == ("containerapp", "job", "execution", "show"):
            return {"properties": {"status": "Failed"}}
        return {}

    monkeypatch.setattr(release, "az", fake_az)
    with pytest.raises(release.DeploymentError, match="Migration failed"):
        release.deploy(config, tmp_path)
    assert not any(call[:2] == ("containerapp", "update") for call in calls)


def test_an_existing_migration_prevents_a_second_execution(monkeypatch):
    calls = []

    def fake_az(*args, **kwargs):
        calls.append(args)
        return [{"properties": {"status": "Running"}}]

    monkeypatch.setattr(release, "az", fake_az)
    with pytest.raises(release.DeploymentError, match="already running"):
        release.migrate({"AZURE_RESOURCE_GROUP": "test", "AZURE_MIGRATION_JOB": "migrate"}, "image", {})
    assert len(calls) == 1


def test_a_published_demo_is_rejected_even_when_its_health_endpoint_works(monkeypatch):
    responses = {
        "/api/health": (200, b'{"status":"ok","mode":"production"}'),
        "/healthz": (200, b"ok"),
        "/api/config": (200, b'{"mode":"production"}'),
        "/api/demo/accounts": (200, b"[]"),
    }
    monkeypatch.setattr(
        release, "probe", lambda url: (*responses[url.removeprefix("https://test.example")], {})
    )
    with pytest.raises(release.DeploymentError, match="Demo accounts"):
        release.smoke("https://test.example", "https://tenant.ciamlogin.com")


def test_old_healthy_revision_cannot_mask_a_failed_new_image(monkeypatch):
    old = {
        "properties": {
            "active": True,
            "healthState": "Healthy",
            "template": {"containers": [{"image": "old-image"}]},
        }
    }
    new = {
        "properties": {
            "active": False,
            "healthState": "Unhealthy",
            "template": {"containers": [{"image": "new-image"}]},
        }
    }
    monkeypatch.setattr(release, "az", lambda *args, **kwargs: [old, new])
    clock = iter((0, 1, 301))
    monkeypatch.setattr(release.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    with pytest.raises(release.DeploymentError, match="active, healthy"):
        release.wait_revision(
            {"AZURE_RESOURCE_GROUP": "test", "AZURE_WORKER_APP": "worker"}, "worker", "new-image"
        )


def test_cli_errors_do_not_leak_response_environment_values(monkeypatch, capsys):
    response = subprocess.CompletedProcess(["az"], 1, "", "DATABASE_URL=PRIVATE_SECRET")
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: response)
    with pytest.raises(release.DeploymentError) as error:
        release.az("containerapp", "show")
    assert "PRIVATE_SECRET" not in str(error.value)
    assert "PRIVATE_SECRET" not in capsys.readouterr().out


def test_docker_registry_digest_is_pinned_for_all_deployments(tmp_path, monkeypatch):
    commands = []
    digest = "sha256:" + "a" * 64

    def fake_command(*args, **kwargs):
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            image = args[3].split(":")[0]
            return [image + "@" + digest]
        return ""

    monkeypatch.setattr(release, "az", lambda *args, **kwargs: "")
    monkeypatch.setattr(release, "command", fake_command)
    result = release.publish_images(
        {"COMMIT_SHA": "b" * 40, "AZURE_CONTAINER_REGISTRY": "registry"}, tmp_path, "registry.azurecr.io"
    )
    assert result == {
        component: f"registry.azurecr.io/passit-{component}@{digest}" for component in ("api", "web")
    }
    assert sum(call[:2] == ("docker", "push") for call in commands) == 2


def test_plaintext_database_credentials_are_rejected():
    item = {
        "env": [
            {"name": "PASSIT_MODE", "value": "production"},
            {"name": "PASSIT_ORIGIN", "value": "https://web.example"},
            {"name": "PASSIT_DATABASE_URL", "value": "postgresql://user:private@db/app"},
        ]
    }
    with pytest.raises(release.DeploymentError, match="secret reference"):
        release.backend_config(item, "api", "https://web.example")


def test_bootstrap_can_publish_without_creating_or_requiring_app_resources(tmp_path, monkeypatch):
    for component in ("api", "web"):
        (tmp_path / f"{component}.tar").touch()
    env = {
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "AZURE_RESOURCE_GROUP": "test",
        "AZURE_CONTAINER_REGISTRY": "registry",
        "COMMIT_SHA": "a" * 40,
        "VITE_OIDC_AUTHORITY": "https://tenant.ciamlogin.com/tenant/v2.0",
        "VITE_OIDC_CLIENT_ID": "client",
        "VITE_OIDC_SCOPE": "openid api://api/play",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(release, "registry_target", lambda _: "registry.azurecr.io")
    calls = []
    monkeypatch.setattr(
        release,
        "publish_images",
        lambda *args: calls.append("publish") or {"api": "api-digest", "web": "web-digest"},
    )
    monkeypatch.setattr(release, "deploy", lambda *args: pytest.fail("Bootstrap must not deploy apps"))
    monkeypatch.setattr(
        release, "az", lambda *args, **kwargs: pytest.fail("Bootstrap must not provision resources")
    )
    monkeypatch.setattr("sys.argv", ["azure_deploy.py", "--images", str(tmp_path), "--publish-only"])
    release.main()
    assert calls == ["publish"]


@pytest.fixture
def azure_resources():
    config = {
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "AZURE_RESOURCE_GROUP": "test",
        "AZURE_CONTAINER_REGISTRY": "registry",
        "AZURE_WEB_APP": "web",
        "AZURE_API_APP": "api",
        "AZURE_WORKER_APP": "worker",
        "AZURE_MIGRATION_JOB": "migration",
        "authority_origin": "https://tenant.ciamlogin.com",
    }
    backend_env = [
        {"name": "PASSIT_MODE", "value": "production"},
        {"name": "PASSIT_ORIGIN", "value": "https://web.example"},
        {"name": "PASSIT_DATABASE_URL", "secretRef": "database-url"},
        {"name": "PASSIT_OIDC_ISSUER", "value": "https://tenant.ciamlogin.com/tenant/v2.0"},
        {"name": "PASSIT_OIDC_AUDIENCE", "value": "api"},
        {"name": "PASSIT_OIDC_JWKS_URL", "value": "https://tenant.ciamlogin.com/keys"},
    ]
    resources = {}
    for name in ("api", "web", "worker", "migration"):
        resources[name] = {
            "properties": {
                "environmentId": "/test/environment",
                "configuration": {
                    "activeRevisionsMode": "Single",
                    "registries": [{"server": "registry.azurecr.io", "identity": "/test/pull-identity"}],
                },
                "template": {
                    "containers": [{"name": name, "env": copy.deepcopy(backend_env)}],
                    "scale": {"minReplicas": 1},
                },
            }
        }
    resources["api"]["properties"]["configuration"]["ingress"] = {
        "external": False,
        "targetPort": 8000,
        "fqdn": "api.internal.example",
    }
    resources["web"]["properties"]["configuration"]["ingress"] = {
        "external": True,
        "targetPort": 8080,
        "fqdn": "web.example",
        "allowInsecure": False,
    }
    resources["web"]["properties"]["template"]["containers"][0]["env"] = [
        {"name": "PASSIT_API_UPSTREAM", "value": "https://api.internal.example"},
        {"name": "PASSIT_CONNECT_SOURCES", "value": "'self' https://tenant.ciamlogin.com"},
    ]
    resources["worker"]["properties"]["template"]["containers"][0]["command"] = [
        "python",
        "-m",
        "passit.worker",
    ]
    resources["migration"]["properties"]["configuration"].update(
        triggerType="Manual",
        replicaRetryLimit=0,
        manualTriggerConfig={"parallelism": 1, "replicaCompletionCount": 1},
    )
    resources["migration"]["properties"]["template"]["containers"][0]["command"] = [
        "/bin/sh",
        "-c",
        release.MIGRATION,
    ]
    calls = []

    def fake_az(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("account", "show"):
            return {"id": "subscription"}
        if args[:2] == ("acr", "show"):
            return {"loginServer": "registry.azurecr.io", "adminUserEnabled": False}
        return resources[args[args.index("--name") + 1]]

    return config, resources, calls, fake_az


def test_preflight_reads_existing_resources_without_provisioning(azure_resources, monkeypatch):
    config, _, calls, fake_az = azure_resources
    monkeypatch.setattr(release, "az", fake_az)
    server, _, _, origin = release.preflight(config)
    assert server == "registry.azurecr.io" and origin == "https://web.example"
    assert calls and all("show" in call for call in calls)


@pytest.mark.parametrize("unsafe", ["public_api", "stopped_worker", "missing_signin_origin"])
def test_unsafe_existing_configuration_is_rejected(azure_resources, monkeypatch, unsafe):
    config, resources, _, fake_az = azure_resources
    if unsafe == "public_api":
        resources["api"]["properties"]["configuration"]["ingress"]["external"] = True
    elif unsafe == "stopped_worker":
        resources["worker"]["properties"]["template"]["scale"]["minReplicas"] = 0
    else:
        resources["web"]["properties"]["template"]["containers"][0]["env"][1]["value"] = "'self'"
    monkeypatch.setattr(release, "az", fake_az)
    with pytest.raises(release.DeploymentError):
        release.preflight(config)
