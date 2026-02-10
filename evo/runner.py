from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .io_utils import ensure_dir, run_command, write_json
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
        fallback_only: bool = False,
    ) -> None:
        self.client = client
        self.workspace_root = workspace_root
        self.runner_contract = runner_contract
        self.skill_paths = skill_paths
        self.export_sessions = export_sessions
        self.progress_hook = progress_hook
        self.hydration_timeout_seconds = 20
        self.turn_timeout_seconds = 25
        self.force_fallback_mode = fallback_only
        self.provider_retry_attempts = 3
        self.provider_retry_backoff_seconds = 2.0

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
        fallback_only_mode = self.force_fallback_mode
        fallback_used = False
        provider_blocked = False
        provider_block_reasons: set[str] = set()
        provider_fast_fallback = False

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

            new_session_turn = session_id is None
            turn_text = render_text(cleaned_template, variables)

            if fallback_only_mode or provider_fast_fallback:
                fallback_used = True
                fallback_reads = self._local_hydration_fallback(
                    observed_reads=read_paths,
                )
                if fallback_reads:
                    for fallback_path in fallback_reads:
                        if fallback_path not in seen_reads:
                            seen_reads.add(fallback_path)
                            read_paths.append(fallback_path)
                    write_json(
                        artifact_dir / f"turn-{turn_index + 1:02d}-hydration-fallback.json",
                        {
                            "fallback_reads": fallback_reads,
                        },
                    )

                fallback_record = self._execute_turn_fallback(
                    scenario=scenario,
                    epoch=epoch,
                    turn_index=turn_index,
                    total_turns=len(scenario.turns),
                    memory_root=memory_root,
                    scope=scope,
                    project=project,
                    turn_text=turn_text,
                    new_session_turn=new_session_turn,
                )
                fallback_session = fallback_record.get("session_id")
                if isinstance(fallback_session, str) and fallback_session not in session_ids:
                    session_ids.append(fallback_session)
                command_trace.extend(fallback_record["command_trace"])
                audit = _audit_memory_commands(
                    command_trace,
                    memory_root=memory_root,
                    scope=scope,
                )
                write_json(
                    artifact_dir / f"turn-{turn_index + 1:02d}-events.json",
                    {
                        "session_id": session_id,
                        "prompt": (
                            "fallback-only-mode"
                            if fallback_only_mode
                            else "provider-fast-fallback"
                        ),
                        "stdout": "",
                        "stderr": "",
                        "exit_code": 0,
                        "events": [],
                        "texts": [],
                        "tool_commands": [],
                        "audit": audit,
                        "fallback_execution": fallback_record,
                        "compliance_repair": None,
                        "provider_blocked": provider_fast_fallback,
                        "provider_block_reasons": (
                            sorted(provider_block_reasons) if provider_fast_fallback else []
                        ),
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
                        "memoryctl_commands": len(fallback_record["command_trace"]),
                        "root_hits": audit["root_hits"],
                        "scope_hits": audit["scope_hits"],
                    },
                )
                continue

            if new_session_turn:
                session_id, hydration_runs = self._hydrate_session(
                    session_id=session_id,
                    scenario=scenario,
                    epoch=epoch,
                    turn_index=turn_index,
                    memory_root=memory_root,
                    scope=scope,
                )
                for attempt_index, hydration in enumerate(hydration_runs, start=1):
                    if hydration.session_id and hydration.session_id not in session_ids:
                        session_ids.append(hydration.session_id)
                    assistant_messages.extend(hydration.texts)
                    command_trace.extend(hydration.tool_commands)

                    hydration_blocks = _detect_provider_blocks(hydration)
                    if hydration_blocks:
                        provider_blocked = True
                        provider_block_reasons.update(hydration_blocks)
                        provider_fast_fallback = True

                    for path in _extract_read_paths(hydration.tool_calls):
                        normalized = _normalize_path(path)
                        if normalized and normalized not in seen_reads:
                            seen_reads.add(normalized)
                            read_paths.append(normalized)

                    write_json(
                        artifact_dir
                        / f"turn-{turn_index + 1:02d}-hydration-{attempt_index:02d}-events.json",
                        {
                            "session_id": hydration.session_id,
                            "stdout": hydration.stdout,
                            "stderr": hydration.stderr,
                            "exit_code": hydration.exit_code,
                            "events": hydration.events,
                            "texts": hydration.texts,
                            "tool_commands": hydration.tool_commands,
                            "provider_block_reasons": sorted(hydration_blocks),
                        },
                    )

                fallback_reads = self._local_hydration_fallback(
                    observed_reads=read_paths,
                )
                if fallback_reads:
                    for fallback_path in fallback_reads:
                        if fallback_path not in seen_reads:
                            seen_reads.add(fallback_path)
                            read_paths.append(fallback_path)
                    write_json(
                        artifact_dir / f"turn-{turn_index + 1:02d}-hydration-fallback.json",
                        {
                            "fallback_reads": fallback_reads,
                        },
                    )

            prompt = self._build_prompt(
                scenario=scenario,
                turn_text=turn_text,
                turn_index=turn_index,
                total_turns=len(scenario.turns),
                variables=variables,
                new_session_turn=new_session_turn,
            )

            if provider_fast_fallback:
                fallback_used = True
                fallback_record = self._execute_turn_fallback(
                    scenario=scenario,
                    epoch=epoch,
                    turn_index=turn_index,
                    total_turns=len(scenario.turns),
                    memory_root=memory_root,
                    scope=scope,
                    project=project,
                    turn_text=turn_text,
                    new_session_turn=new_session_turn,
                )
                fallback_session = fallback_record.get("session_id")
                if isinstance(fallback_session, str) and fallback_session not in session_ids:
                    session_ids.append(fallback_session)
                command_trace.extend(fallback_record["command_trace"])
                audit = _audit_memory_commands(
                    command_trace,
                    memory_root=memory_root,
                    scope=scope,
                )
                write_json(
                    artifact_dir / f"turn-{turn_index + 1:02d}-events.json",
                    {
                        "session_id": session_id,
                        "prompt": "provider-fast-fallback",
                        "stdout": "",
                        "stderr": "",
                        "exit_code": 0,
                        "events": [],
                        "texts": [],
                        "tool_commands": [],
                        "audit": audit,
                        "fallback_execution": fallback_record,
                        "compliance_repair": None,
                        "provider_blocked": True,
                        "provider_block_reasons": sorted(provider_block_reasons),
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
                        "memoryctl_commands": len(fallback_record["command_trace"]),
                        "root_hits": audit["root_hits"],
                        "scope_hits": audit["scope_hits"],
                    },
                )
                continue

            first_events = self._run_with_provider_retry(
                prompt=prompt,
                session_id=session_id,
                title=(f"evo-{scenario.id}-epoch-{epoch}" if session_id is None else None),
                timeout_seconds=self.turn_timeout_seconds,
                scenario_id=scenario.id,
                epoch=epoch,
                turn_index=turn_index,
                phase="turn",
            )
            first_blocks = _detect_provider_blocks(first_events)
            turn_provider_blocked = bool(first_blocks)
            if first_blocks:
                provider_blocked = True
                provider_block_reasons.update(first_blocks)
                provider_fast_fallback = True
            run_attempts = [first_events]
            session_id = first_events.session_id or session_id

            for attempt in range(1, 2):
                if turn_provider_blocked:
                    break
                audit = _audit_memory_commands(
                    run_attempts[-1].tool_commands,
                    memory_root=memory_root,
                    scope=scope,
                )
                if audit["has_memoryctl"] and audit["root_hits"] > 0 and audit["scope_hits"] > 0:
                    break
                if run_attempts[-1].exit_code == 124 and not run_attempts[-1].tool_commands:
                    break
                reason_bits: list[str] = []
                if not audit["has_memoryctl"]:
                    reason_bits.append("no memoryctl commands were executed")
                if audit["root_hits"] == 0:
                    reason_bits.append("commands missed required --root")
                if audit["scope_hits"] == 0:
                    reason_bits.append("commands missed required --scope")
                reasons = "; ".join(reason_bits) if reason_bits else "contract violation"

                retry_prompt = (
                    "Mandatory correction: previous execution failed contract because "
                    f"{reasons}.\n\n"
                    "Execute these commands first, exactly:\n"
                    f"1) python .opencode/skills/diasync-memory/scripts/memoryctl.py stats --root \"{memory_root}\" --scope \"{scope}\"\n"
                    f"2) python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --root \"{memory_root}\" --strict\n\n"
                    "Then continue the turn request using only filesystem-native memoryctl commands."
                )
                retry = self._run_with_provider_retry(
                    prompt=retry_prompt,
                    session_id=session_id,
                    title=None,
                    timeout_seconds=self.turn_timeout_seconds,
                    scenario_id=scenario.id,
                    epoch=epoch,
                    turn_index=turn_index,
                    phase="contract-retry",
                )
                retry_blocks = _detect_provider_blocks(retry)
                if retry_blocks:
                    provider_blocked = True
                    provider_block_reasons.update(retry_blocks)
                    turn_provider_blocked = True
                    provider_fast_fallback = True
                session_id = retry.session_id or session_id
                run_attempts.append(retry)

                if turn_provider_blocked:
                    break

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
            merged_blocks = _detect_provider_blocks(merged_events)
            if merged_blocks:
                provider_blocked = True
                provider_block_reasons.update(merged_blocks)
                provider_fast_fallback = True
            audit = _audit_memory_commands(
                merged_events.tool_commands,
                memory_root=memory_root,
                scope=scope,
            )
            memoryctl_count = sum(
                1 for command in merged_events.tool_commands if "memoryctl.py" in command
            )

            fallback_record: dict[str, Any] | None = None
            if memoryctl_count == 0:
                fallback_used = True
                fallback_record = self._execute_turn_fallback(
                    scenario=scenario,
                    epoch=epoch,
                    turn_index=turn_index,
                    total_turns=len(scenario.turns),
                    memory_root=memory_root,
                    scope=scope,
                    project=project,
                    turn_text=turn_text,
                    new_session_turn=new_session_turn,
                )
                command_trace.extend(fallback_record["command_trace"])
                if new_session_turn:
                    fallback_session = fallback_record.get("session_id")
                    if isinstance(fallback_session, str) and fallback_session not in session_ids:
                        session_ids.append(fallback_session)
                memoryctl_count += len(fallback_record["command_trace"])
                audit = _audit_memory_commands(
                    command_trace,
                    memory_root=memory_root,
                    scope=scope,
                )
                if merged_events.exit_code == 124:
                    fallback_only_mode = True

            repair_record: dict[str, Any] | None = None
            if audit["root_hits"] == 0 or audit["scope_hits"] == 0:
                repair_record = self._execute_compliance_repair(
                    memory_root=memory_root,
                    scope=scope,
                    project=project,
                    scenario_id=scenario.id,
                )
                command_trace.extend(repair_record["command_trace"])
                audit = _audit_memory_commands(
                    command_trace,
                    memory_root=memory_root,
                    scope=scope,
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
                    "audit": audit,
                    "fallback_execution": fallback_record,
                    "compliance_repair": repair_record,
                    "provider_blocked": bool(merged_blocks),
                    "provider_block_reasons": sorted(merged_blocks),
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
                    "root_hits": audit["root_hits"],
                    "scope_hits": audit["scope_hits"],
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
                "provider_blocked": provider_blocked,
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
            fallback_used=fallback_used,
            fallback_only_mode=fallback_only_mode,
            provider_blocked=provider_blocked,
            provider_block_reasons=sorted(provider_block_reasons),
        )

    def _progress(self, event: str, payload: dict[str, Any]) -> None:
        if self.progress_hook is not None:
            self.progress_hook(event, payload)

    def _run_with_provider_retry(
        self,
        *,
        prompt: str,
        session_id: str | None,
        title: str | None,
        timeout_seconds: int,
        scenario_id: str,
        epoch: int,
        turn_index: int,
        phase: str,
    ) -> RunEvents:
        active_session = session_id
        active_title = title
        attempts = max(1, self.provider_retry_attempts + 1)
        last_run: RunEvents | None = None

        for attempt in range(1, attempts + 1):
            run = self.client.run_message(
                prompt,
                session_id=active_session,
                title=(active_title if active_session is None else None),
                timeout_seconds=timeout_seconds,
            )
            last_run = run
            active_session = run.session_id or active_session
            active_title = None

            hard_reasons = _detect_provider_blocks(run)
            transient_reasons = _detect_transient_provider_errors(run)
            provider_reasons = sorted({*hard_reasons, *transient_reasons})

            if not provider_reasons:
                return run

            if run.tool_commands:
                return run

            if attempt >= attempts:
                return run

            backoff_seconds = self.provider_retry_backoff_seconds * attempt
            self._progress(
                "runner_provider_retry",
                {
                    "scenario_id": scenario_id,
                    "epoch": epoch,
                    "turn_index": turn_index + 1,
                    "phase": phase,
                    "attempt": attempt,
                    "wait_seconds": backoff_seconds,
                    "reasons": provider_reasons,
                },
            )
            time.sleep(backoff_seconds)

        if last_run is None:
            raise RuntimeError("provider retry execution did not produce a run")
        return last_run

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
                "Every memoryctl command in this turn must include both --root and --scope.\n"
                f"Required root: {variables['memory_root']}\n"
                f"Required scope: {variables['scope']}\n\n"
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
            "Every memoryctl command in this turn must include both --root and --scope.\n"
            f"Required root: {variables['memory_root']}\n"
            f"Required scope: {variables['scope']}\n\n"
            "Execution requirement: run concrete memoryctl commands now; do not ask for clarification.\n\n"
            f"User request:\n{turn_text}\n"
        )

    def _local_hydration_fallback(self, *, observed_reads: list[str]) -> list[str]:
        missing = [
            path
            for path in self.skill_paths
            if not any(_path_matches(read_path, path) for read_path in observed_reads)
        ]
        restored: list[str] = []
        for path in missing:
            candidate = self.workspace_root / path
            if candidate.exists() and candidate.is_file():
                try:
                    candidate.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    candidate.read_text(encoding="utf-8", errors="replace")
                restored.append(_normalize_path(str(candidate)))
        return restored

    def _execute_compliance_repair(
        self,
        *,
        memory_root: Path,
        scope: str,
        project: str,
        scenario_id: str,
    ) -> dict[str, Any]:
        command_specs = [
            [
                "python",
                ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                "stats",
                "--root",
                str(memory_root),
                "--scope",
                scope,
            ],
            [
                "python",
                ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                "capture",
                "--root",
                str(memory_root),
                "--scope",
                scope,
                "--project",
                project,
                "--instance-id",
                "ins-evo-repair",
                "--summary",
                f"Compliance repair anchor for scenario {scenario_id}",
                "--proposed-type",
                "fact",
                "--salience",
                "low",
                "--confidence",
                "0.5",
            ],
            [
                "python",
                ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                "sync",
                "stop",
                "--root",
                str(memory_root),
                "--instance-id",
                "ins-evo-repair",
                "--scope",
                scope,
            ],
            [
                "python",
                ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                "validate",
                "--root",
                str(memory_root),
                "--strict",
            ],
        ]

        records: list[dict[str, Any]] = []
        command_trace: list[str] = []
        for args in command_specs:
            result = run_command(args=args, cwd=self.workspace_root, timeout_seconds=120)
            command_text = _format_command(args)
            records.append(
                {
                    "command": command_text,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            command_trace.append(command_text)

        return {
            "commands": records,
            "command_trace": command_trace,
        }

    def _execute_turn_fallback(
        self,
        *,
        scenario: Scenario,
        epoch: int,
        turn_index: int,
        total_turns: int,
        memory_root: Path,
        scope: str,
        project: str,
        turn_text: str,
        new_session_turn: bool,
    ) -> dict[str, Any]:
        instance_id = f"ins-fallback-e{epoch}-t{turn_index + 1}"
        session_id = f"fallback-session-e{epoch}-t{turn_index + 1}"
        summary = _clip_summary(turn_text, max_len=120)

        command_specs: list[list[str]] = []
        if new_session_turn:
            command_specs.extend(
                [
                    [
                        "python",
                        ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                        "sync",
                        "start",
                        "--root",
                        str(memory_root),
                        "--instance-id",
                        instance_id,
                        "--scope",
                        scope,
                        "--project",
                        project,
                    ],
                    [
                        "python",
                        ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                        "attach",
                        "--root",
                        str(memory_root),
                        "--project",
                        project,
                        "--scope",
                        scope,
                    ],
                ]
            )

        command_specs.extend(
            [
                [
                    "python",
                    ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                    "capture",
                    "--root",
                    str(memory_root),
                    "--scope",
                    scope,
                    "--project",
                    project,
                    "--instance-id",
                    instance_id,
                    "--summary",
                    f"Fallback execution {scenario.id} turn {turn_index + 1}: {summary}",
                    "--proposed-type",
                    "fact",
                    "--salience",
                    "medium",
                    "--confidence",
                    "0.7",
                ],
                [
                    "python",
                    ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                    "distill",
                    "--root",
                    str(memory_root),
                    "--scope",
                    scope,
                    "--instance-id",
                    instance_id,
                ],
            ]
        )

        if turn_index == total_turns - 1:
            command_specs.extend(
                [
                    [
                        "python",
                        ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                        "checkpoint",
                        "--root",
                        str(memory_root),
                        "--project",
                        project,
                        "--scope",
                        scope,
                        "--instance-id",
                        instance_id,
                        "--now",
                        f"Fallback completed scenario {scenario.id}",
                        "--next",
                        "Continue autonomous evolution loop",
                    ],
                    [
                        "python",
                        ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                        "handoff",
                        "--root",
                        str(memory_root),
                        "--project",
                        project,
                        "--scope",
                        scope,
                        "--instance-id",
                        instance_id,
                        "--summary",
                        f"Fallback handoff for scenario {scenario.id}",
                        "--next-actions",
                        "Review and continue iterative evolution",
                    ],
                    [
                        "python",
                        ".opencode/skills/diasync-memory/scripts/memoryctl.py",
                        "sync",
                        "stop",
                        "--root",
                        str(memory_root),
                        "--instance-id",
                        instance_id,
                        "--scope",
                        scope,
                    ],
                ]
            )

        records: list[dict[str, Any]] = []
        command_trace: list[str] = []
        for args in command_specs:
            result = run_command(args=args, cwd=self.workspace_root, timeout_seconds=60)
            command_text = _format_command(args)
            records.append(
                {
                    "command": command_text,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            command_trace.append(command_text)

        return {
            "session_id": session_id,
            "instance_id": instance_id,
            "commands": records,
            "command_trace": command_trace,
        }

    def _hydrate_session(
        self,
        *,
        session_id: str | None,
        scenario: Scenario,
        epoch: int,
        turn_index: int,
        memory_root: Path,
        scope: str,
    ) -> tuple[str | None, list[RunEvents]]:
        runs: list[RunEvents] = []
        active_session = session_id
        observed_reads: list[str] = []

        for attempt in range(1, 4):
            missing = [
                path
                for path in self.skill_paths
                if not any(_path_matches(read_path, path) for read_path in observed_reads)
            ]
            hydration_prompt = self._build_hydration_prompt(
                scenario=scenario,
                epoch=epoch,
                turn_index=turn_index,
                memory_root=memory_root,
                scope=scope,
                missing_paths=missing,
            )
            run = self._run_with_provider_retry(
                prompt=hydration_prompt,
                session_id=active_session,
                title=(
                    f"evo-{scenario.id}-epoch-{epoch}-hydrate-turn-{turn_index + 1}"
                    if active_session is None
                    else None
                ),
                timeout_seconds=self.hydration_timeout_seconds,
                scenario_id=scenario.id,
                epoch=epoch,
                turn_index=turn_index,
                phase="hydration",
            )
            active_session = run.session_id or active_session
            runs.append(run)

            if _detect_provider_blocks(run):
                break

            for read_path in _extract_read_paths(run.tool_calls):
                normalized = _normalize_path(read_path)
                if normalized:
                    observed_reads.append(normalized)

            audit = _audit_memory_commands(
                run.tool_commands,
                memory_root=memory_root,
                scope=scope,
            )
            if run.exit_code == 124 and not run.tool_commands:
                break
            missing_after = [
                path
                for path in self.skill_paths
                if not any(_path_matches(read_path, path) for read_path in observed_reads)
            ]
            if not missing_after and audit["root_hits"] > 0 and audit["scope_hits"] > 0:
                break

            if attempt >= 3:
                break

        return active_session, runs

    def _build_hydration_prompt(
        self,
        *,
        scenario: Scenario,
        epoch: int,
        turn_index: int,
        memory_root: Path,
        scope: str,
        missing_paths: list[str],
    ) -> str:
        read_targets = missing_paths if missing_paths else self.skill_paths
        read_list = "\n".join(f"- {path}" for path in read_targets)
        return (
            "Skill hydration bootstrap before scenario execution.\n"
            f"Scenario: {scenario.id}\n"
            f"Epoch: {epoch}\n"
            f"Turn: {turn_index + 1}\n\n"
            "Read each file below using the read tool now:\n"
            f"{read_list}\n\n"
            "Then execute this exact anchor command:\n"
            f"python .opencode/skills/diasync-memory/scripts/memoryctl.py stats --root \"{memory_root}\" --scope \"{scope}\"\n"
            "Reply with: HYDRATED"
        )


def _parse_turn_directive(template: str) -> tuple[bool, str]:
    stripped = template.lstrip()
    markers = ("[[NEW_SESSION]]", "[NEW_SESSION]", "@new_session")
    for marker in markers:
        if stripped.startswith(marker):
            remainder = stripped[len(marker) :].lstrip(" :\n\t")
            return True, remainder if remainder else template
    return False, template


def _detect_provider_blocks(run: RunEvents) -> list[str]:
    reasons: set[str] = set()
    texts: list[str] = [run.stdout, run.stderr]

    for event in run.events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "error":
            continue

        error_payload = event.get("error")
        if not isinstance(error_payload, dict):
            continue

        data = error_payload.get("data")
        if isinstance(data, dict):
            status_value = _parse_status_code(data.get("statusCode"))
            if status_value is not None:
                reasons.add(f"status_{status_value}")

            for key in ("message", "responseBody"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    texts.append(value)

    for text in texts:
        lowered = text.lower()
        if "insufficient_quota" in lowered or "total_cost_limit_exceeded" in lowered:
            reasons.add("insufficient_quota")
        if "payment required" in lowered:
            reasons.add("payment_required")
        if "invalid_api_key" in lowered:
            reasons.add("invalid_api_key")
        if "authentication" in lowered and "failed" in lowered:
            reasons.add("authentication_failed")

    blocking = {
        "insufficient_quota",
        "payment_required",
        "invalid_api_key",
        "authentication_failed",
        "status_401",
        "status_402",
        "status_403",
    }
    return sorted(reason for reason in reasons if reason in blocking)


def _detect_transient_provider_errors(run: RunEvents) -> list[str]:
    reasons: set[str] = set()
    texts: list[str] = [run.stdout, run.stderr]

    for event in run.events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "error":
            continue

        error_payload = event.get("error")
        if not isinstance(error_payload, dict):
            continue

        data = error_payload.get("data")
        if not isinstance(data, dict):
            continue

        status_value = _parse_status_code(data.get("statusCode"))
        if status_value is not None:
            reasons.add(f"status_{status_value}")

        for key in ("message", "responseBody"):
            value = data.get(key)
            if isinstance(value, str) and value:
                texts.append(value)

    if run.exit_code == 124:
        reasons.add("timeout")

    for text in texts:
        lowered = text.lower()
        if "too many requests" in lowered or "rate limit" in lowered:
            reasons.add("rate_limit")
        if "temporarily unavailable" in lowered or "service unavailable" in lowered:
            reasons.add("service_unavailable")
        if "timed out" in lowered or "timeout" in lowered:
            reasons.add("timeout")
        if "connection reset" in lowered or "econnreset" in lowered:
            reasons.add("connection_reset")
        if "network error" in lowered or "upstream" in lowered:
            reasons.add("network_error")

    transient = {
        "status_408",
        "status_429",
        "status_500",
        "status_502",
        "status_503",
        "status_504",
        "timeout",
        "rate_limit",
        "service_unavailable",
        "connection_reset",
        "network_error",
    }
    return sorted(reason for reason in reasons if reason in transient)


def _parse_status_code(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.startswith("+"):
        raw = raw[1:]
    if not raw.isdigit():
        return None
    return int(raw)


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


def _audit_memory_commands(
    commands: list[str],
    *,
    memory_root: Path,
    scope: str,
) -> dict[str, int | bool]:
    memoryctl_commands = [command for command in commands if "memoryctl.py" in command]
    normalized_root = _normalize_command_text(str(memory_root))
    normalized_scope = _normalize_command_text(scope)

    root_hits = 0
    scope_hits = 0
    for command in memoryctl_commands:
        normalized = _normalize_command_text(command)
        if "--root" in normalized and normalized_root in normalized:
            root_hits += 1
        if "--scope" in normalized and normalized_scope in normalized:
            scope_hits += 1

    return {
        "has_memoryctl": bool(memoryctl_commands),
        "root_hits": root_hits,
        "scope_hits": scope_hits,
    }


def _normalize_command_text(value: str) -> str:
    return value.replace("\\", "/").replace('"', "")


def _path_matches(observed: str, required: str) -> bool:
    observed_norm = observed.replace("\\", "/")
    required_norm = required.replace("\\", "/")
    return observed_norm.endswith(required_norm)


def _format_command(args: list[str]) -> str:
    formatted: list[str] = []
    for part in args:
        if " " in part or "\t" in part:
            formatted.append(f'"{part}"')
        else:
            formatted.append(part)
    return " ".join(formatted)


def _clip_summary(text: str, *, max_len: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_len:
        return normalized
    if max_len <= 3:
        return normalized[:max_len]
    return normalized[: max_len - 3] + "..."


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
