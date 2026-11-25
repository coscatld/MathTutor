"""Run the shared development cases against this or another MathTutor checkout."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.checkout.resolve()
    sys.path[:0] = [str(root / "src"), str(root / "tests")]
    from test_phase4_learning import _assessment

    cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        assessment = _assessment(case["answer"], case["problem"])[2]
        verdict = assessment.correctness.value
        line = next((r["line"] for r in assessment.remaining_requirements if "line" in r), None)
        matched = (verdict == case["verdict"] and line == case["issue_line"]
                   and (case["signal"] is None or case["signal"] in assessment.signals))
        results.append({"id": case["id"], "verdict": verdict, "line": line, "matched": matched})
    incomplete = [(case, row) for case, row in zip(cases, results) if case["verdict"] != "correct"]
    print(json.dumps({
        "cases": len(cases), "matched": sum(row["matched"] for row in results),
        "incomplete_or_invalid": len(incomplete),
        "false_completions": sum(row["verdict"] == "correct" for _, row in incomplete),
        "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
