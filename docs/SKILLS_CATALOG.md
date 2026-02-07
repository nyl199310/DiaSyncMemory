# Skills Catalog (V3.1)

## 1. Published Skills

This repository currently publishes one skill package:

- `diasync-memory`

Install location:

- `.opencode/skills/diasync-memory/SKILL.md`

## 2. Skill Mission

`diasync-memory` provides an operational memory system for coding agents with:

- cross-session continuity,
- multi-instance synchronization,
- explicit conflict and lease handling,
- and built-in governance loops.

## 3. Capability Modules

Capabilities are activated through reference modules rather than separate skill installs.

- **Attach and sync**: session startup grounding and instance lifecycle.
- **Capture and distill**: private stream capture and object distillation.
- **Publish and reduce**: cross-instance sharing and deterministic convergence.
- **Lease and reconcile**: contention control and superseding correction.
- **Checkpoint and handoff**: anti-drift continuity artifacts.
- **Recall protocol**: filesystem-native retrieval workflow.
- **Governance loop**: diagnose and optimize for memory health.

## 4. Why Single-Skill Packaging

- Lower install and versioning overhead.
- Stronger coupling between protocol docs and runtime behavior.
- Clear ownership of memory lifecycle within one distributable unit.

## 5. Expansion Guidance

If new skills are added in the future, this catalog should include:

- skill name,
- mission statement,
- compatibility constraints,
- interaction boundaries with `diasync-memory`.
