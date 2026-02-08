from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import MutationConfig
from .io_utils import extract_json_payload, write_json
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

        prompt = self._build_prompt(
            epoch=epoch,
            baseline_summary=baseline_summary,
            recent_failures=recent_failures,
        )
        run = self.client.run_message(
            prompt,
            title=f"mutator-epoch-{epoch}",
            timeout_seconds=600,
        )

        raw_text = "\n".join(run.texts)
        payload = extract_json_payload(raw_text)
        if not isinstance(payload, dict):
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

        operations_payload = payload.get("operations", [])
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
            write_json(
                artifact_dir / "mutation-proposal-empty.json",
                {
                    "raw_text": raw_text,
                    "payload": payload,
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
            },
        )
        return proposal

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
        baseline_summary: dict[str, Any],
        recent_failures: list[dict[str, Any]],
    ) -> str:
        skill_manifest = "\n".join(f"- {path}" for path in self.skill_paths)
        contract = self.mutator_contract.format(
            skill_manifest=skill_manifest,
            allow_paths="\n".join(f"- {item}" for item in self.mutation_config.allow_paths),
            deny_paths="\n".join(f"- {item}" for item in self.mutation_config.deny_paths),
            max_operations=self.mutation_config.max_operations,
        )

        payload = {
            "epoch": epoch,
            "baseline_summary": baseline_summary,
            "recent_failures": recent_failures,
        }
        return f"{contract}\n\nMutation context:\n{json.dumps(payload, indent=2, ensure_ascii=True)}"

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
