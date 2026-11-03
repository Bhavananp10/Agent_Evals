"""Run the 7-metric suite deterministically and write versioned artifacts.

Usage (from repo root):
    .venv\\Scripts\\python.exe evaluations\\run_eval.py --version baseline_v1
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "eval_artifacts"
FROZEN_DATE = "2026-11-03"
METRICS = [
    "Task Completion",
    "Step Efficiency",
    "Plan Quality",
    "Plan Adherence",
    "Tool Correctness",
    "Argument Correctness",
    "Answer Correctness",
]

# Must be set before the agent package imports data.py.
os.environ["EVAL_TODAY"] = os.getenv("EVAL_TODAY", FROZEN_DATE)
sys.path.insert(0, str(Path(__file__).resolve().parent))



def canonical(name: str) -> str:
    for metric in METRICS:
        if name.startswith(metric):
            return metric
    return name


def git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def collect(phase: str) -> list:
    """Per-case metric results: trace metrics live on the in-memory test run,
    single-turn metrics in the latest full-run export."""
    if phase == "trace":
        from deepeval.test_run import global_test_run_manager

        run = global_test_run_manager.get_test_run().model_dump(
            by_alias=True, exclude_none=True
        )
        cases = [
            (c, (c.get("trace") or {}).get("metricsData") or [])
            for c in run["testCases"]
        ]
    else:
        run = json.loads(Path(".deepeval/.latest_run_full.json").read_text(encoding="utf-8"))
        cases = [(c, c.get("metricsData") or []) for c in run["testCases"]]
    return [
        {
            "index": i,
            "input": case.get("input"),
            "metrics": [
                {
                    "name": canonical(m["name"]),
                    "score": m.get("score"),
                    "threshold": m.get("threshold"),
                    "success": m.get("success"),
                    "reason": m.get("reason"),
                    "error": m.get("error"),
                }
                for m in metrics
            ],
        }
        for i, (case, metrics) in enumerate(cases)
    ]

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="baseline_v1")
    args = parser.parse_args()

    (ARTIFACTS / "runs").mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "logs").mkdir(parents=True, exist_ok=True)
    log_path = ARTIFACTS / "logs" / f"{args.version}.log"
    logging.getLogger().addHandler(
        logging.FileHandler(log_path, mode="w", encoding="utf-8")
    )

    os.chdir(ROOT / "evaluations")
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    import eval_all
    from model import eval_model

    started = datetime.now(timezone.utc)
    phases: dict[str, list] = {}

    def snapshot(phase: str) -> None:
        phases[phase] = collect(phase)
        from deepeval.test_run import global_test_run_manager

        cost = getattr(global_test_run_manager.get_test_run(), "evaluation_cost", None)
        costs[phase] = cost or 0.0

    costs: dict[str, float] = {}
    transcripts = eval_all.main(on_phase_done=snapshot)
    duration = (datetime.now(timezone.utc) - started).total_seconds()

    by_metric: dict[str, list] = {m: [] for m in METRICS}
    for phase_cases in phases.values():
        for case in phase_cases:
            for metric in case["metrics"]:
                by_metric.setdefault(metric["name"], []).append(
                    {**metric, "case": case["index"], "input": case["input"]}
                )

    aggregate = {}
    failures = []
    for name in METRICS:
        results = by_metric.get(name, [])
        scores = [r["score"] for r in results if r["score"] is not None]
        passed = sum(1 for r in results if r["success"])
        aggregate[name] = {
            "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
            "passed": passed,
            "total": len(results),
            "pass_rate": round(passed / len(results), 3) if results else None,
            "threshold": results[0]["threshold"] if results else None,
        }
        failures += [
            {
                "metric": name,
                "case": r["case"],
                "input": r["input"],
                "score": r["score"],
                "reason": r["reason"] or r["error"],
            }
            for r in results
            if not r["success"]
        ]

    with log_path.open("a", encoding="utf-8") as log:
        for i, t in enumerate(transcripts):
            log.write(f"\n=== case {i}: {t['input']}\n")
            for call in t["tools_called"]:
                log.write(f"  tool: {call['name']} {json.dumps(call['input_parameters'])}\n")
            log.write(f"  expected: {t['expected_output']}\n")
            log.write(f"  actual:   {t['actual_output']}\n")

    report = {
        "metadata": {
            "run_tag": args.version,
            "timestamp_utc": started.isoformat(timespec="seconds"),
            "git_commit": git("rev-parse", "--short", "HEAD"),
            "git_dirty": bool(git("status", "--porcelain")),
            "agent_model": "openai/gpt-oss-120b (groq, temperature=0)",
            "judge_model": getattr(eval_model, "name", "gpt-4o-mini"),
            "frozen_date": os.environ["EVAL_TODAY"],
            "num_cases": len(transcripts),
            "duration_seconds": round(duration, 1),
            "judge_cost_usd": round(sum(costs.values()), 4),
        },
        "aggregate": aggregate,
        "failures": failures,
        "cases": transcripts,
    }
    out = ARTIFACTS / "runs" / f"{args.version}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out} and {log_path}")


if __name__ == "__main__":
    main()
