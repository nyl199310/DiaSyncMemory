# Soft Trigger Protocol (V3.1)

Soft triggers define when agents should run memory operations proactively, so memory quality
is maintained without step-by-step human intervention. The goal is autonomous consistency with
minimal overhead.

## 1. Trigger Matrix

- Session starts or resumes: run `sync start`, then `attach`.
- High-value new context appears: run `capture`.
- Scope changes or milestone reached: run `distill`.
- Knowledge should be shared across instances: run `publish`.
- Shared bus has backlog or planning needs fresh views: run `reduce`.
- Shared decision key is contested: run `lease acquire`, then `reconcile`, then `lease release`.
- Long sessions or imminent context compression: run `checkpoint`.
- Session ends: run `handoff`, then `sync stop`.
- Health maintenance window: run `diagnose`, then `optimize`.

## 2. Trigger Intent By Command

### 2.1 `capture`

Use when information has durable value, such as:

- goals, constraints, decisions, tradeoffs,
- dependencies, risks, and commitments.

Do not capture low-value chat noise.

### 2.2 `distill`

Use when stream events are accumulating or when semantic clarity matters before planning.

### 2.3 `publish` and `reduce`

Use `publish` for information other instances should see.

Use `reduce` to keep views converged with published events and to expose unresolved
collisions through conflict ledgers.

### 2.4 `checkpoint` and `handoff`

Use `checkpoint` during long sessions to avoid drift.

Use `handoff` before exit to maximize cold-start quality for the next session.

## 3. Recall Trigger

Run recall before high-impact planning or final answers.

Recommended order:

1. Read attach capsule and project state/resume files.
2. Search relevant view shards by scope/type.
3. Read matching records and follow event/object references.
4. Load evidence lazily only when needed.

## 4. Governance Trigger

- Run `diagnose` once per session (or after major memory churn).
- Run `optimize` after `diagnose`.
- Use `--dry-run` first when operating in sensitive contexts.

## 5. Trigger Frequency Guidelines

- Capture frequently, distill periodically.
- Publish intentionally, reduce promptly.
- Diagnose regularly, optimize conservatively.
- Checkpoint on milestones, handoff on every session end.

## 6. Guardrails

- Never rewrite historical ledger lines.
- Use `supersedes` for corrections.
- Keep summaries concise and explicit.
- Keep uncertainty visible (`confidence`, assumptions, evidence).
- Prefer conflict visibility over silent overwrite behavior.
