from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io_utils import extract_json_payload, run_command


class MemoryProbe:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def run(
        self,
        *,
        memory_root: Path,
        scope: str,
        project: str,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}

        results["stats"] = self._memoryctl_json(
            [
                "stats",
                "--root",
                str(memory_root),
                "--scope",
                scope,
            ],
        )
        results["validate_strict"] = self._memoryctl_json(
            [
                "validate",
                "--root",
                str(memory_root),
                "--strict",
            ],
        )
        results["diagnose_dry_run"] = self._memoryctl_json(
            [
                "diagnose",
                "--root",
                str(memory_root),
                "--scope",
                scope,
                "--project",
                project,
                "--dry-run",
            ],
        )
        results["optimize_dry_run"] = self._memoryctl_json(
            [
                "optimize",
                "--root",
                str(memory_root),
                "--max-actions",
                "5",
                "--dry-run",
            ],
        )

        validate = results.get("validate_strict", {})
        validate_ok = bool(validate.get("ok"))
        error_count = int(validate.get("error_count", 1))
        warning_count = int(validate.get("warning_count", 1))
        results["hard_pass"] = validate_ok and error_count == 0 and warning_count == 0
        return results

    def _memoryctl_json(self, args: list[str]) -> dict[str, Any]:
        command = run_command(
            args=[
                "python",
                ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                *args,
            ],
            cwd=self.workspace_root,
            timeout_seconds=120,
        )

        payload = extract_json_payload(command.stdout)
        if isinstance(payload, dict):
            payload.setdefault("exit_code", command.exit_code)
            return payload

        return {
            "ok": False,
            "error": "unable to parse memoryctl JSON output",
            "exit_code": command.exit_code,
            "stdout": command.stdout,
            "stderr": command.stderr,
        }
