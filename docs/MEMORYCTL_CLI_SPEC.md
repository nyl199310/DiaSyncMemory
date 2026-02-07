# memoryctl CLI Spec (V3.1)

## 1. Invocation

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py <command> [options]
```

Default memory root:

- `.memory` (auto-initialized)

Global option on commands:

- `--root <path>` overrides the runtime root (or use `MEMORY_ROOT`).

## 2. Command Index

- Lifecycle: `init`, `sync`, `attach`, `checkpoint`, `handoff`
- Knowledge flow: `capture`, `distill`, `publish`, `reduce`, `reconcile`
- Coordination: `lease`, `agenda`
- Governance and maintenance: `hygiene`, `validate`, `diagnose`, `optimize`, `stats`

## 3. Command Reference

### 3.1 `init`

Initialize required directories and metadata files.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py init [--root <path>] [--force]
```

- `--force`: rewrite default metadata files under `_meta/`.

### 3.2 `sync`

Emit instance lifecycle events and maintain cursor/lease state.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync {start|heartbeat|stop} --instance-id <id> [--scope <scope>] [--project <name>] [--run-id <id>] [--note <text>] [--dry-run]
```

Notes:

- `start` initializes reducer cursor position.
- `stop` releases leases currently held by the instance.

### 3.3 `attach`

Build an attach capsule from project state + active decisions/commitments.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project <name> [--scope <scope>] [--top-decisions <n>] [--top-commitments <n>] [--dry-run]
```

### 3.4 `capture`

Append high-value event to a private instance stream.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --scope <scope> --summary <text> [--project <name>] [--instance-id <id>] [--run-id <id>] [--proposed-type {fact|decision|commitment}] [--horizon {now|day|week|month|quarter|year}] [--salience {low|medium|high}] [--confidence <0..1>] [--tags csv] [--source csv] [--review-at YYYY-MM-DD] [--due-at YYYY-MM-DD] [--evidence-ref <path>] [--why <text>] [--assumptions csv] [--decision-key <key>] [--visibility {private|project|global}] [--ts <iso>] [--dry-run]
```

### 3.5 `distill`

Transform captured stream events into view objects.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill [--scope <scope>] [--instance-id <id>] [--limit <n>] [--dry-run]
```

### 3.6 `publish`

Emit shareable knowledge event to the shared bus.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py publish --scope <scope> --summary <text> [--project <name>] [--instance-id <id>] [--run-id <id>] [--object-type {fact|decision|commitment}] [--horizon {now|day|week|month|quarter|year}] [--salience {low|medium|high}] [--confidence <0..1>] [--tags csv] [--review-at YYYY-MM-DD] [--due-at YYYY-MM-DD] [--evidence-ref <path>] [--why <text>] [--decision-key <key>] [--visibility {private|project|global}] [--dry-run]
```

### 3.7 `reduce`

Reduce bus events into view objects and optionally rebuild indexes.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py reduce [--scope <scope>] [--limit <n>] [--reindex] [--dry-run]
```

### 3.8 `lease`

Manage lease ownership for contested `(scope, key)` updates.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py lease {acquire|release|list} [--instance-id <id>] [--scope <scope>] [--key <key>] [--ttl-seconds <n>] [--dry-run]
```

Notes:

- `list` does not require `--instance-id` or `--key`.
- `acquire` and `release` require both `--instance-id` and `--key`.

### 3.9 `reconcile`

Create a superseding object for conflict/manual correction.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py reconcile --id <object-id> --summary <text> [--confidence <0..1>] [--horizon {now|day|week|month|quarter|year}] [--salience {low|medium|high}] [--tags csv] [--review-at YYYY-MM-DD] [--evidence-ref <path>] [--why <text>] [--assumptions csv] [--decision-key <key>] [--resolve-conflict <conflict-id>] [--dry-run]
```

### 3.10 `checkpoint`

Update project state capsule and append checkpoint event.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py checkpoint --project <name> [--scope <scope>] [--instance-id <id>] [--run-id <id>] [--now <text>] [--next <text>] [--risks csv] [--decisions csv] [--commitments csv] [--dry-run]
```

### 3.11 `handoff`

Write project resume capsule and append handoff event.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py handoff --project <name> --summary <text> [--scope <scope>] [--instance-id <id>] [--run-id <id>] [--next-actions csv] [--risks csv] [--open-questions csv] [--dry-run]
```

### 3.12 `agenda`

Operate project agenda ledger.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py agenda --project <name> (--add <text> | --list | --close <id> | --update <id>) [--summary <text>] [--priority {high|medium|low}] [--due-at YYYY-MM-DD] [--status <status>] [--status-filter <status>] [--owner <id>] [--tags csv]
```

Exactly one action flag must be provided.

### 3.13 `hygiene`

Run maintenance operations (reindex, rotate, archive).

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py hygiene [--reindex] [--rotate] [--max-lines <n>] [--archive-before YYYY-MM] [--prune] [--dry-run]
```

If no action is given, `hygiene` defaults to reindex.

### 3.14 `validate`

Validate schema integrity, hashes, references, and ledger consistency.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate [--strict]
```

- `--strict` treats warnings as failures.

### 3.15 `diagnose`

Compute health score, derive findings, and write scorecards.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose [--scope <scope>] [--project <name>] [--stale-seconds <n>] [--dry-run]
```

### 3.16 `optimize`

Generate optimization plans and optionally execute safe actions.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize [--max-actions <n>] [--execute] [--dry-run]
```

### 3.17 `stats`

Show event/view counts and operational totals.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py stats [--scope <scope>]
```

## 4. Output Contract

- All commands print JSON.
- `ok` is always present.
- Command failures return `ok: false` with an `error` message.

## 5. Important Recall Note

There is no scripted `recall` command by design.

Recall is protocol-driven and filesystem-native via `Read`, `Grep`, and `Glob`.
