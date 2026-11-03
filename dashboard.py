"""Local eval dashboard.  Launch with:  streamlit run dashboard.py"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

RUNS_DIR = Path(__file__).parent / "eval_artifacts" / "runs"
METRICS = [
    "Task Completion",
    "Step Efficiency",
    "Plan Quality",
    "Plan Adherence",
    "Tool Correctness",
    "Argument Correctness",
    "Answer Correctness",
]

@st.cache_data
def load_run(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def discover() -> dict[str, Path]:
    return {p.stem: p for p in sorted(RUNS_DIR.glob("*.json"))}


def fmt(value, spec="{:.3f}", default="n/a"):
    return default if value is None else spec.format(value)


def delta_label(delta: float | None) -> str:
    if delta is None:
        return "–"
    if abs(delta) < 1e-9:
        return "⚪ 0.000"
    return f"{'🟢 ▲' if delta > 0 else '🔴 ▼'} {delta:+.3f}"


def metric_frame(run: dict) -> pd.DataFrame:
    rows = []
    for name in METRICS:
        a = run["aggregate"].get(name, {})
        rows.append(
            {
                "Metric": name,
                "Avg score": a.get("avg_score"),
                "Pass rate": a.get("pass_rate"),
                "Passed": f"{a.get('passed', 0)}/{a.get('total', 0)}",
                "Threshold": a.get("threshold"),
            }
        )
    return pd.DataFrame(rows)


def overview_cards(run: dict) -> None:
    meta, agg = run["metadata"], run["aggregate"]
    rates = [a["pass_rate"] for a in agg.values() if a.get("pass_rate") is not None]
    overall = sum(rates) / len(rates) if rates else None
    seconds = meta.get("duration_seconds")
    cost = meta.get("judge_cost_usd")

    c = st.columns(5)
    c[0].metric("Mean pass rate", fmt(overall and overall * 100, "{:.1f}%"))
    c[1].metric("Test cases", meta.get("num_cases", len(run.get("cases", []))))
    c[2].metric("Execution time", fmt(seconds, "{:.0f} s"))
    c[3].metric("Judge cost", fmt(cost, "${:.4f}"))
    c[4].metric("Failed checks", len(run.get("failures", [])))

    d = st.columns(4)
    d[0].caption(f"**Agent model**  \n{meta.get('agent_model', 'n/a')}")
    d[1].caption(f"**Judge model**  \n{meta.get('judge_model', 'n/a')}")
    d[2].caption(
        f"**Git**  \n{meta.get('git_commit', 'n/a')}"
        f"{' (dirty)' if meta.get('git_dirty') else ''} · frozen date {meta.get('frozen_date', 'n/a')}"
    )
    d[3].caption(f"**Timestamp (UTC)**  \n{meta.get('timestamp_utc', 'n/a')}")
    st.caption(
        "Agent token cost is not recorded by the harness; cost shown is the "
        "LLM-judge cost reported by DeepEval (n/a for runs that predate it)."
    )


def single_run_view(run: dict) -> None:
    st.subheader("Metrics")
    df = metric_frame(run)
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Avg score": st.column_config.ProgressColumn(
                "Avg score", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "Pass rate": st.column_config.ProgressColumn(
                "Pass rate", min_value=0.0, max_value=1.0, format="%.2f"
            ),
        },
    )
    st.bar_chart(df.set_index("Metric")[["Avg score", "Pass rate"]])


def comparison_view(base: dict, cand: dict, base_name: str, cand_name: str) -> None:
    st.subheader(f"Comparison: {base_name} → {cand_name}")
    rows = []
    for name in METRICS:
        a, b = base["aggregate"].get(name, {}), cand["aggregate"].get(name, {})
        d_score = _diff(a.get("avg_score"), b.get("avg_score"))
        d_rate = _diff(a.get("pass_rate"), b.get("pass_rate"))
        rows.append(
            {
                "Metric": name,
                f"Score ({base_name})": a.get("avg_score"),
                f"Score ({cand_name})": b.get("avg_score"),
                "Score Δ": delta_label(d_score),
                f"Pass ({base_name})": f"{a.get('passed', 0)}/{a.get('total', 0)}",
                f"Pass ({cand_name})": f"{b.get('passed', 0)}/{b.get('total', 0)}",
                "Pass-rate Δ": delta_label(d_rate),
                "_d": d_score,
            }
        )
    df = pd.DataFrame(rows)
    regressions = df[df["_d"].notna() & (df["_d"] < -1e-9)]["Metric"].tolist()
    if regressions:
        st.error("Regression in: " + ", ".join(regressions))
    else:
        st.success("No metric regressed.")
    st.dataframe(
        df.drop(columns="_d"),
        hide_index=True,
        use_container_width=True,
        column_config={
            c: st.column_config.NumberColumn(c, format="%.3f")
            for c in df.columns
            if c.startswith("Score (")
        },
    )
    chart = pd.DataFrame(
        {
            base_name: [base["aggregate"].get(m, {}).get("avg_score") for m in METRICS],
            cand_name: [cand["aggregate"].get(m, {}).get("avg_score") for m in METRICS],
        },
        index=METRICS,
    )
    st.bar_chart(chart)


def _diff(a, b):
    return None if a is None or b is None else b - a


def case_inspection(run: dict) -> None:
    st.subheader("Test case inspection")
    failures: dict[int, list] = {}
    for f in run.get("failures", []):
        failures.setdefault(f["case"], []).append(f)

    for i, case in enumerate(run.get("cases", [])):
        fails = failures.get(i, [])
        icon = "🔴" if fails else "🟢"
        with st.expander(f"{icon} Case {i}: {case['input']}  ({len(fails)} failed checks)"):
            left, right = st.columns(2)
            left.markdown("**Expected output**")
            left.info(case.get("expected_output", ""))
            right.markdown("**Actual output**")
            right.info(case.get("actual_output", ""))

            st.markdown("**Tool call trace**")
            calls = case.get("tools_called", [])
            if calls:
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Step": range(1, len(calls) + 1),
                            "Tool": [c["name"] for c in calls],
                            "Arguments": [
                                json.dumps(c["input_parameters"]) for c in calls
                            ],
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.write("No tools called.")

            st.markdown("**Judge failure reasons**")
            if not fails:
                st.success("All metrics passed.")
            for f in fails:
                score = fmt(f.get("score"), "{:.2f}")
                st.markdown(f"- **{f['metric']}** (score {score}): {f.get('reason') or '—'}")


def main() -> None:
    st.set_page_config(page_title="Agent Evals", layout="wide")
    st.title("Agent Evals Dashboard")
    runs = discover()
    if not runs:
        st.warning(f"No run files found in {RUNS_DIR}")
        return

    names = list(runs)
    with st.sidebar:
        st.header("Runs")
        compare = st.toggle("Comparison mode", value=False, disabled=len(names) < 2)
        if compare:
            base_name = st.selectbox("Baseline run", names, index=0)
            cand_name = st.selectbox("Candidate run", names, index=len(names) - 1)
        else:
            base_name = st.selectbox("Run", names, index=len(names) - 1)
            cand_name = None
        if st.button("Reload runs"):
            st.cache_data.clear()
            st.rerun()

    def get(name):
        p = runs[name]
        return load_run(str(p), p.stat().st_mtime)

    base = get(base_name)
    if compare and cand_name:
        cand = get(cand_name)
        tab_a, tab_b = st.tabs([f"Baseline: {base_name}", f"Candidate: {cand_name}"])
        with tab_a:
            overview_cards(base)
        with tab_b:
            overview_cards(cand)
        comparison_view(base, cand, base_name, cand_name)
        which = st.radio("Inspect cases from", [base_name, cand_name], horizontal=True)
        case_inspection(base if which == base_name else cand)
    else:
        overview_cards(base)
        single_run_view(base)
        case_inspection(base)


from streamlit.runtime.scriptrunner import get_script_run_ctx  # noqa: E402

if get_script_run_ctx(suppress_warning=True) is None:
    # Launched with plain `python dashboard.py`: hand over to Streamlit.
    import subprocess
    import sys

    raise SystemExit(
        subprocess.call([sys.executable, "-m", "streamlit", "run", __file__])
    )
main()