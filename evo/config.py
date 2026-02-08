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
class EvolutionConfig:
    project: str
    scope: str
    max_epochs: int
    max_stagnant_epochs: int
    stop_file: str
    artifact_root: str
    memory_run_root: str
    train_scenarios_glob: str
    holdout_scenarios_glob: str
    skill_paths: list[str]
    quality_gate_commands: list[str]
    runner: AgentConfig = field(default_factory=AgentConfig)
    judge: AgentConfig = field(default_factory=AgentConfig)
    mutator: AgentConfig = field(default_factory=AgentConfig)
    mutation: MutationConfig = field(default_factory=MutationConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)

    @classmethod
    def from_file(cls, file_path: Path) -> "EvolutionConfig":
        payload = json.loads(file_path.read_text(encoding="utf-8"))

        runner = AgentConfig(**payload.get("runner", {}))
        judge = AgentConfig(**payload.get("judge", {}))
        mutator = AgentConfig(**payload.get("mutator", {}))
        mutation = MutationConfig(**payload.get("mutation", {}))
        batch = BatchConfig(**payload.get("batch", {}))

        return cls(
            project=payload["project"],
            scope=payload["scope"],
            max_epochs=int(payload.get("max_epochs", 20)),
            max_stagnant_epochs=int(payload.get("max_stagnant_epochs", 6)),
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
            runner=runner,
            judge=judge,
            mutator=mutator,
            mutation=mutation,
            batch=batch,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "scope": self.scope,
            "max_epochs": self.max_epochs,
            "max_stagnant_epochs": self.max_stagnant_epochs,
            "stop_file": self.stop_file,
            "artifact_root": self.artifact_root,
            "memory_run_root": self.memory_run_root,
            "train_scenarios_glob": self.train_scenarios_glob,
            "holdout_scenarios_glob": self.holdout_scenarios_glob,
            "skill_paths": self.skill_paths,
            "quality_gate_commands": self.quality_gate_commands,
            "runner": self.runner.__dict__,
            "judge": self.judge.__dict__,
            "mutator": self.mutator.__dict__,
            "mutation": self.mutation.__dict__,
            "batch": self.batch.__dict__,
        }
