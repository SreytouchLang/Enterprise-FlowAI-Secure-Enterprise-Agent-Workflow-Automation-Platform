"""Deploy built images with the AWS CLI without reading secret values.

Run from the protected workflow after infrastructure bootstrap. Migrations must
remain backwards-compatible with the previous application release.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path


def aws(*args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--output", "json"], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout or "{}")


def register(prefix: str, component: str, image: str) -> str:
    task = aws("ecs", "describe-task-definition", "--task-definition", f"{prefix}-{component}")[
        "taskDefinition"
    ]
    for key in (
        "taskDefinitionArn", "revision", "status", "requiresAttributes", "compatibilities",
        "registeredAt", "registeredBy", "deregisteredAt",
    ):
        task.pop(key, None)
    containers = [container for container in task["containerDefinitions"] if container["name"] == component]
    if len(containers) != 1:
        raise SystemExit(f"Task {prefix}-{component} must contain exactly one {component} container.")
    containers[0]["image"] = image
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "task.json"
        path.write_text(json.dumps(task))
        return aws("ecs", "register-task-definition", "--cli-input-json", f"file://{path}")[
            "taskDefinition"
        ]["taskDefinitionArn"]


def deploy() -> None:
    prefix = os.environ["TASK_FAMILY_PREFIX"]
    cluster = os.environ["ECS_CLUSTER"]
    registry = os.environ["REGISTRY"]
    release = os.environ["RELEASE_SHA"]
    api = f"{registry}/{os.environ['ECR_API_REPOSITORY']}:{release}"
    web = f"{registry}/{os.environ['ECR_WEB_REPOSITORY']}:{release}"
    services = [f"{prefix}-{component}" for component in ("api", "worker", "web", "scheduler")]
    current = aws("ecs", "describe-services", "--cluster", cluster, "--services", *services)
    if current.get("failures") or len(current.get("services", [])) != 4:
        raise SystemExit("All four services must be provisioned before deployment.")
    if any(service["desiredCount"] < 1 for service in current["services"]):
        raise SystemExit("Services are at zero capacity. Complete the documented bootstrap first.")
    migration = register(prefix, "migration", api)
    network = {"awsvpcConfiguration": {
        "subnets": os.environ["PRIVATE_SUBNET_IDS"].split(","),
        "securityGroups": [os.environ["TASK_SECURITY_GROUP_ID"]],
        "assignPublicIp": "DISABLED",
    }}
    result = aws(
        "ecs", "run-task", "--cluster", cluster, "--launch-type", "FARGATE",
        "--task-definition", migration, "--network-configuration", json.dumps(network),
    )
    if result.get("failures") or not result.get("tasks"):
        raise SystemExit("Migration task could not start; inspect ECS service events.")
    task_arn = result["tasks"][0]["taskArn"]
    aws("ecs", "wait", "tasks-stopped", "--cluster", cluster, "--tasks", task_arn)
    stopped = aws("ecs", "describe-tasks", "--cluster", cluster, "--tasks", task_arn)["tasks"][0]
    containers = stopped.get("containers", [])
    if not containers or any(container.get("exitCode") != 0 for container in containers):
        raise SystemExit("Migration failed; services were not changed. Inspect migration CloudWatch logs.")
    # Prepare every revision before starting the rollout. A registration error
    # must not leave earlier services running a partially deployed release.
    expected = {
        f"{prefix}-{component}": register(prefix, component, web if component == "web" else api)
        for component in ("api", "worker", "web", "scheduler")
    }
    for service, definition in expected.items():
        aws("ecs", "update-service", "--cluster", cluster, "--service", service,
            "--task-definition", definition)
    aws("ecs", "wait", "services-stable", "--cluster", cluster, "--services", *services)
    actual = aws("ecs", "describe-services", "--cluster", cluster, "--services", *services)
    if actual.get("failures") or len(actual.get("services", [])) != 4:
        raise SystemExit("Could not verify all deployed services.")
    for service in actual["services"]:
        if service["taskDefinition"] != expected[service["serviceName"]]:
            raise SystemExit("ECS rolled back or replaced a requested task revision; release failed.")
        if service["runningCount"] < 1:
            raise SystemExit("A service has no running tasks; release failed.")
    print(f"Release {release} deployed; all four requested task revisions are running.")


if __name__ == "__main__":
    deploy()
