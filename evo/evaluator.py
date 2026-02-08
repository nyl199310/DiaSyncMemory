from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .io_utils import extract_json_payload, write_json
from .models import SCORE_DIMENSIONS, ScenarioExecution, ScenarioResult
from .opencode_client import OpenCodeClient


class SkillJudge:
    def __init__(
        self,
        *,
        client: OpenCodeClient,
        judge_contract: str,
        workspace_root: Path,
        skill_paths: list[str],
    ) -> None:
        self.client = client
        self.judge_contract = judge_contract
        self.workspace_root = workspace_root
        self.skill_paths = skill_paths

    def score(
        self,
        *,
        execution: ScenarioExecution,
        probe: dict[str, Any],
        artifact_dir: Path,
    ) -> dict[str, Any]:
        command_trace = execution.command_trace
        message_texts = execution.assistant_messages[-8:]

        prompt = self._build_prompt(
            execution=execution,
            probe=probe,
            command_trace=command_trace,
            message_texts=message_texts,
        )
        judge_run = self.client.run_message(
            prompt,
            title=f"judge-{execution.scenario.id}-epoch-{execution.epoch}",
            timeout_seconds=600,
        )

        joined_text = "\n".join(judge_run.texts)
        parsed = extract_json_payload(joined_text)
        if not isinstance(parsed, dict):
            parsed = {
                "overall": 0,
                "dimensions": {dimension: 0 for dimension in SCORE_DIMENSIONS},
                "hard_failures": ["judge_response_not_json"],
                "violations": ["Judge did not return machine-parseable JSON."],
                "strengths": [],
                "next_focus": ["Improve judge prompt and output strict JSON only."],
                "confidence": 0.0,
            }

        parsed.setdefault("overall", 0)
        parsed.setdefault("dimensions", {})
        parsed.setdefault("hard_failures", [])
        parsed.setdefault("violations", [])
        parsed.setdefault("strengths", [])
        parsed.setdefault("next_focus", [])

        write_json(
            artifact_dir / "judge-result.json",
            {
                "raw_text": joined_text,
                "parsed": parsed,
                "session_id": judge_run.session_id,
                "stdout": judge_run.stdout,
                "stderr": judge_run.stderr,
                "exit_code": judge_run.exit_code,
            },
        )
        return parsed

    def _build_prompt(
        self,
        *,
        execution: ScenarioExecution,
        probe: dict[str, Any],
        command_trace: list[str],
        message_texts: list[str],
    ) -> str:
        skill_manifest = "\n".join(f"- {path}" for path in self.skill_paths)
        contract = self.judge_contract.format(skill_manifest=skill_manifest)
        scenario = execution.scenario

        command_preview = command_trace[-80:]
        message_preview = message_texts[-8:]

        payload = {
            "scenario": {
                "id": scenario.id,
                "title": scenario.title,
                "description": scenario.description,
                "complexity_mode": scenario.complexity_mode,
                "difficulty": scenario.difficulty,
                "success_criteria": scenario.success_criteria,
                "tags": scenario.tags,
            },
            "memory_root": str(execution.memory_root),
            "session_id": execution.session_id,
            "command_trace": command_preview,
            "assistant_messages": message_preview,
            "probe": probe,
            "artifact_dir": str(execution.artifact_dir),
        }

        return f"{contract}\n\nEvaluation payload:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"


def score_execution(
    *,
    execution: ScenarioExecution,
    probe: dict[str, Any],
    judge_payload: dict[str, Any],
) -> ScenarioResult:
    dimensions = _normalize_dimensions(judge_payload.get("dimensions", {}))
    judge_score = float(judge_payload.get("overall", 0.0))
    violations = [str(item) for item in judge_payload.get("violations", [])]
    strengths = [str(item) for item in judge_payload.get("strengths", [])]
    next_focus = [str(item) for item in judge_payload.get("next_focus", [])]
    hard_failures = [str(item) for item in judge_payload.get("hard_failures", [])]

    hard_pass = bool(probe.get("hard_pass")) and not hard_failures
    machine_penalty = _machine_penalty(
        command_trace=execution.command_trace,
        memory_root=execution.memory_root,
    )
    if machine_penalty:
        violations.extend(machine_penalty)

    fitness = max(0.0, judge_score - 8.0 * len(machine_penalty))
    if not hard_pass:
        fitness = 0.0

    return ScenarioResult(
        scenario_id=execution.scenario.id,
        partition=execution.partition,
        epoch=execution.epoch,
        memory_root=str(execution.memory_root),
        session_id=execution.session_id,
        hard_pass=hard_pass,
        fitness=fitness,
        judge_score=judge_score,
        dimensions=dimensions,
        violations=violations,
        strengths=strengths,
        next_focus=next_focus,
        probe=probe,
        command_trace=execution.command_trace,
        artifact_dir=str(execution.artifact_dir),
    )


def _normalize_dimensions(payload: dict[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key in SCORE_DIMENSIONS:
        value = payload.get(key, 0)
        try:
            normalized[key] = float(value)
        except (TypeError, ValueError):
            normalized[key] = 0.0
    return normalized


def _machine_penalty(command_trace: list[str], memory_root: Path) -> list[str]:
    penalties: list[str] = []
    root_marker = f"--root {memory_root}"

    memoryctl_commands = [
        command for command in command_trace if "memoryctl.py" in command
    ]
    if not memoryctl_commands:
        penalties.append("No memoryctl commands observed in command trace.")
        return penalties

    root_count = sum(1 for command in memoryctl_commands if root_marker in command)
    if root_count == 0:
        penalties.append(
            "Memory commands did not target the scenario-specific filesystem root."
        )

    unresolved_stop = [
        command
        for command in memoryctl_commands
        if " sync start" in command and " sync stop" not in " ".join(memoryctl_commands)
    ]
    if unresolved_stop:
        penalties.append("Lifecycle appears incomplete: sync start without sync stop.")

    return penalties


def aggregate_scores(results: list[ScenarioResult]) -> tuple[float, float]:
    if not results:
        return 0.0, 0.0

    total_fitness = sum(item.fitness for item in results)
    hard_count = sum(1 for item in results if item.hard_pass)
    return total_fitness / len(results), hard_count / len(results)
