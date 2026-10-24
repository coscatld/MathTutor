"""Run the fixed multi-turn tutoring evaluation and write JSON + Markdown.

    PYTHONPATH=src python scripts/tutor_multiturn_eval.py --output build/eval
    PYTHONPATH=src MT_EVAL_API_KEY=... python scripts/tutor_multiturn_eval.py --mode live \
        --base-url https://api.deepseek.com/v1 --model deepseek-chat --output build/eval

Scoring is automatic (rules + local verifier); there is no human rater.
Exit code 1 for failed checks, 2 for invalid selection. A successful --only
subset exits 0, but only a complete suite can set report.release_gate.passed.
"""
import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    from mathtutor.evaluation.tutor_multiturn import render_markdown, run

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["template", "live"], default="template")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key-env", default="MT_EVAL_API_KEY")
    parser.add_argument("--only", nargs="+", default=None,
                        help="Run a non-empty subset of known scenario IDs; omit for the full release gate")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    live = None
    if args.mode == "live":
        key = os.environ.get(args.api_key_env, "")
        if not (args.base_url and args.model and key):
            parser.error(f"live mode needs --base-url, --model and ${args.api_key_env}")
        live = {"base_url": args.base_url, "model": args.model, "api_key": key}
    try:
        report = run(args.mode, live=live, only=args.only)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    stem = f"tutor-multiturn-{args.mode}"
    (args.output / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / f"{stem}.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
