from __future__ import annotations

import json
import statistics
import uuid
from pathlib import Path
from typing import Any

from .config import EvolutionConfig
from .evaluator import SkillJudge, aggregate_scores, score_execution
from .io_utils import ensure_dir, now_utc_stamp, run_shell_command, write_json
from .models import Decision, EvaluationSnapshot, ScenarioResult
from .mutator import Mutator
from .opencode_client import OpenCodeClient
from .probe import MemoryProbe
from .runner import ScenarioRunner
from .scenarios import load_scenarios, select_batch


class EvolutionOrchestrator:
    def __init__(
        self,
        *,
        workspace_root: Path,
        config: EvolutionConfig,
        dry_run: bool = False,
        disable_mutation: bool = False,
    ) -> None:
        self.workspace_root = workspace_root
        self.config = config
        self.dry_run = dry_run
        self.disable_mutation = disable_mutation

        self.run_id = f"{now_utc_stamp()}-{uuid.uuid4().hex[:8]}"
        self.run_dir = self.workspace_root / config.artifact_root / self.run_id

        runner_contract = _read_text(self.workspace_root / "evo/prompts/runner_contract.md")
        judge_contract = _read_text(self.workspace_root / "evo/prompts/judge_contract.md")
        mutator_contract = _read_text(self.workspace_root / "evo/prompts/mutator_contract.md")

        runner_client = OpenCodeClient(workspace_root, config.runner)
        judge_client = OpenCodeClient(workspace_root, config.judge)
        mutator_client = OpenCodeClient(workspace_root, config.mutator)

        self.runner = ScenarioRunner(
            client=runner_client,
            workspace_root=workspace_root,
            runner_contract=runner_contract,
            skill_paths=config.skill_paths,
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
        self.probe = MemoryProbe(workspace_root)

    def run(self) -> dict[str, Any]:
        ensure_dir(self.run_dir)
        ensure_dir(self.workspace_root / self.config.memory_run_root / self.run_id)

        train_scenarios = load_scenarios(
            self.workspace_root,
            self.config.train_scenarios_glob,
        )
        holdout_scenarios = load_scenarios(
            self.workspace_root,
            self.config.holdout_scenarios_glob,
        )
        if not train_scenarios:
            raise RuntimeError("No training scenarios found for evolution loop.")
        if not holdout_scenarios:
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

        baseline = self._evaluate_snapshot(
            epoch=0,
            label="baseline",
            train_scenarios=train_scenarios,
            holdout_scenarios=holdout_scenarios,
        )
        write_json(
            self.run_dir / "epoch-000-baseline-summary.json",
            _snapshot_to_dict(baseline),
        )

        best = baseline
        stagnant_epochs = 0
        history: list[dict[str, Any]] = []

        for epoch in range(1, self.config.max_epochs + 1):
            if self._should_stop():
                history.append(
                    {
                        "epoch": epoch,
                        "event": "stop-file-triggered",
                        "stop_file": self.config.stop_file,
                    }
                )
                break

            epoch_dir = self.run_dir / f"epoch-{epoch:03d}"
            ensure_dir(epoch_dir)

            proposal = None
            transaction = None
            if not self.disable_mutation and not self.dry_run:
                proposal = self.mutator.propose(
                    epoch=epoch,
                    baseline_summary=best.summary,
                    recent_failures=_collect_recent_failures(best.scenario_results),
                    artifact_dir=epoch_dir,
                )
                if proposal is None:
                    stagnant_epochs += 1
                    history.append(
                        {
                            "epoch": epoch,
                            "event": "mutation-skipped",
                            "reason": "no valid mutation proposal",
                        }
                    )
                    if stagnant_epochs >= self.config.max_stagnant_epochs:
                        break
                    continue

                transaction = self.mutator.apply(proposal)
                if transaction.errors:
                    stagnant_epochs += 1
                    write_json(
                        epoch_dir / "mutation-apply-errors.json",
                        {
                            "errors": transaction.errors,
                            "proposal": proposal.parsed_payload,
                        },
                    )
                    if stagnant_epochs >= self.config.max_stagnant_epochs:
                        break
                    continue

            gate_results = self._run_quality_gates()
            write_json(epoch_dir / "quality-gates.json", gate_results)
            if gate_results["failed"]:
                if transaction is not None:
                    self.mutator.rollback(transaction)
                stagnant_epochs += 1
                history.append(
                    {
                        "epoch": epoch,
                        "event": "quality-gate-failed",
                        "failed_commands": gate_results["failed"],
                    }
                )
                if stagnant_epochs >= self.config.max_stagnant_epochs:
                    break
                continue

            candidate = self._evaluate_snapshot(
                epoch=epoch,
                label="candidate",
                train_scenarios=train_scenarios,
                holdout_scenarios=holdout_scenarios,
            )

            decision = self._decide(baseline=best, candidate=candidate)
            write_json(
                epoch_dir / "decision.json",
                {
                    "decision": decision.__dict__,
                    "candidate": _snapshot_to_dict(candidate),
                    "baseline": _snapshot_to_dict(best),
                    "proposal": (proposal.parsed_payload if proposal else None),
                },
            )

            if decision.accepted:
                best = candidate
                stagnant_epochs = 0
                history.append(
                    {
                        "epoch": epoch,
                        "event": "accepted",
                        "reason": decision.reason,
                        "train_score": candidate.train_score,
                        "holdout_score": candidate.holdout_score,
                    }
                )
            else:
                if transaction is not None:
                    self.mutator.rollback(transaction)
                stagnant_epochs += 1
                history.append(
                    {
                        "epoch": epoch,
                        "event": "rejected",
                        "reason": decision.reason,
                        "candidate_train_score": candidate.train_score,
                        "candidate_holdout_score": candidate.holdout_score,
                    }
                )

            if stagnant_epochs >= self.config.max_stagnant_epochs:
                history.append(
                    {
                        "event": "stagnation-stop",
                        "stagnant_epochs": stagnant_epochs,
                    }
                )
                break

        final_summary = {
            "run_id": self.run_id,
            "best_snapshot": _snapshot_to_dict(best),
            "history": history,
            "stagnant_epochs": stagnant_epochs,
        }
        write_json(self.run_dir / "final-summary.json", final_summary)
        return final_summary

    def _evaluate_snapshot(
        self,
        *,
        epoch: int,
        label: str,
        train_scenarios: list,
        holdout_scenarios: list,
    ) -> EvaluationSnapshot:
        seed = self.config.batch.random_seed
        train_batch = select_batch(
            train_scenarios,
            self.config.batch.train_batch_size,
            epoch=epoch,
            seed=seed,
            curriculum_enabled=True,
        )
        holdout_batch = select_batch(
            holdout_scenarios,
            self.config.batch.holdout_batch_size,
            epoch=epoch + 97,
            seed=seed,
            curriculum_enabled=False,
        )

        epoch_dir = self.run_dir / f"epoch-{epoch:03d}" / label
        ensure_dir(epoch_dir)

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
        scenarios: list,
        epoch_dir: Path,
    ) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        for scenario in scenarios:
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

            scenario_result = score_execution(
                execution=execution,
                probe=probe_payload,
                judge_payload=judge_payload,
            )
            write_json(
                scenario_artifact / "scenario-result.json",
                _scenario_result_to_dict(scenario_result),
            )
            results.append(scenario_result)

        return results

    def _run_quality_gates(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for command in self.config.quality_gate_commands:
            result = run_shell_command(command, cwd=self.workspace_root, timeout_seconds=180)
            record = {
                "command": command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            checks.append(record)
            if result.exit_code != 0:
                failed.append(record)
        return {
            "checks": checks,
            "failed": failed,
        }

    def _decide(
        self,
        *,
        baseline: EvaluationSnapshot,
        candidate: EvaluationSnapshot,
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

        required_delta = self.config.mutation.require_improvement
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

    def _should_stop(self) -> bool:
        stop_path = self.workspace_root / self.config.stop_file
        return stop_path.exists()


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


def _collect_recent_failures(results: list[ScenarioResult]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for item in results:
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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
