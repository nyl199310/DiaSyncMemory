from __future__ import annotations

import json
import re
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
from .models import (
    Decision,
    EvaluationSnapshot,
    MutationProposal,
    MutationTransaction,
    SCORE_DIMENSIONS,
    Scenario,
    ScenarioResult,
)
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
            fallback_only=config.runner_fallback_only,
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
            workspace_root=workspace_root,
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
        candidate_bank: list[dict[str, Any]] = []
        stagnant_epochs = 0
        provisional_accepts = 0
        provisional_pending = False
        provisional_confirmations = 0
        epoch = 1
        stop_reason = ""
        provider_blocked_streak = 0
        baseline_blocked = self._is_provider_blocked_snapshot(baseline_snapshot)
        if baseline_blocked:
            provider_blocked_streak = 1
            rate = self._provider_blocked_rate(baseline_snapshot)
            self._progress(
                "provider_blocked_observed",
                epoch=0,
                label="baseline",
                provider_blocked_rate=rate,
                blocked_streak=provider_blocked_streak,
                grace_snapshots=self.config.objectives.provider_blocked_grace_snapshots,
            )
            if provider_blocked_streak > self.config.objectives.provider_blocked_grace_snapshots:
                if self.config.objectives.stop_when_provider_blocked and not self.config.objectives.continue_on_provider_blocked:
                    stop_reason = "provider-blocked"
                    self._progress(
                        "provider_blocked_stop",
                        epoch=0,
                        label="baseline",
                        provider_blocked_rate=rate,
                        blocked_streak=provider_blocked_streak,
                    )
                else:
                    self._progress(
                        "provider_blocked_degraded",
                        epoch=0,
                        label="baseline",
                        provider_blocked_rate=rate,
                        blocked_streak=provider_blocked_streak,
                    )

        while not stop_reason:
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

            rate = 0.0
            provider_degraded_mode = False
            control_blocked = self._is_provider_blocked_snapshot(control_snapshot)
            if control_blocked:
                provider_blocked_streak += 1
                rate = self._provider_blocked_rate(control_snapshot)
                self._progress(
                    "provider_blocked_observed",
                    epoch=epoch,
                    label="control",
                    provider_blocked_rate=rate,
                    blocked_streak=provider_blocked_streak,
                    grace_snapshots=self.config.objectives.provider_blocked_grace_snapshots,
                )
            else:
                provider_blocked_streak = 0

            if control_blocked and (
                provider_blocked_streak > self.config.objectives.provider_blocked_grace_snapshots
            ):
                if self.config.objectives.stop_when_provider_blocked and not self.config.objectives.continue_on_provider_blocked:
                    active_snapshot = control_snapshot
                    recent_train_failures = _collect_recent_failures(
                        active_snapshot.scenario_results,
                        partition="train",
                    )
                    history.append(
                        {
                            "epoch": epoch,
                            "event": "provider-blocked-stop",
                            "reason": "provider-blocked",
                            "provider_blocked_rate": rate,
                            "provider_blocked_streak": provider_blocked_streak,
                            "train_score": control_snapshot.train_score,
                            "holdout_score": control_snapshot.holdout_score,
                        }
                    )
                    self._progress(
                        "provider_blocked_stop",
                        epoch=epoch,
                        label="control",
                        provider_blocked_rate=rate,
                        blocked_streak=provider_blocked_streak,
                    )
                    stop_reason = "provider-blocked"
                    break

                provider_degraded_mode = True
                self._progress(
                    "provider_blocked_degraded",
                    epoch=epoch,
                    label="control",
                    provider_blocked_rate=rate,
                    blocked_streak=provider_blocked_streak,
                )

            if provisional_pending and not provider_degraded_mode:
                confirmation = self._assess_provisional_confirmation(control_snapshot)
                if confirmation["confirmed"]:
                    provisional_pending = False
                    provisional_confirmations += 1
                    history.append(
                        {
                            "epoch": epoch,
                            "event": "provisional-confirmed",
                            "details": confirmation,
                            "train_score": control_snapshot.train_score,
                            "holdout_score": control_snapshot.holdout_score,
                        }
                    )
                    self._progress(
                        "provisional_confirmed",
                        epoch=epoch,
                        validation_confidence=confirmation["validation_confidence_mean"],
                        hard_pass_rate=confirmation["hard_pass_rate"],
                    )
                else:
                    history.append(
                        {
                            "epoch": epoch,
                            "event": "provisional-pending",
                            "details": confirmation,
                            "train_score": control_snapshot.train_score,
                            "holdout_score": control_snapshot.holdout_score,
                        }
                    )
                    self._progress(
                        "provisional_pending",
                        epoch=epoch,
                        reason=confirmation["reason"],
                        validation_confidence=confirmation["validation_confidence_mean"],
                        hard_pass_rate=confirmation["hard_pass_rate"],
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
                stable_snapshot = _is_stable_snapshot(control_snapshot)
                if stable_snapshot:
                    stagnant_epochs = 0
                else:
                    stagnant_epochs += 1
                active_snapshot = control_snapshot
                recent_train_failures = _collect_recent_failures(
                    active_snapshot.scenario_results,
                    partition="train",
                )
                history.append(
                    {
                        "epoch": epoch,
                        "event": "mutation-skipped" if not stable_snapshot else "steady-state-no-mutation",
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

            candidate_delta = self._analyze_candidate_delta(
                transaction,
                proposal=proposal,
                recent_failures=recent_train_failures,
            )
            write_json(epoch_dir / "candidate-delta.json", candidate_delta)
            if not candidate_delta["has_required_evolution_diff"]:
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
                        "event": "rejected-no-evolution-diff",
                        "reason": "candidate mutation did not create meaningful skill/runtime evolution diff",
                        "delta": candidate_delta,
                    }
                )
                self._progress(
                    "candidate_delta_rejected",
                    epoch=epoch,
                    changed_files=candidate_delta["changed_file_count"],
                    eligible_files=candidate_delta["eligible_file_count"],
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
                candidate_delta=candidate_delta,
                degraded_provider_mode=provider_degraded_mode,
                provisional_accepts=provisional_accepts,
            )

            candidate_bank_entry = {
                "epoch": epoch,
                "accepted": decision.accepted,
                "provisional": decision.provisional,
                "reason": decision.reason,
                "runtime_touched": runtime_touched,
                "provider_degraded_mode": provider_degraded_mode,
                "candidate_delta": candidate_delta,
                "objective_progress": decision.objective_progress,
                "candidate_train_score": candidate_snapshot.train_score,
                "candidate_holdout_score": candidate_snapshot.holdout_score,
                "baseline_train_score": control_for_decision.train_score,
                "baseline_holdout_score": control_for_decision.holdout_score,
            }
            candidate_bank.append(candidate_bank_entry)
            write_json(epoch_dir / "candidate-bank-entry.json", candidate_bank_entry)

            write_json(
                epoch_dir / "decision.json",
                {
                    "decision": decision.__dict__,
                    "runtime_touched": runtime_touched,
                    "candidate_delta": candidate_delta,
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
                if decision.provisional:
                    provisional_accepts += 1
                    provisional_pending = True
                else:
                    provisional_pending = False
                accepted_event = "accepted-provisional" if decision.provisional else "accepted"
                history.append(
                    {
                        "epoch": epoch,
                        "event": accepted_event,
                        "reason": decision.reason,
                        "runtime_touched": runtime_touched,
                        "provider_degraded_mode": provider_degraded_mode,
                        "provisional": decision.provisional,
                        "candidate_delta": candidate_delta,
                        "objective_progress": decision.objective_progress,
                        "train_score": candidate_snapshot.train_score,
                        "holdout_score": candidate_snapshot.holdout_score,
                    }
                )
                self._progress(
                    "epoch_accepted_provisional" if decision.provisional else "epoch_accepted",
                    epoch=epoch,
                    train_score=candidate_snapshot.train_score,
                    holdout_score=candidate_snapshot.holdout_score,
                    runtime_touched=runtime_touched,
                    provisional=decision.provisional,
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
                        "provider_degraded_mode": provider_degraded_mode,
                        "provisional": decision.provisional,
                        "candidate_delta": candidate_delta,
                        "objective_progress": decision.objective_progress,
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
            "candidate_bank_size": len(candidate_bank),
            "provisional_accepts": provisional_accepts,
            "provisional_pending": provisional_pending,
            "provisional_confirmations": provisional_confirmations,
            "stagnant_epochs": stagnant_epochs,
            "completed_epochs": max(0, epoch - 1),
        }
        write_json(
            self.run_dir / "candidate-bank.json",
            {
                "run_id": self.run_id,
                "entries": candidate_bank,
            },
        )
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
        objective_metrics_all = _objective_metrics(all_results)
        objective_metrics_train = _objective_metrics(train_results)
        objective_metrics_holdout = _objective_metrics(holdout_results)
        policy_metrics = _skill_policy_metrics(self.workspace_root, self.config.skill_paths)
        objective_metrics_all.update(policy_metrics)
        objective_metrics_train.update(policy_metrics)
        objective_metrics_holdout.update(policy_metrics)

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
            "objective_metrics": objective_metrics_all,
            "partition_objective_metrics": {
                "train": objective_metrics_train,
                "holdout": objective_metrics_holdout,
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

            before_status = self._git_status_lines()

            execution = self.runner.execute(
                scenario=scenario,
                partition=partition,
                epoch=epoch,
                memory_root=memory_root,
                artifact_dir=scenario_artifact,
                project=self.config.project,
                scope=self.config.scope,
            )

            after_status = self._git_status_lines()
            workspace_delta = sorted(after_status - before_status)
            if workspace_delta:
                self._revert_workspace_delta(workspace_delta)
                self.runner.force_fallback_mode = True
                write_json(
                    scenario_artifact / "workspace-delta.json",
                    {
                        "detected": workspace_delta,
                        "reverted": True,
                    },
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
            if workspace_delta:
                scenario_result.hard_pass = False
                scenario_result.fitness = 0.0
                scenario_result.violations.append(
                    "Runner attempted workspace edits outside memory roots; changes were reverted."
                )
                preview = ", ".join(workspace_delta[:4])
                if preview:
                    scenario_result.violations.append(
                        "Workspace delta preview: " + preview
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

    def _provider_blocked_rate(self, snapshot: EvaluationSnapshot) -> float:
        objective_metrics = snapshot.summary.get("objective_metrics", {})
        if not isinstance(objective_metrics, dict):
            return 0.0
        try:
            return float(objective_metrics.get("provider_blocked_rate", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _objective_metric(
        self,
        snapshot: EvaluationSnapshot,
        key: str,
        default: float = 0.0,
    ) -> float:
        objective_metrics = snapshot.summary.get("objective_metrics", {})
        if not isinstance(objective_metrics, dict):
            return default
        try:
            return float(objective_metrics.get(key, default))
        except (TypeError, ValueError):
            return default

    def _is_provider_blocked_snapshot(self, snapshot: EvaluationSnapshot) -> bool:
        if not self.config.objectives.stop_when_provider_blocked:
            return False
        rate = self._provider_blocked_rate(snapshot)
        return rate >= self.config.objectives.provider_blocked_stop_rate

    def _assess_provisional_confirmation(self, snapshot: EvaluationSnapshot) -> dict[str, Any]:
        confidence = self._objective_metric(snapshot, "validation_confidence_mean", 0.0)
        provider_rate = self._objective_metric(snapshot, "provider_blocked_rate", 0.0)
        hard_pass_rate = float(snapshot.hard_pass_rate)

        if provider_rate > self.config.objectives.provisional_confirm_max_provider_blocked_rate:
            return {
                "confirmed": False,
                "reason": "provider still blocked in confirmation snapshot",
                "validation_confidence_mean": confidence,
                "provider_blocked_rate": provider_rate,
                "hard_pass_rate": hard_pass_rate,
            }

        if confidence < self.config.objectives.provisional_confirm_min_validation_confidence:
            return {
                "confirmed": False,
                "reason": "validation confidence below provisional confirmation threshold",
                "validation_confidence_mean": confidence,
                "provider_blocked_rate": provider_rate,
                "hard_pass_rate": hard_pass_rate,
            }

        if hard_pass_rate < self.config.objectives.provisional_confirm_min_hard_pass_rate:
            return {
                "confirmed": False,
                "reason": "hard pass rate below provisional confirmation threshold",
                "validation_confidence_mean": confidence,
                "provider_blocked_rate": provider_rate,
                "hard_pass_rate": hard_pass_rate,
            }

        return {
            "confirmed": True,
            "reason": "provider recovered and objective confidence is sufficient",
            "validation_confidence_mean": confidence,
            "provider_blocked_rate": provider_rate,
            "hard_pass_rate": hard_pass_rate,
        }

    def _decide(
        self,
        *,
        baseline: EvaluationSnapshot,
        candidate: EvaluationSnapshot,
        runtime_touched: bool,
        candidate_delta: dict[str, Any],
        degraded_provider_mode: bool,
        provisional_accepts: int,
    ) -> Decision:
        objective_progress = _build_objective_progress(
            baseline=baseline,
            candidate=candidate,
            min_dimension_improvement=self.config.objectives.min_dimension_improvement,
            max_dimension_regression=self.config.objectives.max_dimension_regression,
            min_fallback_reduction=self.config.objectives.min_fallback_reduction,
            max_fallback_increase=self.config.objectives.max_fallback_increase,
        )

        if degraded_provider_mode and self.config.objectives.allow_provisional_acceptance:
            return self._decide_degraded(
                baseline=baseline,
                candidate=candidate,
                candidate_delta=candidate_delta,
                objective_progress=objective_progress,
                provisional_accepts=provisional_accepts,
            )

        if not candidate_delta.get("has_required_evolution_diff", False):
            return Decision(
                accepted=False,
                reason="candidate has no meaningful skill/runtime diff",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
            )

        if not objective_progress["fallback_gate_ok"]:
            return Decision(
                accepted=False,
                reason="candidate increased fallback dependency",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
            )

        if not objective_progress["provider_block_gate_ok"]:
            return Decision(
                accepted=False,
                reason="candidate increased provider-blocked executions",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
            )

        if not objective_progress["dimension_floor_ok"]:
            return Decision(
                accepted=False,
                reason="candidate regressed core complexity dimensions",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
            )

        if candidate.hard_pass_rate < 1.0:
            return Decision(
                accepted=False,
                reason="candidate failed hard memory integrity gates",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
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
                objective_progress=objective_progress,
            )

        if self.config.objectives.require_objective_gain and not objective_progress[
            "has_objective_gain"
        ]:
            return Decision(
                accepted=False,
                reason="candidate did not improve core objective metrics",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
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
                objective_progress=objective_progress,
            )

        if objective_progress["has_objective_gain"]:
            return Decision(
                accepted=True,
                reason="candidate improved core objective metrics while preserving hard gates",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
            )

        return Decision(
            accepted=False,
            reason="candidate did not improve enough",
            candidate_train_score=candidate.train_score,
            candidate_holdout_score=candidate.holdout_score,
            baseline_train_score=baseline.train_score,
            baseline_holdout_score=baseline.holdout_score,
            candidate_hard_pass_rate=candidate.hard_pass_rate,
            objective_progress=objective_progress,
        )

    def _decide_degraded(
        self,
        *,
        baseline: EvaluationSnapshot,
        candidate: EvaluationSnapshot,
        candidate_delta: dict[str, Any],
        objective_progress: dict[str, Any],
        provisional_accepts: int,
    ) -> Decision:
        if provisional_accepts >= self.config.objectives.max_provisional_accepts_per_run:
            return Decision(
                accepted=False,
                reason="provisional acceptance budget exhausted for this run",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        if not candidate_delta.get("has_required_evolution_diff", False):
            return Decision(
                accepted=False,
                reason="candidate has no meaningful skill/runtime diff",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        if candidate_delta.get("required_hydration_paths_touched", 0) <= 0:
            return Decision(
                accepted=False,
                reason="candidate did not modify actively hydrated skill surfaces",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        alignment = float(candidate_delta.get("failure_alignment_score", 0.0))
        if alignment < self.config.objectives.min_failure_alignment_score:
            return Decision(
                accepted=False,
                reason="candidate did not align sufficiently with observed failure clusters",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        if not objective_progress["fallback_gate_ok"]:
            return Decision(
                accepted=False,
                reason="candidate increased fallback dependency",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        if not objective_progress["provider_block_gate_ok"]:
            return Decision(
                accepted=False,
                reason="candidate increased provider-blocked executions",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        if not objective_progress["dimension_floor_ok"]:
            return Decision(
                accepted=False,
                reason="candidate regressed core complexity dimensions",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        if self.config.objectives.require_objective_gain and not (
            objective_progress["has_objective_gain"]
            or alignment >= self.config.objectives.min_failure_alignment_score
        ):
            return Decision(
                accepted=False,
                reason="candidate did not improve objective signals in degraded mode",
                candidate_train_score=candidate.train_score,
                candidate_holdout_score=candidate.holdout_score,
                baseline_train_score=baseline.train_score,
                baseline_holdout_score=baseline.holdout_score,
                candidate_hard_pass_rate=candidate.hard_pass_rate,
                objective_progress=objective_progress,
                provisional=True,
            )

        return Decision(
            accepted=True,
            reason="provisional acceptance under provider-blocked degraded mode",
            candidate_train_score=candidate.train_score,
            candidate_holdout_score=candidate.holdout_score,
            baseline_train_score=baseline.train_score,
            baseline_holdout_score=baseline.holdout_score,
            candidate_hard_pass_rate=candidate.hard_pass_rate,
            objective_progress=objective_progress,
            provisional=True,
        )

    def _analyze_candidate_delta(
        self,
        transaction: MutationTransaction,
        *,
        proposal: MutationProposal,
        recent_failures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        active_skill_paths = [_normalize_path(path) for path in self.config.skill_paths]
        required_hydration_paths = [
            _normalize_path(path)
            for path in (
                self.config.skill_hydration.required_paths
                if self.config.skill_hydration.required_paths
                else self.config.skill_paths[:1]
            )
        ]
        runtime_paths = [_normalize_path(path) for path in self.config.runtime_lane.paths]
        entries: list[dict[str, Any]] = []

        for path in transaction.changed_paths:
            backup = transaction.backups.get(path)
            if backup is None:
                continue
            existed, before = backup
            after = path.read_text(encoding="utf-8") if path.exists() else ""
            rel_path = _to_rel_posix(path, self.workspace_root)
            content_changed = before != after
            meaningful = _meaningful_text(before) != _meaningful_text(after)

            touches_active_skill = any(
                _path_is_within(rel_path, skill_path)
                for skill_path in active_skill_paths
            )
            touches_runtime = any(
                rel_path == runtime_path or rel_path.startswith(runtime_path + "/")
                for runtime_path in runtime_paths
            )
            eligible = meaningful and (touches_active_skill or touches_runtime)

            entries.append(
                {
                    "path": rel_path,
                    "existed": existed,
                    "content_changed": content_changed,
                    "meaningful_changed": meaningful,
                    "touches_active_skill": touches_active_skill,
                    "touches_runtime": touches_runtime,
                    "eligible": eligible,
                }
            )

        changed_entries = [item for item in entries if item["content_changed"]]
        eligible_entries = [item for item in changed_entries if item["eligible"]]
        required_touch = [
            item
            for item in eligible_entries
            if any(
                _path_is_within(item["path"], required_path)
                for required_path in required_hydration_paths
            )
        ]
        failure_alignment = _analyze_failure_alignment(
            proposal=proposal,
            recent_failures=recent_failures,
            changed_entries=eligible_entries,
        )
        return {
            "changed_file_count": len(changed_entries),
            "eligible_file_count": len(eligible_entries),
            "eligible_paths": [item["path"] for item in eligible_entries],
            "required_hydration_paths_touched": len(required_touch),
            "required_hydration_paths": [item["path"] for item in required_touch],
            "failure_alignment_score": failure_alignment["score"],
            "failure_alignment_hits": failure_alignment["hits"],
            "failure_alignment_keywords": failure_alignment["keywords"],
            "has_required_evolution_diff": bool(eligible_entries),
            "entries": entries,
        }

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
        if not self.config.continuous:
            if self.config.max_epochs <= 0 and epoch > 0:
                return "max-epochs-reached"
            if self.config.max_epochs > 0 and epoch > self.config.max_epochs:
                return "max-epochs-reached"

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

    def _git_status_lines(self) -> set[str]:
        result = run_shell_command("git status --porcelain", cwd=self.workspace_root)
        if result.exit_code != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _revert_workspace_delta(self, delta_lines: list[str]) -> None:
        for line in delta_lines:
            if len(line) < 4:
                continue
            status = line[:2]
            path_text = line[3:].strip()
            path = self.workspace_root / path_text

            if status == "??":
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                continue

            run_shell_command(
                f'git checkout -- "{path_text}"',
                cwd=self.workspace_root,
                timeout_seconds=60,
            )


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
        "fallback_used": result.fallback_used,
        "provider_blocked": result.provider_blocked,
        "provider_block_reasons": result.provider_block_reasons,
        "validation_confidence": result.validation_confidence,
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


def _is_stable_snapshot(snapshot: EvaluationSnapshot) -> bool:
    if snapshot.hard_pass_rate < 1.0:
        return False
    return snapshot.train_score >= 90.0 and snapshot.holdout_score >= 90.0


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/")


def _to_rel_posix(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return _normalize_path(str(path))


def _meaningful_text(value: str) -> str:
    collapsed = " ".join(value.split())
    return collapsed.strip()


def _path_is_within(rel_path: str, target: str) -> bool:
    normalized_rel = _normalize_path(rel_path).rstrip("/")
    normalized_target = _normalize_path(target).rstrip("/")
    if not normalized_target:
        return False
    if normalized_rel == normalized_target:
        return True
    return normalized_rel.startswith(normalized_target + "/")


def _analyze_failure_alignment(
    *,
    proposal: MutationProposal,
    recent_failures: list[dict[str, Any]],
    changed_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    keywords = _collect_failure_keywords(recent_failures)
    if not keywords:
        return {
            "score": 0.0,
            "hits": [],
            "keywords": [],
        }

    corpus_parts: list[str] = [
        proposal.rationale,
        proposal.expected_effect,
        proposal.raw_response,
    ]
    for operation in proposal.operations:
        corpus_parts.extend(
            [
                operation.path,
                operation.find or "",
                operation.replace or "",
                operation.anchor or "",
                operation.text or "",
                operation.content or "",
            ]
        )
    for item in changed_entries:
        corpus_parts.append(str(item.get("path", "")))

    corpus = "\n".join(corpus_parts).lower()
    hits = [keyword for keyword in keywords if keyword in corpus]
    score = len(hits) / float(len(keywords))
    return {
        "score": round(score, 6),
        "hits": hits,
        "keywords": keywords,
    }


def _collect_failure_keywords(recent_failures: list[dict[str, Any]]) -> list[str]:
    stop_words = {
        "about",
        "after",
        "again",
        "before",
        "candidate",
        "continue",
        "contract",
        "execution",
        "fallback",
        "focus",
        "improve",
        "memory",
        "provider",
        "restore",
        "runner",
        "scenario",
        "score",
        "should",
        "strict",
        "through",
        "using",
        "without",
    }

    counts: dict[str, int] = {}
    for item in recent_failures:
        text_chunks: list[str] = []
        violations = item.get("violations", [])
        next_focus = item.get("next_focus", [])
        if isinstance(violations, list):
            text_chunks.extend(str(chunk) for chunk in violations)
        if isinstance(next_focus, list):
            text_chunks.extend(str(chunk) for chunk in next_focus)

        for chunk in text_chunks:
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{4,}", chunk.lower()):
                if token in stop_words:
                    continue
                counts[token] = counts.get(token, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ranked[:24]]


def _skill_policy_metrics(workspace_root: Path, skill_paths: list[str]) -> dict[str, float]:
    if not skill_paths:
        return {
            "skill_policy_score": 0.0,
            "skill_path_coverage": 0.0,
            "skill_policy_anchor_coverage": 0.0,
        }

    loaded_count = 0
    corpus_chunks: list[str] = []
    for rel_path in skill_paths:
        candidate = workspace_root / rel_path
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        corpus_chunks.append(text.lower())
        loaded_count += 1

    corpus = "\n".join(corpus_chunks)
    policy_anchors: dict[str, tuple[str, ...]] = {
        "memory_correctness": (
            "memory correctness",
            "append-only",
            "validate --strict",
            "integrity",
        ),
        "memory_relevance": (
            "salience",
            "confidence",
            "distill",
            "decision",
        ),
        "diachronic": (
            "diachronic",
            "resume",
            "checkpoint",
            "handoff",
        ),
        "synchronic": (
            "synchronic",
            "conflict",
            "reconcile",
            "lease",
        ),
        "self_evolution": (
            "diagnose",
            "optimize",
            "governance",
            "evolution",
        ),
    }

    anchor_hits = 0
    for terms in policy_anchors.values():
        if any(term in corpus for term in terms):
            anchor_hits += 1

    path_coverage = loaded_count / float(len(skill_paths))
    anchor_coverage = anchor_hits / float(len(policy_anchors))
    score = 100.0 * (0.8 * anchor_coverage + 0.2 * path_coverage)

    return {
        "skill_policy_score": round(score, 3),
        "skill_path_coverage": round(path_coverage, 6),
        "skill_policy_anchor_coverage": round(anchor_coverage, 6),
    }


def _objective_metrics(results: list[ScenarioResult]) -> dict[str, float]:
    if not results:
        empty: dict[str, float] = {
            "hard_pass_rate": 0.0,
            "validate_clean_rate": 0.0,
            "fallback_usage_rate": 0.0,
            "effective_autonomy_rate": 0.0,
            "provider_blocked_rate": 0.0,
            "validation_confidence_mean": 0.0,
            "memory_correctness_score": 0.0,
            "core_complexity_mean": 0.0,
        }
        for dimension in SCORE_DIMENSIONS:
            empty[f"{dimension}_mean"] = 0.0
        return empty

    total = float(len(results))
    hard_count = sum(1 for item in results if item.hard_pass)
    fallback_count = sum(1 for item in results if item.fallback_used)
    provider_blocked_count = sum(1 for item in results if item.provider_blocked)
    confidence_total = sum(float(item.validation_confidence) for item in results)

    validate_clean_count = 0
    for item in results:
        validate = item.probe.get("validate_strict", {})
        if not isinstance(validate, dict):
            continue
        if not validate.get("ok", False):
            continue
        try:
            error_count = int(validate.get("error_count", 1))
        except (TypeError, ValueError):
            error_count = 1
        if error_count == 0:
            validate_clean_count += 1

    metrics: dict[str, float] = {
        "hard_pass_rate": hard_count / total,
        "validate_clean_rate": validate_clean_count / total,
        "fallback_usage_rate": fallback_count / total,
        "provider_blocked_rate": provider_blocked_count / total,
        "validation_confidence_mean": confidence_total / total,
    }
    metrics["effective_autonomy_rate"] = max(0.0, 1.0 - metrics["fallback_usage_rate"])

    for dimension in SCORE_DIMENSIONS:
        dim_total = sum(float(item.dimensions.get(dimension, 0.0)) for item in results)
        metrics[f"{dimension}_mean"] = dim_total / total

    metrics["core_complexity_mean"] = (
        metrics["diachronic_mean"] + metrics["synchronic_mean"]
    ) / 2.0
    metrics["memory_correctness_score"] = 100.0 * (
        0.6 * metrics["hard_pass_rate"] + 0.4 * metrics["validate_clean_rate"]
    )
    return metrics


def _build_objective_progress(
    *,
    baseline: EvaluationSnapshot,
    candidate: EvaluationSnapshot,
    min_dimension_improvement: float,
    max_dimension_regression: float,
    min_fallback_reduction: float,
    max_fallback_increase: float,
) -> dict[str, Any]:
    baseline_metrics = _objective_metrics(baseline.scenario_results)
    candidate_metrics = _objective_metrics(candidate.scenario_results)
    baseline_summary_metrics = baseline.summary.get("objective_metrics", {})
    if isinstance(baseline_summary_metrics, dict):
        for key, value in baseline_summary_metrics.items():
            try:
                baseline_metrics[str(key)] = float(value)
            except (TypeError, ValueError):
                continue

    candidate_summary_metrics = candidate.summary.get("objective_metrics", {})
    if isinstance(candidate_summary_metrics, dict):
        for key, value in candidate_summary_metrics.items():
            try:
                candidate_metrics[str(key)] = float(value)
            except (TypeError, ValueError):
                continue

    tracked_metrics = (
        "diachronic_mean",
        "synchronic_mean",
        "skill_alignment_mean",
        "skill_policy_score",
        "memory_correctness_score",
        "validation_confidence_mean",
        "fallback_usage_rate",
        "effective_autonomy_rate",
        "provider_blocked_rate",
    )
    deltas = {
        metric: candidate_metrics.get(metric, 0.0) - baseline_metrics.get(metric, 0.0)
        for metric in tracked_metrics
    }

    core_dimension_metrics = (
        "diachronic_mean",
        "synchronic_mean",
        "skill_alignment_mean",
    )
    dimension_floor_violations = [
        metric
        for metric in core_dimension_metrics
        if deltas.get(metric, 0.0) < -max_dimension_regression
    ]
    dimension_gain_metrics = [
        metric
        for metric in core_dimension_metrics
        if deltas.get(metric, 0.0) >= min_dimension_improvement
    ]

    fallback_delta = deltas.get("fallback_usage_rate", 0.0)
    fallback_gate_ok = fallback_delta <= (max_fallback_increase + 1e-9)
    fallback_gain = fallback_delta <= -(min_fallback_reduction - 1e-9)

    provider_block_delta = deltas.get("provider_blocked_rate", 0.0)
    provider_block_gate_ok = provider_block_delta <= 1e-9
    provider_block_gain = provider_block_delta < -1e-9

    correctness_gain = deltas.get("memory_correctness_score", 0.0) >= min_dimension_improvement
    policy_gain = (
        deltas.get("skill_policy_score", 0.0) >= min_dimension_improvement
        and candidate_metrics.get("fallback_usage_rate", 0.0) < 1.0
        and candidate_metrics.get("provider_blocked_rate", 0.0) <= 0.0
    )
    has_objective_gain = bool(
        dimension_gain_metrics
        or fallback_gain
        or provider_block_gain
        or correctness_gain
        or policy_gain
    )

    return {
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "delta": deltas,
        "baseline_provider_blocked_rate": baseline_metrics.get("provider_blocked_rate", 0.0),
        "candidate_provider_blocked_rate": candidate_metrics.get("provider_blocked_rate", 0.0),
        "baseline_validation_confidence_mean": baseline_metrics.get(
            "validation_confidence_mean",
            0.0,
        ),
        "candidate_validation_confidence_mean": candidate_metrics.get(
            "validation_confidence_mean",
            0.0,
        ),
        "dimension_floor_ok": not dimension_floor_violations,
        "dimension_floor_violations": dimension_floor_violations,
        "dimension_gain_metrics": dimension_gain_metrics,
        "fallback_gate_ok": fallback_gate_ok,
        "fallback_gain": fallback_gain,
        "provider_block_gate_ok": provider_block_gate_ok,
        "provider_block_gain": provider_block_gain,
        "correctness_gain": correctness_gain,
        "policy_gain": policy_gain,
        "has_objective_gain": has_objective_gain,
    }


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
