from __future__ import annotations

import json
import os
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
    return _run_subprocess(
        command=args,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        shell=False,
    )


def run_shell_command(
    command: str,
    cwd: Path,
    timeout_seconds: int | None = None,
) -> CommandResult:
    return _run_subprocess(
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        shell=True,
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


def _run_subprocess(
    *,
    command: list[str] | str,
    cwd: Path,
    timeout_seconds: int | None,
    shell: bool,
) -> CommandResult:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=shell,
    )

    try:
        stdout_text, stderr_text = process.communicate(timeout=timeout_seconds)
        return CommandResult(
            args=[command] if isinstance(command, str) else command,
            exit_code=int(process.returncode or 0),
            stdout=stdout_text,
            stderr=stderr_text,
        )
    except subprocess.TimeoutExpired as exc:
        partial_stdout = _coerce_timeout_text(exc.stdout)
        partial_stderr = _coerce_timeout_text(exc.stderr)

        _terminate_process_tree(process.pid)
        try:
            stdout_text, stderr_text = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_text, stderr_text = process.communicate()

        merged_stdout = (partial_stdout + stdout_text).strip("\n")
        merged_stderr = (partial_stderr + stderr_text).strip("\n")
        suffix = "Shell command timed out." if shell else "Command timed out."
        merged_stderr = (merged_stderr + "\n" + suffix).strip("\n")

        return CommandResult(
            args=[command] if isinstance(command, str) else command,
            exit_code=124,
            stdout=merged_stdout,
            stderr=merged_stderr,
        )


def _terminate_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    try:
        os.kill(pid, 15)
    except OSError:
        return
