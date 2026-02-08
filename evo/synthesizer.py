from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import ScenarioSynthesisConfig
from .io_utils import extract_json_payload, fill_placeholders, write_json
from .models import Scenario
from .opencode_client import OpenCodeClient


class ScenarioSynthesizer:
    def __init__(
        self,
        *,
        client: OpenCodeClient,
        synthesis_config: ScenarioSynthesisConfig,
        contract: str,
        skill_paths: list[str],
    ) -> None:
        self.client = client
        self.synthesis_config = synthesis_config
        self.contract = contract
        self.skill_paths = skill_paths

    def synthesize(
        self,
        *,
        epoch: int,
        partition: str,
        count: int,
        base_scenarios: list[Scenario],
        recent_failures: list[dict[str, Any]],
        artifact_dir: Path,
        project: str,
        scope: str,
    ) -> list[Scenario]:
        if not self.synthesis_config.enabled or count <= 0:
            return []

        ensure_count = max(1, count)
        prompt = self._build_prompt(
            epoch=epoch,
            partition=partition,
            count=ensure_count,
            base_scenarios=base_scenarios,
            recent_failures=recent_failures,
            project=project,
            scope=scope,
        )
        run = self.client.run_message(
            prompt,
            title=f"synth-{partition}-epoch-{epoch}",
            timeout_seconds=60,
        )

        raw_text = "\n".join(run.texts)
        payload = extract_json_payload(raw_text)
        if payload is None:
            repaired = self._repair_json_response(
                session_id=run.session_id,
                raw_text=raw_text,
            )
            repaired_payload = extract_json_payload(repaired)
            if repaired_payload is not None:
                raw_text = raw_text + "\n" + repaired
                payload = repaired_payload

        candidates = _extract_candidates(payload)

        normalized: list[Scenario] = []
        for index, raw in enumerate(candidates):
            scenario = self._normalize_candidate(
                raw,
                epoch=epoch,
                partition=partition,
                index=index,
            )
            if scenario is not None:
                normalized.append(scenario)
            if len(normalized) >= ensure_count:
                break

        write_json(
            artifact_dir / f"synthetic-{partition}.json",
            {
                "epoch": epoch,
                "partition": partition,
                "requested": ensure_count,
                "generated": len(normalized),
                "raw_text": raw_text,
                "payload": payload,
                "scenarios": [_scenario_to_payload(item) for item in normalized],
                "session_id": run.session_id,
                "exit_code": run.exit_code,
            },
        )
        return normalized

    def _build_prompt(
        self,
        *,
        epoch: int,
        partition: str,
        count: int,
        base_scenarios: list[Scenario],
        recent_failures: list[dict[str, Any]],
        project: str,
        scope: str,
    ) -> str:
        skill_manifest = "\n".join(f"- {path}" for path in self.skill_paths)
        contract = fill_placeholders(
            self.contract,
            {
                "skill_manifest": skill_manifest,
                "partition": partition,
                "count": str(count),
                "project": project,
                "scope": scope,
            },
        )

        payload = {
            "epoch": epoch,
            "partition": partition,
            "project": project,
            "scope": scope,
            "base_scenarios": [_scenario_to_payload(item) for item in base_scenarios],
            "recent_failures": recent_failures,
            "constraints": {
                "min_turns": self.synthesis_config.min_turns,
                "max_turns": self.synthesis_config.max_turns,
                "max_difficulty": self.synthesis_config.max_difficulty,
            },
        }
        return f"{contract}\n\nSynthesis context:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"

    def _repair_json_response(self, *, session_id: str | None, raw_text: str) -> str:
        if not session_id:
            return ""

        repair_prompt = (
            "Your previous output was not strict JSON. "
            "Return one JSON object with key 'scenarios' only. "
            "No markdown, no questions.\n\n"
            "Previous output:\n"
            f"{raw_text}"
        )
        repair = self.client.run_message(
            repair_prompt,
            session_id=session_id,
            timeout_seconds=45,
        )
        return "\n".join(repair.texts)

    def _normalize_candidate(
        self,
        raw: dict[str, Any],
        *,
        epoch: int,
        partition: str,
        index: int,
    ) -> Scenario | None:
        if not isinstance(raw, dict):
            return None

        title = _string_or_default(raw.get("title"), f"Synthetic {partition} scenario {index + 1}")
        complexity_mode = _normalize_complexity(raw.get("complexity_mode"))
        difficulty = _clamp_int(
            raw.get("difficulty", 1),
            minimum=1,
            maximum=self.synthesis_config.max_difficulty,
            fallback=1,
        )

        turns = [str(item) for item in raw.get("turns", []) if str(item).strip()]
        if len(turns) < self.synthesis_config.min_turns:
            turns.extend(
                [
                    "[[NEW_SESSION]] Continue from the persisted memory state without asking to restate known context.",
                    "Close this scenario with governance checks and a clean handoff.",
                ]
            )
        turns = turns[: self.synthesis_config.max_turns]

        criteria = [str(item) for item in raw.get("success_criteria", []) if str(item).strip()]
        if not criteria:
            criteria = [
                "Behavior should remain filesystem-native and auditable.",
                "Conflicts and continuity gaps should be explicit.",
                "Scenario should end with clear next-action continuity.",
            ]

        tags = [str(item) for item in raw.get("tags", []) if str(item).strip()]
        tags.extend(["synthetic", partition])
        dedup_tags = sorted(set(tags))

        slug_seed = _string_or_default(raw.get("id"), title)
        slug = _slugify(slug_seed)
        scenario_id = f"synth_{partition}_e{epoch}_{index + 1}_{slug}"[:96]

        description = _string_or_default(
            raw.get("description"),
            f"Synthetic {partition} scenario generated for epoch {epoch}.",
        )

        weights_raw = raw.get("weights", {})
        weights = weights_raw if isinstance(weights_raw, dict) else {}

        metadata = {
            "synthetic": True,
            "partition": partition,
            "epoch": epoch,
        }

        return Scenario(
            id=scenario_id,
            title=title,
            description=description,
            complexity_mode=complexity_mode,
            difficulty=difficulty,
            turns=turns,
            success_criteria=criteria,
            tags=dedup_tags,
            weights={str(k): float(v) for k, v in weights.items() if _is_number(v)},
            metadata=metadata,
        )


def _extract_candidates(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("scenarios"), list):
            return [item for item in payload["scenarios"] if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _scenario_to_payload(scenario: Scenario) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "title": scenario.title,
        "description": scenario.description,
        "complexity_mode": scenario.complexity_mode,
        "difficulty": scenario.difficulty,
        "turns": scenario.turns,
        "success_criteria": scenario.success_criteria,
        "tags": scenario.tags,
        "weights": scenario.weights,
        "metadata": scenario.metadata,
    }


def _normalize_complexity(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"diachronic", "synchronic", "mixed"}:
        return text
    return "mixed"


def _string_or_default(value: object, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else default


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = lowered.strip("-")
    return lowered or "scenario"


def _clamp_int(value: object, *, minimum: int, maximum: int, fallback: int) -> int:
    try:
        text_value = f"{value}"
        parsed = int(text_value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _is_number(value: object) -> bool:
    try:
        text_value = f"{value}"
        float(text_value)
    except (TypeError, ValueError):
        return False
    return True
