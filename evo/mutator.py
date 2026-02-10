from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import MutationConfig
from .io_utils import extract_json_payload, fill_placeholders, write_json
from .models import MutationOperation, MutationProposal, MutationTransaction
from .opencode_client import OpenCodeClient


class Mutator:
    def __init__(
        self,
        *,
        client: OpenCodeClient,
        workspace_root: Path,
        mutation_config: MutationConfig,
        mutator_contract: str,
        skill_paths: list[str],
    ) -> None:
        self.client = client
        self.workspace_root = workspace_root
        self.mutation_config = mutation_config
        self.mutator_contract = mutator_contract
        self.skill_paths = skill_paths

    def propose(
        self,
        *,
        epoch: int,
        baseline_summary: dict[str, Any],
        recent_failures: list[dict[str, Any]],
        artifact_dir: Path,
    ) -> MutationProposal | None:
        if not self.mutation_config.enabled:
            return None

        context_payload = {
            "epoch": epoch,
            "baseline_summary": baseline_summary,
            "recent_failures": recent_failures,
        }
        context_path = artifact_dir / "mutation-context.json"
        write_json(context_path, context_payload)

        prompt = self._build_prompt(
            epoch=epoch,
            context_path=context_path,
        )
        run = self.client.run_message(
            prompt,
            title=f"mutator-epoch-{epoch}",
            timeout_seconds=60,
        )

        raw_text = "\n".join(run.texts)
        payload = _extract_mutation_payload(raw_text)
        if not isinstance(payload, dict):
            repaired = self._repair_json_response(
                session_id=run.session_id,
                raw_text=raw_text,
            )
            repaired_payload = _extract_mutation_payload(repaired)
            if isinstance(repaired_payload, dict):
                raw_text = raw_text + "\n" + repaired
                payload = repaired_payload

        if not isinstance(payload, dict):
            deterministic = self._build_deterministic_fallback(
                epoch=epoch,
                recent_failures=recent_failures,
                reason="mutator_non_json",
            )
            if deterministic is not None:
                write_json(
                    artifact_dir / "mutation-proposal-fallback.json",
                    {
                        "proposal": {
                            "rationale": deterministic.rationale,
                            "expected_effect": deterministic.expected_effect,
                            "operations": [op.__dict__ for op in deterministic.operations],
                        },
                        "reason": "mutator returned non-json; deterministic fallback used",
                    },
                )
                return deterministic
            write_json(
                artifact_dir / "mutation-proposal-invalid.json",
                {
                    "error": "mutator did not return JSON",
                    "raw_text": raw_text,
                    "stdout": run.stdout,
                    "stderr": run.stderr,
                    "exit_code": run.exit_code,
                },
            )
            return None

        operations_payload = _coerce_operations_payload(payload)
        operations: list[MutationOperation] = []
        for raw_operation in operations_payload:
            if not isinstance(raw_operation, dict):
                continue
            operation = MutationOperation(
                op=str(raw_operation.get("op", "")).strip(),
                path=str(raw_operation.get("path", "")).strip(),
                find=_optional_str(raw_operation.get("find")),
                replace=_optional_str(raw_operation.get("replace")),
                anchor=_optional_str(raw_operation.get("anchor")),
                text=_optional_str(raw_operation.get("text")),
                content=_optional_str(raw_operation.get("content")),
            )
            if operation.op and operation.path:
                operations.append(operation)

        if not operations:
            deterministic = self._build_deterministic_fallback(
                epoch=epoch,
                recent_failures=recent_failures,
                reason="empty_operations",
            )
            if deterministic is not None:
                write_json(
                    artifact_dir / "mutation-proposal-fallback.json",
                    {
                        "proposal": {
                            "rationale": deterministic.rationale,
                            "expected_effect": deterministic.expected_effect,
                            "operations": [op.__dict__ for op in deterministic.operations],
                        },
                        "reason": "mutator returned empty operations; deterministic fallback used",
                    },
                )
                return deterministic
            write_json(
                artifact_dir / "mutation-proposal-empty.json",
                {
                    "raw_text": raw_text,
                    "payload": payload,
                    "context_path": _display_path(context_path, self.workspace_root),
                },
            )
            return None

        operations = operations[: self.mutation_config.max_operations]
        proposal = MutationProposal(
            rationale=str(payload.get("rationale", "")),
            expected_effect=str(payload.get("expected_effect", "")),
            operations=operations,
            raw_response=raw_text,
            parsed_payload=payload,
        )
        write_json(
            artifact_dir / "mutation-proposal.json",
            {
                "proposal": {
                    "rationale": proposal.rationale,
                    "expected_effect": proposal.expected_effect,
                    "operations": [operation.__dict__ for operation in operations],
                },
                "raw_text": raw_text,
                "session_id": run.session_id,
                "context_path": _display_path(context_path, self.workspace_root),
            },
        )
        return proposal

    def _build_deterministic_fallback(
        self,
        *,
        epoch: int,
        recent_failures: list[dict[str, Any]],
        reason: str,
    ) -> MutationProposal | None:
        target_path = self._select_fallback_target_path()
        if target_path is None:
            return None

        focus_lines = _collect_failure_focus(recent_failures)
        focus_themes = _collect_failure_themes(recent_failures)
        feedback_block = _render_feedback_block(
            focus_themes=focus_themes,
        )
        target_file = self.workspace_root / target_path
        current_text = ""
        if target_file.exists() and target_file.is_file():
            try:
                current_text = target_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                current_text = target_file.read_text(encoding="utf-8", errors="replace")
        updated_text = _upsert_feedback_block(current_text, feedback_block)

        operation = MutationOperation(
            op="write_file",
            path=target_path,
            content=updated_text,
        )
        parsed_payload = {
            "rationale": "Fallback mutation generated from clustered failures when mutator output was unusable.",
            "expected_effect": "Preserve evolution pressure by refreshing a stable autonomous resilience policy on hydrated skill surfaces.",
            "operations": [operation.__dict__],
            "deterministic_fallback": True,
            "fallback_reason": reason,
            "focus_lines": focus_lines,
            "focus_themes": focus_themes,
        }
        return MutationProposal(
            rationale=parsed_payload["rationale"],
            expected_effect=parsed_payload["expected_effect"],
            operations=[operation],
            raw_response=json_dumps_compact(parsed_payload),
            parsed_payload=parsed_payload,
        )

    def _select_fallback_target_path(self) -> str | None:
        normalized_skill_paths = [item.replace("\\", "/") for item in self.skill_paths]

        preferred_references = [
            path
            for path in normalized_skill_paths
            if "/references/" in path.lower() and path.lower().endswith(".md")
        ]
        preferred_non_skill = [
            path
            for path in normalized_skill_paths
            if path.lower().endswith(".md") and not path.lower().endswith("/skill.md")
        ]
        fallback_order: list[str] = []
        for candidate in [*preferred_references, *preferred_non_skill, *normalized_skill_paths]:
            if candidate not in fallback_order:
                fallback_order.append(candidate)

        for candidate in fallback_order:
            if self._is_allowed(candidate) and not self._is_denied(candidate):
                return candidate

        for prefix in self.mutation_config.allow_paths:
            normalized = prefix.replace("\\", "/").rstrip("/")
            if not normalized:
                continue
            if normalized.endswith(".md"):
                if not self._is_denied(normalized):
                    return normalized
                continue
            candidate = normalized + "/SKILL.md"
            if self._is_allowed(candidate) and not self._is_denied(candidate):
                return candidate
        return None

    def apply(self, proposal: MutationProposal) -> MutationTransaction:
        transaction = MutationTransaction(changed_paths=[], backups={}, errors=[])

        for operation in proposal.operations:
            try:
                path = self._resolve_and_validate(operation.path)
                if path not in transaction.backups:
                    if path.exists():
                        transaction.backups[path] = (True, path.read_text(encoding="utf-8"))
                    else:
                        transaction.backups[path] = (False, "")
                self._apply_operation(path, operation)
                if path not in transaction.changed_paths:
                    transaction.changed_paths.append(path)
            except Exception as exc:  # noqa: BLE001
                transaction.errors.append(f"{operation.path}: {exc}")
                self.rollback(transaction)
                break

        return transaction

    def rollback(self, transaction: MutationTransaction) -> None:
        for path, (existed, content) in transaction.backups.items():
            if existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            elif path.exists():
                path.unlink()

    def _build_prompt(
        self,
        *,
        epoch: int,
        context_path: Path,
    ) -> str:
        skill_manifest = "\n".join(f"- {path}" for path in self.skill_paths)
        contract = fill_placeholders(
            self.mutator_contract,
            {
                "skill_manifest": skill_manifest,
                "allow_paths": "\n".join(
                    f"- {item}" for item in self.mutation_config.allow_paths
                ),
                "deny_paths": "\n".join(
                    f"- {item}" for item in self.mutation_config.deny_paths
                ),
                "max_operations": str(self.mutation_config.max_operations),
            },
        )
        context_ref = _display_path(context_path, self.workspace_root)
        return (
            f"{contract}\n\n"
            f"Epoch: {epoch}\n"
            "Read mutation context JSON using the read tool from:\n"
            f"- {context_ref}\n\n"
            "Return strict JSON only. If no safe change, return operations as an empty list."
        )

    def _repair_json_response(self, *, session_id: str | None, raw_text: str) -> str:
        if not session_id:
            return ""

        repair_prompt = (
            "Your previous output was not strict JSON. "
            "Return one JSON object only, matching the mutation schema. "
            "Do not ask clarifying questions. No markdown.\n\n"
            "Previous output:\n"
            f"{raw_text}"
        )
        repair = self.client.run_message(
            repair_prompt,
            session_id=session_id,
            timeout_seconds=45,
        )
        return "\n".join(repair.texts)

    def _resolve_and_validate(self, raw_path: str) -> Path:
        normalized = raw_path.replace("\\", "/")
        candidate = (self.workspace_root / normalized).resolve()
        workspace = self.workspace_root.resolve()
        if workspace not in candidate.parents and candidate != workspace:
            raise ValueError("path escapes workspace root")

        rel = candidate.relative_to(workspace).as_posix()
        if self._is_denied(rel):
            raise ValueError("path is denied by mutation policy")
        if not self._is_allowed(rel):
            raise ValueError("path is outside mutation allow-list")
        return candidate

    def _is_allowed(self, rel_posix: str) -> bool:
        for prefix in self.mutation_config.allow_paths:
            p = prefix.replace("\\", "/").rstrip("/")
            if rel_posix == p or rel_posix.startswith(p + "/"):
                return True
        return False

    def _is_denied(self, rel_posix: str) -> bool:
        for prefix in self.mutation_config.deny_paths:
            p = prefix.replace("\\", "/").rstrip("/")
            if rel_posix == p or rel_posix.startswith(p + "/"):
                return True
        return False

    def _apply_operation(self, path: Path, operation: MutationOperation) -> None:
        op = operation.op
        if op == "write_file":
            if operation.content is None:
                raise ValueError("write_file requires content")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(operation.content, encoding="utf-8")
            return

        current = path.read_text(encoding="utf-8") if path.exists() else ""

        if op == "replace_text":
            if operation.find is None or operation.replace is None:
                raise ValueError("replace_text requires find and replace")
            if operation.find not in current:
                raise ValueError("find text not found")
            updated = current.replace(operation.find, operation.replace, 1)
            path.write_text(updated, encoding="utf-8")
            return

        if op == "insert_after":
            if operation.anchor is None or operation.text is None:
                raise ValueError("insert_after requires anchor and text")
            index = current.find(operation.anchor)
            if index == -1:
                raise ValueError("anchor not found")
            position = index + len(operation.anchor)
            updated = current[:position] + operation.text + current[position:]
            path.write_text(updated, encoding="utf-8")
            return

        if op == "insert_before":
            if operation.anchor is None or operation.text is None:
                raise ValueError("insert_before requires anchor and text")
            index = current.find(operation.anchor)
            if index == -1:
                raise ValueError("anchor not found")
            updated = current[:index] + operation.text + current[index:]
            path.write_text(updated, encoding="utf-8")
            return

        if op == "append_text":
            if operation.text is None:
                raise ValueError("append_text requires text")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(current + operation.text, encoding="utf-8")
            return

        raise ValueError(f"unsupported mutation operation: {op}")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _display_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _coerce_operations_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_operations = payload.get("operations")
    if isinstance(raw_operations, list):
        return [item for item in raw_operations if isinstance(item, dict)]

    return []


def _extract_mutation_payload(text: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []

    direct = extract_json_payload(text)
    if isinstance(direct, dict):
        candidates.append(direct)

    for block in _extract_fenced_blocks(text):
        parsed = extract_json_payload(block)
        if isinstance(parsed, dict):
            candidates.append(parsed)

    for candidate in candidates:
        if _coerce_operations_payload(candidate):
            return candidate

    return candidates[0] if candidates else None


def _extract_fenced_blocks(text: str) -> list[str]:
    results: list[str] = []
    marker = "```"
    position = 0
    while True:
        start = text.find(marker, position)
        if start == -1:
            break
        end = text.find(marker, start + len(marker))
        if end == -1:
            break
        block = text[start + len(marker) : end].strip()
        if block.startswith("json"):
            block = block[4:].strip()
        if block:
            results.append(block)
        position = end + len(marker)
    return results


def _render_feedback_block(*, focus_themes: list[str]) -> str:
    bullet_lines = "\n".join(f"- {line}" for line in focus_themes)
    if not bullet_lines:
        bullet_lines = "- Maintain memory correctness and governance integrity while reducing fallback dependence."
    return (
        "<!-- EVO-POLICY:START -->\n"
        "## Autonomous Resilience Policy\n"
        "- Keep autonomous memoryctl lifecycle as primary behavior; fallback is temporary safety only.\n"
        "- Preserve diachronic continuity across interruptions using checkpoint/handoff discipline.\n"
        "- Resolve synchronic contention with explicit lease ownership and reconcile flows.\n"
        "- Enforce command contract correctness (`--root` and `--scope`) before optimization.\n"
        "- Maintain governance loops (`validate`, `diagnose`, `optimize`) as continuous controls.\n"
        "- Active improvement themes:\n"
        f"{bullet_lines}\n"
        "<!-- EVO-POLICY:END -->"
    )


def _upsert_feedback_block(current_text: str, feedback_block: str) -> str:
    start_marker = "<!-- EVO-POLICY:START -->"
    end_marker = "<!-- EVO-POLICY:END -->"

    if start_marker in current_text and end_marker in current_text:
        pattern = re.compile(
            re.escape(start_marker) + r"[\s\S]*?" + re.escape(end_marker),
            re.MULTILINE,
        )
        replaced, count = pattern.subn(feedback_block, current_text, count=1)
        if count > 0:
            return _ensure_text_newline(replaced)

    cleaned = current_text
    legacy_comment_pattern = re.compile(
        r"\n?<!-- EVO-FEEDBACK:START -->[\s\S]*?<!-- EVO-FEEDBACK:END -->\n?",
        re.MULTILINE,
    )
    cleaned = legacy_comment_pattern.sub("\n", cleaned)

    legacy_pattern = re.compile(
        r"\n## Epoch \d+ Evolution Reinforcement\n[\s\S]*?"
        r"(?=\n## [^\n]+\n|\Z)",
        re.MULTILINE,
    )
    cleaned = legacy_pattern.sub("\n", cleaned)
    cleaned = cleaned.rstrip()
    if cleaned:
        return _ensure_text_newline(cleaned + "\n\n" + feedback_block)
    return _ensure_text_newline(feedback_block)


def _ensure_text_newline(value: str) -> str:
    if value.endswith("\n"):
        return value
    return value + "\n"


def _collect_failure_focus(recent_failures: list[dict[str, Any]]) -> list[str]:
    points: list[str] = []
    for item in recent_failures[:6]:
        scenario_id = str(item.get("scenario_id", "unknown"))
        violations = item.get("violations", [])
        next_focus = item.get("next_focus", [])
        if isinstance(violations, list):
            for text in violations[:2]:
                points.append(f"{scenario_id}: violation -> {str(text).strip()}")
        if isinstance(next_focus, list):
            for text in next_focus[:2]:
                points.append(f"{scenario_id}: next_focus -> {str(text).strip()}")

    deduped: list[str] = []
    seen: set[str] = set()
    for point in points:
        normalized = " ".join(point.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= 6:
            break

    if not deduped:
        return [
            "No detailed failure cluster available; reinforce contract-following and memory integrity behavior.",
        ]
    return deduped


def _collect_failure_themes(recent_failures: list[dict[str, Any]]) -> list[str]:
    theme_map = {
        "provider": "Provider availability resilience and retry/backoff discipline.",
        "quota": "Provider availability resilience and retry/backoff discipline.",
        "payment": "Provider availability resilience and retry/backoff discipline.",
        "fallback": "Fallback dependency reduction through stronger autonomous contract-following.",
        "contract": "Command-contract compliance for root/scope correctness on every turn.",
        "resume": "Diachronic continuity across resume/interruption boundaries.",
        "checkpoint": "Diachronic continuity across resume/interruption boundaries.",
        "handoff": "Diachronic continuity across resume/interruption boundaries.",
        "lease": "Synchronic contention management via lease/reconcile discipline.",
        "reconcile": "Synchronic contention management via lease/reconcile discipline.",
        "conflict": "Synchronic contention management via lease/reconcile discipline.",
        "judge": "Evaluation reliability and strict scoring JSON contract adherence.",
        "validate": "Validation-first memory correctness gates before acceptance.",
        "integrity": "Validation-first memory correctness gates before acceptance.",
    }

    detected: list[str] = []
    seen: set[str] = set()
    for item in recent_failures:
        chunks: list[str] = []
        violations = item.get("violations", [])
        next_focus = item.get("next_focus", [])
        if isinstance(violations, list):
            chunks.extend(str(chunk).lower() for chunk in violations)
        if isinstance(next_focus, list):
            chunks.extend(str(chunk).lower() for chunk in next_focus)

        merged = "\n".join(chunks)
        for key, theme in theme_map.items():
            if key not in merged:
                continue
            if theme in seen:
                continue
            seen.add(theme)
            detected.append(theme)
            if len(detected) >= 5:
                return detected

    if not detected:
        return [
            "Memory correctness and governance integrity hard-gate compliance.",
        ]
    return detected


def json_dumps_compact(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
