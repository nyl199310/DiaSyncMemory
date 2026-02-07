# Memory Debt

Memory debt is the gap between current memory quality and the quality needed for reliable
autonomous operation.

Use this as a soft prioritization model, not hard logic.

## 1. Debt Classes

### 1.1 Convergence debt

Symptoms:

- published events waiting for reduction,
- duplicate active decision keys,
- stale indexes after major updates.

Actions:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py reduce --scope <scope> --reindex
python .opencode/skills/diasync-memory/scripts/memoryctl.py hygiene --reindex
```

### 1.2 Contention debt

Symptoms:

- open conflict backlog,
- stale unreleased leases,
- contested decision keys.

Actions:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py lease list --scope <scope>
python .opencode/skills/diasync-memory/scripts/memoryctl.py reconcile --id <object-id> --summary "<superseding decision>"
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --max-actions 5 --execute
```

### 1.3 Continuity debt

Symptoms:

- missing attach capsule,
- stale or vague `state.md` / `resume.md`,
- no checkpoint across long execution windows.

Actions:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project <project> --scope <scope>
python .opencode/skills/diasync-memory/scripts/memoryctl.py checkpoint --project <project> --scope <scope> --instance-id <instance> --now "<state>" --next "<next action>"
python .opencode/skills/diasync-memory/scripts/memoryctl.py handoff --project <project> --scope <scope> --instance-id <instance> --summary "<handoff summary>"
```

### 1.4 Governance debt

Symptoms:

- health score trending down,
- open findings not addressed,
- recurring stale-instance or stale-lease findings.

Actions:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --scope <scope> --project <project>
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --max-actions 5
```

### 1.5 Retrieval debt

Symptoms:

- slow recall because capsules are noisy,
- key facts hard to locate,
- evidence pointers missing.

Actions:

- capture concise, high-signal summaries,
- distill at milestones,
- keep attach/state/resume explicit and current.

## 2. Prioritization Rule

Prefer reducing debt that blocks correctness before debt that blocks convenience.

Recommended order:

1. contention debt
2. convergence debt
3. continuity debt
4. governance debt
5. retrieval debt

Reorder only when current objective requires faster retrieval than coordination safety.

## 3. Quick Review Loop

At planning boundaries, ask:

- What is the highest debt right now?
- What single command reduces it the most?
- What is the next highest debt after that?

This keeps memory upkeep proactive, bounded, and autonomous.
