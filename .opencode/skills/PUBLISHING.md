# Publishing Guide

## Publish Unit

Publish `.opencode/skills/diasync-memory/` as one skill package.

## Pre-release Checklist

1. `SKILL.md` frontmatter is valid and `name` matches `diasync-memory`.
2. Command examples point to `scripts/memoryctl.py`.
3. References are relative and loadable.
4. Script passes `python -m py_compile scripts/memoryctl.py`.
5. Runtime bootstrap works with hidden root `.memory`.

## Suggested Open Source Layout

```text
diasync-memory/
  SKILL.md
  README.md
  scripts/
    memoryctl.py
  references/
    *.md
  examples/
    *.md
```

## Consumer Quick Start

If the package is installed at `.opencode/skills/diasync-memory`:

```bash
python .opencode/skills/diasync-memory/scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python .opencode/skills/diasync-memory/scripts/memoryctl.py attach --project demo
```

If running from inside the package root:

```bash
python scripts/memoryctl.py sync start --instance-id ins-main --scope project:demo --project demo
python scripts/memoryctl.py attach --project demo
```
