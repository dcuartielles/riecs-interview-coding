"""
Entry point for the offline interview analysis pipeline.

Usage:
    python main.py                          # process all .txt files in interviews/
    python main.py --interview path/to.txt  # process a single transcript
    python main.py --compare-only           # re-run corpus comparison on existing output
    python main.py --stage anonymise        # run only one stage (anonymise|summarise|themes|sentiment)
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from anonymise import anonymise_transcript
from analyse import summarise, extract_themes, analyse_sentiment
from compare import build_corpus_comparison

console = Console()


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def run_pipeline(cfg: dict, interviews: list[Path], run_dir: Path, stages: set[str]) -> None:
    (run_dir / "anonymised").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis").mkdir(exist_ok=True)
    entities_dir = run_dir / cfg["gdpr"]["entities_subdir"]
    entities_dir.mkdir(exist_ok=True)

    log_path = run_dir / "run_log.jsonl"

    def log(record: dict) -> None:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(record) + "\n")

    results_table = Table(title="Pipeline results", show_lines=True)
    results_table.add_column("Interview", style="cyan")
    results_table.add_column("Anon", justify="center")
    results_table.add_column("Summary", justify="center")
    results_table.add_column("Themes", justify="center")
    results_table.add_column("Sentiment", justify="center")
    results_table.add_column("Time (s)", justify="right")

    for interview_path in interviews:
        interview_id = interview_path.stem
        console.rule(f"[bold]{interview_id}")
        t_start = time.time()

        raw_text = interview_path.read_text(encoding="utf-8")
        row = [interview_id, "—", "—", "—", "—"]

        try:
            # Stage 1 — anonymise
            anon_text, entity_map = None, None
            if "anonymise" in stages:
                console.print(f"  [dim]anonymising...[/dim]")
                anon_text, entity_map = anonymise_transcript(raw_text, cfg)
                (run_dir / "anonymised" / f"{interview_id}_anon.txt").write_text(
                    anon_text, encoding="utf-8"
                )
                (entities_dir / f"{interview_id}_entities.json").write_text(
                    json.dumps(entity_map, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                row[1] = "[green]✓[/green]"
                log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "anonymise", "entities": len(entity_map)})
            else:
                anon_path = run_dir / "anonymised" / f"{interview_id}_anon.txt"
                if anon_path.exists():
                    anon_text = anon_path.read_text(encoding="utf-8")

            working_text = anon_text or raw_text

            # Stage 2 — summarise
            if "summarise" in stages:
                console.print(f"  [dim]summarising...[/dim]")
                summary = summarise(working_text, interview_id, cfg)
                (run_dir / "analysis" / f"{interview_id}_summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                row[2] = "[green]✓[/green]"
                log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "summarise"})

            # Stage 3 — themes
            if "themes" in stages:
                console.print(f"  [dim]extracting themes...[/dim]")
                themes = extract_themes(working_text, interview_id, cfg)
                (run_dir / "analysis" / f"{interview_id}_themes.json").write_text(
                    json.dumps(themes, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                row[3] = "[green]✓[/green]"
                log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "themes", "n_themes": len(themes.get("themes", []))})

            # Stage 4 — sentiment
            if "sentiment" in stages:
                console.print(f"  [dim]analysing sentiment...[/dim]")
                sentiment = analyse_sentiment(working_text, interview_id, cfg)
                (run_dir / "analysis" / f"{interview_id}_sentiment.json").write_text(
                    json.dumps(sentiment, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                row[4] = "[green]✓[/green]"
                log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "stage": "sentiment"})

        except Exception as exc:
            console.print(f"  [red]ERROR: {exc}[/red]")
            log({"ts": datetime.utcnow().isoformat(), "id": interview_id, "error": str(exc)})

        elapsed = round(time.time() - t_start, 1)
        row.append(str(elapsed))
        results_table.add_row(*row)

    console.print(results_table)


def run_comparison(cfg: dict, run_dir: Path) -> None:
    corpus_dir = run_dir / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    console.rule("[bold]Corpus comparison")

    analysis_dir = run_dir / "analysis"
    summaries = sorted(analysis_dir.glob("*_summary.json"))
    themes    = sorted(analysis_dir.glob("*_themes.json"))

    if not summaries:
        console.print("[yellow]No summary files found — run full pipeline first.[/yellow]")
        return

    console.print(f"  Comparing {len(summaries)} interview(s)...")
    result = build_corpus_comparison(summaries, themes, cfg)
    (corpus_dir / "themes_matrix.json").write_text(
        json.dumps(result["matrix"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (corpus_dir / "comparison_report.md").write_text(result["report"], encoding="utf-8")
    console.print(f"  [green]Corpus comparison written to {corpus_dir}[/green]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline interview analysis pipeline")
    parser.add_argument("--interview", type=Path, help="Single transcript file to process")
    parser.add_argument("--compare-only", action="store_true", help="Re-run corpus comparison on existing run")
    parser.add_argument("--run-dir", type=Path, help="Reuse an existing run directory")
    parser.add_argument("--stage", choices=["anonymise", "summarise", "themes", "sentiment"],
                        help="Run only this stage")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()

    if not args.config.exists():
        console.print(f"[red]Config not found: {args.config}[/red]")
        sys.exit(1)

    cfg = load_config(args.config)

    # Determine output run directory
    if args.run_dir:
        run_dir = args.run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        run_dir = Path(cfg["paths"]["output"]) / ts
        run_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Output directory:[/bold] {run_dir}\n")

    if args.compare_only:
        run_comparison(cfg, run_dir)
        return

    # Resolve interviews
    if args.interview:
        interviews = [args.interview]
    else:
        interview_dir = Path(cfg["paths"]["interviews"])
        interviews = sorted(interview_dir.glob("*.txt"))
        if not interviews:
            console.print(f"[yellow]No .txt files found in {interview_dir}[/yellow]")
            sys.exit(0)

    stages = {args.stage} if args.stage else {"anonymise", "summarise", "themes", "sentiment"}

    t0 = time.time()
    run_pipeline(cfg, interviews, run_dir, stages)

    if not args.stage or args.stage == "sentiment":
        run_comparison(cfg, run_dir)

    total = round(time.time() - t0, 1)
    console.print(f"\n[bold green]Done in {total}s.[/bold green]  Results in: {run_dir}")


if __name__ == "__main__":
    main()
