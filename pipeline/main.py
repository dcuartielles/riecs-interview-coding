"""
Entry point for the offline analysis pipeline.

Two modes (see config.yaml `mode:` or `--mode`):
  interviews  — anonymise → summarise → themes (vs. labelbook) → sentiment
  workshop    — [anonymise] → summarise → questions (per question coverage,
                sentiment, emerging themes)

Usage:
    python main.py                                  # process all .txt files in interviews/
    python main.py --interview path/to.txt          # process a single transcript
    python main.py --mode workshop                  # workshop-mode run
    python main.py --questions path/questions.yaml  # questions list for workshop mode
    python main.py --compare-only                   # re-run corpus comparison on existing output
    python main.py --stage anonymise                # run only one stage
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from anonymise import anonymise_transcript
from analyse import summarise, extract_themes, analyse_sentiment
from questions import analyse_questions
from demographics import extract_demographics
from compare import build_corpus_comparison
from timing import estimate_seconds, format_duration, stage_label

console = Console()

# Plain-text per-tick progress file path. When set, every tick callback
# overwrites this file with a one-line status — useful when the CLI is
# launched detached (no TTY) and Rich's in-place progress is suppressed.
# `tail -f <run_dir>/.progress.txt` then becomes a live progress meter.
_PROGRESS_FILE: Path | None = None


def set_progress_file(path: Path | None) -> None:
    global _PROGRESS_FILE
    _PROGRESS_FILE = path
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("starting…\n", encoding="utf-8")


def _run_stage(stage: str, estimate: float, fn):
    """Run one pipeline stage with a live progress bar.

    The bar fills against the time estimate; on completion the actual
    duration is printed. If a progress file has been registered via
    set_progress_file, each tick also overwrites it with one line of
    plain text suitable for `tail -f`. Returns (stage result, elapsed seconds).
    """
    total = max(estimate, 1.0)
    t0 = time.time()
    with Progress(
        TextColumn("  [bold]{task.description}"),
        BarColumn(bar_width=32),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(stage_label(stage), total=total)

        def tick(tokens, elapsed, note=""):
            progress.update(task, completed=min(elapsed, total * 0.99))
            if _PROGRESS_FILE is not None:
                pct = min(100, int(100 * elapsed / total)) if total else 0
                extra = f" · {note}" if note else ""
                try:
                    _PROGRESS_FILE.write_text(
                        f"{stage_label(stage)}: {pct:3d}%  "
                        f"({tokens:,} tokens · {int(elapsed)}s elapsed · "
                        f"est. {format_duration(total)}){extra}\n",
                        encoding="utf-8",
                    )
                except OSError:
                    pass  # never let progress reporting break the run

        result = fn(tick)
        progress.update(task, completed=total)
        if _PROGRESS_FILE is not None:
            try:
                _PROGRESS_FILE.write_text(
                    f"{stage_label(stage)}: done ({format_duration(time.time() - t0)})\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
    seconds = time.time() - t0
    console.print(
        f"  [green]✓[/green] {stage_label(stage)} "
        f"[dim]— {format_duration(seconds)}[/dim]"
    )
    return result, seconds


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_pipeline(cfg: dict, interviews: list[Path], run_dir: Path, stages: set[str]) -> None:
    (run_dir / "anonymised").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis").mkdir(exist_ok=True)
    entities_dir = run_dir / cfg["gdpr"]["entities_subdir"]
    entities_dir.mkdir(exist_ok=True)

    mode = (cfg.get("mode") or "interviews").lower()
    is_workshop = mode == "workshop"
    anonymise_enabled = (
        cfg.get("analysis", {}).get("anonymise_workshop_sheets", True)
        if is_workshop else True
    )

    log_path = run_dir / "run_log.jsonl"

    def log(record: dict) -> None:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(record) + "\n")

    results_table = Table(title=f"Pipeline results ({mode})", show_lines=True)
    results_table.add_column("Document" if is_workshop else "Interview", style="cyan")
    results_table.add_column("Anon", justify="center")
    results_table.add_column("Summary", justify="center")
    results_table.add_column("Questions" if is_workshop else "Themes", justify="center")
    if not is_workshop:
        results_table.add_column("Sentiment", justify="center")
    results_table.add_column("Time (s)", justify="right")

    for interview_path in interviews:
        # When iterating over `<run_dir>/anonymised/*_anon.txt` for a stage
        # rerun, strip the `_anon` suffix so the document_id matches the rest
        # of the pipeline outputs (e.g. `<iid>_summary.json`).
        interview_id = interview_path.stem
        if interview_id.endswith("_anon"):
            interview_id = interview_id[:-len("_anon")]
        console.rule(f"[bold]{interview_id}")
        t_start = time.time()

        raw_text = interview_path.read_text(encoding="utf-8")
        word_count = len(raw_text.split())
        row = [interview_id, "—", "—", "—"] if is_workshop else [interview_id, "—", "—", "—", "—"]
        timings: dict[str, float] = {}

        try:
            # Stage 1 — anonymise (skipped in workshop mode if user disabled it)
            anon_text, entity_map = None, None
            if "anonymise" in stages and anonymise_enabled:
                (anon_text, entity_map), dur = _run_stage(
                    "anonymise", estimate_seconds("anonymise", word_count),
                    lambda tick: anonymise_transcript(raw_text, cfg, tick_cb=tick),
                )
                (run_dir / "anonymised" / f"{interview_id}_anon.txt").write_text(
                    anon_text, encoding="utf-8"
                )
                (entities_dir / f"{interview_id}_entities.json").write_text(
                    json.dumps(entity_map, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                timings["anonymise"] = dur
                row[1] = "[green]✓[/green]"
                log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "anonymise", "entities": len(entity_map), "duration_s": round(dur, 1)})
            else:
                anon_path = run_dir / "anonymised" / f"{interview_id}_anon.txt"
                if anon_path.exists():
                    anon_text = anon_path.read_text(encoding="utf-8")
                if is_workshop and not anonymise_enabled:
                    row[1] = "[dim]skip[/dim]"

            working_text = anon_text or raw_text

            # Stage 2 — summarise
            if "summarise" in stages:
                summary, dur = _run_stage(
                    "summarise", estimate_seconds("summarise", word_count),
                    lambda tick: summarise(working_text, interview_id, cfg, tick_cb=tick),
                )
                (run_dir / "analysis" / f"{interview_id}_summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                timings["summarise"] = dur
                row[2] = "[green]✓[/green]"
                log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "summarise", "duration_s": round(dur, 1)})

            # Stage 3 — themes (interviews) or questions+demographics (workshop)
            if is_workshop:
                if "questions" in stages:
                    findings, dur = _run_stage(
                        "questions", estimate_seconds("questions", word_count),
                        lambda tick: analyse_questions(working_text, interview_id, cfg, tick_cb=tick),
                    )
                    (run_dir / "analysis" / f"{interview_id}_questions.json").write_text(
                        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    timings["questions"] = dur
                    row[3] = "[green]✓[/green]"
                    log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "questions", "n_questions": len(findings.get("questions", [])), "duration_s": round(dur, 1)})

                if "demographics" in stages:
                    demo, dur = _run_stage(
                        "demographics", estimate_seconds("demographics", word_count),
                        lambda tick: extract_demographics(working_text, interview_id, cfg, tick_cb=tick),
                    )
                    (run_dir / "analysis" / f"{interview_id}_demographics.json").write_text(
                        json.dumps(demo, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    timings["demographics"] = dur
                    log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "demographics", "n_participants": demo.get("n_participants"), "duration_s": round(dur, 1)})
            else:
                if "themes" in stages:
                    themes, dur = _run_stage(
                        "themes", estimate_seconds("themes", word_count),
                        lambda tick: extract_themes(working_text, interview_id, cfg, tick_cb=tick),
                    )
                    (run_dir / "analysis" / f"{interview_id}_themes.json").write_text(
                        json.dumps(themes, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    timings["themes"] = dur
                    row[3] = "[green]✓[/green]"
                    log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "themes", "n_themes": len(themes.get("themes", [])), "duration_s": round(dur, 1)})

                # Stage 4 — sentiment (interviews only; workshop folds sentiment into stage 3)
                if "sentiment" in stages:
                    sentiment, dur = _run_stage(
                        "sentiment", estimate_seconds("sentiment", word_count),
                        lambda tick: analyse_sentiment(working_text, interview_id, cfg, tick_cb=tick),
                    )
                    (run_dir / "analysis" / f"{interview_id}_sentiment.json").write_text(
                        json.dumps(sentiment, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    timings["sentiment"] = dur
                    row[4] = "[green]✓[/green]"
                    log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "sentiment", "duration_s": round(dur, 1)})

        except Exception as exc:
            console.print(f"  [red]ERROR: {exc}[/red]")
            log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "error": str(exc)})

        if timings:
            (run_dir / "analysis" / f"{interview_id}_timings.json").write_text(
                json.dumps(timings, indent=2), encoding="utf-8"
            )

        elapsed = round(time.time() - t_start, 1)
        row.append(str(elapsed))
        results_table.add_row(*row)

    console.print(results_table)


def run_comparison(cfg: dict, run_dir: Path) -> None:
    corpus_dir = run_dir / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    console.rule("[bold]Corpus comparison")

    mode = (cfg.get("mode") or "interviews").lower()
    is_workshop = mode == "workshop"

    analysis_dir = run_dir / "analysis"
    summaries = sorted(analysis_dir.glob("*_summary.json"))
    stage3_files = sorted(analysis_dir.glob(
        "*_questions.json" if is_workshop else "*_themes.json"
    ))

    if not summaries:
        console.print("[yellow]No summary files found — run full pipeline first.[/yellow]")
        return

    # Workshop mode: re-hydrate workshop_ids and potential_duplicates from disk
    # so the LLM prompt has the same FIXED FACTS as a fresh in-UI run. For
    # runs predating the workshop_id feature, assign IDs deterministically
    # from the analysis files' document_ids (sorted) and persist the mapping
    # so subsequent CLI/UI calls stay consistent.
    workshop_ids: dict[str, str] = {}
    potential_duplicates: list[dict] = []
    if is_workshop:
        ws_path = run_dir / "workshops.yaml"
        if ws_path.exists():
            workshop_ids = yaml.safe_load(ws_path.read_text(encoding="utf-8")) or {}
        else:
            doc_ids: list[str] = []
            for sf in summaries:
                try:
                    data = json.loads(sf.read_text(encoding="utf-8"))
                    doc_ids.append(
                        data.get("interview_id") or sf.stem.replace("_summary", "")
                    )
                except Exception:
                    doc_ids.append(sf.stem.replace("_summary", ""))
            doc_ids = sorted(set(doc_ids))
            workshop_ids = {
                doc_id: f"workshop_{i + 1:02d}"
                for i, doc_id in enumerate(doc_ids)
            }
            ws_path.write_text(
                yaml.dump(workshop_ids, allow_unicode=True, sort_keys=True),
                encoding="utf-8",
            )
            console.print(
                f"  [dim]Assigned workshop IDs to {len(workshop_ids)} document(s); "
                f"wrote {ws_path}[/dim]"
            )
        pd_path = corpus_dir / "potential_duplicates.json"
        if pd_path.exists():
            potential_duplicates = json.loads(pd_path.read_text(encoding="utf-8")) or []

    noun = "document" if is_workshop else "interview"
    console.print(f"  Comparing {len(summaries)} {noun}(s)...")
    result, _ = _run_stage(
        "compare", estimate_seconds("compare", n_interviews=len(summaries)),
        lambda tick: build_corpus_comparison(
            summaries, stage3_files, cfg, tick_cb=tick,
            potential_duplicates=potential_duplicates,
            workshop_ids=workshop_ids if is_workshop else None,
        ),
    )
    matrix_name = "questions_matrix.json" if is_workshop else "themes_matrix.json"
    (corpus_dir / matrix_name).write_text(
        json.dumps(result["matrix"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (corpus_dir / "comparison_report.md").write_text(result["report"], encoding="utf-8")
    console.print(f"  [green]Corpus comparison written to {corpus_dir}[/green]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline analysis pipeline (interviews + workshops)")
    parser.add_argument("--interview", type=Path, help="Single transcript/document file to process")
    parser.add_argument("--mode", choices=["interviews", "workshop"],
                        help="Override the mode set in config.yaml")
    parser.add_argument("--questions", type=Path,
                        help="Path to questions.yaml (workshop mode). Overrides config.yaml.")
    parser.add_argument("--compare-only", action="store_true", help="Re-run corpus comparison on existing run")
    parser.add_argument("--run-dir", type=Path, help="Reuse an existing run directory")
    parser.add_argument("--stage", choices=["anonymise", "summarise", "themes", "questions", "demographics", "sentiment"],
                        help="Run only this stage")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()

    if not args.config.exists():
        console.print(f"[red]Config not found: {args.config}[/red]")
        sys.exit(1)

    cfg = load_config(args.config)
    if args.mode:
        cfg["mode"] = args.mode
    if args.questions:
        cfg.setdefault("paths", {})["questions"] = str(args.questions)

    mode = (cfg.get("mode") or "interviews").lower()
    is_workshop = mode == "workshop"

    # Only the `questions` stage actually needs a questions.yaml: --compare-only
    # reads them from the existing *_questions.json files, and the demographics
    # / anonymise / summarise stages are independent of the question list.
    will_run_questions_stage = (
        is_workshop
        and not args.compare_only
        and (args.stage is None or args.stage == "questions")
    )
    if will_run_questions_stage and not cfg.get("paths", {}).get("questions"):
        console.print(
            "[red]Workshop mode (default stages) requires --questions or "
            "paths.questions in config.yaml.[/red]"
        )
        sys.exit(1)

    # Determine output run directory
    if args.run_dir:
        run_dir = args.run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        run_dir = Path(cfg["paths"]["output"]) / ts
        run_dir.mkdir(parents=True, exist_ok=True)

    # Plain-text progress meter for detached runs: `tail -f` to watch.
    set_progress_file(run_dir / ".progress.txt")

    console.print(f"\n[bold]Mode:[/bold] {mode}")
    console.print(f"[bold]Output directory:[/bold] {run_dir}\n")
    console.print(f"[dim]Live progress: tail -f {run_dir}/.progress.txt[/dim]\n")

    if args.compare_only:
        run_comparison(cfg, run_dir)
        return

    # Resolve documents
    if args.interview:
        interviews = [args.interview]
    elif args.stage and args.run_dir:
        # Re-running a single stage against an existing run: iterate over the
        # anonymised files already in the run dir, so we don't need the
        # original raw inputs (which may be gone if uploaded via the UI).
        anon_dir = args.run_dir / "anonymised"
        interviews = sorted(anon_dir.glob("*_anon.txt"))
        if not interviews:
            console.print(
                f"[yellow]No anonymised files found in {anon_dir} — "
                "cannot re-run a stage without inputs.[/yellow]"
            )
            sys.exit(1)
    else:
        interview_dir = Path(cfg["paths"]["interviews"])
        interviews = sorted(interview_dir.glob("*.txt"))
        if not interviews:
            console.print(f"[yellow]No .txt files found in {interview_dir}[/yellow]")
            sys.exit(0)

    default_stages = (
        {"anonymise", "summarise", "questions", "demographics"} if is_workshop
        else {"anonymise", "summarise", "themes", "sentiment"}
    )
    stages = {args.stage} if args.stage else default_stages

    t0 = time.time()
    run_pipeline(cfg, interviews, run_dir, stages)

    last_stage = "questions" if is_workshop else "sentiment"
    if not args.stage or args.stage == last_stage:
        run_comparison(cfg, run_dir)

    total = round(time.time() - t0, 1)
    console.print(f"\n[bold green]Done in {total}s.[/bold green]  Results in: {run_dir}")


if __name__ == "__main__":
    main()
