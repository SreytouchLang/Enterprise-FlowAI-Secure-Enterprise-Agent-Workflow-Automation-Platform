"""Collect disposable CI service diagnostics without exporting session secrets."""
import re
import subprocess
from pathlib import Path


def redact(content: str, dotenv: str) -> str:
    # Include encoded connection URLs as well as their configured passwords.
    for line in dotenv.splitlines():
        name, separator, value = line.partition("=")
        value = value.strip().strip("\"'")
        if separator and value and re.search(r"PASSWORD|SECRET|TOKEN|KEY|DATABASE_URL|REDIS_URL", name):
            content = content.replace(value, "[REDACTED]")
    content = re.sub(r"\b([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@",
                     r"\1[REDACTED]@", content)
    content = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
                     "[REDACTED JWT]", content)
    content = re.sub(r"(?i)(Bearer\s+)[^\s,\"']+", r"\1[REDACTED]", content)
    content = re.sub(
        r"(?i)([?&](?:code|state|session_state|nonce|token|access_token|refresh_token|id_token)=)[^&#\s]*",
        r"\1[REDACTED]", content,
    )
    content = re.sub(
        r"(?i)((?:[\"']?)(?:access_token|refresh_token|id_token|csrf_token|password|secret|verifier)"
        r"(?:[\"']?)\s*[:=]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,}\"']+)",
        r"\1[REDACTED]", content,
    )
    return re.sub(r"(?im)([\"']?(?:set-)?cookie[\"']?\s*[:=]).*$", r"\1 [REDACTED]", content)


def collect() -> None:
    destination = Path("artifacts/live-compose")
    destination.mkdir(parents=True, exist_ok=True)
    dotenv = Path(".env").read_text() if Path(".env").exists() else ""
    commands = {
        "status.txt": ["docker", "compose", "ps", "--all"],
        "services.log": ["docker", "compose", "logs", "--no-color", "--tail=150"],
    }
    for filename, command in commands.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            content = redact(result.stdout + result.stderr, dotenv)
        except (OSError, subprocess.TimeoutExpired):
            content = "Service diagnostics unavailable for this command.\n"
        (destination / filename).write_text(content)


if __name__ == "__main__":
    collect()
