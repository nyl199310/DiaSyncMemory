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
        judge_input = self._build_input_payload(
            execution=execution,
            probe=probe,
        )
        input_path = artifact_dir / "judge-input.json"
        write_json(input_path, judge_input)

        prompt_payload = self._build_prompt_payload(judge_input)

        prompt = self._build_prompt(
            prompt_payload=prompt_payload,
        )
        judge_run = self.client.run_message(
            prompt,
            title=f"judge-{execution.scenario.id}-epoch-{execution.epoch}",
            timeout_seconds=60,
        )

        joined_text = "\n".join(judge_run.texts)
        parsed = _extract_judge_payload(joined_text)
        if not _is_valid_judge_payload(parsed):
            repaired = self._repair_json_response(
                session_id=judge_run.session_id,
                raw_text=joined_text,
            )
            repaired_payload = _extract_judge_payload(repaired)
            if _is_valid_judge_payload(repaired_payload):
                joined_text = joined_text + "\n" + repaired
                parsed = repaired_payload

        if not _is_valid_judge_payload(parsed):
            forced = self._force_judge_json(input_path=input_path)
            forced_payload = _extract_judge_payload(forced)
            if _is_valid_judge_payload(forced_payload):
                joined_text = joined_text + "\n" + forced
                parsed = forced_payload

        if _is_valid_judge_payload(parsed) and _is_unusable_judge_payload(parsed):
            compact = self._request_compact_ai_score(prompt_payload=prompt_payload)
            compact_payload = _extract_judge_payload(compact)
            if _is_valid_judge_payload(compact_payload):
                joined_text = joined_text + "\n" + compact
                parsed = compact_payload

        if not _is_valid_judge_payload(parsed):
            parsed = {
                "overall": 0,
                "dimensions": {dimension: 0 for dimension in SCORE_DIMENSIONS},
                "hard_failures": ["judge_response_not_json"],
                "violations": ["Judge did not return machine-parseable JSON."],
                "strengths": [],
                "next_focus": ["Improve judge prompt and output strict JSON only."],
                "confidence": 0.0,
            }

        assert isinstance(parsed, dict)
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
                "input_path": _display_path(input_path, self.workspace_root),
                "prompt_payload": prompt_payload,
            },
        )
        return parsed

    def _build_prompt(
        self,
        *,
        prompt_payload: dict[str, Any],
    ) -> str:
        payload_text = json.dumps(prompt_payload, ensure_ascii=True, indent=2)
        template_text = json.dumps(
            {
                "overall": 80,
                "dimensions": {
                    "diachronic": 80,
                    "synchronic": 80,
                    "governance": 80,
                    "realism": 80,
                    "skill_alignment": 80,
                },
                "hard_failures": [],
                "violations": [],
                "strengths": [],
                "next_focus": [],
                "confidence": 0.8,
            },
            ensure_ascii=True,
            indent=2,
        )
        return (
            "Return strict JSON only. Do not ask questions.\n"
            "Use this exact JSON template shape (same keys) and fill values from facts:\n"
            f"{template_text}\n\n"
            "Evaluation facts:\n"
            f"{payload_text}\n\n"
            "If uncertain, still return valid JSON using the same template with conservative values."
        )

    def _build_input_payload(
        self,
        *,
        execution: ScenarioExecution,
        probe: dict[str, Any],
    ) -> dict[str, Any]:
        scenario = execution.scenario
        command_preview = [_clip_text(command, 320) for command in execution.command_trace[-40:]]
        message_preview = [_clip_text(text, 600) for text in execution.assistant_messages[-6:]]

        return {
            "scenario": {
                "id": scenario.id,
                "title": scenario.title,
                "description": scenario.description,
                "complexity_mode": scenario.complexity_mode,
                "difficulty": scenario.difficulty,
                "success_criteria": scenario.success_criteria,
                "tags": scenario.tags,
                "turns": scenario.turns,
            },
            "execution": {
                "memory_root": str(execution.memory_root),
                "session_id": execution.session_id,
                "session_ids": execution.session_ids,
                "read_paths": execution.read_paths,
                "command_trace_tail": command_preview,
                "assistant_messages_tail": message_preview,
            },
            "probe": probe,
            "artifact_dir": str(execution.artifact_dir),
        }

    def _build_prompt_payload(self, judge_input: dict[str, Any]) -> dict[str, Any]:
        execution = judge_input.get("execution", {})
        probe = judge_input.get("probe", {})
        scenario = judge_input.get("scenario", {})

        command_tail = execution.get("command_trace_tail", [])
        if isinstance(command_tail, list):
            command_tail = command_tail[-10:]
        else:
            command_tail = []

        messages_tail = execution.get("assistant_messages_tail", [])
        if isinstance(messages_tail, list):
            messages_tail = messages_tail[-4:]
        else:
            messages_tail = []

        validate = probe.get("validate_strict", {})
        diagnose = probe.get("diagnose_dry_run", {})
        optimize = probe.get("optimize_dry_run", {})

        return {
            "scenario": {
                "id": scenario.get("id"),
                "complexity_mode": scenario.get("complexity_mode"),
                "difficulty": scenario.get("difficulty"),
                "success_criteria": scenario.get("success_criteria", []),
            },
            "execution": {
                "session_ids": execution.get("session_ids", []),
                "read_paths": execution.get("read_paths", []),
                "command_trace_tail": command_tail,
                "assistant_messages_tail": messages_tail,
            },
            "probe": {
                "hard_pass": probe.get("hard_pass"),
                "validate": {
                    "ok": validate.get("ok"),
                    "error_count": validate.get("error_count"),
                    "warning_count": validate.get("warning_count"),
                },
                "diagnose": {
                    "ok": diagnose.get("ok"),
                    "score": diagnose.get("score"),
                    "health": diagnose.get("health"),
                },
                "optimize": {
                    "ok": optimize.get("ok"),
                    "planned_count": optimize.get("planned_count"),
                    "executed_count": optimize.get("executed_count"),
                },
            },
        }

    def _repair_json_response(self, *, session_id: str | None, raw_text: str) -> str:
        if not session_id:
            return ""

        repair_prompt = (
            "Your previous output was not valid scoring JSON. "
            "Return only one strict JSON object now with keys: overall, dimensions, "
            "hard_failures, violations, strengths, next_focus, confidence. "
            "dimensions must include diachronic, synchronic, governance, realism, skill_alignment. "
            "No markdown. No questions."
        )
        repair = self.client.run_message(
            repair_prompt,
            session_id=session_id,
            timeout_seconds=45,
        )
        return "\n".join(repair.texts)

    def _force_judge_json(self, *, input_path: Path) -> str:
        template_text = json.dumps(
            {
                "overall": 75,
                "dimensions": {
                    "diachronic": 75,
                    "synchronic": 75,
                    "governance": 75,
                    "realism": 75,
                    "skill_alignment": 75,
                },
                "hard_failures": [],
                "violations": [],
                "strengths": [],
                "next_focus": [],
                "confidence": 0.7,
            },
            ensure_ascii=True,
            indent=2,
        )
        force_prompt = (
            "Return one strict JSON object only. No markdown. No questions.\n"
            "Read evaluation payload first from:\n"
            f"- {_display_path(input_path, self.workspace_root)}\n\n"
            "Use this exact template shape:\n"
            f"{template_text}"
        )
        force_run = self.client.run_message(
            force_prompt,
            title="judge-force-json",
            timeout_seconds=45,
        )
        return "\n".join(force_run.texts)

    def _request_compact_ai_score(self, *, prompt_payload: dict[str, Any]) -> str:
        compact_payload = {
            "scenario": prompt_payload.get("scenario", {}),
            "execution": {
                "session_count": len(prompt_payload.get("execution", {}).get("session_ids", [])),
                "skill_read_count": len(prompt_payload.get("execution", {}).get("read_paths", [])),
                "command_count": len(prompt_payload.get("execution", {}).get("command_trace_tail", [])),
            },
            "probe": prompt_payload.get("probe", {}),
        }
        compact_text = json.dumps(compact_payload, ensure_ascii=True)
        prompt = (
            "Score this memory execution and return strict JSON only. "
            "Do not ask questions.\n"
            "Required keys: overall, dimensions, hard_failures, violations, strengths, next_focus, confidence.\n"
            "Set hard_failures to [] when probe.hard_pass is true.\n"
            "Use 0-100 numbers for dimensions and overall.\n"
            f"Facts: {compact_text}"
        )
        run = self.client.run_message(
            prompt,
            title="judge-compact-fallback",
            timeout_seconds=45,
        )
        return "\n".join(run.texts)


def score_execution(
    *,
    execution: ScenarioExecution,
    probe: dict[str, Any],
    judge_payload: dict[str, Any],
    required_skill_paths: list[str] | None = None,
    minimum_skill_reads: int = 0,
    enforce_skill_hydration: bool = False,
    hard_fail_missing_skills: bool = True,
) -> ScenarioResult:
    dimensions = _normalize_dimensions(judge_payload.get("dimensions", {}))
    judge_score = float(judge_payload.get("overall", 0.0))
    violations = [str(item) for item in judge_payload.get("violations", [])]
    strengths = [str(item) for item in judge_payload.get("strengths", [])]
    next_focus = [str(item) for item in judge_payload.get("next_focus", [])]
    hard_failures = [str(item) for item in judge_payload.get("hard_failures", [])]

    judge_unavailable = "judge_response_not_json" in hard_failures
    judge_unreliable = judge_unavailable or (
        judge_score <= 0.0 and bool(hard_failures)
    )

    if judge_unreliable:
        violations = [
            item
            for item in violations
            if not _is_judge_meta_violation(item) and not _is_judge_parser_violation(item)
        ]
        next_focus = [
            item for item in next_focus if not _is_judge_meta_focus(item)
        ]
        fallback = _fallback_judge_score(execution=execution, probe=probe)
        judge_score = fallback["overall"]
        dimensions = fallback["dimensions"]
        hard_failures = []
        strengths.append("Heuristic fallback scoring maintained autonomous loop continuity.")
        next_focus.append("Restore strict JSON judge outputs to remove fallback mode.")

    validation_confidence = 1.0
    if judge_unreliable:
        validation_confidence = min(validation_confidence, 0.6)

    machine_penalty, hydration_fail = _machine_penalty(
        execution=execution,
        required_skill_paths=required_skill_paths or [],
        minimum_skill_reads=minimum_skill_reads,
        enforce_skill_hydration=enforce_skill_hydration,
        hard_fail_missing_skills=hard_fail_missing_skills,
    )
    hard_pass = bool(probe.get("hard_pass")) and not hard_failures and not hydration_fail
    if machine_penalty:
        violations.extend(machine_penalty)

    provider_penalty = 0.0
    if execution.provider_blocked:
        provider_penalty = 45.0
        hard_pass = False
        validation_confidence = min(validation_confidence, 0.2)
        reason_text = ", ".join(execution.provider_block_reasons) or "provider_error"
        violations.append(
            "Runner provider was unavailable during autonomous execution "
            f"({reason_text}); evaluation cannot confirm true self-improvement behavior."
        )
        next_focus.append(
            "Restore runner provider quota or credentials so autonomous execution can be evaluated."
        )

    fallback_penalty = 0.0
    if execution.fallback_only_mode:
        fallback_penalty = 35.0
        validation_confidence = min(validation_confidence, 0.3)
        violations.append(
            "Runner stayed in deterministic fallback-only mode; autonomous behavior was not exercised."
        )
        next_focus.append("Disable fallback-only mode and restore autonomous runner execution.")
    elif execution.fallback_used:
        fallback_penalty = 15.0
        validation_confidence = min(validation_confidence, 0.65)
        violations.append(
            "Runner required deterministic fallback execution for at least one turn."
        )
        next_focus.append("Reduce fallback dependency by improving contract-following behavior.")

    total_penalty = fallback_penalty + provider_penalty
    if total_penalty > 0.0:
        judge_score = max(0.0, judge_score - total_penalty)
        dimensions = {
            key: max(0.0, value - total_penalty)
            for key, value in dimensions.items()
        }

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
        fallback_used=execution.fallback_used,
        provider_blocked=execution.provider_blocked,
        provider_block_reasons=execution.provider_block_reasons,
        validation_confidence=validation_confidence,
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


def _machine_penalty(
    *,
    execution: ScenarioExecution,
    required_skill_paths: list[str],
    minimum_skill_reads: int,
    enforce_skill_hydration: bool,
    hard_fail_missing_skills: bool,
) -> tuple[list[str], bool]:
    penalties: list[str] = []
    hydration_fail = False

    command_trace = execution.command_trace
    memory_root = execution.memory_root
    normalized_root = _normalize_cli_text(str(memory_root))

    memoryctl_commands = [
        command for command in command_trace if "memoryctl.py" in command
    ]
    if not memoryctl_commands:
        penalties.append("No memoryctl commands observed in command trace.")
        return penalties, hydration_fail

    root_count = sum(
        1
        for command in memoryctl_commands
        if "--root" in command and normalized_root in _normalize_cli_text(command)
    )
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

    expects_multi_session = any(
        index > 0
        and turn.lstrip().startswith(("[[NEW_SESSION]]", "[NEW_SESSION]", "@new_session"))
        for index, turn in enumerate(execution.scenario.turns)
    )
    multi_session_observed = len(set(execution.session_ids)) >= 2
    multi_session_observed = multi_session_observed or _has_multi_session_signature(
        memoryctl_commands
    )
    if expects_multi_session and not multi_session_observed:
        penalties.append(
            "Scenario expected multiple sessions but runner stayed in a single session."
        )

    if enforce_skill_hydration:
        read_paths = execution.read_paths
        if len(read_paths) < max(0, minimum_skill_reads):
            penalties.append(
                "Skill hydration read count below required minimum before execution."
            )
            if hard_fail_missing_skills:
                hydration_fail = True

        missing = [
            path
            for path in required_skill_paths
            if not any(_path_matches(read_path, path) for read_path in read_paths)
        ]
        if missing:
            penalties.append(
                "Missing required skill reads: " + ", ".join(missing)
            )
            if hard_fail_missing_skills:
                hydration_fail = True

    return penalties, hydration_fail


def _path_matches(observed: str, required: str) -> bool:
    observed_norm = observed.replace("\\", "/")
    required_norm = required.replace("\\", "/")
    return observed_norm.endswith(required_norm)


def _normalize_cli_text(value: str) -> str:
    return value.replace("\\", "/").replace('"', "")


def _display_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _clip_text(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 3] + "..."


def _is_valid_judge_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False

    if "overall" not in payload or "dimensions" not in payload:
        return False
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict):
        return False

    for dimension in SCORE_DIMENSIONS:
        value = dimensions.get(dimension)
        if value is None:
            return False
        try:
            float(value)
        except (TypeError, ValueError):
            return False

    for key in ("hard_failures", "violations", "strengths", "next_focus"):
        if key not in payload:
            return False
        if not isinstance(payload[key], list):
            return False

    return True


def _is_unusable_judge_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return True
    hard_failures = payload.get("hard_failures", [])
    if isinstance(hard_failures, list) and hard_failures:
        return True
    try:
        overall = float(payload.get("overall", 0))
    except (TypeError, ValueError):
        return True
    return overall <= 0.0


def _fallback_judge_score(
    *,
    execution: ScenarioExecution,
    probe: dict[str, Any],
) -> dict[str, Any]:
    validate = probe.get("validate_strict", {})
    diagnose = probe.get("diagnose_dry_run", {})

    validate_ok = bool(validate.get("ok")) and int(validate.get("error_count", 1)) == 0
    diagnose_score = float(diagnose.get("score", 0.0))

    score = 45.0
    if validate_ok:
        score += 20.0
    if diagnose_score >= 95:
        score += 15.0
    if execution.read_paths:
        score += 8.0

    root_hint = sum(1 for command in execution.command_trace if "--root" in command)
    if root_hint > 0:
        score += 7.0

    score = max(0.0, min(100.0, score))
    dimensions = {
        "diachronic": score,
        "synchronic": score,
        "governance": score,
        "realism": score,
        "skill_alignment": score,
    }
    return {
        "overall": score,
        "dimensions": dimensions,
    }


def _extract_judge_payload(text: str) -> object:
    candidates: list[dict[str, Any]] = []

    direct = extract_json_payload(text)
    normalized_direct = _normalize_judge_candidate(direct)
    if normalized_direct is not None:
        candidates.append(normalized_direct)

    for block in _extract_fenced_json_blocks(text):
        try:
            normalized = _normalize_judge_candidate(json.loads(block))
            if normalized is not None:
                candidates.append(normalized)
        except json.JSONDecodeError:
            continue

    for block in _extract_braced_candidates(text):
        try:
            normalized = _normalize_judge_candidate(json.loads(block))
            if normalized is not None:
                candidates.append(normalized)
        except json.JSONDecodeError:
            continue

    for candidate in candidates:
        if _is_valid_judge_payload(candidate):
            return candidate

    return candidates[0] if candidates else None


def _normalize_judge_candidate(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    overall_raw = payload.get("overall", payload.get("score"))
    try:
        overall = float(f"{overall_raw}")
    except (TypeError, ValueError):
        return None

    dimensions_raw = payload.get("dimensions")
    numeric_values: list[float] = []
    if isinstance(dimensions_raw, dict):
        for value in dimensions_raw.values():
            try:
                numeric_values.append(float(f"{value}"))
            except (TypeError, ValueError):
                continue

    dimension_fill = overall if not numeric_values else sum(numeric_values) / len(numeric_values)
    dimensions: dict[str, float] = {}
    if isinstance(dimensions_raw, dict):
        for key in SCORE_DIMENSIONS:
            value = dimensions_raw.get(key)
            if value is None:
                dimensions[key] = float(dimension_fill)
                continue
            try:
                dimensions[key] = float(f"{value}")
            except (TypeError, ValueError):
                dimensions[key] = float(dimension_fill)
    else:
        dimensions = {key: float(dimension_fill) for key in SCORE_DIMENSIONS}

    confidence_raw = payload.get("confidence", 0.8)
    try:
        confidence = float(f"{confidence_raw}")
    except (TypeError, ValueError):
        confidence = 0.8
    if confidence > 1.0:
        confidence = confidence / 100.0
    confidence = max(0.0, min(1.0, confidence))

    normalized = {
        "overall": max(0.0, min(100.0, overall)),
        "dimensions": dimensions,
        "hard_failures": _coerce_list(payload.get("hard_failures")),
        "violations": _coerce_list(payload.get("violations")),
        "strengths": _coerce_list(payload.get("strengths")),
        "next_focus": _coerce_list(payload.get("next_focus")),
        "confidence": confidence,
    }
    return normalized


def _coerce_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _extract_fenced_json_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    marker = "```"
    position = 0
    while True:
        start = text.find(marker, position)
        if start == -1:
            break
        end = text.find(marker, start + len(marker))
        if end == -1:
            break
        block = text[start + len(marker) : end]
        if block.startswith("json"):
            blocks.append(block[4:].strip())
        else:
            blocks.append(block.strip())
        position = end + len(marker)
    return blocks


def _extract_braced_candidates(text: str) -> list[str]:
    results: list[str] = []
    start_positions = [index for index, char in enumerate(text) if char == "{"]
    for start in start_positions:
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    results.append(text[start : index + 1])
                    break
    return results


def _is_judge_meta_violation(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "no context",
        "cannot assess",
        "target artifact",
        "memory root",
        "baseline or reference",
        "artifact or system state",
    )
    return any(marker in lowered for marker in markers)


def _is_judge_meta_focus(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "provide memory root",
        "specify validation scope",
        "supply ledger",
        "artifact to score",
    )
    return any(marker in lowered for marker in markers)


def _is_judge_parser_violation(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "judge did not return machine-parseable json",
        "judge response unavailable",
        "judge scoring unavailable",
    )
    return any(marker in lowered for marker in markers)


def _has_multi_session_signature(commands: list[str]) -> bool:
    instance_ids: set[str] = set()
    sync_start_count = 0
    for command in commands:
        if " sync start" not in command:
            continue
        sync_start_count += 1
        match = re.search(r"--instance-id\s+\"?([^\s\"]+)", command)
        if match:
            instance_ids.add(match.group(1))

    if len(instance_ids) >= 2:
        return True
    return sync_start_count >= 2 and len(instance_ids) >= 1


def aggregate_scores(results: list[ScenarioResult]) -> tuple[float, float]:
    if not results:
        return 0.0, 0.0

    total_fitness = sum(item.fitness for item in results)
    hard_count = sum(1 for item in results if item.hard_pass)
    return total_fitness / len(results), hard_count / len(results)
