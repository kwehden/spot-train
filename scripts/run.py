#!/usr/bin/env python3
"""Spot-Train agent REPL entrypoint.

Usage:
    python scripts/run.py                  # connect to real Spot
    python scripts/run.py --dry-run        # fake adapters, no robot
    python scripts/run.py --model-id us.anthropic.claude-3-7-sonnet-20250219-v1:0
"""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Spot-Train Agent REPL")
    parser.add_argument(
        "--dry-run", action="store_true", help="Use fake adapters instead of real Spot"
    )
    parser.add_argument("--model-id", default=None, help="Bedrock model ID override")
    parser.add_argument("--region", default=None, help="AWS region override")
    args = parser.parse_args()

    from spot_train.agent.repl import run_repl

    run_repl(
        mode="dry_run" if args.dry_run else "robot",
        model_id=args.model_id,
        region=args.region,
    )


if __name__ == "__main__":
    main()
