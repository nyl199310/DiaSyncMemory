# AGENTS.md
Agent operating guide for `DiaSyncMemory`.

Repository type: Python CLI + Markdown docs.
Authoritative runtime: `.opencode/skills/diasync-memory/scripts/memoryctl.py`.

## Scope And Priority
- Treat this file as the default playbook for agents operating in this repo.
- If explicit task instructions conflict with this file, follow the task instructions.
- Keep edits focused; avoid broad refactors unless requested.
- Do not edit generated/runtime directories: `.memory/`, `venv/`, `.opencode/node_modules/`.

## Repository Map
- `README.md`: high-level overview.
- `docs/`: architecture, protocol, and CLI specs.
- `.opencode/skills/diasync-memory/SKILL.md`: activation router.
- `.opencode/skills/diasync-memory/scripts/memoryctl.py`: core implementation.
- `.opencode/skills/diasync-memory/references/*.md`: operational references.
- `.opencode/skills/diasync-memory/examples/*.md`: runnable demos and scenario tests.

## Cursor And Copilot Rules
Checked paths:
- `.cursorrules`
- `.cursor/rules/`
- `.github/copilot-instructions.md`

Current status: none of these files exist in this repository.
If they are added later, treat them as higher-priority constraints and update this guide.

## Toolchain
- Python 3.10+ expected (per skill metadata).
- Core runtime uses Python stdlib only.
- No dedicated package/build system for the core runtime.
- Node files under `.opencode/` are ancillary, not core runtime source.

## Build / Lint / Test Commands
Run commands from repo root: `D:\code\DiaSyncMemory`.

### Quick Sanity
```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py --help
```

### Build
There is no packaging build pipeline. Use syntax compilation as the build gate:
```bash
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
```

### Lint
No linter config is committed (`pyproject.toml`, `ruff.toml`, etc. are absent).
Minimum static check:
```bash
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
```
If you add a linter in a PR, also commit its config and update this section.

### Test
No formal `pytest` suite exists in tracked files.
Primary integrity tests:
```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
```
Useful smoke checks:
```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py stats
python .opencode/skills/diasync-memory/scripts/memoryctl.py diagnose --dry-run
python .opencode/skills/diasync-memory/scripts/memoryctl.py optimize --dry-run
```

### Running A Single Test
Because there is no unit-test runner, a "single test" means one behavior-level CLI check.
Recommended single-behavior test:
```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py capture --root .memory_test --scope project:demo --project demo --instance-id ins-test --summary "smoke capture" --dry-run
```
Then run strict validation on that isolated root:
```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --root .memory_test --strict
```
For a complete end-to-end flow, run `.opencode/skills/diasync-memory/examples/DEMO_COMMANDS.md`.

## Code Style Guidelines
Conventions below are inferred from `memoryctl.py` and current docs.

### Imports
- Keep `from __future__ import annotations` first.
- Group imports as: future, stdlib, typing/helpers.
- Prefer stdlib over new dependencies unless strongly justified.
- Use explicit imports; avoid wildcard imports.

### Formatting
- Follow PEP 8 and 4-space indentation.
- Wrap long literals/calls with hanging indentation for readability.
- Use trailing commas in multiline dict/list/call literals.
- End files with a newline.

### Types
- Add type hints on new/changed functions.
- Prefer built-in generics (`list[str]`, `dict[str, Any]`).
- Use `| None` for optionals.
- Keep `Any` limited to boundaries (argparse payloads, JSON blobs).

### Naming
- `snake_case` for functions/variables/helpers.
- `UPPER_SNAKE_CASE` for constants and schema tokens.
- `PascalCase` for classes/exceptions (for example `MemoryCtlError`).
- Name CLI handlers as `command_<subcommand>`.

### CLI Structure
- Register subcommands in `build_parser()`.
- Use `set_defaults(func=...)` for command dispatch.
- Keep handlers returning integer exit codes (`0` success, `1` failure).
- Guard side effects with `--dry-run` where supported.

### Error Handling
- Validate inputs early; fail with clear actionable messages.
- Raise `MemoryCtlError` for user-facing command failures.
- Prefer explicit exception handling (`ValueError`, parse errors) over broad catches.
- Preserve `main()` behavior: catch `MemoryCtlError` and `KeyboardInterrupt`, emit JSON error.

### Filesystem And Integrity
- Use `pathlib.Path` for path handling.
- Keep ledgers append-only via `append_jsonl`; do not rewrite history.
- Use `atomic_write` for full-file replacements (`state.md`, `resume.md`, etc.).
- Keep object/event hashes correct via `hash_object`.
- Use UTC ISO-8601 timestamps with `Z` suffix (`now_iso`).
- For corrections, append a new object with `supersedes`; do not mutate prior records.

### Output Contract
- Keep CLI output machine-readable JSON via `print_json`.
- Include `ok` in all command outputs.
- Keep existing payload key names stable unless migration is intentional.
- When adding schema fields, update validation logic accordingly.

### Domain Rules To Preserve
- Reducer only consumes `memory.published` events.
- Decision-key collisions must create conflict records; never auto-overwrite.
- Lease ownership is keyed by `(scope, key)` with expiry and owner checks.
- Open/close findings through governance ledgers, not ad-hoc state mutation.
- Recall remains filesystem-native (no ranked recall command).

## Documentation Conventions
- Keep docs concise, operational, and command-oriented.
- Prefer short numbered sections in spec/protocol docs.
- Use fenced `bash` blocks for runnable commands.
- Preserve project terminology: attach, capture, distill, publish, reduce, reconcile,
  checkpoint, handoff, diagnose, optimize.

## Agent Change Checklist
Before finishing changes, run:
```bash
python -m py_compile .opencode/skills/diasync-memory/scripts/memoryctl.py
python .opencode/skills/diasync-memory/scripts/memoryctl.py validate --strict
```

If CLI flags or behavior changed, also update:
- `docs/MEMORYCTL_CLI_SPEC.md`
- `.opencode/skills/diasync-memory/references/COMMANDS.md`
- affected examples under `.opencode/skills/diasync-memory/examples/`
