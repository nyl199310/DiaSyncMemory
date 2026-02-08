from __future__ import annotations

import json
import shutil
import statistics
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import EvolutionConfig
from .evaluator import SkillJudge, aggregate_scores, score_execution
from .io_utils import ensure_dir, now_utc_stamp, run_shell_command, write_json
from .models import Decision, EvaluationSnapshot, MutationProposal, Scenario, ScenarioResult
from .mutator import Mutator
from .opencode_client import OpenCodeClient
from .probe import MemoryProbe
from .runner import ScenarioRunner
from .scenarios import load_scenarios, select_batch
from .synthesizer import ScenarioSynthesizer


class EvolutionOrchestrator:
    def __init__(
        self,
        *,
        workspace_root: Path,
        config: EvolutionConfig,
        dry_run: bool = False,
        disable_mutation: bool = False,
        progress_enabled: bool = True,
        heartbeat_seconds: int = 15,
    ) -> None:
        self.workspace_root = workspace_root
        self.config = config
        self.dry_run = dry_run
        self.disable_mutation = disable_mutation
        self.progress_enabled = progress_enabled
        self.heartbeat_seconds = max(1, heartbeat_seconds)

        self._activate_runtime_lane_allow_paths()

        self.run_id = f"{now_utc_stamp()}-{uuid.uuid4().hex[:8]}"
        self.run_dir = self.workspace_root / config.artifact_root / self.run_id
        self.progress_log_path = self.run_dir / "progress.jsonl"
        self.started_monotonic = time.monotonic()
        self._progress_lock = threading.Lock()
        self._live_progress_enabled = self.progress_enabled and sys.stderr.isatty()
        self._last_live_line_len = 0
        self._live_state: dict[str, Any] = {
            "run_id": self.run_id,
            "event": "init",
            "epoch": 0,
            "epoch_total": self.config.max_epochs,
            "label": "",
            "partition": "",
            "scenario_id": "",
            "progress": "",
            "role": "",
            "elapsed_seconds": 0,
            "train_score": None,
            "holdout_score": None,
        }

        runner_contract = _read_text(self.workspace_root / "evo/prompts/runner_contract.md")
        judge_contract = _read_text(self.workspace_root / "evo/prompts/judge_contract.md")
        mutator_contract = _read_text(self.workspace_root / "evo/prompts/mutator_contract.md")
        synthesizer_contract = _read_text(
            self.workspace_root / "evo/prompts/scenario_synthesizer_contract.md"
        )

        runner_client = OpenCodeClient(
            workspace_root,
            config.runner,
            progress_callback=lambda event, payload: self._progress(
                event,
                role="runner",
                **payload,
            ),
            heartbeat_seconds=self.heartbeat_seconds,
        )
        judge_client = OpenCodeClient(
            workspace_root,
            config.judge,
            progress_callback=lambda event, payload: self._progress(
                event,
                role="judge",
                **payload,
            ),
            heartbeat_seconds=self.heartbeat_seconds,
        )
        mutator_client = OpenCodeClient(
            workspace_root,
            config.mutator,
            progress_callback=lambda event, payload: self._progress(
                event,
                role="mutator",
                **payload,
            ),
            heartbeat_seconds=self.heartbeat_seconds,
        )
        synthesizer_client = OpenCodeClient(
            workspace_root,
            config.synthesizer,
            progress_callback=lambda event, payload: self._progress(
                event,
                role="synthesizer",
                **payload,
            ),
            heartbeat_seconds=self.heartbeat_seconds,
        )

        self.runner = ScenarioRunner(
            client=runner_client,
            workspace_root=workspace_root,
            runner_contract=runner_contract,
            skill_paths=config.skill_paths,
            export_sessions=config.export_sessions,
            progress_hook=lambda event, payload: self._progress(event, **payload),
        )
        self.judge = SkillJudge(
            client=judge_client,
            judge_contract=judge_contract,
            workspace_root=workspace_root,
            skill_paths=config.skill_paths,
        )
        self.mutator = Mutator(
            client=mutator_client,
            workspace_root=workspace_root,
            mutation_config=config.mutation,
            mutator_contract=mutator_contract,
            skill_paths=config.skill_paths,
        )
        self.synthesizer = ScenarioSynthesizer(
            client=synthesizer_client,
            synthesis_config=config.synthesis,
            contract=synthesizer_contract,
            skill_paths=config.skill_paths,
        )
        self.probe = MemoryProbe(workspace_root)

    def run(self) -> dict[str, Any]:
        ensure_dir(self.run_dir)
        ensure_dir(self.workspace_root / self.config.memory_run_root / self.run_id)
        self._progress(
            "run_start",
            run_id=self.run_id,
            max_epochs=self.config.max_epochs,
            continuous=self.config.continuous,
            dry_run=self.dry_run,
            disable_mutation=self.disable_mutation,
        )

        static_train = load_scenarios(
            self.workspace_root,
            self.config.train_scenarios_glob,
        )
        static_holdout = load_scenarios(
            self.workspace_root,
            self.config.holdout_scenarios_glob,
        )
        if not static_train:
            raise RuntimeError("No training scenarios found for evolution loop.")
        if not static_holdout:
            raise RuntimeError("No holdout scenarios found for evolution loop.")

        write_json(
            self.run_dir / "run-config.json",
            {
                "run_id": self.run_id,
                "workspace_root": str(self.workspace_root),
                "config": self.config.to_dict(),
                "dry_run": self.dry_run,
                "disable_mutation": self.disable_mutation,
            },
        )
        self._progress(
            "scenario_pool_loaded",
            train_count=len(static_train),
            holdout_count=len(static_holdout),
        )

        baseline_synth_train, baseline_synth_holdout = self._synthesize_epoch_scenarios(
            epoch=0,
            static_train=static_train,
            static_holdout=static_holdout,
            recent_train_failures=[],
            epoch_dir=self.run_dir / "epoch-000",
        )
        baseline_train_pool = _merge_scenarios(static_train, baseline_synth_train)
        baseline_holdout_pool = _merge_scenarios(static_holdout, baseline_synth_holdout)
        baseline_train_batch, baseline_holdout_batch = self._select_batches(
            epoch=0,
            train_pool=baseline_train_pool,
            holdout_pool=baseline_holdout_pool,
            force_full=False,
        )
        baseline_snapshot = self._evaluate_snapshot(
            epoch=0,
            label="baseline",
            train_batch=baseline_train_batch,
            holdout_batch=baseline_holdout_batch,
        )
        self._progress(
            "baseline_complete",
            train_score=baseline_snapshot.train_score,
            holdout_score=baseline_snapshot.holdout_score,
            hard_pass_rate=baseline_snapshot.hard_pass_rate,
        )
        write_json(
            self.run_dir / "epoch-000-baseline-summary.json",
            _snapshot_to_dict(baseline_snapshot),
        )

        active_snapshot = baseline_snapshot
        recent_train_failures = _collect_recent_failures(
            active_snapshot.scenario_results,
            partition="train",
        )

        history: list[dict[str, Any]] = []
        stagnant_epochs = 0
        epoch = 1
        stop_reason = ""

        while True:
            reason = self._stop_reason(epoch=epoch, stagnant_epochs=stagnant_epochs)
            if reason:
                stop_reason = reason
                break

            self._progress(
                "epoch_start",
                epoch=epoch,
                stagnant_epochs=stagnant_epochs,
            )

            epoch_dir = self.run_dir / f"epoch-{epoch:03d}"
            ensure_dir(epoch_dir)

            synth_train, synth_holdout = self._synthesize_epoch_scenarios(
                epoch=epoch,
                static_train=static_train,
                static_holdout=static_holdout,
                recent_train_failures=recent_train_failures,
                epoch_dir=epoch_dir,
            )
            train_pool = _merge_scenarios(static_train, synth_train)
            holdout_pool = _merge_scenarios(static_holdout, synth_holdout)

            control_train_batch, control_holdout_batch = self._select_batches(
                epoch=epoch,
                train_pool=train_pool,
                holdout_pool=holdout_pool,
                force_full=False,
            )
            control_snapshot = self._evaluate_snapshot(
                epoch=epoch,
                label="control",
                train_batch=control_train_batch,
                holdout_batch=control_holdout_batch,
            )
            self._progress(
                "control_snapshot_complete",
                epoch=epoch,
                train_score=control_snapshot.train_score,
                holdout_score=control_snapshot.holdout_score,
                hard_pass_rate=control_snapshot.hard_pass_rate,
            )

            if self.dry_run or self.disable_mutation:
                active_snapshot = control_snapshot
                recent_train_failures = _collect_recent_failures(
                    active_snapshot.scenario_results,
                    partition="train",
                )
                history.append(
                    {
                        "epoch": epoch,
                        "event": "evaluation-only",
                        "train_score": control_snapshot.train_score,
                        "holdout_score": control_snapshot.holdout_score,
                        "hard_pass_rate": control_snapshot.hard_pass_rate,
                    }
                )
                self._progress(
                    "epoch_evaluation_only",
                    epoch=epoch,
                    train_score=control_snapshot.train_score,
                    holdout_score=control_snapshot.holdout_score,
                )
                epoch += 1
                continue

            proposal = self.mutator.propose(
                epoch=epoch,
                baseline_summary=control_snapshot.summary,
                recent_failures=recent_train_failures,
                artifact_dir=epoch_dir,
            )
            if proposal is None:
                stagnant_epochs += 1
                active_snapshot = control_snapshot
                recent_train_failures = _collect_recent_failures(
                    active_snapshot.scenario_results,
                    partition="train",
                )
                history.append(
                    {
                        "epoch": epoch,
                        "event": "mutation-skipped",
                        "reason": "no valid mutation proposal",
                        "train_score": control_snapshot.train_score,
                        "holdout_score": control_snapshot.holdout_score,
                    }
                )
                self._progress(
                    "mutation_skipped",
                    epoch=epoch,
                )
                epoch += 1
                continue

            runtime_touched = self._proposal_touches_runtime_lane(proposal)
            decision_train_batch = control_train_batch
            decision_holdout_batch = control_holdout_batch
            control_for_decision = control_snapshot

            if runtime_touched and self.config.runtime_lane.force_full_evaluation:
                decision_train_batch = list(train_pool)
                decision_holdout_batch = list(holdout_pool)
                control_for_decision = self._evaluate_snapshot(
                    epoch=epoch,
                    label="control-runtime-lane",
                    train_batch=decision_train_batch,
                    holdout_batch=decision_holdout_batch,
                )

            transaction = self.mutator.apply(proposal)
            if transaction.errors:
                self.mutator.rollback(transaction)
                stagnant_epochs += 1
                active_snapshot = control_for_decision
                recent_train_failures = _collect_recent_failures(
                    active_snapshot.scenario_results,
                    partition="train",
                )
                write_json(
                    epoch_dir / "mutation-apply-errors.json",
                    {
                        "errors": transaction.errors,
                        "proposal": proposal.parsed_payload,
                    },
                )
                history.append(
                    {
                        "epoch": epoch,
                        "event": "mutation-apply-failed",
                        "errors": transaction.errors,
                    }
                )
                self._progress(
                    "mutation_apply_failed",
                    epoch=epoch,
                    error_count=len(transaction.errors),
                )
                epoch += 1
                continue

            gate_results = self._run_quality_gates(runtime_touched=runtime_touched)
            write_json(epoch_dir / "quality-gates.json", gate_results)
            if gate_results["failed"]:
                self.mutator.rollback(transaction)
                stagnant_epochs += 1
                active_snapshot = control_for_decision
                recent_train_failures = _collect_recent_failures(
                    active_snapshot.scenario_results,
                    partition="train",
                )
                history.append(
                    {
                        "epoch": epoch,
                        "event": "quality-gate-failed",
                        "failed_commands": gate_results["failed"],
                    }
                )
                self._progress(
                    "quality_gate_failed",
                    epoch=epoch,
                    failed_count=len(gate_results["failed"]),
                )
                epoch += 1
                continue

            candidate_snapshot = self._evaluate_snapshot(
                epoch=epoch,
                label="candidate",
                train_batch=decision_train_batch,
                holdout_batch=decision_holdout_batch,
            )
            self._progress(
                "candidate_snapshot_complete",
                epoch=epoch,
                train_score=candidate_snapshot.train_score,
                holdout_score=candidate_snapshot.holdout_score,
                hard_pass_rate=candidate_snapshot.hard_pass_rate,
            )

            decision = self._decide(
                baseline=control_for_decision,
                candidate=candidate_snapshot,
                runtime_touched=runtime_touched,
            )
            write_json(
                epoch_dir / "decision.json",
                {
                    "decision": decision.__dict__,
                    "runtime_touched": runtime_touched,
                    "candidate": _snapshot_to_dict(candidate_snapshot),
                    "baseline": _snapshot_to_dict(control_for_decision),
                    "proposal": proposal.parsed_payload,
                },
            )

            if decision.accepted:
                active_snapshot = candidate_snapshot
                recent_train_failures = _collect_recent_failures(
                    active_snapshot.scenario_results,
                    partition="train",
                )
                stagnant_epochs = 0
                history.append(
                    {
                        "epoch": epoch,
                        "event": "accepted",
                        "reason": decision.reason,
                        "runtime_touched": runtime_touched,
                        "train_score": candidate_snapshot.train_score,
                        "holdout_score": candidate_snapshot.holdout_score,
                    }
                )
                self._progress(
                    "epoch_accepted",
                    epoch=epoch,
                    train_score=candidate_snapshot.train_score,
                    holdout_score=candidate_snapshot.holdout_score,
                    runtime_touched=runtime_touched,
                )
            else:
                self.mutator.rollback(transaction)
                active_snapshot = control_for_decision
                recent_train_failures = _collect_recent_failures(
                    active_snapshot.scenario_results,
                    partition="train",
                )
                stagnant_epochs += 1
                history.append(
                    {
                        "epoch": epoch,
                        "event": "rejected",
                        "reason": decision.reason,
                        "runtime_touched": runtime_touched,
                        "candidate_train_score": candidate_snapshot.train_score,
                        "candidate_holdout_score": candidate_snapshot.holdout_score,
                    }
                )
                self._progress(
                    "epoch_rejected",
                    epoch=epoch,
                    reason=decision.reason,
                    runtime_touched=runtime_touched,
                )

            epoch += 1

        final_summary = {
            "run_id": self.run_id,
            "stop_reason": stop_reason,
            "best_snapshot": _snapshot_to_dict(active_snapshot),
            "history": history,
            "stagnant_epochs": stagnant_epochs,
            "completed_epochs": max(0, epoch - 1),
        }
        write_json(self.run_dir / "final-summary.json", final_summary)
        self._progress(
            "run_finish",
            run_id=self.run_id,
            stop_reason=stop_reason,
            completed_epochs=max(0, epoch - 1),
            final_train_score=active_snapshot.train_score,
            final_holdout_score=active_snapshot.holdout_score,
        )
        return final_summary

    def _evaluate_snapshot(
        self,
        *,
        epoch: int,
        label: str,
        train_batch: list[Scenario],
        holdout_batch: list[Scenario],
    ) -> EvaluationSnapshot:
        epoch_dir = self.run_dir / f"epoch-{epoch:03d}" / label
        ensure_dir(epoch_dir)
        self._progress(
            "snapshot_start",
            epoch=epoch,
            label=label,
            train_count=len(train_batch),
            holdout_count=len(holdout_batch),
        )

        train_results = self._run_partition(
            partition="train",
            epoch=epoch,
            label=label,
            scenarios=train_batch,
            epoch_dir=epoch_dir,
        )
        holdout_results = self._run_partition(
            partition="holdout",
            epoch=epoch,
            label=label,
            scenarios=holdout_batch,
            epoch_dir=epoch_dir,
        )

        train_score, train_hard = aggregate_scores(train_results)
        holdout_score, holdout_hard = aggregate_scores(holdout_results)

        all_results = [*train_results, *holdout_results]
        _, hard_rate = aggregate_scores(all_results)

        summary = {
            "epoch": epoch,
            "label": label,
            "train_scenarios": [item.scenario_id for item in train_results],
            "holdout_scenarios": [item.scenario_id for item in holdout_results],
            "train_score": train_score,
            "holdout_score": holdout_score,
            "hard_pass_rate": hard_rate,
            "mean_judge_score": (
                statistics.mean([item.judge_score for item in all_results]) if all_results else 0.0
            ),
            "violations": {
                item.scenario_id: item.violations
                for item in all_results
                if item.violations
            },
            "next_focus": {
                item.scenario_id: item.next_focus
                for item in all_results
                if item.next_focus
            },
            "partition_hard_pass_rate": {
                "train": train_hard,
                "holdout": holdout_hard,
            },
        }

        write_json(epoch_dir / "snapshot-summary.json", summary)
        self._progress(
            "snapshot_finish",
            epoch=epoch,
            label=label,
            train_score=train_score,
            holdout_score=holdout_score,
            hard_pass_rate=hard_rate,
        )

        return EvaluationSnapshot(
            epoch=epoch,
            label=label,
            train_score=train_score,
            holdout_score=holdout_score,
            hard_pass_rate=hard_rate,
            scenario_results=all_results,
            summary=summary,
        )

    def _run_partition(
        self,
        *,
        partition: str,
        epoch: int,
        label: str,
        scenarios: list[Scenario],
        epoch_dir: Path,
    ) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        total = len(scenarios)
        for index, scenario in enumerate(scenarios, start=1):
            self._progress(
                "scenario_start",
                epoch=epoch,
                label=label,
                partition=partition,
                scenario_id=scenario.id,
                progress=f"{index}/{total}",
            )
            scenario_artifact = epoch_dir / partition / scenario.id
            memory_root = (
                self.workspace_root
                / self.config.memory_run_root
                / self.run_id
                / f"epoch-{epoch:03d}"
                / label
                / partition
                / scenario.id
            )

            execution = self.runner.execute(
                scenario=scenario,
                partition=partition,
                epoch=epoch,
                memory_root=memory_root,
                artifact_dir=scenario_artifact,
                project=self.config.project,
                scope=self.config.scope,
            )

            probe_payload = self.probe.run(
                memory_root=memory_root,
                scope=self.config.scope,
                project=self.config.project,
            )
            write_json(scenario_artifact / "memory-probe.json", probe_payload)

            judge_payload = self.judge.score(
                execution=execution,
                probe=probe_payload,
                artifact_dir=scenario_artifact,
            )

            hydration_required = (
                self.config.skill_hydration.required_paths
                if self.config.skill_hydration.required_paths
                else self.config.skill_paths[:1]
            )
            scenario_result = score_execution(
                execution=execution,
                probe=probe_payload,
                judge_payload=judge_payload,
                required_skill_paths=hydration_required,
                minimum_skill_reads=self.config.skill_hydration.minimum_reads,
                enforce_skill_hydration=self.config.skill_hydration.enforce,
                hard_fail_missing_skills=self.config.skill_hydration.hard_fail_missing,
            )
            write_json(
                scenario_artifact / "scenario-result.json",
                _scenario_result_to_dict(scenario_result),
            )
            results.append(scenario_result)
            self._progress(
                "scenario_finish",
                epoch=epoch,
                label=label,
                partition=partition,
                scenario_id=scenario.id,
                hard_pass=scenario_result.hard_pass,
                fitness=scenario_result.fitness,
                progress=f"{index}/{total}",
            )

        return results

    def _synthesize_epoch_scenarios(
        self,
        *,
        epoch: int,
        static_train: list[Scenario],
        static_holdout: list[Scenario],
        recent_train_failures: list[dict[str, Any]],
        epoch_dir: Path,
    ) -> tuple[list[Scenario], list[Scenario]]:
        if not self.config.synthesis.enabled:
            return [], []

        synth_dir = epoch_dir / "synthetic"
        ensure_dir(synth_dir)
        self._progress(
            "synthesis_start",
            epoch=epoch,
            train_target=self.config.synthesis.per_epoch_train,
            holdout_target=self.config.synthesis.per_epoch_holdout,
        )

        train = self.synthesizer.synthesize(
            epoch=epoch,
            partition="train",
            count=self.config.synthesis.per_epoch_train,
            base_scenarios=static_train,
            recent_failures=recent_train_failures,
            artifact_dir=synth_dir,
            project=self.config.project,
            scope=self.config.scope,
        )
        holdout = self.synthesizer.synthesize(
            epoch=epoch,
            partition="holdout",
            count=self.config.synthesis.per_epoch_holdout,
            base_scenarios=static_holdout,
            recent_failures=recent_train_failures,
            artifact_dir=synth_dir,
            project=self.config.project,
            scope=self.config.scope,
        )
        self._progress(
            "synthesis_finish",
            epoch=epoch,
            train_generated=len(train),
            holdout_generated=len(holdout),
        )
        return train, holdout

    def _select_batches(
        self,
        *,
        epoch: int,
        train_pool: list[Scenario],
        holdout_pool: list[Scenario],
        force_full: bool,
    ) -> tuple[list[Scenario], list[Scenario]]:
        if force_full:
            return list(train_pool), list(holdout_pool)

        seed = self.config.batch.random_seed
        train_batch = select_batch(
            train_pool,
            self.config.batch.train_batch_size,
            epoch=epoch,
            seed=seed,
            curriculum_enabled=True,
        )
        holdout_batch = select_batch(
            holdout_pool,
            self.config.batch.holdout_batch_size,
            epoch=epoch + 97,
            seed=seed,
            curriculum_enabled=False,
        )
        return train_batch, holdout_batch

    def _run_quality_gates(self, *, runtime_touched: bool) -> dict[str, Any]:
        commands = list(self.config.quality_gate_commands)
        if runtime_touched and self.config.runtime_lane.extra_gate_commands:
            commands.extend(self.config.runtime_lane.extra_gate_commands)

        checks: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for command in commands:
            self._progress(
                "quality_gate_start",
                command=command,
                runtime_touched=runtime_touched,
            )
            result = run_shell_command(command, cwd=self.workspace_root, timeout_seconds=300)
            record = {
                "command": command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            checks.append(record)
            if result.exit_code != 0:
                failed.append(record)
            self._progress(
                "quality_gate_finish",
                command=command,
                exit_code=result.exit_code,
            )
        return {
            "checks": checks,
            "failed": failed,
        }

    def _decide(
        self,
        *,
        baseline: EvaluationSnapshot,
        candidate: EvaluationSnapshot,
        runtime_touched: bool,
    ) -> Decision:
        if candidate.hard_pass_rate < 1.0:
            return Decision(
                accepted=False,
                reason="candidate failed hard memory integrity gates",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
            )

        holdout_floor = (
            baseline.holdout_score - self.config.mutation.holdout_regression_tolerance
        )
        if candidate.holdout_score < holdout_floor:
            return Decision(
                accepted=False,
                reason="candidate regressed holdout score",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
            )

        required_delta = (
            self.config.runtime_lane.min_improvement
            if runtime_touched
            else self.config.mutation.require_improvement
        )
        train_delta = candidate.train_score - baseline.train_score
        holdout_delta = candidate.holdout_score - baseline.holdout_score
        if train_delta >= required_delta or holdout_delta >= required_delta:
            return Decision(
                accepted=True,
                reason="candidate improved score while preserving hard gates",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
            )

        return Decision(
            accepted=False,
            reason="candidate did not improve enough",
            candidate_train_score=candidate.train_score,
            candidate_holdout_score=candidate.holdout_score,
            baseline_train_score=baseline.train_score,
            baseline_holdout_score=baseline.holdout_score,
            candidate_hard_pass_rate=candidate.hard_pass_rate,
        )

    def _progress(self, event: str, **payload: Any) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00",
            "Z",
        )
        record: dict[str, Any] = {
            "ts": timestamp,
            "event": event,
        }
        record.update(payload)

        epoch_value = record.get("epoch")
        if isinstance(epoch_value, int) and self.config.max_epochs > 0:
            record["epoch_percent"] = round(
                min(100.0, (epoch_value / self.config.max_epochs) * 100.0),
                2,
            )

        with self._progress_lock:
            ensure_dir(self.run_dir)
            with self.progress_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")

            self._update_live_state(record)

            if self._live_progress_enabled:
                live_line = self._build_live_line(record)
                self._write_live_line(live_line)
                if event in {
                    "run_finish",
                    "stop-file-triggered",
                    "max-epochs-reached",
                    "max-stagnant-epochs-reached",
                    "max-wall-seconds-reached",
                }:
                    sys.stderr.write("\n")
                    sys.stderr.flush()
                    self._last_live_line_len = 0
            elif self.progress_enabled:
                print(self._format_progress(record), file=sys.stderr, flush=True)

    def _update_live_state(self, record: dict[str, Any]) -> None:
        self._live_state["event"] = record.get("event", self._live_state.get("event", ""))
        self._live_state["elapsed_seconds"] = int(
            time.monotonic() - self.started_monotonic
        )

        for key in (
            "epoch",
            "label",
            "partition",
            "scenario_id",
            "progress",
            "role",
            "train_score",
            "holdout_score",
        ):
            if key in record and record[key] not in (None, ""):
                self._live_state[key] = record[key]

        if self.config.max_epochs > 0:
            self._live_state["epoch_total"] = self.config.max_epochs

    def _build_live_line(self, record: dict[str, Any]) -> str:
        epoch = self._live_state.get("epoch")
        epoch_total = self._live_state.get("epoch_total")
        epoch_bar = self._render_bar(
            current=int(epoch) if isinstance(epoch, int) else 0,
            total=int(epoch_total) if isinstance(epoch_total, int) and epoch_total > 0 else 0,
            width=14,
        )

        scenario_progress = self._live_state.get("progress", "")
        scenario_current, scenario_total = _parse_progress_token(str(scenario_progress))
        scenario_bar = self._render_bar(
            current=scenario_current,
            total=scenario_total,
            width=8,
        )

        event = str(record.get("event", self._live_state.get("event", "event")))
        label = str(self._live_state.get("label", ""))
        partition = str(self._live_state.get("partition", ""))
        scenario_id = str(self._live_state.get("scenario_id", ""))
        role = str(self._live_state.get("role", ""))
        elapsed = int(self._live_state.get("elapsed_seconds", 0))

        parts = [
            f"E{epoch_bar}",
            f"S{scenario_bar}",
            f"t+{_format_duration(elapsed)}",
        ]

        if isinstance(epoch, int) and isinstance(epoch_total, int) and epoch_total > 0:
            parts.append(f"epoch={epoch}/{epoch_total}")
        elif isinstance(epoch, int):
            parts.append(f"epoch={epoch}")

        if label:
            parts.append(f"label={label}")
        if partition:
            parts.append(f"part={partition}")
        if scenario_id:
            parts.append(f"scenario={_clip_text(scenario_id, 24)}")
        if role:
            parts.append(f"role={role}")

        train_score = self._live_state.get("train_score")
        holdout_score = self._live_state.get("holdout_score")
        if isinstance(train_score, (int, float)) and isinstance(holdout_score, (int, float)):
            parts.append(f"score={float(train_score):.1f}/{float(holdout_score):.1f}")

        parts.append(f"event={event}")

        text = " | ".join(parts)
        max_width = max(40, shutil.get_terminal_size((120, 20)).columns - 1)
        return _clip_text(text, max_width)

    def _write_live_line(self, line: str) -> None:
        padded = line
        if len(line) < self._last_live_line_len:
            padded = line + (" " * (self._last_live_line_len - len(line)))
        sys.stderr.write("\r" + padded)
        sys.stderr.flush()
        self._last_live_line_len = len(line)

    @staticmethod
    def _render_bar(*, current: int, total: int, width: int) -> str:
        if total <= 0:
            return "[" + ("-" * width) + "]"
        safe_current = max(0, min(current, total))
        ratio = safe_current / total if total else 0.0
        filled = int(round(ratio * width))
        filled = max(0, min(width, filled))
        return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"

    def _format_progress(self, record: dict[str, Any]) -> str:
        ts = str(record.get("ts", ""))
        event = str(record.get("event", "event"))
        epoch_part = ""
        if isinstance(record.get("epoch"), int):
            epoch = record["epoch"]
            if isinstance(record.get("epoch_percent"), float):
                epoch_part = f" epoch={epoch} ({record['epoch_percent']:.1f}%)"
            else:
                epoch_part = f" epoch={epoch}"

        details = []
        for key in (
            "label",
            "partition",
            "scenario_id",
            "progress",
            "role",
            "exit_code",
            "elapsed_seconds",
            "train_score",
            "holdout_score",
            "hard_pass_rate",
            "reason",
        ):
            value = record.get(key)
            if value is None or value == "":
                continue
            details.append(f"{key}={value}")

        detail_text = " | " + ", ".join(details) if details else ""
        return f"[evo {ts}] {event}{epoch_part}{detail_text}"

    def _stop_reason(self, *, epoch: int, stagnant_epochs: int) -> str:
        if self._stop_file_exists():
            return "stop-file-triggered"

        if self.config.max_wall_seconds > 0:
            elapsed = int(time.monotonic() - self.started_monotonic)
            if elapsed >= self.config.max_wall_seconds:
                return "max-wall-seconds-reached"

        if self.config.max_stagnant_epochs > 0 and stagnant_epochs >= self.config.max_stagnant_epochs:
            return "max-stagnant-epochs-reached"

        if self.config.continuous:
            if self.config.max_epochs > 0 and epoch > self.config.max_epochs:
                return "max-epochs-reached"
            return ""

        if self.config.max_epochs <= 0 and epoch > 0:
            return "max-epochs-reached"
        if self.config.max_epochs > 0 and epoch > self.config.max_epochs:
            return "max-epochs-reached"
        return ""

    def _proposal_touches_runtime_lane(self, proposal: MutationProposal) -> bool:
        if not self.config.runtime_lane.enabled:
            return False

        runtime_paths = [_normalize_path(path) for path in self.config.runtime_lane.paths]
        for operation in proposal.operations:
            operation_path = _normalize_path(operation.path)
            for runtime_path in runtime_paths:
                if operation_path == runtime_path or operation_path.startswith(runtime_path + "/"):
                    return True
        return False

    def _activate_runtime_lane_allow_paths(self) -> None:
        if not self.config.runtime_lane.enabled:
            return

        for path in self.config.runtime_lane.paths:
            if path not in self.config.mutation.allow_paths:
                self.config.mutation.allow_paths.append(path)

    def _stop_file_exists(self) -> bool:
        return (self.workspace_root / self.config.stop_file).exists()


def _snapshot_to_dict(snapshot: EvaluationSnapshot) -> dict[str, Any]:
    return {
        "epoch": snapshot.epoch,
        "label": snapshot.label,
        "train_score": snapshot.train_score,
        "holdout_score": snapshot.holdout_score,
        "hard_pass_rate": snapshot.hard_pass_rate,
        "summary": snapshot.summary,
        "scenario_results": [_scenario_result_to_dict(item) for item in snapshot.scenario_results],
    }


def _scenario_result_to_dict(result: ScenarioResult) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario_id,
        "partition": result.partition,
        "epoch": result.epoch,
        "memory_root": result.memory_root,
        "session_id": result.session_id,
        "hard_pass": result.hard_pass,
        "fitness": result.fitness,
        "judge_score": result.judge_score,
        "dimensions": result.dimensions,
        "violations": result.violations,
        "strengths": result.strengths,
        "next_focus": result.next_focus,
        "probe": result.probe,
        "command_trace": result.command_trace,
        "artifact_dir": result.artifact_dir,
    }


def _collect_recent_failures(
    results: list[ScenarioResult],
    *,
    partition: str,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for item in results:
        if item.partition != partition:
            continue
        if item.hard_pass and item.fitness > 80:
            continue
        failures.append(
            {
                "scenario_id": item.scenario_id,
                "fitness": item.fitness,
                "hard_pass": item.hard_pass,
                "violations": item.violations,
                "next_focus": item.next_focus,
            }
        )
    return failures


def _merge_scenarios(static_pool: list[Scenario], synthetic_pool: list[Scenario]) -> list[Scenario]:
    merged: list[Scenario] = []
    seen: set[str] = set()
    for scenario in [*static_pool, *synthetic_pool]:
        if scenario.id in seen:
            continue
        seen.add(scenario.id)
        merged.append(scenario)
    return merged


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/")


def _parse_progress_token(token: str) -> tuple[int, int]:
    if "/" not in token:
        return 0, 0
    left, right = token.split("/", 1)
    try:
        current = int(left.strip())
        total = int(right.strip())
    except ValueError:
        return 0, 0
    if total <= 0:
        return 0, 0
    return max(0, current), total


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{rem:02d}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins:02d}m"


def _clip_text(text: str, max_len: int) -> str:
    if max_len <= 3:
        return text[:max_len]
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
