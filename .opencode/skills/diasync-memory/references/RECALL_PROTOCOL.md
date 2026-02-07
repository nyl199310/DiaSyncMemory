# Recall Protocol

Recall is intentionally tool-native and not script-ranked.

## Order

1. Read `.memory/views/attach/<project>.md`
2. Read `.memory/projects/<project>/state.md` and `resume.md`
3. Grep `.memory/views/decisions`, `.memory/views/facts`, `.memory/views/commitments`
4. Read only matched shards
5. Load `evidence_ref` lazily

## Suppression

- If B supersedes A, suppress A from active reasoning unless explicitly requested.

## Output Pack

- active decisions
- active commitments
- stable facts
- unresolved conflicts
- uncertainty notes
