import os
from datetime import date


def today() -> date:
    """Return the current date, or the frozen date in EVAL_TODAY (YYYY-MM-DD) for deterministic runs."""
    frozen = os.getenv("EVAL_TODAY")
    return date.fromisoformat(frozen) if frozen else date.today()
