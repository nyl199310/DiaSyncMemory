from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCORE_DIMENSIONS = (
    "diachronic",
    "synchronic",
    "governance",
    "realism",
    "skill_alignment",
)


@dataclass
class Scenario:
    id: str
    title: str
    description: str
    complexity_mode: str
    difficulty: int
    turns: list[str]
    success_criteria: list[str]
    tags: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunEvents:
    session_id: str | None
    stdout: str
    stderr: str
    exit_code: int
    events: list[dict[str, Any]]
    texts: list[str]
    tool_commands: list[str]
    tool_calls: list[dict[str, Any]]


@dataclass
class ScenarioExecution:
    scenario: Scenario
    partition: str
    epoch: int
    memory_root: Path
    artifact_dir: Path
    session_id: str | None
    turns: list[RunEvents]
    assistant_messages: list[str]
    command_trace: list[str]
    read_paths: list[str]
    session_ids: list[str]
    exported_session_path: Path | None
    fallback_used: bool
    fallback_only_mode: bool
    provider_blocked: bool
    provider_block_reasons: list[str]


@dataclass
class ScenarioResult:
    scenario_id: str
    partition: str
    epoch: int
    memory_root: str
    session_id: str | None
    hard_pass: bool
    fitness: float
    judge_score: float
    dimensions: dict[str, float]
    violations: list[str]
    strengths: list[str]
    next_focus: list[str]
    probe: dict[str, Any]
    command_trace: list[str]
    artifact_dir: str
    fallback_used: bool
    provider_blocked: bool
    provider_block_reasons: list[str]
    validation_confidence: float


@dataclass
class EvaluationSnapshot:
    epoch: int
    label: str
    train_score: float
    holdout_score: float
    hard_pass_rate: float
    scenario_results: list[ScenarioResult]
    summary: dict[str, Any]


@dataclass
class MutationOperation:
    op: str
    path: str
    find: str | None = None
    replace: str | None = None
    anchor: str | None = None
    text: str | None = None
    content: str | None = None


@dataclass
class MutationProposal:
    rationale: str
    expected_effect: str
    operations: list[MutationOperation]
    raw_response: str
    parsed_payload: dict[str, Any]


@dataclass
class MutationTransaction:
    changed_paths: list[Path]
    backups: dict[Path, tuple[bool, str]]
    errors: list[str] = field(default_factory=list)


@dataclass
class Decision:
    accepted: bool
    reason: str
    candidate_train_score: float
    candidate_holdout_score: float
    baseline_train_score: float
    baseline_holdout_score: float
    candidate_hard_pass_rate: float
    objective_progress: dict[str, Any] = field(default_factory=dict)
    provisional: bool = False
