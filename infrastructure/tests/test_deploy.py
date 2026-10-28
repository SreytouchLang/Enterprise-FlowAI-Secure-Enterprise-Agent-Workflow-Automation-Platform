"""Release safety tests use a fake AWS boundary and never contact AWS."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("release", Path(__file__).parents[1] / "deploy.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def release_env(monkeypatch):
    for name, value in {
        "TASK_FAMILY_PREFIX": "ef-staging", "ECS_CLUSTER": "cluster", "REGISTRY": "registry",
        "RELEASE_SHA": "a" * 40, "ECR_API_REPOSITORY": "api", "ECR_WEB_REPOSITORY": "web",
        "PRIVATE_SUBNET_IDS": "subnet-a,subnet-b", "TASK_SECURITY_GROUP_ID": "sg-app",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(release, "register", lambda prefix, component, image: f"arn:{component}:new")


def fake_aws(calls, migration_exit=0, zero=False, rollback=False):
    def request(*args):
        calls.append(args)
        if args[1] == "describe-services":
            return {"services": [
                {"serviceName": f"ef-staging-{key}", "desiredCount": 0 if zero else 1,
                 "runningCount": 1, "taskDefinition": f"arn:{key}:{'old' if rollback else 'new'}"}
                for key in ("api", "worker", "web", "scheduler")
            ]}
        if args[1] == "run-task":
            return {"tasks": [{"taskArn": "migration-task"}]}
        if args[1] == "describe-tasks":
            return {"tasks": [{"containers": [{"exitCode": migration_exit}]}]}
        return {}
    return request


def test_failed_migration_never_updates_services(monkeypatch, release_env):
    calls = []
    monkeypatch.setattr(release, "aws", fake_aws(calls, migration_exit=1))
    with pytest.raises(SystemExit, match="Migration failed"):
        release.deploy()
    assert not any(call[1] == "update-service" for call in calls)


def test_zero_capacity_is_not_reported_as_a_working_deployment(monkeypatch, release_env):
    calls = []
    monkeypatch.setattr(release, "aws", fake_aws(calls, zero=True))
    with pytest.raises(SystemExit, match="zero capacity"):
        release.deploy()
    assert not any(call[1] == "run-task" for call in calls)


def test_circuit_breaker_rollback_is_reported_as_failed_release(monkeypatch, release_env):
    calls = []
    monkeypatch.setattr(release, "aws", fake_aws(calls, rollback=True))
    with pytest.raises(SystemExit, match="rolled back"):
        release.deploy()


def test_success_requires_all_four_requested_task_revisions(monkeypatch, release_env, capsys):
    calls = []
    monkeypatch.setattr(release, "aws", fake_aws(calls))
    release.deploy()
    assert len([call for call in calls if call[1] == "update-service"]) == 4
    assert "requested task revisions are running" in capsys.readouterr().out


def test_registration_failure_never_starts_a_partial_rollout(monkeypatch, release_env):
    calls = []
    monkeypatch.setattr(release, "aws", fake_aws(calls))

    def register(prefix, component, image):
        if component == "web":
            raise RuntimeError("Task definition rejected")
        return f"arn:{component}:new"

    monkeypatch.setattr(release, "register", register)
    with pytest.raises(RuntimeError, match="Task definition rejected"):
        release.deploy()
    assert not any(call[1] == "update-service" for call in calls)


def test_register_preserves_sidecars_and_removes_response_only_fields(monkeypatch):
    registered = []

    def request(*args):
        if args[1] == "describe-task-definition":
            return {"taskDefinition": {
                "family": "ef-staging-api", "taskDefinitionArn": "arn:api:old",
                "revision": 1, "status": "ACTIVE", "registeredBy": "deployer",
                "containerDefinitions": [
                    {"name": "api", "image": "registry/api:old"},
                    {"name": "telemetry", "image": "registry/telemetry:stable"},
                ],
            }}
        assert args[1] == "register-task-definition"
        registered.append(json.loads(Path(args[-1].removeprefix("file://")).read_text()))
        return {"taskDefinition": {"taskDefinitionArn": "arn:api:new"}}

    monkeypatch.setattr(release, "aws", request)
    assert release.register("ef-staging", "api", "registry/api:new") == "arn:api:new"
    assert registered == [{
        "family": "ef-staging-api", "containerDefinitions": [
            {"name": "api", "image": "registry/api:new"},
            {"name": "telemetry", "image": "registry/telemetry:stable"},
        ],
    }]


def test_register_rejects_task_without_expected_container(monkeypatch):
    calls = []

    def request(*args):
        calls.append(args)
        return {"taskDefinition": {"containerDefinitions": [
            {"name": "telemetry", "image": "registry/telemetry:stable"},
        ]}}

    monkeypatch.setattr(release, "aws", request)
    with pytest.raises(SystemExit, match="exactly one api container"):
        release.register("ef-staging", "api", "registry/api:new")
    assert len(calls) == 1
