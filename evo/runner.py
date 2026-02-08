from __future__ import annotations

import json
from pathlib import Path

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
    ) -> None:
        self.client = client
        self.workspace_root = workspace_root
        self.runner_contract = runner_contract
        self.skill_paths = skill_paths

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
        ensure_dir(memory_root)
        ensure_dir(artifact_dir)

        session_id: str | None = None
        turns: list[RunEvents] = []
        assistant_messages: list[str] = []
        command_trace: list[str] = []

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
            turn_text = render_text(turn_template, variables)
            prompt = self._build_prompt(
                scenario=scenario,
                turn_text=turn_text,
                turn_index=turn_index,
                total_turns=len(scenario.turns),
                variables=variables,
            )

            events = self.client.run_message(
                prompt,
                session_id=session_id,
                title=(f"evo-{scenario.id}-epoch-{epoch}" if session_id is None else None),
                timeout_seconds=600,
            )
            session_id = events.session_id or session_id
            turns.append(events)
            assistant_messages.extend(events.texts)
            command_trace.extend(events.tool_commands)

            write_json(
                artifact_dir / f"turn-{turn_index + 1:02d}-events.json",
                {
                    "session_id": session_id,
                    "prompt": prompt,
                    "stdout": events.stdout,
                    "stderr": events.stderr,
                    "exit_code": events.exit_code,
                    "events": events.events,
                    "texts": events.texts,
                    "tool_commands": events.tool_commands,
                },
            )

        exported_session_path: Path | None = None
        if session_id:
            exported_payload = self.client.export_session(session_id)
            exported_session_path = artifact_dir / "session-export.json"
            write_json(exported_session_path, exported_payload)

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
            exported_session_path=exported_session_path,
        )

    def _build_prompt(
        self,
        *,
        scenario: Scenario,
        turn_text: str,
        turn_index: int,
        total_turns: int,
        variables: dict[str, str],
    ) -> str:
        if turn_index == 0:
            header = render_text(self.runner_contract, variables)
            return (
                f"{header}\n\n"
                f"Scenario ID: {scenario.id}\n"
                f"Complexity mode: {scenario.complexity_mode}\n"
                f"Turn: {turn_index + 1}/{total_turns}\n\n"
                f"User request:\n{turn_text}\n"
            )

        return (
            "Continue in the same session contract.\n"
            f"Scenario ID: {scenario.id}\n"
            f"Turn: {turn_index + 1}/{total_turns}\n"
            f"Memory root remains: {variables['memory_root']}\n"
            f"Scope remains: {variables['scope']}\n"
            f"Project remains: {variables['project']}\n\n"
            f"User request:\n{turn_text}\n"
        )
