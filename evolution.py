from __future__ import annotations

import argparse
import json
from pathlib import Path

from evo.config import EvolutionConfig
from evo.orchestrator import EvolutionOrchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run autonomous skill-driven evolution for DiaSync memory behavior.",
    )
    parser.add_argument(
        "--config",
        default="evo/config.default.json",
        help="Path to evolution configuration JSON.",
    )
    parser.add_argument(
        "--max-epochs",
        type=int,
        default=None,
        help="Override max epochs from config.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate loop without applying mutations.",
    )
    parser.add_argument(
        "--disable-mutation",
        action="store_true",
        help="Disable mutation phase and run evaluation-only epochs.",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run continuously until stop signal or optional limits.",
    )
    parser.add_argument(
        "--max-wall-minutes",
        type=int,
        default=None,
        help="Override wall-clock runtime limit in minutes (0 disables).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable live progress output (progress.jsonl still written).",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=15,
        help="Seconds between waiting heartbeats for long OpenCode calls.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    workspace_root = Path(__file__).resolve().parent
    config_path = workspace_root / args.config
    config = EvolutionConfig.from_file(config_path)
    if args.max_epochs is not None:
        config.max_epochs = args.max_epochs
    if args.continuous:
        config.continuous = True
    if args.max_wall_minutes is not None:
        config.max_wall_seconds = max(0, args.max_wall_minutes) * 60

    orchestrator = EvolutionOrchestrator(
        workspace_root=workspace_root,
        config=config,
        dry_run=args.dry_run,
        disable_mutation=args.disable_mutation,
        progress_enabled=not args.no_progress,
        heartbeat_seconds=max(1, args.heartbeat_seconds),
    )
    final_summary = orchestrator.run()
    print(json.dumps(final_summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
