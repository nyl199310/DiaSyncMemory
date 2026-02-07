#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


EVENT_SCHEMA_VERSION = "diasync-v1-event"
OBJECT_SCHEMA_VERSION = "diasync-v1-object"
FINDING_EVENT_SCHEMA_VERSION = "diasync-v1-finding-event"

OBJECT_TYPES = {"fact", "decision", "commitment"}
HORIZONS = {"now", "day", "week", "month", "quarter", "year"}
SALIENCE_LEVELS = {"low", "medium", "high"}
OBJECT_STATUSES = {"active", "completed", "cancelled", "superseded", "invalid"}
VISIBILITY_LEVELS = {"private", "project", "global"}

EVENT_TYPES = {
    "memory.instance.started",
    "memory.instance.heartbeat",
    "memory.instance.stopped",
    "memory.captured",
    "memory.distilled",
    "memory.published",
    "memory.reduced",
    "memory.reconciled",
    "memory.checkpointed",
    "memory.handoff",
}

VIEW_COLLECTIONS = {
    "fact": "facts",
    "decision": "decisions",
    "commitment": "commitments",
}

ID_PREFIXES = {
    "event": "evt",
    "run": "run",
    "instance": "ins",
    "fact": "fac",
    "decision": "dec",
    "commitment": "com",
    "agenda": "agd",
    "conflict": "cnf",
    "finding": "fdg",
    "plan": "pln",
    "execution": "exe",
    "lease": "les",
}

REQUIRED_DIRS = [
    "_meta",
    "streams",
    "bus",
    "views",
    "views/facts",
    "views/decisions",
    "views/commitments",
    "views/attach",
    "coordination",
    "projects",
    "governance",
    "governance/findings",
    "governance/health",
    "governance/actions",
    "index",
    "archive",
    "evidence",
]

TRACKED_JSONL_ZONES = [
    "streams",
    "bus",
    "views",
    "coordination",
    "governance",
]

DEFAULT_SPEC = {
    "name": "diasync-memory",
    "version": "3.1",
    "event_schema_version": EVENT_SCHEMA_VERSION,
    "object_schema_version": OBJECT_SCHEMA_VERSION,
    "formats": {"structured": "jsonl", "narrative": "markdown"},
    "collections": [
        "streams",
        "bus",
        "views",
        "coordination",
        "projects",
        "governance",
        "index",
        "archive",
        "evidence",
    ],
}

DEFAULT_POLICY = {
    "soft_triggers": {
        "attach": {
            "on_new_session": True,
            "entry_skill": "diasync-memory",
        },
        "capture": {
            "keywords": [
                "goal",
                "constraint",
                "preference",
                "risk",
                "dependency",
                "decision",
                "tradeoff",
            ]
        },
        "distill": {
            "stream_threshold": 20,
            "on_milestone": True,
            "on_scope_switch": True,
        },
        "recall": {
            "mode": "filesystem-free",
            "entry_skill": "diasync-memory",
            "preferred_tools": ["Read", "Grep", "Glob"],
        },
        "checkpoint": {
            "on_milestone": True,
            "before_context_compression": True,
            "on_strategy_change": True,
        },
        "diagnose": {
            "run_per_session": True,
            "run_after_hygiene": True,
        },
    },
    "governance": {
        "append_only": True,
        "supersedes_required_for_rewrites": True,
        "default_wip_limit": 3,
    },
    "health_weights": {
        "sync_lag": 20,
        "conflict_backlog": 20,
        "stale_leases": 15,
        "stale_instances": 15,
        "attach_coverage": 15,
        "view_freshness": 15,
    },
}

DEFAULT_EVENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DiaSync Memory Event",
    "type": "object",
    "required": [
        "schema_version",
        "event_id",
        "type",
        "scope",
        "instance_id",
        "run_id",
        "actor",
        "ts_wall",
        "lc",
        "causal_refs",
        "visibility",
        "owner",
        "payload",
        "idempotency_key",
        "hash",
    ],
}

DEFAULT_OBJECT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DiaSync Memory View Object",
    "type": "object",
    "required": [
        "schema_version",
        "id",
        "type",
        "scope",
        "ts",
        "summary",
        "status",
        "horizon",
        "salience",
        "confidence",
        "tags",
        "event_refs",
        "visibility",
        "owner",
        "hash",
    ],
}


class MemoryCtlError(Exception):
    pass


def print_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def parse_ymd(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def month_key(ts: str) -> str:
    return parse_iso(ts).strftime("%Y-%m")


def day_key(ts: str) -> str:
    return parse_iso(ts).strftime("%Y-%m-%d")


def to_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "default"


def scope_slug(scope: str) -> str:
    return to_slug(scope.replace(":", "-"))


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return unique([part.strip() for part in raw.split(",") if part.strip()])


def as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return unique(out)


def unique(items: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def make_id(kind: str) -> str:
    prefix = ID_PREFIXES[kind]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}-{stamp}-{suffix}"


def hash_object(payload: dict[str, Any], *, exclude: set[str] | None = None) -> str:
    ignore = exclude or set()
    body = {k: v for k, v in payload.items() if k not in ignore}
    data = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha1:" + hashlib.sha1(data).hexdigest()


def norm(path: Path) -> str:
    return path.as_posix()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    text = "\n".join(lines)
    if text:
        text += "\n"
    atomic_write(path, text)


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any] | None, str | None]]:
    with path.open("r", encoding="utf-8") as handle:
        for idx, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                yield idx, None, f"json decode error: {exc.msg}"
                continue
            if not isinstance(data, dict):
                yield idx, None, "line is not a JSON object"
                continue
            yield idx, data, None


def list_jsonl_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted([p for p in path.rglob("*.jsonl") if p.is_file()])


def stream_path(root: Path, scope: str, instance_id: str, ts: str) -> Path:
    return root / "streams" / scope_slug(scope) / to_slug(instance_id) / f"{day_key(ts)}.jsonl"


def bus_path(root: Path, scope: str, ts: str) -> Path:
    return root / "bus" / scope_slug(scope) / f"{day_key(ts)}.jsonl"


def view_path(root: Path, obj_type: str, scope: str, ts: str) -> Path:
    collection = VIEW_COLLECTIONS[obj_type]
    return root / "views" / collection / scope_slug(scope) / f"{month_key(ts)}.jsonl"


def project_state_path(root: Path, project: str) -> Path:
    return root / "projects" / to_slug(project) / "state.md"


def project_resume_path(root: Path, project: str) -> Path:
    return root / "projects" / to_slug(project) / "resume.md"


def project_agenda_path(root: Path, project: str) -> Path:
    return root / "projects" / to_slug(project) / "agenda.jsonl"


def ensure_project_files(root: Path, project: str) -> None:
    state = project_state_path(root, project)
    resume = project_resume_path(root, project)
    if not state.exists():
        atomic_write(
            state,
            "# Project State\n\n"
            "## Current Goal\n-\n\n"
            "## Current Stage\n-\n\n"
            "## Constraints\n-\n\n"
            "## Risks\n-\n\n"
            "## Next Action\n-\n\n"
            f"## Updated At\n- {now_iso()}\n",
        )
    if not resume.exists():
        atomic_write(
            resume,
            "# Project Resume\n\n"
            "## Last Session Summary\n-\n\n"
            "## Next Session First Action\n-\n\n"
            "## Open Risks\n-\n\n"
            "## Open Questions\n-\n\n"
            f"## Updated At\n- {now_iso()}\n",
        )


def ensure_store(root: Path, force: bool = False) -> dict[str, Any]:
    created_dirs: list[str] = []
    for relative in REQUIRED_DIRS:
        path = root / relative
        if not path.exists():
            created_dirs.append(relative)
        path.mkdir(parents=True, exist_ok=True)

    meta_payloads = {
        "_meta/spec.json": DEFAULT_SPEC,
        "_meta/policy.json": DEFAULT_POLICY,
        "_meta/event_schema.json": DEFAULT_EVENT_SCHEMA,
        "_meta/object_schema.json": DEFAULT_OBJECT_SCHEMA,
    }
    written_meta: list[str] = []
    for relative, payload in meta_payloads.items():
        path = root / relative
        if force or not path.exists():
            write_json(path, payload)
            written_meta.append(relative)

    gitkeep_targets = [
        "streams/.gitkeep",
        "bus/.gitkeep",
        "views/facts/.gitkeep",
        "views/decisions/.gitkeep",
        "views/commitments/.gitkeep",
        "views/attach/.gitkeep",
        "coordination/.gitkeep",
        "projects/.gitkeep",
        "governance/findings/.gitkeep",
        "governance/health/.gitkeep",
        "governance/actions/.gitkeep",
        "index/.gitkeep",
        "archive/.gitkeep",
        "evidence/.gitkeep",
    ]
    for relative in gitkeep_targets:
        path = root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    return {"created_dirs": created_dirs, "written_meta": written_meta}


def build_event(
    *,
    event_type: str,
    scope: str,
    instance_id: str,
    run_id: str,
    actor: str,
    payload: dict[str, Any],
    ts_wall: str,
    project: str,
    visibility: str,
    owner: str,
    lc: int = 0,
    causal_refs: list[str] | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise MemoryCtlError(f"unsupported event type: {event_type}")
    if visibility not in VISIBILITY_LEVELS:
        raise MemoryCtlError(f"unsupported visibility: {visibility}")
    if not scope.strip():
        raise MemoryCtlError("scope must not be empty")
    parse_iso(ts_wall)

    event: dict[str, Any] = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": event_id or make_id("event"),
        "type": event_type,
        "scope": scope,
        "instance_id": instance_id,
        "run_id": run_id,
        "actor": actor,
        "ts_wall": ts_wall,
        "lc": int(lc),
        "causal_refs": unique(causal_refs or []),
        "visibility": visibility,
        "owner": owner,
        "payload": payload,
    }
    if project:
        event["project"] = to_slug(project)
    event["idempotency_key"] = hash_object(event, exclude={"idempotency_key", "hash", "event_id"})
    event["hash"] = hash_object(event, exclude={"hash"})
    return event


def build_object(
    *,
    obj_type: str,
    scope: str,
    summary: str,
    ts: str,
    status: str,
    horizon: str,
    salience: str,
    confidence: float,
    tags: list[str],
    owner: str,
    visibility: str,
    project: str,
    source: list[str] | None = None,
    event_refs: list[str] | None = None,
    review_at: str | None = None,
    due_at: str | None = None,
    evidence_ref: str | None = None,
    supersedes: str | None = None,
    decision_key: str | None = None,
    why: str | None = None,
    assumptions: list[str] | None = None,
    object_id: str | None = None,
) -> dict[str, Any]:
    if obj_type not in OBJECT_TYPES:
        raise MemoryCtlError(f"unsupported object type: {obj_type}")
    if status not in OBJECT_STATUSES:
        raise MemoryCtlError(f"unsupported status: {status}")
    if horizon not in HORIZONS:
        raise MemoryCtlError(f"unsupported horizon: {horizon}")
    if salience not in SALIENCE_LEVELS:
        raise MemoryCtlError(f"unsupported salience: {salience}")
    if visibility not in VISIBILITY_LEVELS:
        raise MemoryCtlError(f"unsupported visibility: {visibility}")
    if not summary.strip():
        raise MemoryCtlError("summary must not be empty")
    parse_iso(ts)
    if review_at:
        parse_ymd(review_at)
    if due_at:
        parse_ymd(due_at)

    payload: dict[str, Any] = {
        "schema_version": OBJECT_SCHEMA_VERSION,
        "id": object_id or make_id(obj_type),
        "type": obj_type,
        "scope": scope,
        "ts": ts,
        "summary": summary.strip(),
        "status": status,
        "horizon": horizon,
        "salience": salience,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "tags": unique(tags),
        "event_refs": unique(event_refs or []),
        "visibility": visibility,
        "owner": owner,
    }
    if project:
        payload["project"] = to_slug(project)
    if source:
        payload["source"] = unique(source)
    if review_at:
        payload["review_at"] = review_at
    if due_at:
        payload["due_at"] = due_at
    if evidence_ref:
        payload["evidence_ref"] = evidence_ref
    if supersedes:
        payload["supersedes"] = supersedes
    if decision_key:
        payload["decision_key"] = decision_key
    if why:
        payload["why"] = why
    if assumptions:
        payload["assumptions"] = unique(assumptions)

    payload["hash"] = hash_object(payload, exclude={"hash"})
    return payload


def load_processed_ids(path: Path, key: str) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        value = data.get(key)
        if isinstance(value, str) and value:
            out.add(value)
    return out


def add_processed_id(path: Path, key: str, value: str) -> None:
    append_jsonl(path, {key: value, "ts": now_iso()})


def infer_type(summary: str, proposed: str) -> str:
    if proposed in OBJECT_TYPES:
        return proposed
    text = summary.lower()
    if any(word in text for word in ["decide", "decision", "tradeoff", "adopt", "choose"]):
        return "decision"
    if any(word in text for word in ["must", "next", "follow-up", "deadline", "due", "todo", "commit"]):
        return "commitment"
    return "fact"


def iter_events(root: Path, *, zone: str, scope: str | None = None, instance_id: str | None = None) -> Iterable[tuple[Path, int, dict[str, Any]]]:
    base = root / zone
    for path in list_jsonl_files(base):
        if scope and f"/{scope_slug(scope)}/" not in norm(path):
            continue
        if instance_id and f"/{to_slug(instance_id)}/" not in norm(path):
            continue
        for line_no, data, err in iter_jsonl(path):
            if err or not data:
                continue
            yield path, line_no, data


def iter_view_objects(root: Path, *, obj_type: str | None = None, scope: str | None = None) -> Iterable[tuple[Path, int, dict[str, Any]]]:
    base = root / "views"
    target_dirs: list[Path] = []
    if obj_type:
        target_dirs = [base / VIEW_COLLECTIONS[obj_type]]
    else:
        target_dirs = [base / "facts", base / "decisions", base / "commitments"]

    for directory in target_dirs:
        for path in list_jsonl_files(directory):
            if scope and f"/{scope_slug(scope)}/" not in norm(path):
                continue
            for line_no, data, err in iter_jsonl(path):
                if err or not data:
                    continue
                yield path, line_no, data


def find_object(root: Path, object_id: str) -> tuple[Path, dict[str, Any]] | None:
    for path, _, data in iter_view_objects(root):
        if data.get("id") == object_id:
            return path, data
    return None


def active_objects(
    root: Path,
    *,
    obj_type: str,
    scope: str | None = None,
    project: str | None = None,
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    superseded: set[str] = set()
    project_slug = to_slug(project) if project else None

    for _, _, data in iter_view_objects(root, obj_type=obj_type, scope=scope):
        if project_slug and data.get("project") != project_slug:
            continue
        all_items.append(data)
        supersedes = data.get("supersedes")
        if isinstance(supersedes, str) and supersedes:
            superseded.add(supersedes)

    out = [
        item
        for item in all_items
        if item.get("status") == "active" and isinstance(item.get("id"), str) and item.get("id") not in superseded
    ]
    out.sort(key=lambda x: str(x.get("ts", "")), reverse=True)
    return out


def find_active_decision_by_key(root: Path, scope: str, decision_key: str) -> dict[str, Any] | None:
    for item in active_objects(root, obj_type="decision", scope=scope):
        if item.get("decision_key") == decision_key:
            return item
    return None


def add_agenda_item(
    root: Path,
    *,
    project: str,
    summary: str,
    priority: str,
    due_at: str | None,
    tags: list[str],
    owner: str,
    item_id: str | None = None,
    origin: str = "manual",
) -> dict[str, Any]:
    if priority not in {"high", "medium", "low"}:
        raise MemoryCtlError("agenda priority must be high, medium, or low")
    if due_at:
        parse_ymd(due_at)
    item = {
        "id": item_id or make_id("agenda"),
        "summary": summary.strip(),
        "status": "active",
        "priority": priority,
        "owner": owner,
        "created_at": now_iso(),
        "tags": unique(tags),
        "origin": origin,
    }
    if due_at:
        item["due_at"] = due_at
    append_jsonl(project_agenda_path(root, project), {"op": "add", "ts": now_iso(), "item": item})
    return item


def reconstruct_agenda(path: Path) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return items
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        op = data.get("op")
        if op == "add":
            item = data.get("item")
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                items[item["id"]] = item
        elif op in {"close", "update"}:
            target = data.get("target_id")
            if isinstance(target, str) and target in items:
                if op == "close":
                    items[target]["status"] = data.get("status", "completed")
                    items[target]["closed_at"] = data.get("ts", now_iso())
                else:
                    patch = data.get("patch")
                    if isinstance(patch, dict):
                        items[target].update(patch)
    return items


def append_conflict(
    root: Path,
    *,
    scope: str,
    conflict_key: str,
    summary: str,
    evidence: list[str],
    recommendation: str,
    conflict_id: str | None = None,
) -> dict[str, Any]:
    record = {
        "schema_version": "diasync-v1-conflict-event",
        "op": "open",
        "conflict_id": conflict_id or make_id("conflict"),
        "scope": scope,
        "conflict_key": conflict_key,
        "summary": summary,
        "evidence": unique(evidence),
        "recommendation": recommendation,
        "ts": now_iso(),
    }
    record["hash"] = hash_object(record, exclude={"hash"})
    append_jsonl(root / "coordination" / "conflicts.jsonl", record)
    return record


def resolve_conflict(root: Path, conflict_id: str, reason: str) -> None:
    record = {
        "schema_version": "diasync-v1-conflict-event",
        "op": "resolve",
        "conflict_id": conflict_id,
        "reason": reason,
        "ts": now_iso(),
    }
    record["hash"] = hash_object(record, exclude={"hash"})
    append_jsonl(root / "coordination" / "conflicts.jsonl", record)


def open_conflicts(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "coordination" / "conflicts.jsonl"
    state: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return state
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        cid = data.get("conflict_id")
        if not isinstance(cid, str):
            continue
        op = data.get("op")
        if op == "open":
            state[cid] = data
        elif op == "resolve" and cid in state:
            del state[cid]
    return state


def active_leases(root: Path, now_ts: dt.datetime | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    path = root / "coordination" / "leases.jsonl"
    current: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return current
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        scope = data.get("scope")
        key = data.get("key")
        if not isinstance(scope, str) or not isinstance(key, str):
            continue
        token = (scope, key)
        op = data.get("op")
        if op == "acquire":
            current[token] = data
        elif op == "release" and token in current:
            del current[token]

    now_value = now_ts or dt.datetime.now(dt.timezone.utc)
    expired = []
    for token, lease in current.items():
        expires_at = lease.get("expires_at")
        if isinstance(expires_at, str):
            try:
                if parse_iso(expires_at) <= now_value:
                    expired.append(token)
            except ValueError:
                expired.append(token)
    for token in expired:
        del current[token]
    return current


def expired_unreleased_leases(root: Path) -> list[dict[str, Any]]:
    path = root / "coordination" / "leases.jsonl"
    if not path.exists():
        return []

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        scope = data.get("scope")
        key = data.get("key")
        if not isinstance(scope, str) or not isinstance(key, str):
            continue
        latest[(scope, key)] = data

    now_value = dt.datetime.now(dt.timezone.utc)
    out: list[dict[str, Any]] = []
    for data in latest.values():
        if data.get("op") != "acquire":
            continue
        expires = data.get("expires_at")
        if not isinstance(expires, str):
            continue
        try:
            expires_ts = parse_iso(expires)
        except ValueError:
            continue
        if expires_ts <= now_value:
            out.append(data)
    return out


def latest_instances(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "coordination" / "instances.jsonl"
    state: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return state
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        instance_id = data.get("instance_id")
        if isinstance(instance_id, str):
            state[instance_id] = data
    return state


def latest_cursors(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = root / "coordination" / "cursors.jsonl"
    state: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return state
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        instance_id = data.get("instance_id")
        scope = data.get("scope")
        if isinstance(instance_id, str) and isinstance(scope, str):
            state[(instance_id, scope)] = data
    return state


def latest_findings(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "governance" / "findings" / "findings.jsonl"
    state: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return state
    for _, data, err in iter_jsonl(path):
        if err or not data:
            continue
        finding_id = data.get("finding_id")
        if isinstance(finding_id, str):
            state[finding_id] = data
    return state


def open_findings(root: Path) -> dict[str, dict[str, Any]]:
    latest = latest_findings(root)
    return {fid: rec for fid, rec in latest.items() if rec.get("status") == "open"}


def open_findings_by_rule(root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rec in open_findings(root).values():
        rule = str(rec.get("rule_id", ""))
        scope = str(rec.get("scope", ""))
        project = str(rec.get("project", ""))
        out[(rule, scope, project)] = rec
    return out


def add_finding(
    root: Path,
    *,
    rule_id: str,
    severity: str,
    scope: str,
    project: str,
    summary: str,
    evidence: list[str],
    recommendation: str,
    metric: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "schema_version": FINDING_EVENT_SCHEMA_VERSION,
        "finding_id": make_id("finding"),
        "rule_id": rule_id,
        "severity": severity,
        "scope": scope,
        "project": project,
        "summary": summary,
        "evidence": unique(evidence),
        "recommendation": recommendation,
        "metric": metric,
        "status": "open",
        "ts": now_iso(),
    }
    record["hash"] = hash_object(record, exclude={"hash"})
    append_jsonl(root / "governance" / "findings" / "findings.jsonl", record)
    return record


def close_finding(root: Path, finding_id: str, reason: str) -> dict[str, Any]:
    record = {
        "schema_version": FINDING_EVENT_SCHEMA_VERSION,
        "finding_id": finding_id,
        "status": "closed",
        "reason": reason,
        "ts": now_iso(),
    }
    record["hash"] = hash_object(record, exclude={"hash"})
    append_jsonl(root / "governance" / "findings" / "findings.jsonl", record)
    return record


def rebuild_indexes(root: Path, *, dry_run: bool) -> dict[str, Any]:
    catalog_rows: list[dict[str, Any]] = []
    id_map_rows: list[dict[str, Any]] = []

    for zone in TRACKED_JSONL_ZONES:
        zone_path = root / zone
        for path in list_jsonl_files(zone_path):
            count = 0
            ts_min: str | None = None
            ts_max: str | None = None
            scope_hint: str | None = None

            for line_no, data, err in iter_jsonl(path):
                if err or not data:
                    continue
                count += 1
                ts = data.get("ts")
                if not isinstance(ts, str):
                    ts = data.get("ts_wall") if isinstance(data.get("ts_wall"), str) else None
                if ts:
                    ts_min = min(ts_min, ts) if ts_min else ts
                    ts_max = max(ts_max, ts) if ts_max else ts
                if not scope_hint and isinstance(data.get("scope"), str):
                    scope_hint = data.get("scope")
                if zone == "views" and isinstance(data.get("id"), str):
                    id_map_rows.append(
                        {
                            "id": data["id"],
                            "type": data.get("type"),
                            "scope": data.get("scope"),
                            "status": data.get("status"),
                            "path": norm(path.relative_to(root)),
                            "line": line_no,
                            "ts": data.get("ts"),
                        }
                    )

            if count:
                catalog_rows.append(
                    {
                        "zone": zone,
                        "path": norm(path.relative_to(root)),
                        "scope": scope_hint,
                        "count": count,
                        "ts_min": ts_min,
                        "ts_max": ts_max,
                    }
                )

    open_conflict_rows = [
        {
            "conflict_id": rec.get("conflict_id"),
            "scope": rec.get("scope"),
            "conflict_key": rec.get("conflict_key"),
            "summary": rec.get("summary"),
            "ts": rec.get("ts"),
        }
        for rec in open_conflicts(root).values()
    ]

    latest_instance_rows = []
    for instance_id, rec in latest_instances(root).items():
        latest_instance_rows.append(
            {
                "instance_id": instance_id,
                "event": rec.get("event"),
                "scope": rec.get("scope"),
                "project": rec.get("project"),
                "ts": rec.get("ts"),
            }
        )

    open_finding_rows = []
    for rec in open_findings(root).values():
        open_finding_rows.append(
            {
                "finding_id": rec.get("finding_id"),
                "rule_id": rec.get("rule_id"),
                "severity": rec.get("severity"),
                "scope": rec.get("scope"),
                "project": rec.get("project"),
                "ts": rec.get("ts"),
            }
        )

    catalog_rows.sort(key=lambda row: str(row.get("path", "")))
    id_map_rows.sort(key=lambda row: str(row.get("id", "")))
    latest_instance_rows.sort(key=lambda row: str(row.get("instance_id", "")))
    open_conflict_rows.sort(key=lambda row: str(row.get("conflict_id", "")))
    open_finding_rows.sort(key=lambda row: str(row.get("finding_id", "")))

    if not dry_run:
        index_dir = root / "index"
        write_jsonl(index_dir / "catalog.jsonl", catalog_rows)
        write_jsonl(index_dir / "id_map.jsonl", id_map_rows)
        write_jsonl(index_dir / "instances_active.jsonl", latest_instance_rows)
        write_jsonl(index_dir / "conflicts_open.jsonl", open_conflict_rows)
        write_jsonl(index_dir / "findings_open.jsonl", open_finding_rows)

    return {
        "catalog_entries": len(catalog_rows),
        "id_entries": len(id_map_rows),
        "instance_entries": len(latest_instance_rows),
        "open_conflicts": len(open_conflict_rows),
        "open_findings": len(open_finding_rows),
    }


def file_month_token(path: Path) -> str | None:
    stem = path.stem
    if re.fullmatch(r"\d{4}-\d{2}", stem):
        return stem
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stem):
        return stem[:7]
    if "-p" in stem:
        root = stem.split("-p", 1)[0]
        if re.fullmatch(r"\d{4}-\d{2}", root):
            return root
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", root):
            return root[:7]
    return None


def rotate_large_jsonl(root: Path, *, max_lines: int, dry_run: bool) -> list[dict[str, Any]]:
    if max_lines < 1:
        raise MemoryCtlError("--max-lines must be >= 1")
    rotated: list[dict[str, Any]] = []
    for zone in TRACKED_JSONL_ZONES:
        for path in list_jsonl_files(root / zone):
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(lines) <= max_lines:
                continue
            if "-p" in path.stem:
                continue
            chunks: list[str] = []
            total = (len(lines) + max_lines - 1) // max_lines
            for idx in range(total):
                chunk = lines[idx * max_lines : (idx + 1) * max_lines]
                part_path = path.with_name(f"{path.stem}-p{idx + 1:02d}.jsonl")
                chunks.append(norm(part_path))
                if not dry_run:
                    atomic_write(part_path, "\n".join(chunk) + "\n")
            if not dry_run:
                path.unlink()
            rotated.append({"source": norm(path), "parts": chunks})
    return rotated


def archive_old_jsonl(root: Path, *, archive_before: str, prune: bool, dry_run: bool) -> list[dict[str, Any]]:
    if not re.fullmatch(r"\d{4}-\d{2}", archive_before):
        raise MemoryCtlError("--archive-before must be YYYY-MM")
    archived: list[dict[str, Any]] = []
    for zone in TRACKED_JSONL_ZONES:
        base = root / zone
        for path in list_jsonl_files(base):
            token = file_month_token(path)
            if not token or token >= archive_before:
                continue
            rel = path.relative_to(base)
            target = (root / "archive" / zone / rel).with_suffix(path.suffix + ".gz")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not dry_run:
                with path.open("rb") as src, gzip.open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if prune:
                    path.unlink()
            archived.append({"source": norm(path), "target": norm(target), "pruned": bool(prune and not dry_run)})
    return archived


def validate_event(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "schema_version",
        "event_id",
        "type",
        "scope",
        "instance_id",
        "run_id",
        "actor",
        "ts_wall",
        "lc",
        "causal_refs",
        "visibility",
        "owner",
        "payload",
        "idempotency_key",
        "hash",
    ]
    for key in required:
        if key not in data:
            errors.append(f"missing field: {key}")

    if data.get("schema_version") != EVENT_SCHEMA_VERSION:
        errors.append("invalid schema_version")
    event_type = data.get("type")
    if event_type not in EVENT_TYPES:
        errors.append(f"invalid event type: {event_type}")
    visibility = data.get("visibility")
    if visibility not in VISIBILITY_LEVELS:
        errors.append(f"invalid visibility: {visibility}")
    if not isinstance(data.get("payload"), dict):
        errors.append("payload must be object")
    if not isinstance(data.get("causal_refs"), list):
        errors.append("causal_refs must be array")
    if not isinstance(data.get("lc"), int):
        errors.append("lc must be integer")
    ts = data.get("ts_wall")
    if isinstance(ts, str):
        try:
            parse_iso(ts)
        except ValueError:
            errors.append("ts_wall must be ISO timestamp")
    else:
        errors.append("ts_wall must be string")

    expected = hash_object(data, exclude={"hash"})
    if data.get("hash") != expected:
        errors.append("hash mismatch")

    return errors


def validate_object(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "schema_version",
        "id",
        "type",
        "scope",
        "ts",
        "summary",
        "status",
        "horizon",
        "salience",
        "confidence",
        "tags",
        "event_refs",
        "visibility",
        "owner",
        "hash",
    ]
    for key in required:
        if key not in data:
            errors.append(f"missing field: {key}")

    if data.get("schema_version") != OBJECT_SCHEMA_VERSION:
        errors.append("invalid schema_version")
    obj_type = data.get("type")
    if obj_type not in OBJECT_TYPES:
        errors.append(f"invalid type: {obj_type}")
    if data.get("status") not in OBJECT_STATUSES:
        errors.append(f"invalid status: {data.get('status')}")
    if data.get("horizon") not in HORIZONS:
        errors.append(f"invalid horizon: {data.get('horizon')}")
    if data.get("salience") not in SALIENCE_LEVELS:
        errors.append(f"invalid salience: {data.get('salience')}")
    if data.get("visibility") not in VISIBILITY_LEVELS:
        errors.append(f"invalid visibility: {data.get('visibility')}")
    if not isinstance(data.get("tags"), list):
        errors.append("tags must be array")
    if not isinstance(data.get("event_refs"), list):
        errors.append("event_refs must be array")
    try:
        confidence_raw = data.get("confidence", 0.0)
        if confidence_raw is None:
            confidence_raw = 0.0
        confidence = float(confidence_raw)
        if confidence < 0 or confidence > 1:
            errors.append("confidence out of range")
    except (TypeError, ValueError):
        errors.append("invalid confidence")

    ts = data.get("ts")
    if isinstance(ts, str):
        try:
            parse_iso(ts)
        except ValueError:
            errors.append("ts must be ISO timestamp")
    else:
        errors.append("ts must be string")

    if isinstance(data.get("review_at"), str):
        try:
            parse_ymd(str(data.get("review_at")))
        except ValueError:
            errors.append("review_at must be YYYY-MM-DD")
    if isinstance(data.get("due_at"), str):
        try:
            parse_ymd(str(data.get("due_at")))
        except ValueError:
            errors.append("due_at must be YYYY-MM-DD")

    expected = hash_object(data, exclude={"hash"})
    if data.get("hash") != expected:
        errors.append("hash mismatch")

    return errors


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    result = ensure_store(root, force=args.force)
    print_json({"ok": True, "root": norm(root), **result})
    return 0


def command_sync(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    scope = args.scope or "global"
    project = to_slug(args.project) if args.project else ""
    run_id = args.run_id or make_id("run")
    ts = now_iso()

    if args.action == "start":
        event_name = "memory.instance.started"
    elif args.action == "heartbeat":
        event_name = "memory.instance.heartbeat"
    else:
        event_name = "memory.instance.stopped"

    event = {
        "schema_version": "diasync-v1-instance-event",
        "event": event_name,
        "instance_id": to_slug(args.instance_id),
        "run_id": run_id,
        "scope": scope,
        "project": project,
        "note": args.note or "",
        "ts": ts,
    }
    event["hash"] = hash_object(event, exclude={"hash"})
    if not args.dry_run:
        append_jsonl(root / "coordination" / "instances.jsonl", event)

        if args.action == "start":
            bus_event_count = 0
            for _, _, data in iter_events(root, zone="bus", scope=scope):
                if data.get("type") == "memory.published":
                    bus_event_count += 1
            append_jsonl(
                root / "coordination" / "cursors.jsonl",
                {
                    "schema_version": "diasync-v1-cursor-event",
                    "op": "set",
                    "instance_id": to_slug(args.instance_id),
                    "scope": scope,
                    "cursor": bus_event_count,
                    "ts": ts,
                },
            )

        if args.action == "stop":
            for (_, _), lease in active_leases(root).items():
                if lease.get("instance_id") == to_slug(args.instance_id):
                    append_jsonl(
                        root / "coordination" / "leases.jsonl",
                        {
                            "schema_version": "diasync-v1-lease-event",
                            "op": "release",
                            "lease_id": lease.get("lease_id"),
                            "scope": lease.get("scope"),
                            "key": lease.get("key"),
                            "instance_id": to_slug(args.instance_id),
                            "released_at": ts,
                            "ts": ts,
                        },
                    )

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "action": args.action,
            "instance_id": to_slug(args.instance_id),
            "run_id": run_id,
            "scope": scope,
            "project": project,
        }
    )
    return 0


def command_attach(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    if not args.dry_run:
        ensure_project_files(root, args.project)

    project = to_slug(args.project)
    scope = args.scope or f"project:{project}"
    state_path = project_state_path(root, project)
    resume_path = project_resume_path(root, project)
    attach_path = root / "views" / "attach" / f"{project}.md"

    state_text = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
    resume_text = resume_path.read_text(encoding="utf-8") if resume_path.exists() else ""

    decisions = active_objects(root, obj_type="decision", scope=scope, project=project)[: args.top_decisions]
    commitments = active_objects(root, obj_type="commitment", scope=scope, project=project)[: args.top_commitments]

    lines: list[str] = []
    lines.append(f"# Attach Capsule: {project}")
    lines.append("")
    lines.append(f"- Generated at: {now_iso()}")
    lines.append(f"- Scope: {scope}")
    lines.append("")
    lines.append("## Resume")
    lines.append(resume_text.strip() or "- No resume available.")
    lines.append("")
    lines.append("## State")
    lines.append(state_text.strip() or "- No state available.")
    lines.append("")
    lines.append("## Active Decisions")
    if decisions:
        for item in decisions:
            lines.append(f"- {item.get('id')}: {item.get('summary')}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Active Commitments")
    if commitments:
        for item in commitments:
            due = item.get("due_at", "no due date")
            lines.append(f"- {item.get('id')} ({due}): {item.get('summary')}")
    else:
        lines.append("- None")

    capsule = "\n".join(lines) + "\n"

    if not args.dry_run:
        atomic_write(attach_path, capsule)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "project": project,
            "scope": scope,
            "attach_path": norm(attach_path),
            "decision_count": len(decisions),
            "commitment_count": len(commitments),
            "capsule": capsule,
        }
    )
    return 0


def command_capture(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    scope = args.scope
    project = infer_project(scope, args.project)
    instance_id = to_slug(args.instance_id or "instance-unknown")
    run_id = args.run_id or make_id("run")
    ts = args.ts or now_iso()
    parse_iso(ts)

    proposed = args.proposed_type if args.proposed_type in OBJECT_TYPES else "fact"

    payload: dict[str, Any] = {
        "summary": args.summary,
        "proposed_type": proposed,
        "horizon": args.horizon,
        "salience": args.salience,
        "confidence": max(0.0, min(1.0, args.confidence)),
        "tags": parse_csv(args.tags),
        "source": parse_csv(args.source),
    }
    if args.review_at:
        parse_ymd(args.review_at)
        payload["review_at"] = args.review_at
    if args.due_at:
        parse_ymd(args.due_at)
        payload["due_at"] = args.due_at
    if args.evidence_ref:
        payload["evidence_ref"] = args.evidence_ref
    if args.why:
        payload["why"] = args.why
    assumptions = parse_csv(args.assumptions)
    if assumptions:
        payload["assumptions"] = assumptions
    if args.decision_key:
        payload["decision_key"] = args.decision_key

    event = build_event(
        event_type="memory.captured",
        scope=scope,
        instance_id=instance_id,
        run_id=run_id,
        actor="agent",
        payload=payload,
        ts_wall=ts,
        project=project,
        visibility=args.visibility,
        owner=instance_id,
    )

    path = stream_path(root, scope, instance_id, ts)
    if not args.dry_run:
        append_jsonl(path, event)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "event_id": event["event_id"],
            "scope": scope,
            "instance_id": instance_id,
            "run_id": run_id,
            "path": norm(path),
            "proposed_type": proposed,
        }
    )
    return 0


def infer_project(scope: str, project: str | None) -> str:
    if project:
        return to_slug(project)
    if scope.startswith("project:"):
        return to_slug(scope.split(":", 1)[1])
    return ""


def command_distill(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    processed_path = root / "_meta" / "distilled_event_ids.jsonl"
    processed = load_processed_ids(processed_path, "event_id")

    created: list[dict[str, Any]] = []
    scanned = 0

    for path, _, event in iter_events(root, zone="streams", scope=args.scope, instance_id=args.instance_id):
        if event.get("type") != "memory.captured":
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or event_id in processed:
            continue
        scanned += 1
        if len(created) >= args.limit:
            break

        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        summary = str(payload.get("summary", "")).strip()
        scope = str(event.get("scope", "")).strip()
        if not summary or not scope:
            continue

        proposed = str(payload.get("proposed_type", "fact"))
        obj_type = infer_type(summary, proposed)
        obj_ts = now_iso()

        obj = build_object(
            obj_type=obj_type,
            scope=scope,
            summary=summary,
            ts=obj_ts,
            status="active",
            horizon=str(payload.get("horizon", "day")),
            salience=str(payload.get("salience", "medium")),
            confidence=float(payload.get("confidence", 0.7)),
            tags=as_str_list(payload.get("tags")),
            owner=str(event.get("owner", event.get("instance_id", "agent"))),
            visibility=str(event.get("visibility", "project")),
            project=str(event.get("project", "")),
            source=as_str_list(payload.get("source")) + [f"stream:{norm(path.relative_to(root))}"],
            event_refs=[event_id],
            review_at=str(payload.get("review_at", "")) or None,
            due_at=str(payload.get("due_at", "")) or None,
            evidence_ref=str(payload.get("evidence_ref", "")) or None,
            decision_key=str(payload.get("decision_key", "")) or None,
            why=str(payload.get("why", "")) or None,
            assumptions=as_str_list(payload.get("assumptions")),
        )

        out_path = view_path(root, obj_type, scope, obj_ts)
        if not args.dry_run:
            append_jsonl(out_path, obj)
            add_processed_id(processed_path, "event_id", event_id)
            if obj_type == "commitment" and obj.get("project"):
                add_agenda_item(
                    root,
                    project=str(obj.get("project")),
                    summary=str(obj.get("summary")),
                    priority="medium",
                    due_at=obj.get("due_at") if isinstance(obj.get("due_at"), str) else None,
                    tags=as_str_list(obj.get("tags")),
                    owner=str(obj.get("owner", "agent")),
                    item_id=str(obj.get("id")),
                    origin="distill",
                )
            reduce_event = build_event(
                event_type="memory.distilled",
                scope=scope,
                instance_id=str(event.get("instance_id", "instance-unknown")),
                run_id=str(event.get("run_id", make_id("run"))),
                actor="agent",
                payload={"source_event_id": event_id, "target_object_id": obj.get("id"), "target_type": obj_type},
                ts_wall=now_iso(),
                project=str(event.get("project", "")),
                visibility="project",
                owner=str(event.get("owner", "agent")),
                causal_refs=[event_id],
            )
            append_jsonl(stream_path(root, scope, str(event.get("instance_id", "instance-unknown")), now_iso()), reduce_event)

        created.append(
            {
                "event_id": event_id,
                "object_id": obj.get("id"),
                "object_type": obj_type,
                "path": norm(out_path),
            }
        )

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "scanned": scanned,
            "created_count": len(created),
            "created": created,
        }
    )
    return 0


def command_publish(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    scope = args.scope
    project = infer_project(scope, args.project)
    instance_id = to_slug(args.instance_id or "instance-unknown")
    run_id = args.run_id or make_id("run")
    ts = now_iso()

    payload: dict[str, Any] = {
        "summary": args.summary,
        "object_type": args.object_type,
        "horizon": args.horizon,
        "salience": args.salience,
        "confidence": max(0.0, min(1.0, args.confidence)),
        "tags": parse_csv(args.tags),
    }
    if args.review_at:
        parse_ymd(args.review_at)
        payload["review_at"] = args.review_at
    if args.due_at:
        parse_ymd(args.due_at)
        payload["due_at"] = args.due_at
    if args.evidence_ref:
        payload["evidence_ref"] = args.evidence_ref
    if args.why:
        payload["why"] = args.why
    if args.decision_key:
        payload["decision_key"] = args.decision_key

    event = build_event(
        event_type="memory.published",
        scope=scope,
        instance_id=instance_id,
        run_id=run_id,
        actor="agent",
        payload=payload,
        ts_wall=ts,
        project=project,
        visibility=args.visibility,
        owner=instance_id,
    )
    out_path = bus_path(root, scope, ts)

    if not args.dry_run:
        append_jsonl(out_path, event)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "event_id": event.get("event_id"),
            "path": norm(out_path),
            "scope": scope,
            "project": project,
        }
    )
    return 0


def command_reduce(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    processed_path = root / "_meta" / "reduced_event_ids.jsonl"
    processed = load_processed_ids(processed_path, "event_id")

    created: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    scanned = 0

    for path, _, event in iter_events(root, zone="bus", scope=args.scope):
        if event.get("type") != "memory.published":
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or event_id in processed:
            continue
        scanned += 1
        if len(created) + len(conflicts) >= args.limit:
            break

        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue

        summary = str(payload.get("summary", "")).strip()
        scope = str(event.get("scope", "")).strip()
        obj_type = str(payload.get("object_type", "fact"))
        if obj_type not in OBJECT_TYPES:
            obj_type = infer_type(summary, "fact")
        if not summary or not scope:
            continue

        decision_key = str(payload.get("decision_key", "")) or None
        if obj_type == "decision" and decision_key:
            existing = find_active_decision_by_key(root, scope, decision_key)
            if existing and existing.get("summary") != summary:
                conflict = append_conflict(
                    root,
                    scope=scope,
                    conflict_key=f"decision:{decision_key}",
                    summary=f"Concurrent decision collision on key '{decision_key}'",
                    evidence=[str(existing.get("id")), event_id, norm(path.relative_to(root))],
                    recommendation="Run memory-reconcile with explicit tradeoff and supersedes chain.",
                )
                conflicts.append(conflict)
                if not args.dry_run:
                    add_processed_id(processed_path, "event_id", event_id)
                continue

        obj_ts = now_iso()
        obj = build_object(
            obj_type=obj_type,
            scope=scope,
            summary=summary,
            ts=obj_ts,
            status="active",
            horizon=str(payload.get("horizon", "week")),
            salience=str(payload.get("salience", "medium")),
            confidence=float(payload.get("confidence", 0.7)),
            tags=as_str_list(payload.get("tags")),
            owner=str(event.get("owner", event.get("instance_id", "agent"))),
            visibility=str(event.get("visibility", "project")),
            project=str(event.get("project", "")),
            source=[f"bus:{norm(path.relative_to(root))}"],
            event_refs=[event_id],
            review_at=str(payload.get("review_at", "")) or None,
            due_at=str(payload.get("due_at", "")) or None,
            evidence_ref=str(payload.get("evidence_ref", "")) or None,
            decision_key=decision_key,
            why=str(payload.get("why", "")) or None,
        )

        out_path = view_path(root, obj_type, scope, obj_ts)
        if not args.dry_run:
            append_jsonl(out_path, obj)
            add_processed_id(processed_path, "event_id", event_id)
            append_jsonl(
                root / "coordination" / "reducers.jsonl",
                {
                    "schema_version": "diasync-v1-reducer-event",
                    "op": "reduce",
                    "event_id": event_id,
                    "object_id": obj.get("id"),
                    "scope": scope,
                    "type": obj_type,
                    "ts": now_iso(),
                },
            )
            if obj_type == "commitment" and obj.get("project"):
                add_agenda_item(
                    root,
                    project=str(obj.get("project")),
                    summary=str(obj.get("summary")),
                    priority="medium",
                    due_at=obj.get("due_at") if isinstance(obj.get("due_at"), str) else None,
                    tags=as_str_list(obj.get("tags")),
                    owner=str(obj.get("owner", "agent")),
                    item_id=str(obj.get("id")),
                    origin="reduce",
                )

        created.append(
            {
                "event_id": event_id,
                "object_id": obj.get("id"),
                "object_type": obj_type,
                "path": norm(out_path),
            }
        )

    index_stats: dict[str, Any] = {}
    if args.reindex:
        index_stats = rebuild_indexes(root, dry_run=args.dry_run)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "scanned": scanned,
            "created_count": len(created),
            "conflict_count": len(conflicts),
            "created": created,
            "conflicts": conflicts,
            "index": index_stats,
        }
    )
    return 0


def command_lease(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    if args.action == "list":
        leases = list(active_leases(root).values())
        if args.scope:
            leases = [lease for lease in leases if lease.get("scope") == args.scope]
        print_json({"ok": True, "action": "list", "count": len(leases), "leases": leases})
        return 0

    if not args.instance_id:
        raise MemoryCtlError("--instance-id is required for acquire/release")
    instance_id = to_slug(args.instance_id)
    scope = args.scope or "global"
    key = args.key
    if not key:
        raise MemoryCtlError("--key is required for acquire/release")

    now_value = dt.datetime.now(dt.timezone.utc)
    active = active_leases(root, now_ts=now_value)
    token = (scope, key)

    if args.action == "acquire":
        current = active.get(token)
        if current and current.get("instance_id") != instance_id:
            raise MemoryCtlError(
                f"lease is already held by {current.get('instance_id')} until {current.get('expires_at')}"
            )

        lease = {
            "schema_version": "diasync-v1-lease-event",
            "op": "acquire",
            "lease_id": make_id("lease"),
            "scope": scope,
            "key": key,
            "instance_id": instance_id,
            "acquired_at": now_iso(),
            "expires_at": (
                now_value + dt.timedelta(seconds=max(1, int(args.ttl_seconds)))
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "ts": now_iso(),
        }
        lease["hash"] = hash_object(lease, exclude={"hash"})
        if not args.dry_run:
            append_jsonl(root / "coordination" / "leases.jsonl", lease)
        print_json({"ok": True, "action": "acquire", "dry_run": args.dry_run, "lease": lease})
        return 0

    current = active.get(token)
    if current and current.get("instance_id") != instance_id:
        raise MemoryCtlError(f"cannot release lease owned by {current.get('instance_id')}")

    release = {
        "schema_version": "diasync-v1-lease-event",
        "op": "release",
        "lease_id": current.get("lease_id") if current else None,
        "scope": scope,
        "key": key,
        "instance_id": instance_id,
        "released_at": now_iso(),
        "ts": now_iso(),
    }
    release["hash"] = hash_object(release, exclude={"hash"})
    if not args.dry_run:
        append_jsonl(root / "coordination" / "leases.jsonl", release)
    print_json({"ok": True, "action": "release", "dry_run": args.dry_run, "release": release})
    return 0


def command_reconcile(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    located = find_object(root, args.id)
    if not located:
        raise MemoryCtlError(f"object not found: {args.id}")
    path, base = located

    tags = parse_csv(args.tags) or as_str_list(base.get("tags"))
    assumptions = parse_csv(args.assumptions) or as_str_list(base.get("assumptions"))
    event_refs = as_str_list(base.get("event_refs")) + [f"reconcile:{args.id}"]

    ts = now_iso()
    obj = build_object(
        obj_type=str(base.get("type")),
        scope=str(base.get("scope")),
        summary=args.summary,
        ts=ts,
        status="active",
        horizon=args.horizon or str(base.get("horizon", "week")),
        salience=args.salience or str(base.get("salience", "medium")),
        confidence=args.confidence if args.confidence is not None else float(base.get("confidence", 0.7)),
        tags=tags,
        owner=str(base.get("owner", "agent")),
        visibility=str(base.get("visibility", "project")),
        project=str(base.get("project", "")),
        source=as_str_list(base.get("source")),
        event_refs=event_refs,
        review_at=args.review_at or (str(base.get("review_at")) if isinstance(base.get("review_at"), str) else None),
        due_at=str(base.get("due_at")) if isinstance(base.get("due_at"), str) else None,
        evidence_ref=args.evidence_ref or (str(base.get("evidence_ref")) if isinstance(base.get("evidence_ref"), str) else None),
        supersedes=args.id,
        decision_key=args.decision_key
        or (str(base.get("decision_key")) if isinstance(base.get("decision_key"), str) else None),
        why=args.why or (str(base.get("why")) if isinstance(base.get("why"), str) else None),
        assumptions=assumptions,
    )

    out_path = view_path(root, str(base.get("type")), str(base.get("scope")), ts)
    if not args.dry_run:
        append_jsonl(out_path, obj)
        if args.resolve_conflict:
            resolve_conflict(root, args.resolve_conflict, reason="resolved by reconcile")
        if obj.get("type") == "commitment" and obj.get("project"):
            add_agenda_item(
                root,
                project=str(obj.get("project")),
                summary=str(obj.get("summary")),
                priority="high",
                due_at=obj.get("due_at") if isinstance(obj.get("due_at"), str) else None,
                tags=as_str_list(obj.get("tags")),
                owner=str(obj.get("owner", "agent")),
                item_id=str(obj.get("id")),
                origin="reconcile",
            )

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "supersedes": args.id,
            "new_id": obj.get("id"),
            "path": norm(out_path),
        }
    )
    return 0


def command_checkpoint(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    if not args.dry_run:
        ensure_project_files(root, args.project)

    project = to_slug(args.project)
    scope = args.scope or f"project:{project}"
    instance_id = to_slug(args.instance_id or "instance-unknown")
    run_id = args.run_id or make_id("run")
    ts = now_iso()

    now_text = args.now or "-"
    next_text = args.next or "-"
    risks = parse_csv(args.risks)
    decision_ids = parse_csv(args.decisions)
    commitment_ids = parse_csv(args.commitments)

    state_lines = [
        f"# Project State: {project}",
        "",
        f"## Updated At\n- {ts}",
        "",
        "## Now",
        f"- {now_text}",
        "",
        "## Next",
        f"- {next_text}",
        "",
        "## Risks",
    ]
    state_lines.extend([f"- {risk}" for risk in risks] or ["-"])
    state_lines.append("")
    state_lines.append("## Active Decision IDs")
    state_lines.extend([f"- {item}" for item in decision_ids] or ["-"])
    state_lines.append("")
    state_lines.append("## Active Commitment IDs")
    state_lines.extend([f"- {item}" for item in commitment_ids] or ["-"])
    state_lines.append("")
    state_lines.append("## Source")
    state_lines.append(f"- instance: {instance_id}")
    state_lines.append(f"- run: {run_id}")

    state_text = "\n".join(state_lines) + "\n"
    state_file = project_state_path(root, project)

    event = build_event(
        event_type="memory.checkpointed",
        scope=scope,
        instance_id=instance_id,
        run_id=run_id,
        actor="agent",
        payload={
            "now": now_text,
            "next": next_text,
            "risks": risks,
            "decision_ids": decision_ids,
            "commitment_ids": commitment_ids,
            "project": project,
        },
        ts_wall=ts,
        project=project,
        visibility="project",
        owner=instance_id,
    )

    if not args.dry_run:
        atomic_write(state_file, state_text)
        append_jsonl(stream_path(root, scope, instance_id, ts), event)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "project": project,
            "scope": scope,
            "state_path": norm(state_file),
            "event_id": event.get("event_id"),
        }
    )
    return 0


def command_handoff(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    if not args.dry_run:
        ensure_project_files(root, args.project)

    project = to_slug(args.project)
    scope = args.scope or f"project:{project}"
    instance_id = to_slug(args.instance_id or "instance-unknown")
    run_id = args.run_id or make_id("run")
    ts = now_iso()

    next_actions = parse_csv(args.next_actions)
    risks = parse_csv(args.risks)
    questions = parse_csv(args.open_questions)

    lines = [
        f"# Project Resume: {project}",
        "",
        f"## Updated At\n- {ts}",
        "",
        "## Last Session Summary",
        f"- {args.summary.strip()}",
        "",
        "## Next Session First Action",
    ]
    lines.extend([f"- {item}" for item in next_actions] or ["-"])
    lines.append("")
    lines.append("## Open Risks")
    lines.extend([f"- {item}" for item in risks] or ["-"])
    lines.append("")
    lines.append("## Open Questions")
    lines.extend([f"- {item}" for item in questions] or ["-"])
    lines.append("")
    lines.append("## Source")
    lines.append(f"- instance: {instance_id}")
    lines.append(f"- run: {run_id}")

    resume_text = "\n".join(lines) + "\n"
    resume_file = project_resume_path(root, project)

    event = build_event(
        event_type="memory.handoff",
        scope=scope,
        instance_id=instance_id,
        run_id=run_id,
        actor="agent",
        payload={
            "summary": args.summary,
            "next_actions": next_actions,
            "risks": risks,
            "open_questions": questions,
            "project": project,
        },
        ts_wall=ts,
        project=project,
        visibility="project",
        owner=instance_id,
    )

    if not args.dry_run:
        atomic_write(resume_file, resume_text)
        append_jsonl(stream_path(root, scope, instance_id, ts), event)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "project": project,
            "resume_path": norm(resume_file),
            "event_id": event.get("event_id"),
        }
    )
    return 0


def command_agenda(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    project = to_slug(args.project)
    ensure_project_files(root, project)
    path = project_agenda_path(root, project)

    actions = int(bool(args.add)) + int(bool(args.list)) + int(bool(args.close)) + int(bool(args.update))
    if actions != 1:
        raise MemoryCtlError("agenda requires exactly one action: --add, --list, --close, or --update")

    if args.add:
        item = add_agenda_item(
            root,
            project=project,
            summary=args.add,
            priority=args.priority,
            due_at=args.due_at,
            tags=parse_csv(args.tags),
            owner=to_slug(args.owner or "agent"),
            origin="manual",
        )
        print_json({"ok": True, "action": "add", "path": norm(path), "item": item})
        return 0

    if args.close:
        if args.status not in {"active", "completed", "cancelled"}:
            raise MemoryCtlError("--status must be active, completed, or cancelled")
        event = {
            "op": "close",
            "ts": now_iso(),
            "target_id": args.close,
            "status": args.status,
        }
        append_jsonl(path, event)
        print_json({"ok": True, "action": "close", "path": norm(path), "target_id": args.close})
        return 0

    if args.update:
        patch: dict[str, Any] = {}
        if args.summary:
            patch["summary"] = args.summary
        if args.priority:
            patch["priority"] = args.priority
        if args.due_at:
            parse_ymd(args.due_at)
            patch["due_at"] = args.due_at
        if args.tags:
            patch["tags"] = parse_csv(args.tags)
        if args.owner:
            patch["owner"] = to_slug(args.owner)
        append_jsonl(path, {"op": "update", "ts": now_iso(), "target_id": args.update, "patch": patch})
        print_json({"ok": True, "action": "update", "path": norm(path), "target_id": args.update, "patch": patch})
        return 0

    items = list(reconstruct_agenda(path).values())
    if args.status_filter:
        items = [item for item in items if item.get("status") == args.status_filter]
    items.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(str(item.get("priority", "medium")), 1),
            str(item.get("due_at", "9999-12-31")),
            str(item.get("created_at", "")),
        )
    )
    print_json({"ok": True, "action": "list", "path": norm(path), "count": len(items), "items": items})
    return 0


def command_hygiene(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    if not args.reindex and not args.rotate and not args.archive_before:
        args.reindex = True

    rotated: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []
    index_stats: dict[str, Any] = {}

    if args.rotate:
        rotated = rotate_large_jsonl(root, max_lines=args.max_lines, dry_run=args.dry_run)
    if args.archive_before:
        archived = archive_old_jsonl(
            root,
            archive_before=args.archive_before,
            prune=args.prune,
            dry_run=args.dry_run,
        )
    if args.reindex:
        index_stats = rebuild_indexes(root, dry_run=args.dry_run)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "rotated": rotated,
            "archived": archived,
            "index": index_stats,
        }
    )
    return 0


def command_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED_DIRS:
        if not (root / relative).exists():
            errors.append(f"missing required directory: {relative}")

    for relative in ["_meta/spec.json", "_meta/policy.json", "_meta/event_schema.json", "_meta/object_schema.json"]:
        path = root / relative
        if not path.exists():
            errors.append(f"missing required meta file: {relative}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON in {relative}: {exc.msg}")

    all_object_ids: dict[str, str] = {}
    supersedes_refs: list[tuple[str, str]] = []

    for zone in ["streams", "bus"]:
        for path in list_jsonl_files(root / zone):
            rel = norm(path.relative_to(root))
            for line_no, data, err in iter_jsonl(path):
                if err:
                    errors.append(f"{rel}:{line_no}: {err}")
                    continue
                if not data:
                    continue
                for issue in validate_event(data):
                    errors.append(f"{rel}:{line_no}: {issue}")

    for path in list_jsonl_files(root / "views"):
        rel = norm(path.relative_to(root))
        for line_no, data, err in iter_jsonl(path):
            if err:
                errors.append(f"{rel}:{line_no}: {err}")
                continue
            if not data:
                continue
            for issue in validate_object(data):
                errors.append(f"{rel}:{line_no}: {issue}")

            object_id = data.get("id")
            if isinstance(object_id, str):
                if object_id in all_object_ids:
                    errors.append(f"duplicate object id {object_id}: {all_object_ids[object_id]} and {rel}:{line_no}")
                else:
                    all_object_ids[object_id] = f"{rel}:{line_no}"

            supersedes = data.get("supersedes")
            if isinstance(supersedes, str) and supersedes:
                supersedes_refs.append((str(data.get("id")), supersedes))

            evidence_ref = data.get("evidence_ref")
            if isinstance(evidence_ref, str) and evidence_ref:
                evidence_path = root / evidence_ref
                if not evidence_path.exists():
                    warnings.append(f"missing evidence_ref for {object_id}: {evidence_ref}")

    for zone in ["coordination", "governance"]:
        for path in list_jsonl_files(root / zone):
            rel = norm(path.relative_to(root))
            for line_no, data, err in iter_jsonl(path):
                if err:
                    errors.append(f"{rel}:{line_no}: {err}")
                    continue
                if not data:
                    continue
                if "hash" in data:
                    expected = hash_object(data, exclude={"hash"})
                    if data.get("hash") != expected:
                        errors.append(f"{rel}:{line_no}: hash mismatch")

    for source, target in supersedes_refs:
        if target not in all_object_ids:
            warnings.append(f"supersedes target missing: {source} -> {target}")

    # Lease checks
    for lease in expired_unreleased_leases(root):
        warnings.append(
            f"stale lease: scope={lease.get('scope')} key={lease.get('key')} instance={lease.get('instance_id')}"
        )

    # Decision key collision checks
    collisions: Counter[tuple[str, str]] = Counter()
    for item in active_objects(root, obj_type="decision"):
        scope = str(item.get("scope", ""))
        key = str(item.get("decision_key", ""))
        if scope and key:
            collisions[(scope, key)] += 1
    for (scope, key), count in collisions.items():
        if count > 1:
            warnings.append(f"duplicate active decision_key: scope={scope} key={key} count={count}")

    ok = not errors and (not args.strict or not warnings)
    print_json(
        {
            "ok": ok,
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
        }
    )
    return 0 if ok else 1


def command_diagnose(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)
    now_value = dt.datetime.now(dt.timezone.utc)

    stale_threshold = max(60, int(args.stale_seconds))
    latest_instance = latest_instances(root)
    active_instance_records: list[dict[str, Any]] = []
    stale_instances: list[dict[str, Any]] = []
    for rec in latest_instance.values():
        event_name = rec.get("event")
        if event_name == "memory.instance.stopped":
            continue
        active_instance_records.append(rec)
        ts_raw = rec.get("ts")
        if isinstance(ts_raw, str):
            try:
                age = (now_value - parse_iso(ts_raw)).total_seconds()
                if age > stale_threshold:
                    stale_instances.append(rec)
            except ValueError:
                stale_instances.append(rec)

    open_conf = open_conflicts(root)
    stale_lease_rows = expired_unreleased_leases(root)

    # Reduce lag: published bus events not yet reduced
    reduced_ids = load_processed_ids(root / "_meta" / "reduced_event_ids.jsonl", "event_id")
    published_ids: set[str] = set()
    for _, _, event in iter_events(root, zone="bus", scope=args.scope):
        event_id = event.get("event_id")
        if event.get("type") == "memory.published" and isinstance(event_id, str):
            published_ids.add(event_id)
    reduce_lag = len([event_id for event_id in published_ids if event_id not in reduced_ids])

    # Attach coverage
    project_dirs = [p for p in (root / "projects").iterdir() if p.is_dir()]
    missing_attach: list[str] = []
    for project_dir in project_dirs:
        attach = root / "views" / "attach" / f"{project_dir.name}.md"
        if not attach.exists():
            missing_attach.append(project_dir.name)

    # View freshness
    reducer_path = root / "coordination" / "reducers.jsonl"
    last_reduce_ts: str | None = None
    if reducer_path.exists():
        for _, data, err in iter_jsonl(reducer_path):
            if err or not data:
                continue
            ts = data.get("ts")
            if isinstance(ts, str):
                last_reduce_ts = max(last_reduce_ts, ts) if last_reduce_ts else ts

    view_freshness_penalty = 0
    if published_ids:
        if not last_reduce_ts:
            view_freshness_penalty = 10
        else:
            try:
                reduce_age = (now_value - parse_iso(last_reduce_ts)).total_seconds() / 60.0
                if reduce_age > 60:
                    view_freshness_penalty = 10
                elif reduce_age > 20:
                    view_freshness_penalty = 5
            except ValueError:
                view_freshness_penalty = 10

    # Duplicate active decision keys
    duplicate_decision_keys = 0
    collisions: Counter[tuple[str, str]] = Counter()
    for item in active_objects(root, obj_type="decision", scope=args.scope, project=args.project):
        scope = str(item.get("scope", ""))
        key = str(item.get("decision_key", ""))
        if scope and key:
            collisions[(scope, key)] += 1
    duplicate_decision_keys = sum(max(0, count - 1) for count in collisions.values() if count > 1)

    # Score
    score = 100
    score -= min(20, len(stale_instances) * 10)
    score -= min(24, len(open_conf) * 8)
    score -= min(16, len(stale_lease_rows) * 8)
    score -= min(20, reduce_lag)
    score -= min(10, len(missing_attach) * 5)
    score -= view_freshness_penalty
    score -= min(20, duplicate_decision_keys * 10)
    score = max(0, min(100, score))

    if score >= 85:
        health = "green"
    elif score >= 65:
        health = "yellow"
    else:
        health = "red"

    findings_created: list[dict[str, Any]] = []
    open_by_rule = open_findings_by_rule(root)

    def maybe_add_finding(
        *,
        rule_id: str,
        severity: str,
        scope: str,
        project: str,
        summary: str,
        evidence: list[str],
        recommendation: str,
        metric: dict[str, Any],
    ) -> None:
        key = (rule_id, scope, project)
        if key in open_by_rule:
            return
        if args.dry_run:
            findings_created.append(
                {
                    "rule_id": rule_id,
                    "severity": severity,
                    "scope": scope,
                    "project": project,
                    "summary": summary,
                    "recommendation": recommendation,
                    "metric": metric,
                }
            )
            return
        finding = add_finding(
            root,
            rule_id=rule_id,
            severity=severity,
            scope=scope,
            project=project,
            summary=summary,
            evidence=evidence,
            recommendation=recommendation,
            metric=metric,
        )
        findings_created.append(finding)

    scope_value = args.scope or ""
    project_value = to_slug(args.project) if args.project else ""

    if stale_instances:
        maybe_add_finding(
            rule_id="stale_instance",
            severity="high",
            scope=scope_value,
            project=project_value,
            summary="Active instances have stale heartbeats.",
            evidence=[str(rec.get("instance_id")) for rec in stale_instances],
            recommendation="Run memory-sync heartbeat or stop stale instances.",
            metric={"count": len(stale_instances), "threshold_seconds": stale_threshold},
        )
    if open_conf:
        maybe_add_finding(
            rule_id="conflict_backlog",
            severity="high",
            scope=scope_value,
            project=project_value,
            summary="Unresolved conflict backlog detected.",
            evidence=list(open_conf.keys()),
            recommendation="Run memory-reconcile on highest-impact conflict keys.",
            metric={"count": len(open_conf)},
        )
    if stale_lease_rows:
        maybe_add_finding(
            rule_id="stale_lease",
            severity="medium",
            scope=scope_value,
            project=project_value,
            summary="Expired leases remain unreleased in ledger.",
            evidence=[f"{row.get('scope')}::{row.get('key')}" for row in stale_lease_rows],
            recommendation="Run memory-optimize with execute to clean stale leases.",
            metric={"count": len(stale_lease_rows)},
        )
    if reduce_lag > 0:
        maybe_add_finding(
            rule_id="reduce_lag",
            severity="medium",
            scope=scope_value,
            project=project_value,
            summary="Published bus events are waiting for reduction.",
            evidence=[f"lag={reduce_lag}"],
            recommendation="Run memory-reduce and then memory-hygiene --reindex.",
            metric={"lag": reduce_lag},
        )
    if missing_attach:
        maybe_add_finding(
            rule_id="attach_missing",
            severity="medium",
            scope=scope_value,
            project=project_value,
            summary="Projects are missing attach capsules.",
            evidence=missing_attach,
            recommendation="Run diasync-memory attach flow for missing projects.",
            metric={"missing": len(missing_attach)},
        )
    if duplicate_decision_keys > 0:
        maybe_add_finding(
            rule_id="duplicate_active_decision_key",
            severity="high",
            scope=scope_value,
            project=project_value,
            summary="Duplicate active decision keys detected.",
            evidence=[f"{scope}::{key}" for (scope, key), count in collisions.items() if count > 1],
            recommendation="Acquire lease and reconcile duplicated decision chains.",
            metric={"duplicate_keys": duplicate_decision_keys},
        )

    scorecard = {
        "schema_version": "diasync-v1-health-scorecard",
        "ts": now_iso(),
        "scope": scope_value,
        "project": project_value,
        "score": score,
        "health": health,
        "metrics": {
            "active_instances": len(active_instance_records),
            "stale_instances": len(stale_instances),
            "open_conflicts": len(open_conf),
            "stale_leases": len(stale_lease_rows),
            "reduce_lag": reduce_lag,
            "attach_missing": len(missing_attach),
            "duplicate_active_decision_keys": duplicate_decision_keys,
        },
    }
    scorecard["hash"] = hash_object(scorecard, exclude={"hash"})

    if not args.dry_run:
        append_jsonl(root / "governance" / "health" / "scorecards.jsonl", scorecard)
        append_jsonl(
            root / "governance" / "health" / "trends.jsonl",
            {
                "schema_version": "diasync-v1-health-trend",
                "ts": scorecard["ts"],
                "scope": scope_value,
                "project": project_value,
                "score": score,
                "health": health,
            },
        )

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "score": score,
            "health": health,
            "metrics": scorecard["metrics"],
            "findings_created": findings_created,
        }
    )
    return 0


def command_optimize(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    findings = list(open_findings(root).values())
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda rec: (severity_rank.get(str(rec.get("severity", "low")), 2), str(rec.get("ts", ""))))
    findings = findings[: max(1, args.max_actions)]

    plans: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []

    for finding in findings:
        finding_id = str(finding.get("finding_id"))
        rule_id = str(finding.get("rule_id", ""))
        severity = str(finding.get("severity", "medium"))

        if rule_id in {"reduce_lag", "index_stale"}:
            action = "hygiene.reindex"
            safe = True
        elif rule_id == "stale_lease":
            action = "lease.cleanup"
            safe = True
        elif rule_id == "attach_missing":
            action = "attach.refresh"
            safe = True
        elif rule_id == "conflict_backlog":
            action = "reconcile.manual"
            safe = False
        elif rule_id == "duplicate_active_decision_key":
            action = "reconcile.with-lease"
            safe = False
        elif rule_id == "stale_instance":
            action = "sync.cleanup"
            safe = False
        else:
            action = "review.manual"
            safe = False

        plan = {
            "schema_version": "diasync-v1-optimization-plan",
            "plan_id": make_id("plan"),
            "finding_id": finding_id,
            "rule_id": rule_id,
            "severity": severity,
            "action": action,
            "safe_auto_execute": safe,
            "status": "planned",
            "ts": now_iso(),
        }
        plan["hash"] = hash_object(plan, exclude={"hash"})
        plans.append(plan)

        if args.execute and safe and not args.dry_run:
            success = True
            details: dict[str, Any] = {}
            if action == "hygiene.reindex":
                details = rebuild_indexes(root, dry_run=False)
            elif action == "lease.cleanup":
                released = []
                for lease in expired_unreleased_leases(root):
                    release = {
                        "schema_version": "diasync-v1-lease-event",
                        "op": "release",
                        "lease_id": lease.get("lease_id"),
                        "scope": lease.get("scope"),
                        "key": lease.get("key"),
                        "instance_id": lease.get("instance_id"),
                        "released_at": now_iso(),
                        "ts": now_iso(),
                    }
                    release["hash"] = hash_object(release, exclude={"hash"})
                    append_jsonl(root / "coordination" / "leases.jsonl", release)
                    released.append(release)
                details = {"released": len(released)}
            elif action == "attach.refresh":
                refreshed = []
                for project_dir in (root / "projects").iterdir():
                    if not project_dir.is_dir():
                        continue
                    project = project_dir.name
                    attach_file = root / "views" / "attach" / f"{project}.md"
                    if attach_file.exists():
                        continue
                    ensure_project_files(root, project)
                    capsule = f"# Attach Capsule: {project}\n\n- Generated by optimize at {now_iso()}\n"
                    atomic_write(attach_file, capsule)
                    refreshed.append(project)
                details = {"refreshed_projects": refreshed}
            else:
                success = False
                details = {"reason": "unsupported safe action"}

            execution = {
                "schema_version": "diasync-v1-optimization-execution",
                "execution_id": make_id("execution"),
                "plan_id": plan["plan_id"],
                "finding_id": finding_id,
                "action": action,
                "success": success,
                "details": details,
                "ts": now_iso(),
            }
            execution["hash"] = hash_object(execution, exclude={"hash"})
            executions.append(execution)

            append_jsonl(root / "governance" / "actions" / "executions.jsonl", execution)
            if success:
                close_finding(root, finding_id, reason=f"auto-optimized via {action}")

        if not args.dry_run:
            append_jsonl(root / "governance" / "actions" / "plans.jsonl", plan)

    print_json(
        {
            "ok": True,
            "dry_run": args.dry_run,
            "execute": args.execute,
            "plans": plans,
            "executions": executions,
            "planned_count": len(plans),
            "executed_count": len(executions),
        }
    )
    return 0


def command_stats(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ensure_store(root)

    event_counts: Counter[str] = Counter()
    for zone in ["streams", "bus"]:
        for _, _, event in iter_events(root, zone=zone, scope=args.scope):
            event_counts[str(event.get("type", "unknown"))] += 1

    view_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    for _, _, obj in iter_view_objects(root, scope=args.scope):
        view_counts[str(obj.get("type", "unknown"))] += 1
        scope_counts[str(obj.get("scope", ""))] += 1

    active_instances = [
        rec
        for rec in latest_instances(root).values()
        if rec.get("event") != "memory.instance.stopped"
    ]

    print_json(
        {
            "ok": True,
            "scope": args.scope,
            "events": dict(event_counts),
            "views": dict(view_counts),
            "scopes": dict(scope_counts),
            "active_instances": len(active_instances),
            "open_conflicts": len(open_conflicts(root)),
            "open_findings": len(open_findings(root)),
        }
    )
    return 0


def add_root_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=os.environ.get("MEMORY_ROOT", ".memory"), help="Memory root path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DiaSync Memory control CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize memory store")
    add_root_arg(p_init)
    p_init.add_argument("--force", action="store_true", help="Overwrite default meta files")
    p_init.set_defaults(func=command_init)

    p_sync = sub.add_parser("sync", help="Manage instance lifecycle events")
    add_root_arg(p_sync)
    p_sync.add_argument("action", choices=["start", "heartbeat", "stop"])
    p_sync.add_argument("--instance-id", required=True)
    p_sync.add_argument("--run-id")
    p_sync.add_argument("--scope")
    p_sync.add_argument("--project")
    p_sync.add_argument("--note")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.set_defaults(func=command_sync)

    p_attach = sub.add_parser("attach", help="Build attach capsule for a project")
    add_root_arg(p_attach)
    p_attach.add_argument("--project", required=True)
    p_attach.add_argument("--scope")
    p_attach.add_argument("--top-decisions", type=int, default=5)
    p_attach.add_argument("--top-commitments", type=int, default=5)
    p_attach.add_argument("--dry-run", action="store_true")
    p_attach.set_defaults(func=command_attach)

    p_capture = sub.add_parser("capture", help="Capture high-value event into stream")
    add_root_arg(p_capture)
    p_capture.add_argument("--scope", required=True)
    p_capture.add_argument("--summary", required=True)
    p_capture.add_argument("--project")
    p_capture.add_argument("--instance-id")
    p_capture.add_argument("--run-id")
    p_capture.add_argument("--proposed-type", default="fact", choices=sorted(OBJECT_TYPES))
    p_capture.add_argument("--horizon", default="day", choices=sorted(HORIZONS))
    p_capture.add_argument("--salience", default="medium", choices=sorted(SALIENCE_LEVELS))
    p_capture.add_argument("--confidence", type=float, default=0.7)
    p_capture.add_argument("--tags")
    p_capture.add_argument("--source")
    p_capture.add_argument("--review-at")
    p_capture.add_argument("--due-at")
    p_capture.add_argument("--evidence-ref")
    p_capture.add_argument("--why")
    p_capture.add_argument("--assumptions")
    p_capture.add_argument("--decision-key")
    p_capture.add_argument("--visibility", default="project", choices=sorted(VISIBILITY_LEVELS))
    p_capture.add_argument("--ts")
    p_capture.add_argument("--dry-run", action="store_true")
    p_capture.set_defaults(func=command_capture)

    p_distill = sub.add_parser("distill", help="Distill captured stream events into view objects")
    add_root_arg(p_distill)
    p_distill.add_argument("--scope")
    p_distill.add_argument("--instance-id")
    p_distill.add_argument("--limit", type=int, default=200)
    p_distill.add_argument("--dry-run", action="store_true")
    p_distill.set_defaults(func=command_distill)

    p_publish = sub.add_parser("publish", help="Publish knowledge package to bus")
    add_root_arg(p_publish)
    p_publish.add_argument("--scope", required=True)
    p_publish.add_argument("--summary", required=True)
    p_publish.add_argument("--project")
    p_publish.add_argument("--instance-id")
    p_publish.add_argument("--run-id")
    p_publish.add_argument("--object-type", default="fact", choices=sorted(OBJECT_TYPES))
    p_publish.add_argument("--horizon", default="week", choices=sorted(HORIZONS))
    p_publish.add_argument("--salience", default="medium", choices=sorted(SALIENCE_LEVELS))
    p_publish.add_argument("--confidence", type=float, default=0.7)
    p_publish.add_argument("--tags")
    p_publish.add_argument("--review-at")
    p_publish.add_argument("--due-at")
    p_publish.add_argument("--evidence-ref")
    p_publish.add_argument("--why")
    p_publish.add_argument("--decision-key")
    p_publish.add_argument("--visibility", default="project", choices=sorted(VISIBILITY_LEVELS))
    p_publish.add_argument("--dry-run", action="store_true")
    p_publish.set_defaults(func=command_publish)

    p_reduce = sub.add_parser("reduce", help="Reduce bus events into view objects")
    add_root_arg(p_reduce)
    p_reduce.add_argument("--scope")
    p_reduce.add_argument("--limit", type=int, default=500)
    p_reduce.add_argument("--reindex", action="store_true")
    p_reduce.add_argument("--dry-run", action="store_true")
    p_reduce.set_defaults(func=command_reduce)

    p_lease = sub.add_parser("lease", help="Manage decision/resource leases")
    add_root_arg(p_lease)
    p_lease.add_argument("action", choices=["acquire", "release", "list"])
    p_lease.add_argument("--instance-id")
    p_lease.add_argument("--scope")
    p_lease.add_argument("--key")
    p_lease.add_argument("--ttl-seconds", type=int, default=900)
    p_lease.add_argument("--dry-run", action="store_true")
    p_lease.set_defaults(func=command_lease)

    p_reconcile = sub.add_parser("reconcile", help="Create superseding object for conflict resolution")
    add_root_arg(p_reconcile)
    p_reconcile.add_argument("--id", required=True)
    p_reconcile.add_argument("--summary", required=True)
    p_reconcile.add_argument("--confidence", type=float)
    p_reconcile.add_argument("--horizon", choices=sorted(HORIZONS))
    p_reconcile.add_argument("--salience", choices=sorted(SALIENCE_LEVELS))
    p_reconcile.add_argument("--tags")
    p_reconcile.add_argument("--review-at")
    p_reconcile.add_argument("--evidence-ref")
    p_reconcile.add_argument("--why")
    p_reconcile.add_argument("--assumptions")
    p_reconcile.add_argument("--decision-key")
    p_reconcile.add_argument("--resolve-conflict")
    p_reconcile.add_argument("--dry-run", action="store_true")
    p_reconcile.set_defaults(func=command_reconcile)

    p_checkpoint = sub.add_parser("checkpoint", help="Update project state capsule and write checkpoint event")
    add_root_arg(p_checkpoint)
    p_checkpoint.add_argument("--project", required=True)
    p_checkpoint.add_argument("--scope")
    p_checkpoint.add_argument("--instance-id")
    p_checkpoint.add_argument("--run-id")
    p_checkpoint.add_argument("--now")
    p_checkpoint.add_argument("--next")
    p_checkpoint.add_argument("--risks")
    p_checkpoint.add_argument("--decisions")
    p_checkpoint.add_argument("--commitments")
    p_checkpoint.add_argument("--dry-run", action="store_true")
    p_checkpoint.set_defaults(func=command_checkpoint)

    p_handoff = sub.add_parser("handoff", help="Write project resume capsule and handoff event")
    add_root_arg(p_handoff)
    p_handoff.add_argument("--project", required=True)
    p_handoff.add_argument("--summary", required=True)
    p_handoff.add_argument("--scope")
    p_handoff.add_argument("--instance-id")
    p_handoff.add_argument("--run-id")
    p_handoff.add_argument("--next-actions")
    p_handoff.add_argument("--risks")
    p_handoff.add_argument("--open-questions")
    p_handoff.add_argument("--dry-run", action="store_true")
    p_handoff.set_defaults(func=command_handoff)

    p_agenda = sub.add_parser("agenda", help="Manage project agenda queue")
    add_root_arg(p_agenda)
    p_agenda.add_argument("--project", required=True)
    p_agenda.add_argument("--add")
    p_agenda.add_argument("--list", action="store_true")
    p_agenda.add_argument("--close")
    p_agenda.add_argument("--update")
    p_agenda.add_argument("--summary")
    p_agenda.add_argument("--priority", default="medium", choices=["high", "medium", "low"])
    p_agenda.add_argument("--due-at")
    p_agenda.add_argument("--status", default="completed")
    p_agenda.add_argument("--status-filter")
    p_agenda.add_argument("--owner")
    p_agenda.add_argument("--tags")
    p_agenda.set_defaults(func=command_agenda)

    p_hygiene = sub.add_parser("hygiene", help="Rotate, archive, and reindex memory files")
    add_root_arg(p_hygiene)
    p_hygiene.add_argument("--reindex", action="store_true")
    p_hygiene.add_argument("--rotate", action="store_true")
    p_hygiene.add_argument("--max-lines", type=int, default=800)
    p_hygiene.add_argument("--archive-before")
    p_hygiene.add_argument("--prune", action="store_true")
    p_hygiene.add_argument("--dry-run", action="store_true")
    p_hygiene.set_defaults(func=command_hygiene)

    p_validate = sub.add_parser("validate", help="Validate event/object integrity and references")
    add_root_arg(p_validate)
    p_validate.add_argument("--strict", action="store_true")
    p_validate.set_defaults(func=command_validate)

    p_diagnose = sub.add_parser("diagnose", help="Compute memory health score and create findings")
    add_root_arg(p_diagnose)
    p_diagnose.add_argument("--scope")
    p_diagnose.add_argument("--project")
    p_diagnose.add_argument("--stale-seconds", type=int, default=1800)
    p_diagnose.add_argument("--dry-run", action="store_true")
    p_diagnose.set_defaults(func=command_diagnose)

    p_optimize = sub.add_parser("optimize", help="Generate and optionally execute optimization plans")
    add_root_arg(p_optimize)
    p_optimize.add_argument("--max-actions", type=int, default=5)
    p_optimize.add_argument("--execute", action="store_true")
    p_optimize.add_argument("--dry-run", action="store_true")
    p_optimize.set_defaults(func=command_optimize)

    p_stats = sub.add_parser("stats", help="Show memory event/view statistics")
    add_root_arg(p_stats)
    p_stats.add_argument("--scope")
    p_stats.set_defaults(func=command_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except MemoryCtlError as exc:
        print_json({"ok": False, "error": str(exc)})
        return 1
    except KeyboardInterrupt:
        print_json({"ok": False, "error": "interrupted"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
