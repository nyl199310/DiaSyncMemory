from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .io_utils import extract_json_payload, run_command
from .models import RunEvents


class OpenCodeClient:
    def __init__(self, workspace_root: Path, agent_config: AgentConfig) -> None:
        self.workspace_root = workspace_root
        self.agent_config = agent_config
        self.executable = _resolve_opencode_executable()

    def run_message(
        self,
        message: str,
        *,
        session_id: str | None = None,
        title: str | None = None,
        timeout_seconds: int | None = None,
    ) -> RunEvents:
        args = [self.executable, "run", "--format", "json"]

        if session_id:
            args.extend(["-s", session_id])
        elif title:
            args.extend(["--title", title])

        if self.agent_config.agent:
            args.extend(["--agent", self.agent_config.agent])
        if self.agent_config.model:
            args.extend(["--model", self.agent_config.model])
        if self.agent_config.variant:
            args.extend(["--variant", self.agent_config.variant])
        if self.agent_config.thinking:
            args.append("--thinking")

        args.append(message)

        command = run_command(args=args, cwd=self.workspace_root, timeout_seconds=timeout_seconds)

        events: list[dict[str, Any]] = []
        texts: list[str] = []
        tool_commands: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        discovered_session: str | None = session_id

        for raw_line in command.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(event, dict):
                continue

            events.append(event)

            session_from_event = event.get("sessionID")
            if isinstance(session_from_event, str):
                discovered_session = session_from_event

            if event.get("type") == "text":
                part = event.get("part", {})
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)

            if event.get("type") == "tool_use":
                part = event.get("part", {})
                if isinstance(part, dict):
                    tool_calls.append(part)
                    if part.get("tool") == "bash":
                        state = part.get("state", {})
                        input_payload = state.get("input", {})
                        command_text = input_payload.get("command")
                        if isinstance(command_text, str):
                            tool_commands.append(command_text)

        return RunEvents(
            session_id=discovered_session,
            stdout=command.stdout,
            stderr=command.stderr,
            exit_code=command.exit_code,
            events=events,
            texts=texts,
            tool_commands=tool_commands,
            tool_calls=tool_calls,
        )

    def export_session(self, session_id: str) -> dict[str, Any]:
        command = run_command(
            args=[self.executable, "export", session_id],
            cwd=self.workspace_root,
            timeout_seconds=120,
        )
        payload = extract_json_payload(command.stdout)
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "error": "could not parse opencode export payload",
                "stdout": command.stdout,
                "stderr": command.stderr,
                "exit_code": command.exit_code,
            }

        payload.setdefault("ok", command.exit_code == 0)
        return payload


def _resolve_opencode_executable() -> str:
    env_override = os.getenv("OPENCODE_BIN")
    if env_override:
        return env_override

    for candidate in ("opencode", "opencode.cmd", "opencode.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    appdata = os.getenv("APPDATA")
    if appdata:
        npm_cmd = Path(appdata) / "npm" / "opencode.cmd"
        if npm_cmd.exists():
            return str(npm_cmd)

    raise FileNotFoundError(
        "Could not resolve OpenCode CLI executable. Set OPENCODE_BIN to continue."
    )
