"""Critical deployment guards, with no Azure credentials or external resources."""

import copy
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "azure_deploy", Path(__file__).resolve().parents[2] / "scripts" / "azure_deploy.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture(autouse=True)
def isolate_github_command_files(tmp_path, monkeypatch):
    # Mock publishing/deployment must never write to the real runner's command files.
    for variable in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        monkeypatch.setenv(variable, str(tmp_path / variable.lower()))


def test_missing_configuration_and_signin_scope_fail_before_deployment():
    with pytest.raises(release.DeploymentError, match="GitHub variables"):
        release.settings({})
    values = dict.fromkeys(release.REQUIRED, "configured")
    values.update(
        IMAGE_TYPE="snapshot",
        IMAGE_TAG="snapshot-" + "a" * 40 + "-1-1",
        COMMIT_SHA="a" * 40,
        VITE_OIDC_AUTHORITY="https://tenant.ciamlogin.com/tenant/v2.0",
    )
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
        release, "resolve_images", lambda *args: {"api": "api@sha256:scanned", "web": "web@sha256:scanned"}
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
        release.deploy(config)
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


def test_selected_images_are_pinned_without_pulling_or_pushing(monkeypatch):
    calls = []
    digest = "sha256:" + "a" * 64

    def fake_az(*args, **kwargs):
        calls.append(args)
        return {"digest": digest, "changeableAttributes": {"writeEnabled": False}}

    monkeypatch.setattr(release, "az", fake_az)
    monkeypatch.setattr(
        release, "command", lambda *args, **kwargs: pytest.fail("Deployment must not use Docker")
    )
    result = release.resolve_images(
        {
            "IMAGE_TYPE": "snapshot",
            "IMAGE_TAG": "snapshot-" + "b" * 40 + "-123-1",
            "AZURE_CONTAINER_REGISTRY": "registry",
        },
        "registry.azurecr.io",
    )
    assert result == {
        component: f"registry.azurecr.io/passit-{component}@{digest}" for component in ("api", "web")
    }
    assert len(calls) == 2 and all(call[:3] == ("acr", "repository", "show") for call in calls)


@pytest.mark.parametrize(
    "tag", ["latest", "release-" + "a" * 40 + "-1-1", "snapshot-$(evil)", "snapshot-" + "a" * 40 + "-1-1\n"]
)
def test_wrong_type_or_malformed_image_selection_is_rejected(tag):
    with pytest.raises(release.DeploymentError, match="complete published tag"):
        release.validate_selection("snapshot", tag)


@pytest.mark.parametrize(
    "metadata",
    [
        {"digest": "sha256:" + "a" * 64, "changeableAttributes": {"writeEnabled": True}},
        {"digest": "invalid", "changeableAttributes": {"writeEnabled": False}},
    ],
)
def test_unfinished_or_invalid_publication_prevents_migration(metadata, monkeypatch):
    monkeypatch.setattr(release, "preflight", lambda _: ("registry", {}, {}, "https://test.example"))
    monkeypatch.setattr(release, "az", lambda *args, **kwargs: metadata)
    monkeypatch.setattr(release, "migrate", lambda *args: pytest.fail("Must reject before migration"))
    with pytest.raises(release.DeploymentError):
        release.deploy(
            {
                "IMAGE_TYPE": "release",
                "IMAGE_TAG": "release-" + "a" * 40 + "-1-1",
                "AZURE_CONTAINER_REGISTRY": "registry",
            }
        )


def test_missing_second_image_prevents_migration(monkeypatch):
    monkeypatch.setattr(release, "preflight", lambda _: ("registry", {}, {}, "https://test.example"))

    def fake_az(*args, **kwargs):
        if args[-1].startswith("passit-web:"):
            raise release.DeploymentError("Selected web image does not exist")
        return {"digest": "sha256:" + "a" * 64, "changeableAttributes": {"writeEnabled": False}}

    monkeypatch.setattr(release, "az", fake_az)
    monkeypatch.setattr(release, "migrate", lambda *args: pytest.fail("Must resolve both before migration"))
    with pytest.raises(release.DeploymentError, match="does not exist"):
        release.deploy(
            {
                "IMAGE_TYPE": "snapshot",
                "IMAGE_TAG": "snapshot-" + "a" * 40 + "-1-1",
                "AZURE_CONTAINER_REGISTRY": "registry",
            }
        )


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


@pytest.mark.parametrize("branch, expected_type", [("main", "release"), ("feature/new-ui", "snapshot")])
def test_publication_needs_only_registry_and_identifies_branch_type(branch, expected_type):
    config = release.settings(
        {
            "AZURE_SUBSCRIPTION_ID": "subscription",
            "AZURE_CONTAINER_REGISTRY": "registry",
            "COMMIT_SHA": "a" * 40,
            "BUILD_NUMBER": "123",
            "BUILD_ATTEMPT": "2",
            "SOURCE_BRANCH": branch,
        },
        publish_only=True,
    )
    assert config["IMAGE_TYPE"] == expected_type
    assert re.fullmatch(expected_type + r"-[0-9]{8}-aaaaaaa-r123-a2", config["IMAGE_TAG"])
    release.validate_selection(expected_type, config["IMAGE_TAG"])
    assert "AZURE_WEB_APP" not in config


def test_second_push_failure_does_not_mark_a_pair_ready(tmp_path, monkeypatch):
    for component in ("api", "web"):
        (tmp_path / f"{component}.tar").touch()
    config = release.settings(
        {
            "AZURE_SUBSCRIPTION_ID": "subscription",
            "AZURE_CONTAINER_REGISTRY": "registry",
            "COMMIT_SHA": "a" * 40,
            "BUILD_NUMBER": "123",
            "BUILD_ATTEMPT": "1",
            "SOURCE_BRANCH": "main",
        },
        publish_only=True,
    )
    calls = []

    def fake_az(*args, **kwargs):
        calls.append(args)
        return []

    def fake_command(*args, **kwargs):
        if args[:2] == ("docker", "push") and "passit-web:" in args[2]:
            raise release.DeploymentError("Web push failed")

    monkeypatch.setattr(release, "az", fake_az)
    monkeypatch.setattr(release, "command", fake_command)
    with pytest.raises(release.DeploymentError):
        release.publish_images(config, tmp_path, "registry.azurecr.io")
    assert not any(call[:3] == ("acr", "repository", "update") for call in calls)


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
        "VITE_OIDC_AUTHORITY": "https://tenant.ciamlogin.com/tenant/v2.0",
        "VITE_OIDC_CLIENT_ID": "spa-client",
        "VITE_OIDC_SCOPE": "openid api://api/play",
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
    resources["web"]["properties"]["template"]["containers"][0]["env"].extend(
        {"name": name, "value": config[name]}
        for name in ("VITE_OIDC_AUTHORITY", "VITE_OIDC_CLIENT_ID", "VITE_OIDC_SCOPE")
    )
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


def test_successful_publish_locks_both_versions_after_pushes(tmp_path, monkeypatch):
    for component in ("api", "web"):
        (tmp_path / f"{component}.tar").touch()
    config = release.settings(
        {
            "AZURE_SUBSCRIPTION_ID": "sub",
            "AZURE_CONTAINER_REGISTRY": "registry",
            "COMMIT_SHA": "a" * 40,
            "BUILD_NUMBER": "123",
            "BUILD_ATTEMPT": "1",
            "SOURCE_BRANCH": "main",
        },
        publish_only=True,
    )
    calls = []

    def fake_az(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("acr", "repository", "show"):
            return {"digest": "sha256:" + "b" * 64, "changeableAttributes": {"writeEnabled": False}}
        return []

    def fake_command(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(release, "az", fake_az)
    monkeypatch.setattr(release, "command", fake_command)
    images = release.publish_images(config, tmp_path, "registry.azurecr.io")
    pushes = [i for i, call in enumerate(calls) if call[:2] == ("docker", "push")]
    locks = [i for i, call in enumerate(calls) if call[:3] == ("acr", "repository", "update")]
    assert len(pushes) == len(locks) == 2 and max(pushes) < min(locks)
    assert all("--delete-enabled" in calls[i] and "--write-enabled" in calls[i] for i in locks)
    assert len(images) == 2


def test_publisher_refuses_to_overwrite_an_existing_version(tmp_path, monkeypatch):
    for component in ("api", "web"):
        (tmp_path / f"{component}.tar").touch()
    config = {"AZURE_CONTAINER_REGISTRY": "registry", "IMAGE_TAG": "release-" + "a" * 40 + "-1-1"}

    def fake_az(*args, **kwargs):
        return ["passit-api"] if args[2] == "list" else [config["IMAGE_TAG"]]

    monkeypatch.setattr(release, "az", fake_az)
    monkeypatch.setattr(
        release, "command", lambda *args, **kwargs: pytest.fail("Cannot push an existing tag")
    )
    with pytest.raises(release.DeploymentError, match="already exists"):
        release.publish_images(config, tmp_path, "registry.azurecr.io")


def test_deployment_updates_existing_apps_to_selected_digests(azure_resources, monkeypatch):
    config, resources, _, _ = azure_resources
    config.update(IMAGE_TYPE="release", IMAGE_TAG="release-" + "a" * 40 + "-123-1")
    selected = {
        component: "registry.azurecr.io/passit-" + component + "@sha256:" + "b" * 64
        for component in ("api", "web")
    }
    events = []
    monkeypatch.setattr(
        release,
        "preflight",
        lambda _: (
            "registry.azurecr.io",
            {name: resources[name] for name in ("api", "web", "worker")},
            resources["migration"],
            "https://web.example",
        ),
    )
    monkeypatch.setattr(release, "resolve_images", lambda *args: selected)
    monkeypatch.setattr(release, "migrate", lambda config, image, job: events.append(("migrate", image)))
    monkeypatch.setattr(release, "az", lambda *args, **kwargs: events.append(args))
    monkeypatch.setattr(
        release, "wait_revision", lambda config, kind, image: events.append(("healthy", kind, image))
    )
    monkeypatch.setattr(release, "smoke", lambda *args: events.append(("smoke",)))
    monkeypatch.setattr(
        release, "command", lambda *args, **kwargs: pytest.fail("Deployment must not build or push")
    )
    release.deploy(config)
    assert events[0] == ("migrate", selected["api"])
    updates = [event for event in events if event[:2] == ("containerapp", "update")]
    assert len(updates) == 3
    for call in updates:
        name = call[call.index("--name") + 1]
        assert call[call.index("--image") + 1] == selected["web" if name == "web" else "api"]
    assert events[-1] == ("smoke",)
    assert sum(event[0] == "healthy" for event in events) == 3


def test_deployment_rejects_wrong_runtime_signin_configuration(monkeypatch):
    responses = {
        "/api/health": (200, b'{"status":"ok","mode":"production"}'),
        "/healthz": (200, b"ok"),
        "/api/config": (200, b'{"mode":"production"}'),
        "/api/demo/accounts": (404, b"{}"),
        "/api/me": (401, b"{}"),
        "/auth/callback": (200, b'<div id="root">'),
        "/runtime-config.json": (
            200,
            b'{"authority":"https://wrong.example","clientId":"wrong","scope":"openid"}',
        ),
    }
    monkeypatch.setattr(
        release,
        "probe",
        lambda url: (
            *responses[url.removeprefix("https://web.example")],
            {"Content-Security-Policy": "connect-src 'self' https://tenant.example"},
        ),
    )
    with pytest.raises(release.DeploymentError, match="runtime sign-in settings"):
        release.smoke(
            "https://web.example",
            "https://tenant.example",
            {
                "VITE_OIDC_AUTHORITY": "https://tenant.example",
                "VITE_OIDC_CLIENT_ID": "client",
                "VITE_OIDC_SCOPE": "openid api://api/play",
            },
        )


@pytest.mark.parametrize("image_type", ["snapshot", "release"])
def test_readable_tags_and_legacy_versions_are_both_selectable(image_type):
    release.validate_selection(image_type, f"{image_type}-20261003-7917c60-r123-a1")
    release.validate_selection(image_type, f"{image_type}-" + "a" * 40 + "-123-1")
    with pytest.raises(release.DeploymentError):
        release.validate_selection(image_type, f"{image_type}-20261003-7917c60-r123-a1\n")
