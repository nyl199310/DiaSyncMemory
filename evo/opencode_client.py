from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig
from .io_utils import extract_json_payload, run_command
from .models import RunEvents


class OpenCodeClient:
    def __init__(
        self,
        workspace_root: Path,
        agent_config: AgentConfig,
        *,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        heartbeat_seconds: int = 15,
    ) -> None:
        self.workspace_root = workspace_root
        self.agent_config = agent_config
        self.executable = _resolve_opencode_executable()
        self.progress_callback = progress_callback
        self.heartbeat_seconds = max(1, heartbeat_seconds)

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

        start = time.monotonic()
        self._emit_progress(
            "opencode_call_start",
            {
                "session_id": session_id,
                "title": title,
                "timeout_seconds": timeout_seconds,
            },
        )

        stop_event = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        if timeout_seconds and timeout_seconds > 0:
            heartbeat_thread = threading.Thread(
                target=self._heartbeat,
                args=(stop_event, start, session_id, title),
                daemon=True,
            )
            heartbeat_thread.start()

        command = run_command(args=args, cwd=self.workspace_root, timeout_seconds=timeout_seconds)

        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=0.1)

        elapsed_seconds = int(time.monotonic() - start)
        self._emit_progress(
            "opencode_call_finish",
            {
                "session_id": session_id,
                "title": title,
                "exit_code": command.exit_code,
                "elapsed_seconds": elapsed_seconds,
            },
        )

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
        self._emit_progress(
            "opencode_export_start",
            {"session_id": session_id},
        )
        start = time.monotonic()
        command = run_command(
            args=[self.executable, "export", session_id],
            cwd=self.workspace_root,
            timeout_seconds=120,
        )
        self._emit_progress(
            "opencode_export_finish",
            {
                "session_id": session_id,
                "exit_code": command.exit_code,
                "elapsed_seconds": int(time.monotonic() - start),
            },
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

    def _heartbeat(
        self,
        stop_event: threading.Event,
        start: float,
        session_id: str | None,
        title: str | None,
    ) -> None:
        while not stop_event.wait(self.heartbeat_seconds):
            self._emit_progress(
                "opencode_call_wait",
                {
                    "session_id": session_id,
                    "title": title,
                    "elapsed_seconds": int(time.monotonic() - start),
                },
            )

    def _emit_progress(self, event: str, payload: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event, payload)


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
