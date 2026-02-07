# Autonomous Session Scenario

Use this scenario to verify proactive, no-human-prompt memory behavior.

## Goal

Demonstrate that the agent can maintain memory quality and continuity without being asked to
run memory commands explicitly.

## Session A (Build Phase)

User prompt:

"Implement a robust project memory protocol and continue until docs and workflows are stable."

Expected autonomous behavior:

- starts lifecycle (`sync start` + `attach`),
- captures decisions and constraints during implementation,
- distills at milestones,
- checkpoints before major context switches.

## Session B (Continuation Phase)

User prompt:

"Continue from where we left off and give me current status and next action."

Expected autonomous behavior:

- reads attach/state/resume before planning,
- answers with goal, stage, risks, and next action,
- avoids re-asking known context.

## Session C (Concurrent Phase)

User prompt:

"Run another instance to improve risk controls in parallel and share what matters."

Expected autonomous behavior:

- uses separate instance lifecycle,
- publishes shareable updates and reduces them,
- uses lease/reconcile for contested decision keys,
- records conflicts explicitly if collisions occur.

## Session D (Governance Phase)

User prompt:

"Before finalizing, evaluate memory health and apply safe improvements."

Expected autonomous behavior:

- runs `diagnose`,
- runs `optimize` (and `--execute` when safe),
- closes or reduces high-priority findings,
- writes final handoff and stops cleanly.

## Success Criteria

- continuity artifacts are fresh (`attach`, `checkpoint`, `handoff`),
- cross-instance convergence is visible (`publish` + `reduce`),
- contention is controlled (`lease` + `conflicts` + `reconcile`),
- governance loop runs without explicit user micromanagement.
