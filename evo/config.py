from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentConfig:
    agent: str = "build"
    model: str = ""
    variant: str = ""
    thinking: bool = False


@dataclass
class MutationConfig:
    enabled: bool = True
    max_operations: int = 3
    allow_paths: list[str] = field(default_factory=list)
    deny_paths: list[str] = field(default_factory=list)
    require_improvement: float = 0.5
    holdout_regression_tolerance: float = 0.0


@dataclass
class BatchConfig:
    train_batch_size: int = 2
    holdout_batch_size: int = 1
    random_seed: int = 7


@dataclass
class SkillHydrationConfig:
    enforce: bool = True
    required_paths: list[str] = field(default_factory=list)
    minimum_reads: int = 1
    hard_fail_missing: bool = True


@dataclass
class ScenarioSynthesisConfig:
    enabled: bool = True
    per_epoch_train: int = 1
    per_epoch_holdout: int = 1
    min_turns: int = 2
    max_turns: int = 4
    max_difficulty: int = 5


@dataclass
class RuntimeLaneConfig:
    enabled: bool = True
    paths: list[str] = field(
        default_factory=lambda: [
            ".opencode/skills/diasync-memory/scripts/memoryctl.py",
        ]
    )
    extra_gate_commands: list[str] = field(default_factory=list)
    force_full_evaluation: bool = True
    min_improvement: float = 1.0


@dataclass
class ObjectiveGateConfig:
    min_dimension_improvement: float = 0.5
    max_dimension_regression: float = 1.0
    min_fallback_reduction: float = 0.05
    max_fallback_increase: float = 0.0
    require_objective_gain: bool = True
    stop_when_provider_blocked: bool = True
    provider_blocked_stop_rate: float = 1.0
    provider_blocked_grace_snapshots: int = 1
    continue_on_provider_blocked: bool = True
    allow_provisional_acceptance: bool = True
    max_provisional_accepts_per_run: int = 3
    min_failure_alignment_score: float = 0.08
    provisional_confirm_min_validation_confidence: float = 0.85
    provisional_confirm_min_hard_pass_rate: float = 1.0
    provisional_confirm_max_provider_blocked_rate: float = 0.0


@dataclass
class EvolutionConfig:
    project: str
    scope: str
    max_epochs: int
    max_stagnant_epochs: int
    continuous: bool
    max_wall_seconds: int
    stop_file: str
    artifact_root: str
    memory_run_root: str
    train_scenarios_glob: str
    holdout_scenarios_glob: str
    skill_paths: list[str]
    quality_gate_commands: list[str]
    export_sessions: bool
    runner_fallback_only: bool
    runner: AgentConfig = field(default_factory=AgentConfig)
    judge: AgentConfig = field(default_factory=AgentConfig)
    mutator: AgentConfig = field(default_factory=AgentConfig)
    synthesizer: AgentConfig = field(default_factory=AgentConfig)
    mutation: MutationConfig = field(default_factory=MutationConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)
    skill_hydration: SkillHydrationConfig = field(default_factory=SkillHydrationConfig)
    synthesis: ScenarioSynthesisConfig = field(default_factory=ScenarioSynthesisConfig)
    runtime_lane: RuntimeLaneConfig = field(default_factory=RuntimeLaneConfig)
    objectives: ObjectiveGateConfig = field(default_factory=ObjectiveGateConfig)

    @classmethod
    def from_file(cls, file_path: Path) -> "EvolutionConfig":
        payload = json.loads(file_path.read_text(encoding="utf-8"))

        runner = AgentConfig(**payload.get("runner", {}))
        judge = AgentConfig(**payload.get("judge", {}))
        mutator = AgentConfig(**payload.get("mutator", {}))
        synthesizer = AgentConfig(**payload.get("synthesizer", {}))
        mutation = MutationConfig(**payload.get("mutation", {}))
        batch = BatchConfig(**payload.get("batch", {}))
        skill_hydration = SkillHydrationConfig(**payload.get("skill_hydration", {}))
        synthesis = ScenarioSynthesisConfig(**payload.get("synthesis", {}))
        runtime_lane = RuntimeLaneConfig(**payload.get("runtime_lane", {}))
        objectives = ObjectiveGateConfig(**payload.get("objectives", {}))

        return cls(
            project=payload["project"],
            scope=payload["scope"],
            max_epochs=int(payload.get("max_epochs", 20)),
            max_stagnant_epochs=int(payload.get("max_stagnant_epochs", 6)),
            continuous=bool(payload.get("continuous", False)),
            max_wall_seconds=int(payload.get("max_wall_seconds", 0)),
            stop_file=payload.get("stop_file", ".evo/STOP"),
            artifact_root=payload.get("artifact_root", "artifacts/evolution"),
            memory_run_root=payload.get("memory_run_root", ".memory_evolution"),
            train_scenarios_glob=payload.get(
                "train_scenarios_glob",
                "bench/scenarios/train/*.json",
            ),
            holdout_scenarios_glob=payload.get(
                "holdout_scenarios_glob",
                "bench/scenarios/holdout/*.json",
            ),
            skill_paths=payload.get("skill_paths", []),
            quality_gate_commands=payload.get("quality_gate_commands", []),
            export_sessions=bool(payload.get("export_sessions", True)),
            runner_fallback_only=bool(payload.get("runner_fallback_only", False)),
            runner=runner,
            judge=judge,
            mutator=mutator,
            synthesizer=synthesizer,
            mutation=mutation,
            batch=batch,
            skill_hydration=skill_hydration,
            synthesis=synthesis,
            runtime_lane=runtime_lane,
            objectives=objectives,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "scope": self.scope,
            "max_epochs": self.max_epochs,
            "max_stagnant_epochs": self.max_stagnant_epochs,
            "continuous": self.continuous,
            "max_wall_seconds": self.max_wall_seconds,
            "stop_file": self.stop_file,
            "artifact_root": self.artifact_root,
            "memory_run_root": self.memory_run_root,
            "train_scenarios_glob": self.train_scenarios_glob,
            "holdout_scenarios_glob": self.holdout_scenarios_glob,
            "skill_paths": self.skill_paths,
            "quality_gate_commands": self.quality_gate_commands,
            "export_sessions": self.export_sessions,
            "runner_fallback_only": self.runner_fallback_only,
            "runner": self.runner.__dict__,
            "judge": self.judge.__dict__,
            "mutator": self.mutator.__dict__,
            "synthesizer": self.synthesizer.__dict__,
            "mutation": self.mutation.__dict__,
            "batch": self.batch.__dict__,
            "skill_hydration": self.skill_hydration.__dict__,
            "synthesis": self.synthesis.__dict__,
            "runtime_lane": self.runtime_lane.__dict__,
            "objectives": self.objectives.__dict__,
        }
