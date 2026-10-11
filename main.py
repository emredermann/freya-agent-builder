"""CLI entrypoint: python main.py --brief tests/sample_brief.json"""
from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from builder.models import TaskInput
from builder.pipeline import build_agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freya meta-agent builder")
    parser.add_argument("--brief", required=True, help="Path to brief JSON")
    parser.add_argument("--no-llm", action="store_true", help="Skip Anthropic calls (offline heuristics)")
    parser.add_argument("--deploy", action="store_true", help="Create the agent on Freya, simulate, refine, redeploy")
    parser.add_argument("--rounds", type=int, default=3, help="Max simulate/refine rounds (with --deploy)")
    parser.add_argument("--target", type=float, default=0.9, help="Stop when simulation pass rate >= target")
    parser.add_argument("--runs", type=int, default=1, help="Simulation runs per persona (more = less noise)")
    parser.add_argument("--mode", choices=["chat", "voice"], default="chat", help="Simulation mode")
    args = parser.parse_args(argv)

    load_dotenv()
    with open(args.brief, encoding="utf-8") as f:
        task = TaskInput.model_validate(json.load(f))
    if args.deploy:
        from builder.pipeline import build_and_deploy
        from client.freya_client import get_client

        result = build_and_deploy(
            task,
            get_client(),
            rounds=args.rounds,
            target=args.target,
            mode=args.mode,
            runs_per_persona=args.runs,
            use_llm=not args.no_llm,
            log=lambda msg: print(msg, file=sys.stderr),
        )
        print(result.model_dump_json(indent=2))
        return 0
    config = build_agent(task, use_llm=not args.no_llm)
    print(config.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
