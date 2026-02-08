from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .io_utils import ensure_dir, write_json
from .models import RunEvents, Scenario, ScenarioExecution
from .opencode_client import OpenCodeClient
from .scenarios import render_text


class ScenarioRunner:
    def __init__(
        self,
        *,
        client: OpenCodeClient,
        workspace_root: Path,
        runner_contract: str,
        skill_paths: list[str],
        export_sessions: bool = True,
        progress_hook: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.client = client
        self.workspace_root = workspace_root
        self.runner_contract = runner_contract
        self.skill_paths = skill_paths
        self.export_sessions = export_sessions
        self.progress_hook = progress_hook

    def execute(
        self,
        *,
        scenario: Scenario,
        partition: str,
        epoch: int,
        memory_root: Path,
        artifact_dir: Path,
        project: str,
        scope: str,
    ) -> ScenarioExecution:
        self._progress(
            "scenario_execute_start",
            {
                "scenario_id": scenario.id,
                "partition": partition,
                "epoch": epoch,
                "turn_count": len(scenario.turns),
            },
        )
        ensure_dir(memory_root)
        ensure_dir(artifact_dir)

        session_id: str | None = None
        session_ids: list[str] = []
        turns: list[RunEvents] = []
        assistant_messages: list[str] = []
        command_trace: list[str] = []
        read_paths: list[str] = []
        seen_reads: set[str] = set()

        variables = {
            "project": project,
            "scope": scope,
            "memory_root": str(memory_root),
            "scenario_id": scenario.id,
            "scenario_title": scenario.title,
            "scenario_description": scenario.description,
            "skill_manifest": "\n".join(f"- {path}" for path in self.skill_paths),
            "success_criteria": "\n".join(
                f"- {criterion}" for criterion in scenario.success_criteria
            ),
        }

        for turn_index, turn_template in enumerate(scenario.turns):
            self._progress(
                "scenario_turn_start",
                {
                    "scenario_id": scenario.id,
                    "partition": partition,
                    "epoch": epoch,
                    "turn_index": turn_index + 1,
                    "turn_total": len(scenario.turns),
                },
            )
            force_new_session, cleaned_template = _parse_turn_directive(turn_template)
            if force_new_session:
                session_id = None

            turn_text = render_text(cleaned_template, variables)
            new_session_turn = session_id is None
            prompt = self._build_prompt(
                scenario=scenario,
                turn_text=turn_text,
                turn_index=turn_index,
                total_turns=len(scenario.turns),
                variables=variables,
                new_session_turn=new_session_turn,
            )

            first_events = self.client.run_message(
                prompt,
                session_id=session_id,
                title=(f"evo-{scenario.id}-epoch-{epoch}" if session_id is None else None),
                timeout_seconds=45,
            )
            run_attempts = [first_events]
            session_id = first_events.session_id or session_id

            for attempt in range(1, 2):
                if _contains_memoryctl_command(run_attempts[-1].tool_commands):
                    break
                retry_prompt = (
                    "Your last response did not execute concrete memoryctl commands. "
                    "Execute the requested memory operations now with filesystem-native commands. "
                    "Do not ask questions."
                )
                retry = self.client.run_message(
                    retry_prompt,
                    session_id=session_id,
                    timeout_seconds=45,
                )
                session_id = retry.session_id or session_id
                run_attempts.append(retry)

                write_json(
                    artifact_dir / f"turn-{turn_index + 1:02d}-retry-{attempt:02d}-events.json",
                    {
                        "session_id": session_id,
                        "prompt": retry_prompt,
                        "stdout": retry.stdout,
                        "stderr": retry.stderr,
                        "exit_code": retry.exit_code,
                        "events": retry.events,
                        "texts": retry.texts,
                        "tool_commands": retry.tool_commands,
                    },
                )

            merged_events = _merge_run_events(run_attempts)
            memoryctl_count = sum(
                1 for command in merged_events.tool_commands if "memoryctl.py" in command
            )
            session_id = merged_events.session_id or session_id
            if session_id and session_id not in session_ids:
                session_ids.append(session_id)

            turns.append(merged_events)
            assistant_messages.extend(merged_events.texts)
            command_trace.extend(merged_events.tool_commands)

            for path in _extract_read_paths(merged_events.tool_calls):
                normalized = _normalize_path(path)
                if normalized and normalized not in seen_reads:
                    seen_reads.add(normalized)
                    read_paths.append(normalized)

            write_json(
                artifact_dir / f"turn-{turn_index + 1:02d}-events.json",
                {
                    "session_id": session_id,
                    "prompt": prompt,
                    "stdout": merged_events.stdout,
                    "stderr": merged_events.stderr,
                    "exit_code": merged_events.exit_code,
                    "events": merged_events.events,
                    "texts": merged_events.texts,
                    "tool_commands": merged_events.tool_commands,
                },
            )

            self._progress(
                "scenario_turn_finish",
                {
                    "scenario_id": scenario.id,
                    "partition": partition,
                    "epoch": epoch,
                    "turn_index": turn_index + 1,
                    "turn_total": len(scenario.turns),
                    "memoryctl_commands": memoryctl_count,
                },
            )

        exported_session_path: Path | None = None
        if session_id and self.export_sessions:
            exported_payload = self.client.export_session(session_id)
            exported_session_path = artifact_dir / "session-export.json"
            write_json(exported_session_path, exported_payload)

        self._progress(
            "scenario_execute_finish",
            {
                "scenario_id": scenario.id,
                "partition": partition,
                "epoch": epoch,
                "session_ids": session_ids,
                "memoryctl_commands": sum(
                    1 for command in command_trace if "memoryctl.py" in command
                ),
                "skill_reads": len(read_paths),
            },
        )

        return ScenarioExecution(
            scenario=scenario,
            partition=partition,
            epoch=epoch,
            memory_root=memory_root,
            artifact_dir=artifact_dir,
            session_id=session_id,
            turns=turns,
            assistant_messages=assistant_messages,
            command_trace=command_trace,
            read_paths=read_paths,
            session_ids=session_ids,
            exported_session_path=exported_session_path,
        )

    def _progress(self, event: str, payload: dict[str, Any]) -> None:
        if self.progress_hook is not None:
            self.progress_hook(event, payload)

    def _build_prompt(
        self,
        *,
        scenario: Scenario,
        turn_text: str,
        turn_index: int,
        total_turns: int,
        variables: dict[str, str],
        new_session_turn: bool,
    ) -> str:
        if turn_index == 0 or new_session_turn:
            header = render_text(self.runner_contract, variables)
            skill_read_list = "\n".join(
                f"- {path}" for path in self.skill_paths
            )
            return (
                f"{header}\n\n"
                f"Scenario ID: {scenario.id}\n"
                f"Complexity mode: {scenario.complexity_mode}\n"
                f"Turn: {turn_index + 1}/{total_turns}\n\n"
                "Skill hydration requirement: before planning or execution, read these files now:"
                f"\n{skill_read_list}\n\n"
                "Execution requirement: run concrete memoryctl commands now; do not only describe a plan.\n\n"
                f"User request:\n{turn_text}\n"
            )

        return (
            "Continue in the same session contract.\n"
            f"Scenario ID: {scenario.id}\n"
            f"Turn: {turn_index + 1}/{total_turns}\n"
            f"Memory root remains: {variables['memory_root']}\n"
            f"Scope remains: {variables['scope']}\n"
            f"Project remains: {variables['project']}\n\n"
            "Execution requirement: run concrete memoryctl commands now; do not ask for clarification.\n\n"
            f"User request:\n{turn_text}\n"
        )


def _parse_turn_directive(template: str) -> tuple[bool, str]:
    stripped = template.lstrip()
    markers = ("[[NEW_SESSION]]", "[NEW_SESSION]", "@new_session")
    for marker in markers:
        if stripped.startswith(marker):
            remainder = stripped[len(marker) :].lstrip(" :\n\t")
            return True, remainder if remainder else template
    return False, template


def _extract_read_paths(tool_calls: list[dict]) -> list[str]:
    paths: list[str] = []
    for call in tool_calls:
        tool_name = call.get("tool")
        if tool_name != "read":
            continue

        state = call.get("state", {})
        input_payload = state.get("input", {})
        file_path = input_payload.get("filePath")
        if isinstance(file_path, str) and file_path:
            paths.append(file_path)
    return paths


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/")


def _contains_memoryctl_command(commands: list[str]) -> bool:
    return any("memoryctl.py" in command for command in commands)


def _merge_run_events(runs: list[RunEvents]) -> RunEvents:
    if len(runs) == 1:
        return runs[0]

    session_id = runs[-1].session_id or runs[0].session_id
    return RunEvents(
        session_id=session_id,
        stdout="\n".join(run.stdout for run in runs if run.stdout),
        stderr="\n".join(run.stderr for run in runs if run.stderr),
        exit_code=runs[-1].exit_code,
        events=[event for run in runs for event in run.events],
        texts=[text for run in runs for text in run.texts],
        tool_commands=[command for run in runs for command in run.tool_commands],
        tool_calls=[call for run in runs for call in run.tool_calls],
    )
