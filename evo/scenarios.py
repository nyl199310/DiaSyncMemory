from __future__ import annotations

import json
import random
from pathlib import Path

from .models import Scenario


class SafeFormat(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def load_scenarios(workspace_root: Path, pattern: str) -> list[Scenario]:
    files = sorted(workspace_root.glob(pattern))
    scenarios: list[Scenario] = []

    for file_path in files:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        scenario = Scenario(
            id=payload["id"],
            title=payload["title"],
            description=payload["description"],
            complexity_mode=payload.get("complexity_mode", "mixed"),
            difficulty=int(payload.get("difficulty", 1)),
            turns=list(payload.get("turns", [])),
            success_criteria=list(payload.get("success_criteria", [])),
            tags=list(payload.get("tags", [])),
            weights=dict(payload.get("weights", {})),
            metadata=dict(payload.get("metadata", {})),
        )
        scenarios.append(scenario)

    return scenarios


def select_batch(
    scenarios: list[Scenario],
    batch_size: int,
    *,
    epoch: int,
    seed: int,
    curriculum_enabled: bool = True,
) -> list[Scenario]:
    if not scenarios:
        return []

    selected_pool = scenarios
    if curriculum_enabled:
        max_difficulty = max(s.difficulty for s in scenarios)
        stage_ceiling = min(max_difficulty, 1 + epoch // 2)
        staged = [s for s in scenarios if s.difficulty <= stage_ceiling]
        if staged:
            selected_pool = staged

    if batch_size <= 0 or batch_size >= len(selected_pool):
        return list(selected_pool)

    rnd = random.Random(seed + epoch)
    return rnd.sample(selected_pool, batch_size)


def render_text(template: str, variables: dict[str, str]) -> str:
    return template.format_map(SafeFormat(**variables))
