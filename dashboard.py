"""Local eval dashboard.  Launch with:  streamlit run dashboard.py"""
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RUNS_DIR = Path(__file__).parent / "eval_artifacts" / "runs"
GROUPS = {
    "Correctness & Accuracy": ["Tool Correctness", "Argument Correctness", "Answer Correctness"],
    "Agent Planning & Efficiency": [
        "Task Completion",
        "Step Efficiency",
        "Plan Quality",
        "Plan Adherence",
    ],
}
METRICS = [m for group in GROUPS.values() for m in group]
GREEN, RED = "#1a7f37", "#cf222e"


@st.cache_data
def load_run(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def discover() -> dict[str, Path]:
    return {p.stem: p for p in sorted(RUNS_DIR.glob("*.json"))}


def fmt(value, spec="{:.3f}", default="n/a"):
    return default if value is None else spec.format(value)


def diff(a, b):
    return None if a is None or b is None else b - a


def overall_pass_rate(run: dict) -> float | None:
    passed = sum(a.get("passed", 0) for a in run["aggregate"].values())
    total = sum(a.get("total", 0) for a in run["aggregate"].values())
    return passed / total if total else None


def agg(run: dict, metric: str) -> dict:
    return run["aggregate"].get(metric, {})


def delta_text(delta, unit="", scale=1.0):
    """Delta string for st.metric; None hides the delta."""
    if delta is None:
        return None
    return f"{delta * scale:+.1f}{unit}" if unit else f"{delta * scale:+.3f}"


def color_delta(value):
    if pd.isna(value) or abs(value) < 1e-9:
        return "color: #6e7781"
    return f"color: {GREEN if value > 0 else RED}; font-weight: 600"


def score_chart(frame: pd.DataFrame, key: str) -> None:
    """Grouped bars: one cluster per metric, one bar per run, fixed height."""
    chart = (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("Metric:N", title=None, sort=None, axis=alt.Axis(labelAngle=0)),
            xOffset="Run:N",
            y=alt.Y("Score:Q", scale=alt.Scale(domain=[0, 1]), title="Avg score"),
            color=alt.Color("Run:N", title=None, legend=alt.Legend(orient="top")),
            tooltip=["Metric", "Run", alt.Tooltip("Score:Q", format=".3f")],
        )
        .properties(height=300)
    )
    st.altair_chart(chart, use_container_width=True, key=key)


def kpi_header(run: dict, name: str, base: dict | None) -> None:
    """Executive header. When `base` is given, deltas are shown against it."""
    meta = run["metadata"]
    rate, tool = overall_pass_rate(run), agg(run, "Tool Correctness").get("pass_rate")
    scores = [a["avg_score"] for a in run["aggregate"].values() if a.get("avg_score") is not None]
    mean_score = sum(scores) / len(scores) if scores else None

    with st.container(border=True):
        c = st.columns(5)
        c[0].metric(
            "Overall pass rate",
            fmt(rate and rate * 100, "{:.1f}%"),
            delta_text(base and diff(overall_pass_rate(base), rate), " pp", 100),
        )
        c[1].metric(
            "Tool correctness",
            fmt(tool and tool * 100, "{:.0f}%"),
            delta_text(
                base and diff(agg(base, "Tool Correctness").get("pass_rate"), tool),
                " pp",
                100,
            ),
        )
        c[2].metric(
            "Mean score",
            fmt(mean_score),
            delta_text(
                base
                and diff(
                    _mean([a.get("avg_score") for a in base["aggregate"].values()]),
                    mean_score,
                )
            ),
        )
        c[3].metric("Failed checks", len(run.get("failures", [])))
        c[4].metric("Run time", fmt(meta.get("duration_seconds"), "{:.0f} s"))

        m = st.columns(4)
        m[0].caption(f"**Run**  \n{name}")
        m[1].caption(f"**Agent / judge**  \n{meta.get('agent_model', 'n/a')} / {meta.get('judge_model', 'n/a')}")
        m[2].caption(
            f"**Git**  \n{meta.get('git_commit', 'n/a')}{' (dirty)' if meta.get('git_dirty') else ''}"
            f" · date {meta.get('frozen_date', 'n/a')}"
        )
        m[3].caption(
            f"**When (UTC) / judge cost**  \n{meta.get('timestamp_utc', 'n/a')} / "
            f"{fmt(meta.get('judge_cost_usd'), '${:.4f}')}"
        )


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def single_tab(run: dict, name: str, metrics: list[str], key: str) -> None:
    rows = [
        {
            "Metric": m,
            "Avg score": agg(run, m).get("avg_score"),
            "Pass rate": agg(run, m).get("pass_rate"),
            "Passed": f"{agg(run, m).get('passed', 0)}/{agg(run, m).get('total', 0)}",
            "Threshold": agg(run, m).get("threshold"),
        }
        for m in metrics
    ]
    with st.container():
        st.dataframe(
            pd.DataFrame(rows),
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
        chart = pd.DataFrame(
            {"Metric": metrics, "Run": name, "Score": [agg(run, m).get("avg_score") for m in metrics]}
        )
        score_chart(chart, key)


def compare_tab(base, cand, base_name, cand_name, metrics, key) -> None:
    rows = []
    for m in metrics:
        a, b = agg(base, m), agg(cand, m)
        rows.append(
            {
                "Metric": m,
                f"{base_name}": a.get("avg_score"),
                f"{cand_name}": b.get("avg_score"),
                "Δ score": diff(a.get("avg_score"), b.get("avg_score")),
                f"Pass {base_name}": f"{a.get('passed', 0)}/{a.get('total', 0)}",
                f"Pass {cand_name}": f"{b.get('passed', 0)}/{b.get('total', 0)}",
                "Δ pass (pp)": (
                    None
                    if diff(a.get("pass_rate"), b.get("pass_rate")) is None
                    else diff(a.get("pass_rate"), b.get("pass_rate")) * 100
                ),
            }
        )
    df = pd.DataFrame(rows)
    styled = (
        df.style.map(color_delta, subset=["Δ score", "Δ pass (pp)"])
        .format({base_name: "{:.3f}", cand_name: "{:.3f}", "Δ score": "{:+.3f}", "Δ pass (pp)": "{:+.0f}"}, na_rep="–")
    )
    with st.container():
        regressed = df[df["Δ score"].notna() & (df["Δ score"] < -1e-9)]["Metric"].tolist()
        if regressed:
            st.error("Regression in: " + ", ".join(regressed))
        else:
            st.success("No metric in this group regressed.")
        st.dataframe(styled, hide_index=True, use_container_width=True)
        chart = pd.DataFrame(
            [
                {"Metric": m, "Run": n, "Score": agg(r, m).get("avg_score")}
                for m in metrics
                for n, r in ((base_name, base), (cand_name, cand))
            ]
        )
        score_chart(chart, key)


def case_inspection(run: dict, key: str) -> None:
    failures: dict[int, list] = {}
    for f in run.get("failures", []):
        failures.setdefault(f["case"], []).append(f)

    with st.container():
        st.subheader("Test case inspection")
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
                                "Arguments": [json.dumps(c["input_parameters"]) for c in calls],
                            }
                        ),
                        hide_index=True,
                        use_container_width=True,
                        key=f"{key}-trace-{i}",
                    )
                else:
                    st.write("No tools called.")

                st.markdown("**Judge failure reasons**")
                if not fails:
                    st.success("All metrics passed.")
                for f in fails:
                    st.markdown(f"- **{f['metric']}** (score {fmt(f.get('score'), '{:.2f}')}): {f.get('reason') or '—'}")


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
        compare = st.toggle("Comparison mode", value=len(names) > 1, disabled=len(names) < 2)
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
    comparing = bool(compare and cand_name)
    cand = get(cand_name) if comparing else None

    # Header: the candidate (or the single run) with deltas against the baseline.
    kpi_header(cand if comparing else base, cand_name if comparing else base_name, base if comparing else None)
    if comparing:
        st.caption(f"Deltas are {cand_name} vs {base_name}. Baseline: " f"{fmt(_pct(overall_pass_rate(base)), '{:.1f}%')} overall pass rate.")

    with st.container():
        st.subheader("Metrics")
        tabs = st.tabs(list(GROUPS))
        for tab, (label, metrics) in zip(tabs, GROUPS.items()):
            with tab:
                key = f"chart-{label}"
                if comparing:
                    compare_tab(base, cand, base_name, cand_name, metrics, key)
                else:
                    single_tab(base, base_name, metrics, key)

    if comparing:
        which = st.radio("Inspect cases from", [base_name, cand_name], index=1, horizontal=True)
        case_inspection(base if which == base_name else cand, f"cases-{which}")
    else:
        case_inspection(base, f"cases-{base_name}")


def _pct(value):
    return None if value is None else value * 100


from streamlit.runtime.scriptrunner import get_script_run_ctx  # noqa: E402

if get_script_run_ctx(suppress_warning=True) is None:
    # Launched with plain `python dashboard.py`: hand over to Streamlit.
    import subprocess
    import sys

    raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", __file__]))
main()
