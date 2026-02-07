# Proactive Cadence

Use this policy to run `diasync-memory` autonomously without hard orchestration logic.

## 1. Principle

Prefer proactive memory upkeep over reactive repair.

The objective is to keep memory continuously useful, not only valid after failures.

## 2. Cadence Windows

### A. Session start or resume

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id <instance> --scope <scope> --project <project>
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project <project> --scope <scope>
```

### B. Active execution (while work evolves)

- Capture high-value updates as they happen.
- Distill when semantic clarity is needed.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --scope <scope> --project <project> --instance-id <instance> --summary "<high-value update>"
python .opencode/skills/diasync-memory/scripts/memoryctl.py distill --scope <scope> --instance-id <instance>
```

### C. Cross-instance sharing

- Publish only reusable knowledge.
- Reduce promptly to keep views converged.

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py publish --scope <scope> --project <project> --instance-id <instance> --summary "<shareable cognition>"
python .opencode/skills/diasync-memory/scripts/memoryctl.py reduce --scope <scope> --reindex
```

### D. Periodic governance (during long sessions)

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --scope <scope> --project <project>
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --max-actions 5
```

Use `--execute` only when safe actions are appropriate.

### E. Session end

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py checkpoint --project <project> --scope <scope> --instance-id <instance> --now "<current state>" --next "<next action>"
python .opencode/skills/diasync-memory/scripts/memoryctl.py handoff --project <project> --scope <scope> --instance-id <instance> --summary "<session summary>"
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync stop --instance-id <instance> --scope <scope>
```

## 3. Soft Trigger Hints

- If uncertainty grows, capture and distill sooner.
- If another instance could benefit, publish and reduce sooner.
- If health signals degrade, diagnose and optimize sooner.
- If context switching is likely, checkpoint earlier.

## 4. Guardrails

- Keep updates concise and auditable.
- Do not rewrite history in place.
- Use `supersedes` for corrections.
- Prefer proactive prevention over backlog cleanup.
