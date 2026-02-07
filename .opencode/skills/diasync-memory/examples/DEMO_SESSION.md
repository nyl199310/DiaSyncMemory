# Demo Session Script

Use this script to test the user-facing "seamless across sessions" feel.

## Session 1 Prompt

"请基于当前项目做一个并发记忆机制设计，先实现最小可用版，并在过程中维护自己的memory。"

Expected behavior:

- Agent starts sync and attach implicitly.
- Agent captures major decisions.
- Agent checkpoints at milestone.
- Agent writes handoff before ending.

## Session 2 Prompt

"延续上一个会话，直接告诉我当前状态和下一步，不要重复问背景。"

Expected behavior:

- Agent reads attach/state/resume first.
- First response contains current goal, current stage, next action.
- No unnecessary re-questioning.

## Session 3 Prompt (Concurrency)

"你现在相当于另一个实例，请并行推进风险收敛策略，并与主实例共享关键结论。"

Expected behavior:

- New instance uses sync start.
- Shared insights published to bus and reduced.
- Potential collisions appear as explicit conflicts, not silent overwrite.

## Session 4 Prompt (Governance)

"你先给我系统健康度和风险，再做可自动执行的优化。"

Expected behavior:

- Diagnose score and findings produced.
- Optimize emits plan; safe actions can run automatically.
