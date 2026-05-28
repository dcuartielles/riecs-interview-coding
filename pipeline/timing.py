"""Per-stage time estimates for live progress reporting.

Baseline figures come from a measured end-to-end benchmark on a Mac mini
M4 Pro 64 GB with the hybrid 8b/70b model configuration (see Benchmark.md).
They are estimates only: actual time depends on hardware, model choice, and
transcript length, so progress percentages are advisory.
"""

# Wall-clock seconds measured for each stage on the benchmark transcript.
BENCHMARK_WORD_COUNT = 5385

STAGE_BASELINE_SECONDS = {
    "anonymise": 292.0,
    "summarise": 37.0,
    "themes": 360.0,
    "questions": 360.0,    # workshop-mode counterpart of themes; same order of magnitude
    "demographics": 45.0,  # structured extraction; small output, fast
    "sentiment": 42.0,
    "compare": 107.0,
}

# Human-readable stage names for progress displays and reports.
STAGE_LABELS = {
    "anonymise": "Anonymise",
    "summarise": "Summarise",
    "themes": "Themes",
    "questions": "Questions",
    "demographics": "Demographics",
    "sentiment": "Sentiment",
    "compare": "Corpus comparison",
}

# Order the per-document stages run in, per mode.
INTERVIEW_STAGES = ["anonymise", "summarise", "themes", "sentiment"]
WORKSHOP_STAGES  = ["anonymise", "summarise", "questions", "demographics"]


def estimate_seconds(stage: str, word_count: int | None = None,
                     n_interviews: int = 1) -> float:
    """Estimated wall-clock seconds for a stage.

    Per-interview stages scale linearly with transcript word count; the
    corpus comparison scales with the number of interviews.
    """
    base = STAGE_BASELINE_SECONDS.get(stage, 60.0)
    if stage == "compare":
        return base * max(1, n_interviews)
    if word_count and BENCHMARK_WORD_COUNT:
        return base * (word_count / BENCHMARK_WORD_COUNT)
    return base


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage.capitalize())


def format_duration(seconds: float) -> str:
    """Format a duration as a compact human string, e.g. '4m 52s'."""
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def percent_complete(elapsed: float, estimate: float) -> float:
    """Fraction complete (0.0–0.99) from elapsed time against an estimate.

    Capped below 1.0 so a stage that overruns its estimate still reads as
    in-progress until it actually finishes.
    """
    if estimate <= 0:
        return 0.0
    return min(elapsed / estimate, 0.99)
