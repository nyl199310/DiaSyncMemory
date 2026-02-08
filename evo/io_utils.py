from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CommandResult:
    args: list[str]
    exit_code: int
    stdout: str
    stderr: str


def now_utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: object) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def run_command(
    args: list[str],
    cwd: Path,
    timeout_seconds: int | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            args=args,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_timeout_text(exc.stdout)
        stderr = _coerce_timeout_text(exc.stderr)
        return CommandResult(
            args=args,
            exit_code=124,
            stdout=stdout,
            stderr=stderr + "\nCommand timed out.",
        )


def run_shell_command(
    command: str,
    cwd: Path,
    timeout_seconds: int | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=True,
            check=False,
        )
        return CommandResult(
            args=[command],
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_timeout_text(exc.stdout)
        stderr = _coerce_timeout_text(exc.stderr)
        return CommandResult(
            args=[command],
            exit_code=124,
            stdout=stdout,
            stderr=stderr + "\nShell command timed out.",
        )


def extract_json_payload(text: str) -> object | None:
    stripped = text.strip()
    if not stripped:
        return None

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    block = _extract_fenced_json(stripped)
    if block is not None:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            pass

    candidate = _extract_braced_json(stripped)
    if candidate is not None:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def fill_placeholders(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _extract_fenced_json(text: str) -> str | None:
    fence = "```"
    start = text.find(fence)
    while start != -1:
        end = text.find(fence, start + len(fence))
        if end == -1:
            return None
        block = text[start + len(fence) : end]
        if block.startswith("json"):
            return block[4:].strip()
        start = text.find(fence, end + len(fence))
    return None


def _extract_braced_json(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _coerce_timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
