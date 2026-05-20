"""Streamlit UI for the offline interview analysis pipeline."""

import base64
import csv
import io
import json
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
import yaml

INSTALL_DIR  = Path(__file__).parent
PIPELINE_DIR = INSTALL_DIR / "pipeline"
ASSETS_DIR   = INSTALL_DIR / "assets"
sys.path.insert(0, str(PIPELINE_DIR))

from anonymise import anonymise_transcript  # noqa: E402
from analyse import summarise, extract_themes, analyse_sentiment  # noqa: E402
from compare import build_corpus_comparison  # noqa: E402
from timing import (  # noqa: E402
    estimate_seconds,
    format_duration,
    percent_complete,
    stage_label,
)
from charts import theme_cooccurrence_chart, theme_frequency_chart  # noqa: E402


# ── RIECS brand CSS ───────────────────────────────────────────────────────────

_RIECS_CSS = """
<style>
:root {
    --navy:   #2c324c;
    --steel:  #648a9e;
    --sage:   #85ab86;
    --teal:   #376782;
    --cream:  #f5f2ea;
    --white:  #ffffff;
    --muted:  #7a8a9a;
    --border: #dde4ea;
}

/* ── Hide native Streamlit chrome; use our own titlebar ── */
header[data-testid="stHeader"]   { display: none !important; }
[data-testid="stSidebar"]        { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
.stApp { background-color: var(--cream); }
.main .block-container { padding-top: 4.75rem !important; }

/* ── Custom title bar ── */
.riecs-titlebar {
    position: fixed;
    top: 0; left: 0; right: 0;
    height: 3.5rem;
    z-index: 9999;
    background: var(--navy);
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0 1.5rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
}
.riecs-titlebar img         { height: 2rem; width: auto; }
.riecs-titlebar-title       { color: #fff; font-weight: 700; font-size: 1.05rem; line-height: 1.2; }
.riecs-titlebar-sub         { color: #8aa8bc; font-size: 0.7rem; margin-top: 0.05rem; }

/* ── Headings ── */
h1 { color: var(--navy) !important; }
h2 {
    color: var(--navy) !important;
    border-bottom: 2px solid var(--border);
    padding-bottom: 0.4rem;
    margin-bottom: 1rem;
}
h3 { color: var(--navy) !important; }

/* ── Primary button ── */
[data-testid="stBaseButton-primary"], button[kind="primary"] {
    background-color: var(--teal) !important;
    color: var(--white) !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    transition: filter 0.15s;
}
[data-testid="stBaseButton-primary"]:hover, button[kind="primary"]:hover {
    filter: brightness(0.88) !important;
}
[data-testid="stBaseButton-primary"]:disabled,
button[kind="primary"]:disabled { opacity: 0.45 !important; }

/* ── Download button ── */
[data-testid="stDownloadButton"] button {
    background-color: var(--sage) !important;
    color: var(--white) !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
[data-testid="stDownloadButton"] button:hover { filter: brightness(0.90) !important; }

/* ── Progress bar ── */
[data-testid="stProgressBar"] > div {
    background-color: var(--border) !important;
    border-radius: 99px !important;
    height: 10px !important;
}
[data-testid="stProgressBar"] > div > div {
    background-color: var(--teal) !important;
    border-radius: 99px !important;
    transition: width 0.3s ease;
}

/* ── Tabs ── */
[data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 2px solid var(--border) !important;
    gap: 0 !important;
}
[data-baseweb="tab"] {
    color: var(--muted) !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    background: transparent !important;
    border-bottom: 3px solid transparent !important;
    padding: 0.5rem 1.25rem !important;
}
[aria-selected="true"][data-baseweb="tab"] {
    color: var(--teal) !important;
    border-bottom: 3px solid var(--teal) !important;
}
[data-baseweb="tab-highlight"] { display: none !important; }

/* ── Expanders ── */
[data-testid="stExpander"] {
    background: var(--white) !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 8px rgba(44,50,76,0.07) !important;
    border: 1px solid var(--border) !important;
    margin-bottom: 0.5rem;
}
[data-testid="stExpander"] summary {
    color: var(--navy) !important;
    font-weight: 600 !important;
}

/* ── Metrics ── */
[data-testid="stMetricValue"] {
    color: var(--navy) !important;
    font-weight: 700 !important;
    font-size: 1.75rem !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    color: var(--steel) !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(44,50,76,0.07);
}

/* ── Selectbox ── */
[data-testid="stSelectbox"] [data-baseweb="select"] > div:first-child {
    background: var(--white) !important;
    border-color: var(--border) !important;
    border-radius: 6px !important;
}

/* ── File uploader ── */
[data-testid="stFileUploader"] section {
    border: 2px dashed var(--border) !important;
    border-radius: 8px !important;
    background: var(--white) !important;
}
[data-testid="stFileUploader"] section:focus-within,
[data-testid="stFileUploader"] section:hover {
    border-color: var(--teal) !important;
}

/* ── Alert / info banners ── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    border-left: 4px solid var(--steel) !important;
}

/* ── Caption ── */
[data-testid="stCaptionContainer"] {
    color: var(--muted) !important;
    font-size: 0.8rem !important;
}

/* ── Blockquotes ── */
blockquote {
    border-left: 4px solid var(--border);
    padding: 0.5rem 1rem;
    background: #f0f4f7;
    border-radius: 0 6px 6px 0;
    color: var(--steel);
    margin: 0.5rem 0;
}

/* ── Scrollable report pane (Outcomes tab) ── */
.riecs-scroll-pane {
    max-height: 65vh;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem 2rem;
    background: var(--white);
    box-shadow: 0 2px 8px rgba(44,50,76,0.07);
    font-size: 0.92rem;
    line-height: 1.75;
}
.riecs-scroll-pane h2 {
    color: var(--navy);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.3rem;
    margin: 1.5rem 0 0.75rem;
    font-size: 1.1rem;
}
.riecs-scroll-pane h3 {
    color: var(--teal);
    margin: 1.2rem 0 0.4rem;
    font-size: 0.95rem;
}
.riecs-scroll-pane h4 {
    color: var(--steel);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 0.78rem;
    margin: 1rem 0 0.3rem;
}
.riecs-scroll-pane blockquote {
    border-left: 3px solid var(--teal);
    background: #f0f4f7;
    padding: 0.4rem 0.9rem;
    margin: 0.4rem 0;
    color: var(--steel);
    font-style: italic;
    border-radius: 0 4px 4px 0;
}
.riecs-scroll-pane .interview-card {
    border-top: 3px solid var(--teal);
    background: var(--cream);
    border-radius: 0 0 8px 8px;
    padding: 1rem 1.25rem;
    margin: 1.5rem 0;
}
.riecs-scroll-pane .badge {
    display: inline-block; padding: 1px 8px; border-radius: 99px;
    font-size: 0.75rem; font-weight: 600;
}
.tone-positive { background: #d4ead5; color: #1a5c2a; }
.tone-negative { background: #fde8e8; color: #7a2020; }
.tone-neutral  { background: var(--border); color: var(--muted); }
.tone-mixed    { background: #fef6e8; color: #7a4a10; }
.freq-high   { background: #e8f0f5; color: var(--teal); }
.freq-medium { background: #f0f4f7; color: var(--steel); }
.freq-low    { background: #f5f7f9; color: var(--muted); }
</style>
"""

# ── Codebook spreadsheet helpers ─────────────────────────────────────────────

_COL_SYNONYMS = {
    "code":        {"code", "code_name", "code name", "id", "key", "identifier", "theme_code"},
    "label":       {"label", "name", "theme", "theme_name", "theme name", "title", "category"},
    "description": {"description", "definition", "desc", "meaning", "notes", "explanation"},
}


def _auto_detect(headers: list[str], field: str) -> int:
    synonyms = _COL_SYNONYMS[field]
    for i, h in enumerate(headers):
        if h.lower().strip() in synonyms:
            return i
    return 0


def parse_spreadsheet(file_bytes: bytes, filename: str) -> tuple[list[dict], list[str]]:
    ext = Path(filename).suffix.lower()
    if ext in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(
            filename=io.BytesIO(file_bytes), read_only=True, data_only=True
        )
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            return [], []
        headers = [str(h).strip() if h is not None else f"col_{i}"
                   for i, h in enumerate(all_rows[0])]
        data = [
            {h: (str(v).strip() if v is not None else "") for h, v in zip(headers, row)}
            for row in all_rows[1:]
            if any(v not in (None, "") for v in row)
        ]
        return data, headers
    else:
        text = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        data = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
        headers = list(reader.fieldnames or [])
        return data, headers


def codebook_rows_to_yaml(
    rows: list[dict],
    code_col: str,
    label_col: str,
    desc_col: str,
) -> str:
    entries = []
    for row in rows:
        entry: dict = {}
        if row.get(code_col):
            entry["code"] = row[code_col]
        if row.get(label_col):
            entry["label"] = row[label_col]
        if row.get(desc_col):
            entry["description"] = row[desc_col]
        for k, v in row.items():
            if k not in (code_col, label_col, desc_col) and v:
                entry[k] = v
        if entry:
            entries.append(entry)
    return yaml.dump(entries, allow_unicode=True, default_flow_style=False)


# ── Transcript reader ─────────────────────────────────────────────────────────

def read_transcript(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        from docx import Document
        doc = Document(path)
        lines = []
        for block in doc.element.body:
            tag = block.tag.split("}")[-1]
            if tag == "p":
                text = "".join(t.text or "" for t in block.iter() if t.tag.endswith("}t"))
                if text.strip():
                    lines.append(text)
            elif tag == "tbl":
                for tr in block.iter():
                    if tr.tag.endswith("}tr"):
                        seen: set[int] = set()
                        cells = []
                        for tc in tr.iter():
                            if tc.tag.endswith("}tc") and id(tc) not in seen:
                                seen.add(id(tc))
                                cell_text = "".join(
                                    t.text or "" for t in tc.iter() if t.tag.endswith("}t")
                                )
                                if cell_text.strip():
                                    cells.append(cell_text.strip())
                        if cells:
                            lines.append(" | ".join(cells))
        return "\n\n".join(lines)
    else:
        return path.read_text(encoding="utf-8")


# ── Config ────────────────────────────────────────────────────────────────────

def load_cfg(codebook_path: Path | None = None) -> dict:
    cfg = yaml.safe_load((INSTALL_DIR / "config.yaml").read_text())
    if codebook_path:
        cfg.setdefault("paths", {})["codebook"] = str(codebook_path)
    return cfg


# ── Per-interview pipeline helpers ────────────────────────────────────────────

def _process_one_interview(
    interview_path: Path,
    run_dir: Path,
    cfg: dict,
    on_stage_start,
    on_stage_tick,
    on_stage_done,
) -> dict:
    iid          = interview_path.stem
    entities_dir = run_dir / cfg["gdpr"]["entities_subdir"]
    result: dict = {}

    raw_text   = read_transcript(interview_path)
    word_count = len(raw_text.split())
    timings: dict = {}

    def run_stage(stage: str, fn):
        estimate = estimate_seconds(stage, word_count)
        on_stage_start(stage, estimate)
        t0 = time.time()

        def tick(tokens, elapsed, note=""):
            on_stage_tick(stage, elapsed, estimate, tokens, note)

        out = fn(tick)
        duration = time.time() - t0
        timings[stage] = duration
        on_stage_done(stage, duration)
        return out

    anon_text, entity_map = run_stage(
        "anonymise",
        lambda tick: anonymise_transcript(raw_text, cfg, tick_cb=tick),
    )
    (run_dir / "anonymised" / f"{iid}_anon.txt").write_text(anon_text, encoding="utf-8")
    (entities_dir / f"{iid}_entities.json").write_text(
        json.dumps(entity_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = run_stage(
        "summarise",
        lambda tick: summarise(anon_text, iid, cfg, tick_cb=tick),
    )
    (run_dir / "analysis" / f"{iid}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["summary"] = summary

    themes = run_stage(
        "themes",
        lambda tick: extract_themes(anon_text, iid, cfg, tick_cb=tick),
    )
    (run_dir / "analysis" / f"{iid}_themes.json").write_text(
        json.dumps(themes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["themes"] = themes

    sentiment = run_stage(
        "sentiment",
        lambda tick: analyse_sentiment(anon_text, iid, cfg, tick_cb=tick),
    )
    (run_dir / "analysis" / f"{iid}_sentiment.json").write_text(
        json.dumps(sentiment, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["sentiment"] = sentiment

    (run_dir / "analysis" / f"{iid}_timings.json").write_text(
        json.dumps(timings, indent=2), encoding="utf-8"
    )
    result["_timings"] = timings
    return result


def _load_interview_results(iid: str, run_dir: Path) -> dict:
    result: dict = {}
    for key, suffix in [("summary", "_summary"), ("themes", "_themes"), ("sentiment", "_sentiment")]:
        f = run_dir / "analysis" / f"{iid}{suffix}.json"
        if f.exists():
            result[key] = json.loads(f.read_text(encoding="utf-8"))
    timings_f = run_dir / "analysis" / f"{iid}_timings.json"
    if timings_f.exists():
        result["_timings"] = json.loads(timings_f.read_text(encoding="utf-8"))
    return result


def _write_checkpoint(
    run_dir: Path,
    work_dir: Path,
    all_interviews: list[str],
    codebook_path,
    completed: list[str],
) -> None:
    cp = {
        "run_dir":       str(run_dir),
        "work_dir":      str(work_dir),
        "interviews":    all_interviews,
        "codebook_path": str(codebook_path) if codebook_path else None,
        "completed":     completed,
    }
    (run_dir / "checkpoint.json").write_text(json.dumps(cp, indent=2), encoding="utf-8")


def _find_resumable_run() -> dict | None:
    output_dir = INSTALL_DIR / "output"
    if not output_dir.exists():
        return None
    for cp_file in sorted(output_dir.glob("*/checkpoint.json"), reverse=True):
        try:
            cp         = json.loads(cp_file.read_text(encoding="utf-8"))
            completed  = cp.get("completed", [])
            interviews = cp.get("interviews", [])
            if completed and len(completed) < len(interviews) and Path(cp["work_dir"]).exists():
                return cp
        except Exception:
            continue
    return None


# ── HTML report ───────────────────────────────────────────────────────────────

def _logo_data_uri() -> str:
    p = ASSETS_DIR / "riecs-glyph.png"
    if p.exists():
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    return ""


def _md_to_html(text: str) -> str:
    text = re.sub(r"^### (.+)$", r"<h4>\1</h4>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$",  r"<h3>\1</h3>",  text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$",   r"<h2>\1</h2>",   text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    lines = text.split("\n")
    out, in_list = [], False
    for line in lines:
        if re.match(r"^- .+", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(re.sub(r"^- (.+)", r"<li>\1</li>", line))
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(line)
    if in_list:
        out.append("</ul>")
    text = "\n".join(out)
    text = re.sub(r"\n{2,}", "</p><p>", text)
    return f"<p>{text}</p>"


_REPORT_CSS = """
:root{--navy:#2c324c;--steel:#648a9e;--sage:#85ab86;--teal:#376782;
      --cream:#f5f2ea;--white:#fff;--muted:#7a8a9a;--border:#dde4ea}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--cream);
     color:var(--navy);line-height:1.6;min-height:100vh}
.page{max-width:960px;margin:0 auto;padding:2rem 1.5rem}
.report-header{display:flex;align-items:center;gap:1rem;background:var(--navy);
  color:#fff;padding:1rem 1.5rem;border-radius:12px;margin-bottom:1.5rem}
.report-header img{height:3rem;width:auto}
.report-header h1{font-size:1.3rem;color:#fff;margin:0}
.report-header .sub{font-size:0.78rem;text-transform:uppercase;
  letter-spacing:0.08em;color:#648a9e;margin-top:0.15rem}
.report-meta{font-size:0.78rem;color:var(--muted);margin-bottom:2rem}
h2{color:var(--navy);border-bottom:2px solid var(--border);
   padding-bottom:0.4rem;margin:2rem 0 1rem}
h3{color:var(--navy);margin:1.5rem 0 0.5rem}
h4{color:var(--steel);margin:1rem 0 0.4rem;font-size:0.85rem;
   text-transform:uppercase;letter-spacing:0.05em}
.card{background:var(--white);border-radius:12px;padding:1.5rem;
  box-shadow:0 2px 8px rgba(44,50,76,0.07);margin-bottom:1.5rem;
  border-top:4px solid var(--teal)}
blockquote{margin:.5rem 0;padding:.5rem 1rem;
  border-left:4px solid var(--border);background:#f0f4f7;
  border-radius:0 6px 6px 0;color:var(--steel);font-size:.9rem}
ul{padding-left:1.5rem;margin:.4rem 0}li{margin:.25rem 0}
table{border-collapse:collapse;width:100%;margin:.75rem 0;font-size:.88rem;
  background:var(--white);border-radius:8px;overflow:hidden;
  box-shadow:0 2px 8px rgba(44,50,76,0.07)}
th{background:#f0f4f7;text-align:left;padding:.55rem .75rem;
   border:1px solid var(--border);font-size:.78rem;
   text-transform:uppercase;letter-spacing:.05em;color:var(--steel)}
td{padding:.5rem .75rem;border:1px solid var(--border)}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;
  font-size:.78rem;font-weight:600}
.tone-positive{background:#d4ead5;color:#1a5c2a}
.tone-negative{background:#fde8e8;color:#7a2020}
.tone-neutral{background:var(--border);color:var(--muted)}
.tone-mixed{background:#fef6e8;color:#7a4a10}
.freq-high{background:#e8f0f5;color:var(--teal)}
.freq-medium{background:#f0f4f7;color:var(--steel)}
.freq-low{background:#f5f7f9;color:var(--muted)}
code{background:#f0f4f7;padding:1px 5px;border-radius:3px;font-size:.85em}
.meta{color:var(--muted);font-size:.8rem}
a{color:var(--teal);text-decoration:none}
"""


def _interview_stats(interviews: dict) -> list[dict]:
    """Per-interview stats for the report's 'Files Evaluated' section."""
    stats = []
    for iid, data in interviews.items():
        summary = data.get("summary", {}) or {}
        themes  = (data.get("themes", {}) or {}).get("themes", []) or []
        timings = data.get("_timings", {}) or {}
        stats.append({
            "id":       iid,
            "words":    summary.get("word_count"),
            "n_themes": len(themes),
            "seconds":  sum(timings.values()) if timings else None,
        })
    return stats


def generate_html_report(run_dir: Path, results: dict) -> str:
    now      = datetime.now().strftime("%Y-%m-%d %H:%M")
    corpus   = results.get("_corpus", {})
    interviews = {k: v for k, v in results.items() if k != "_corpus"}
    logo_uri = _logo_data_uri()
    logo_img = f'<img src="{logo_uri}" alt="RIECS">' if logo_uri else ""

    parts = [
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<title>Interview Analysis Report — {now}</title>'
        f'<style>{_REPORT_CSS}</style></head><body><div class="page">'
        f'<div class="report-header">{logo_img}'
        f'<div><h1>Interview Analysis Report</h1>'
        f'<div class="sub">RIECS — offline analysis</div></div></div>'
        f'<p class="report-meta">Generated {now} &mdash; {len(interviews)} interview(s)'
        f' &mdash; output: {run_dir}</p>'
    ]

    stats = _interview_stats(interviews)
    if stats:
        rows = ""
        for s in stats:
            secs = format_duration(s["seconds"]) if s["seconds"] else "&mdash;"
            rows += (
                f'<tr><td>{s["id"]}</td>'
                f'<td>{s["words"] if s["words"] is not None else "&mdash;"}</td>'
                f'<td>{s["n_themes"]}</td><td>{secs}</td></tr>'
            )
        if corpus.get("_duration"):
            rows += (
                f'<tr><td><em>Corpus comparison</em></td><td>&mdash;</td>'
                f'<td>&mdash;</td><td>{format_duration(corpus["_duration"])}</td></tr>'
            )
        parts.append(
            f'<h2>Files Evaluated</h2><table>'
            f'<tr><th>Interview</th><th>Words</th><th>Themes</th>'
            f'<th>Processing time</th></tr>{rows}</table>'
        )

    if corpus.get("report"):
        parts.append(f'<h2>Executive Summary</h2>{_md_to_html(corpus["report"])}')

    matrix_codes = corpus.get("matrix", {}).get("codes", {})
    if matrix_codes:
        iids   = sorted({iid for c in matrix_codes.values() for iid in c["by_interview"]})
        header = (
            "<tr><th>Theme</th><th>Code</th>"
            + "".join(f"<th>{i}</th>" for i in iids)
            + "<th>Interviews</th></tr>"
        )
        rows = "".join(
            f'<tr><td>{info["label"]}</td><td><code>{code}</code></td>'
            + "".join(f'<td>{info["by_interview"].get(i,"&mdash;")}</td>' for i in iids)
            + f'<td>{info["total_interviews"]}</td></tr>'
            for code, info in matrix_codes.items()
        )
        parts.append(f'<h2>Theme Matrix</h2><table>{header}{rows}</table>')

    if matrix_codes:
        freq_png = theme_frequency_chart(matrix_codes)
        if freq_png:
            b64 = base64.b64encode(freq_png).decode()
            parts.append(
                f'<h2>Theme Relevance</h2>'
                f'<img src="data:image/png;base64,{b64}" '
                f'style="max-width:100%;height:auto" alt="Theme relevance chart">'
            )
        cooc_png = theme_cooccurrence_chart(matrix_codes)
        if cooc_png:
            b64 = base64.b64encode(cooc_png).decode()
            parts.append(
                f'<h2>Theme Co-occurrence</h2>'
                f'<img src="data:image/png;base64,{b64}" '
                f'style="max-width:100%;height:auto" alt="Theme co-occurrence map">'
            )

    for iid, data in interviews.items():
        parts.append(
            f'<div class="card">'
            f'<h2 style="border:none;margin-top:0">Interview: {iid}</h2>'
        )
        s = data.get("summary", {})
        if s:
            parts.append(
                f'<h3>Summary</h3>'
                f'<p><strong>Estimated duration:</strong> {s.get("estimated_duration_min","&mdash;")} min'
                f' &nbsp;|&nbsp; <strong>Word count:</strong> {s.get("word_count","&mdash;")}</p>'
            )
            if s.get("key_topics"):
                items = "".join(
                    f'<li><strong>{t["topic"]}</strong>: {t.get("brief_description","")}</li>'
                    if isinstance(t, dict) else f"<li>{t}</li>"
                    for t in s["key_topics"]
                )
                parts.append(f'<h4>Key topics</h4><ul>{items}</ul>')
            if s.get("main_positions"):
                items = "".join(f"<li>{p}</li>" for p in s["main_positions"])
                parts.append(f'<h4>Main positions</h4><ul>{items}</ul>')
            if s.get("notable_quotes"):
                quotes = "".join(f"<blockquote>{q}</blockquote>" for q in s["notable_quotes"])
                parts.append(f'<h4>Notable quotes</h4>{quotes}')
            if s.get("methodological_notes"):
                parts.append(f'<p class="meta"><em>{s["methodological_notes"]}</em></p>')

        t = data.get("themes", {})
        if t.get("themes"):
            parts.append("<h3>Themes</h3>")
            for theme in t["themes"]:
                freq  = theme.get("frequency", "")
                sub   = (f'<p class="meta">Sub-themes: {", ".join(theme["sub_themes"])}</p>'
                         if theme.get("sub_themes") else "")
                quotes = "".join(
                    f"<blockquote>{q}</blockquote>"
                    for q in theme.get("supporting_quotes", [])[:3]
                )
                parts.append(
                    f'<h4>{theme.get("label", theme.get("code",""))}'
                    f' <code>{theme.get("code","")}</code>'
                    f' <span class="badge freq-{freq}">{freq}</span></h4>'
                    f'<p>{theme.get("description","")}</p>{sub}{quotes}'
                )
            if t.get("new_codes_proposed"):
                parts.append(
                    f'<p class="meta"><em>New codes proposed: '
                    f'{", ".join(t["new_codes_proposed"])}</em></p>'
                )

        sent = data.get("sentiment", {})
        if sent:
            tone = sent.get("overall_tone", "neutral")
            parts.append(
                f'<h3>Sentiment</h3>'
                f'<p>Overall tone: <span class="badge tone-{tone}">{tone}</span>'
                f' &nbsp; Confidence: {sent.get("confidence","&mdash;")}'
                f' &nbsp; Register: {sent.get("emotional_register","&mdash;")}</p>'
            )
            if sent.get("topic_sentiments"):
                ts_rows = "".join(
                    f'<tr><td>{ts.get("topic","")}</td>'
                    f'<td><span class="badge tone-{ts.get("tone","neutral")}">'
                    f'{ts.get("tone","")}</span></td>'
                    f'<td>{ts.get("notes","")}</td></tr>'
                    for ts in sent["topic_sentiments"]
                )
                parts.append(
                    f'<table><tr><th>Topic</th><th>Tone</th><th>Notes</th></tr>'
                    f'{ts_rows}</table>'
                )
            if sent.get("notable_passages"):
                passages = "".join(
                    f"<blockquote>{p}</blockquote>" for p in sent["notable_passages"]
                )
                parts.append(f'<h4>Notable passages</h4>{passages}')

        parts.append("</div>")

    parts.append("</div></body></html>")
    return "\n".join(parts)


# ── DOCX report ───────────────────────────────────────────────────────────────

def generate_docx_report(run_dir: Path, results: dict) -> bytes:
    from docx import Document as DocxDoc
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = DocxDoc()
    corpus     = results.get("_corpus", {})
    interviews = {k: v for k, v in results.items() if k != "_corpus"}
    now        = datetime.now().strftime("%Y-%m-%d %H:%M")

    t = doc.add_heading("Interview Analysis Report", 0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generated: {now}").italic = True
    doc.add_paragraph(f"Output: {run_dir}").italic = True

    stats = _interview_stats(interviews)
    if stats:
        doc.add_heading("Files Evaluated", 1)
        tbl = doc.add_table(rows=1, cols=4)
        tbl.style = "Table Grid"
        for i, head in enumerate(["Interview", "Words", "Themes", "Processing time"]):
            cell = tbl.rows[0].cells[i]
            cell.text = head
            for r in cell.paragraphs[0].runs:
                r.bold = True
        for s in stats:
            row = tbl.add_row().cells
            row[0].text = s["id"]
            row[1].text = str(s["words"]) if s["words"] is not None else "—"
            row[2].text = str(s["n_themes"])
            row[3].text = format_duration(s["seconds"]) if s["seconds"] else "—"
        if corpus.get("_duration"):
            row = tbl.add_row().cells
            row[0].text = "Corpus comparison"
            row[1].text = "—"
            row[2].text = "—"
            row[3].text = format_duration(corpus["_duration"])

    if corpus.get("report"):
        doc.add_heading("Executive Summary", 1)
        for line in corpus["report"].split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                doc.add_heading(stripped[3:], 2)
            elif stripped.startswith("# "):
                doc.add_heading(stripped[2:], 1)
            elif stripped.startswith("- "):
                doc.add_paragraph(stripped[2:], style="List Bullet")
            elif stripped:
                doc.add_paragraph(stripped)

    matrix_codes = corpus.get("matrix", {}).get("codes", {})
    if matrix_codes:
        doc.add_heading("Theme Matrix", 1)
        iids  = sorted({iid for c in matrix_codes.values() for iid in c["by_interview"]})
        ncols = 2 + len(iids) + 1
        tbl   = doc.add_table(rows=1, cols=ncols)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        hdr[0].text = "Theme"
        hdr[1].text = "Code"
        for i, iid in enumerate(iids):
            hdr[2 + i].text = iid
        hdr[ncols - 1].text = "# Interviews"
        for code, info in matrix_codes.items():
            row = tbl.add_row().cells
            row[0].text = info.get("label", "")
            row[1].text = code
            for i, iid in enumerate(iids):
                row[2 + i].text = str(info["by_interview"].get(iid, ""))
            row[ncols - 1].text = str(info.get("total_interviews", ""))

    if matrix_codes:
        freq_png = theme_frequency_chart(matrix_codes)
        if freq_png:
            doc.add_heading("Theme Relevance", 1)
            doc.add_picture(io.BytesIO(freq_png), width=Inches(6.2))
        cooc_png = theme_cooccurrence_chart(matrix_codes)
        if cooc_png:
            doc.add_heading("Theme Co-occurrence", 1)
            doc.add_picture(io.BytesIO(cooc_png), width=Inches(5.6))

    for iid, data in interviews.items():
        doc.add_heading(f"Interview: {iid}", 1)

        s = data.get("summary", {})
        if s:
            doc.add_heading("Summary", 2)
            doc.add_paragraph(
                f"Estimated duration: {s.get('estimated_duration_min', '—')} min"
                f"  |  Word count: {s.get('word_count', '—')}"
            )
            if s.get("key_topics"):
                doc.add_heading("Key Topics", 3)
                for topic in s["key_topics"]:
                    if isinstance(topic, dict):
                        p = doc.add_paragraph(style="List Bullet")
                        run = p.add_run(f"{topic['topic']}: ")
                        run.bold = True
                        p.add_run(topic.get("brief_description", ""))
                    else:
                        doc.add_paragraph(str(topic), style="List Bullet")
            if s.get("main_positions"):
                doc.add_heading("Main Positions", 3)
                for pos in s["main_positions"]:
                    doc.add_paragraph(str(pos), style="List Bullet")
            if s.get("notable_quotes"):
                doc.add_heading("Notable Quotes", 3)
                for q in s["notable_quotes"]:
                    p = doc.add_paragraph(f'"{q}"')
                    p.runs[0].italic = True
            if s.get("methodological_notes"):
                p = doc.add_paragraph(s["methodological_notes"])
                p.runs[0].italic = True

        themes = data.get("themes", {})
        if themes.get("themes"):
            doc.add_heading("Themes", 2)
            for theme in themes["themes"]:
                label = theme.get("label", theme.get("code", ""))
                freq  = theme.get("frequency", "")
                h = doc.add_heading(f"{label}  [{freq}]", 3)
                doc.add_paragraph(theme.get("description", ""))
                if theme.get("sub_themes"):
                    doc.add_paragraph("Sub-themes: " + ", ".join(theme["sub_themes"]))
                for q in theme.get("supporting_quotes", [])[:3]:
                    p = doc.add_paragraph(f'"{q}"')
                    p.runs[0].italic = True
            if themes.get("new_codes_proposed"):
                doc.add_paragraph("New codes proposed: " + ", ".join(themes["new_codes_proposed"]))

        sent = data.get("sentiment", {})
        if sent:
            doc.add_heading("Sentiment", 2)
            doc.add_paragraph(
                f"Overall tone: {sent.get('overall_tone', '—')}"
                f"  |  Confidence: {sent.get('confidence', '—')}"
                f"  |  Register: {sent.get('emotional_register', '—')}"
            )
            if sent.get("topic_sentiments"):
                for ts in sent["topic_sentiments"]:
                    notes = f" — {ts['notes']}" if ts.get("notes") else ""
                    doc.add_paragraph(
                        f"{ts.get('topic', '')}: {ts.get('tone', '')}{notes}",
                        style="List Bullet",
                    )
            if sent.get("notable_passages"):
                doc.add_heading("Notable Passages", 3)
                for passage in sent["notable_passages"]:
                    p = doc.add_paragraph(f'"{passage}"')
                    p.runs[0].italic = True

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Scrollable pane HTML builder ──────────────────────────────────────────────

def _report_highlights_html(results: dict) -> str:
    corpus     = results.get("_corpus", {})
    interviews = {k: v for k, v in results.items() if k != "_corpus"}
    parts: list[str] = []

    if corpus.get("report"):
        parts.append(f'<h2>Executive Summary</h2>{_md_to_html(corpus["report"])}')

    matrix_codes = corpus.get("matrix", {}).get("codes", {})
    if matrix_codes:
        iids   = sorted({iid for c in matrix_codes.values() for iid in c["by_interview"]})
        header = (
            "<tr><th>Theme</th><th>Code</th>"
            + "".join(f"<th>{i}</th>" for i in iids)
            + "<th>Interviews</th></tr>"
        )
        rows = "".join(
            f'<tr><td>{info["label"]}</td><td><code>{code}</code></td>'
            + "".join(f'<td>{info["by_interview"].get(i, "&mdash;")}</td>' for i in iids)
            + f'<td>{info["total_interviews"]}</td></tr>'
            for code, info in matrix_codes.items()
        )
        parts.append(
            f'<h2>Theme Matrix</h2>'
            f'<table style="border-collapse:collapse;width:100%;font-size:.85rem">'
            f'<thead style="background:#f0f4f7">{header}</thead>'
            f'<tbody>{rows}</tbody></table>'
        )

    for iid, data in interviews.items():
        card: list[str] = [f'<div class="interview-card"><h2>{iid}</h2>']

        s = data.get("summary", {})
        if s:
            card.append(
                f'<h3>Summary</h3>'
                f'<p><strong>Duration (est.):</strong> {s.get("estimated_duration_min","—")} min'
                f' &nbsp;|&nbsp; <strong>Words:</strong> {s.get("word_count","—")}</p>'
            )
            if s.get("key_topics"):
                items = "".join(
                    f'<li><strong>{t["topic"]}</strong>: {t.get("brief_description","")}</li>'
                    if isinstance(t, dict) else f"<li>{t}</li>"
                    for t in s["key_topics"]
                )
                card.append(f'<h4>Key topics</h4><ul>{items}</ul>')
            if s.get("main_positions"):
                card.append('<h4>Main positions</h4><ul>'
                            + "".join(f"<li>{p}</li>" for p in s["main_positions"])
                            + "</ul>")
            if s.get("notable_quotes"):
                card.append('<h4>Notable quotes</h4>'
                            + "".join(f"<blockquote>{q}</blockquote>"
                                      for q in s["notable_quotes"]))

        themes = data.get("themes", {})
        if themes.get("themes"):
            card.append("<h3>Themes</h3>")
            for theme in themes["themes"]:
                freq = theme.get("frequency", "")
                card.append(
                    f'<h4>{theme.get("label", theme.get("code",""))}'
                    f' <code>{theme.get("code","")}</code>'
                    f' <span class="badge freq-{freq}">{freq}</span></h4>'
                    f'<p>{theme.get("description","")}</p>'
                )
                for q in theme.get("supporting_quotes", [])[:2]:
                    card.append(f"<blockquote>{q}</blockquote>")

        sent = data.get("sentiment", {})
        if sent:
            tone = sent.get("overall_tone", "neutral")
            card.append(
                f'<h3>Sentiment</h3>'
                f'<p>Tone: <span class="badge tone-{tone}">{tone}</span>'
                f' &nbsp; Confidence: {sent.get("confidence","—")}'
                f' &nbsp; Register: {sent.get("emotional_register","—")}</p>'
            )
            if sent.get("notable_passages"):
                card.append("".join(
                    f"<blockquote>{p}</blockquote>" for p in sent["notable_passages"]
                ))

        card.append("</div>")
        parts.append("".join(card))

    return "\n".join(parts)


# ── Streamlit app ─────────────────────────────────────────────────────────────

_favicon = ASSETS_DIR / "favicon.ico"
st.set_page_config(
    page_title="Interview Analyser — RIECS",
    page_icon=str(_favicon) if _favicon.exists() else "📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(_RIECS_CSS, unsafe_allow_html=True)

# Custom title bar
_logo_uri = _logo_data_uri()
_logo_img = f'<img src="{_logo_uri}" alt="RIECS">' if _logo_uri else ""
st.markdown(
    f'<div class="riecs-titlebar">'
    f'{_logo_img}'
    f'<div>'
    f'<div class="riecs-titlebar-title">Interview Analyser</div>'
    f'<div class="riecs-titlebar-sub">Fully offline — all processing happens on this machine</div>'
    f'</div></div>',
    unsafe_allow_html=True,
)

for key, default in [
    ("results", None), ("run_dir", None), ("running", False),
    ("work_dir", None), ("pending", []), ("partial_results", {}),
    ("all_interviews", []), ("codebook_path", None), ("stop_requested", False),
    ("cb_rows", None), ("cb_headers", None),
    ("cb_code_col", None), ("cb_label_col", None), ("cb_desc_col", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_progress, tab_outcomes = st.tabs(["Progress", "Outcomes"])

# ── Progress tab ──────────────────────────────────────────────────────────────

with tab_progress:
    col_inputs, col_status = st.columns(2, gap="large")

    # ── Left column: file inputs + run/stop/resume controls ──────────────────

    with col_inputs:
        st.subheader("Transcripts")
        uploaded_txts = st.file_uploader(
            "Interview files",
            type=["txt", "docx"],
            accept_multiple_files=True,
            help="Drag and drop plain-text or Word transcript files.",
            label_visibility="collapsed",
            disabled=st.session_state.running,
        )

        st.subheader("Labelbook")
        uploaded_codebook = st.file_uploader(
            "Labelbook file",
            type=["xlsx", "xls", "csv", "yaml", "yml"],
            help="Excel, CSV, or YAML codebook — optional.",
            label_visibility="collapsed",
            disabled=st.session_state.running,
        )

        if uploaded_codebook and not st.session_state.running:
            ext = Path(uploaded_codebook.name).suffix.lower()
            if ext in (".xlsx", ".xls", ".csv"):
                file_bytes = uploaded_codebook.read()
                rows, headers = parse_spreadsheet(file_bytes, uploaded_codebook.name)
                if rows and headers:
                    if st.session_state.cb_headers != headers:
                        st.session_state.cb_rows      = rows
                        st.session_state.cb_headers   = headers
                        st.session_state.cb_code_col  = headers[_auto_detect(headers, "code")]
                        st.session_state.cb_label_col = headers[_auto_detect(headers, "label")]
                        st.session_state.cb_desc_col  = headers[_auto_detect(headers, "description")]

                    with st.expander(f"{len(rows)} codes — map columns", expanded=False):
                        st.session_state.cb_code_col = st.selectbox(
                            "Code column", headers,
                            index=headers.index(st.session_state.cb_code_col),
                            key="sel_code",
                        )
                        st.session_state.cb_label_col = st.selectbox(
                            "Label column", headers,
                            index=headers.index(st.session_state.cb_label_col),
                            key="sel_label",
                        )
                        st.session_state.cb_desc_col = st.selectbox(
                            "Description column", headers,
                            index=headers.index(st.session_state.cb_desc_col),
                            key="sel_desc",
                        )
                        st.caption("Preview (first 3 codes)")
                        for r in rows[:3]:
                            code  = r.get(st.session_state.cb_code_col, "")
                            label = r.get(st.session_state.cb_label_col, "")
                            st.write(f"- `{code}` — {label}")
                else:
                    st.warning("Could not read rows from the uploaded file.")
            else:
                st.session_state.cb_rows    = uploaded_codebook.read()
                st.session_state.cb_headers = None
        elif not uploaded_codebook and not st.session_state.running:
            st.session_state.cb_rows    = None
            st.session_state.cb_headers = None

        st.divider()

        if st.session_state.running:
            # Stop button — queued click is processed on next rerun after current LLM call
            stop_btn = st.button(
                "Stop after this interview",
                type="secondary",
                use_container_width=True,
            )
            if stop_btn:
                st.session_state.stop_requested = True
            st.caption("The current LLM call will finish before stopping. All progress is saved.")

        else:
            run_btn = st.button(
                "Run Analysis",
                type="primary",
                disabled=not uploaded_txts,
                use_container_width=True,
            )

            # Resume button — only show when a partial run exists
            _resumable = _find_resumable_run()
            if _resumable and not st.session_state.results:
                _n_done  = len(_resumable.get("completed", []))
                _n_total = len(_resumable.get("interviews", []))
                resume_btn = st.button(
                    f"↺  Resume last run  ({_n_done} / {_n_total} done)",
                    use_container_width=True,
                )
                if resume_btn:
                    _run_dir  = Path(_resumable["run_dir"])
                    _work_dir = Path(_resumable["work_dir"])
                    _partial  = {}
                    for _fname in _resumable.get("completed", []):
                        _iid = Path(_fname).stem
                        _partial[_iid] = _load_interview_results(_iid, _run_dir)
                    _pending = [
                        str(_work_dir / _f)
                        for _f in _resumable["interviews"]
                        if _f not in _resumable.get("completed", [])
                    ]
                    st.session_state.run_dir        = _run_dir
                    st.session_state.work_dir       = str(_work_dir)
                    st.session_state.pending        = _pending
                    st.session_state.all_interviews = _resumable["interviews"]
                    st.session_state.codebook_path  = _resumable.get("codebook_path")
                    st.session_state.partial_results = _partial
                    st.session_state.stop_requested = False
                    st.session_state.running        = True
                    st.session_state.results        = None
                    st.rerun()

            # ── Start new run ────────────────────────────────────────────────
            if run_btn and uploaded_txts:
                _run_id = datetime.now().strftime("%Y-%m-%d_%H-%M")
                _work   = INSTALL_DIR / "work" / _run_id
                _work.mkdir(parents=True, exist_ok=True)

                _paths = []
                for _f in uploaded_txts:
                    _dest = _work / _f.name
                    _dest.write_bytes(_f.read())
                    _paths.append(_dest)

                _cb_path = None
                if st.session_state.cb_rows is not None:
                    _cb_path = _work / "codebook.yaml"
                    if isinstance(st.session_state.cb_rows, (bytes, bytearray)):
                        _cb_path.write_bytes(st.session_state.cb_rows)
                    else:
                        _cb_path.write_text(
                            codebook_rows_to_yaml(
                                st.session_state.cb_rows,
                                st.session_state.cb_code_col,
                                st.session_state.cb_label_col,
                                st.session_state.cb_desc_col,
                            ),
                            encoding="utf-8",
                        )

                _cfg     = load_cfg(_cb_path)
                _run_dir = INSTALL_DIR / "output" / _run_id
                (_run_dir / "anonymised").mkdir(parents=True, exist_ok=True)
                (_run_dir / "analysis").mkdir(exist_ok=True)
                (_run_dir / _cfg["gdpr"]["entities_subdir"]).mkdir(exist_ok=True)

                st.session_state.run_dir        = _run_dir
                st.session_state.work_dir       = str(_work)
                st.session_state.pending        = [str(p) for p in _paths]
                st.session_state.all_interviews = [p.name for p in _paths]
                st.session_state.codebook_path  = str(_cb_path) if _cb_path else None
                st.session_state.partial_results = {}
                st.session_state.stop_requested = False
                st.session_state.running        = True
                st.session_state.results        = None
                st.rerun()

    # ── Right column: live status ─────────────────────────────────────────────

    with col_status:
        if st.session_state.running:
            _pending  = st.session_state.pending or []
            _partial  = st.session_state.partial_results or {}
            _all_ivs  = st.session_state.all_interviews or []
            _n_done   = len(_partial)
            _n_total  = len(_all_ivs)

            st.progress(
                _n_done / _n_total if _n_total else 0.0,
                text=f"**{_n_done} of {_n_total}** interviews complete",
            )

            for _fname in _all_ivs:
                _iid = Path(_fname).stem
                if _iid in _partial:
                    st.markdown(f"✅ &nbsp; **{_iid}**")
                elif _pending and Path(_pending[0]).stem == _iid:
                    st.markdown(f"🔄 &nbsp; **{_iid}** — processing…")
                else:
                    st.markdown(f"⏳ &nbsp; {_iid}")

            st.divider()

            # Honour stop request (queued button click from previous run)
            if st.session_state.stop_requested:
                st.session_state.running        = False
                st.session_state.stop_requested = False
                st.warning(
                    "Stopped after last completed interview. "
                    "Click **↺ Resume last run** in the left column to continue."
                )

            elif _pending:
                # Process the next interview
                _path    = Path(_pending[0])
                _iid     = _path.stem
                _cfg     = load_cfg(
                    Path(st.session_state.codebook_path)
                    if st.session_state.codebook_path else None
                )
                _run_dir = Path(st.session_state.run_dir)

                with st.status(f"Processing {_iid}…", expanded=True) as _status_box:

                    _stage_bar = st.empty()

                    def _on_stage_start(stage, estimate, _box=_status_box,
                                        _bar=_stage_bar) -> None:
                        label = stage_label(stage)
                        _box.update(label=f"{_iid}: {label}…")
                        _bar.progress(
                            0.0,
                            text=f"{label} — 0%  ·  est. {format_duration(estimate)}",
                        )

                    def _on_stage_tick(stage, elapsed, estimate, tokens, note,
                                       _bar=_stage_bar) -> None:
                        pct   = percent_complete(elapsed, estimate)
                        extra = f" · {note}" if note else ""
                        _bar.progress(
                            pct,
                            text=f"{stage_label(stage)} — {pct * 100:.0f}%  ·  "
                                 f"{tokens:,} tokens{extra}  ·  {elapsed}s",
                        )

                    def _on_stage_done(stage, duration) -> None:
                        st.write(
                            f"✅ &nbsp; **{stage_label(stage)}** — "
                            f"{format_duration(duration)}"
                        )

                    _result = _process_one_interview(
                        _path, _run_dir, _cfg,
                        _on_stage_start, _on_stage_tick, _on_stage_done,
                    )
                    _stage_bar.empty()
                    _status_box.update(
                        state="complete",
                        label=f"✓  {_iid} complete",
                        expanded=False,
                    )

                st.session_state.partial_results[_iid] = _result
                st.session_state.pending = _pending[1:]
                _write_checkpoint(
                    _run_dir,
                    Path(st.session_state.work_dir),
                    st.session_state.all_interviews,
                    st.session_state.codebook_path,
                    list(st.session_state.partial_results.keys()),
                )
                st.rerun()

            else:
                # All interviews done — corpus comparison
                _cfg     = load_cfg(
                    Path(st.session_state.codebook_path)
                    if st.session_state.codebook_path else None
                )
                _run_dir    = Path(st.session_state.run_dir)
                _corpus_dir = _run_dir / "corpus"
                _corpus_dir.mkdir(exist_ok=True)

                with st.status("Building corpus comparison…", expanded=True) as _status_box:

                    _corpus_bar = st.empty()
                    _corpus_est = estimate_seconds(
                        "compare",
                        n_interviews=len(st.session_state.partial_results),
                    )
                    _corpus_t0  = time.time()

                    def _corpus_tick(tokens: int, elapsed: int,
                                     _bar=_corpus_bar, _est=_corpus_est) -> None:
                        pct = percent_complete(elapsed, _est)
                        _bar.progress(
                            pct,
                            text=f"Corpus comparison — {pct * 100:.0f}%  ·  "
                                 f"{tokens:,} tokens  ·  {elapsed}s",
                        )

                    _sf     = sorted((_run_dir / "analysis").glob("*_summary.json"))
                    _tf     = sorted((_run_dir / "analysis").glob("*_themes.json"))
                    _corpus = build_corpus_comparison(_sf, _tf, _cfg, tick_cb=_corpus_tick)
                    _corpus["_duration"] = time.time() - _corpus_t0
                    (_corpus_dir / "themes_matrix.json").write_text(
                        json.dumps(_corpus["matrix"], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    (_corpus_dir / "comparison_report.md").write_text(
                        _corpus["report"], encoding="utf-8"
                    )
                    _corpus_bar.empty()
                    st.write(
                        f"✅ &nbsp; **Corpus comparison** — "
                        f"{format_duration(_corpus['_duration'])}"
                    )
                    _status_box.update(
                        state="complete",
                        label=f"Corpus comparison — "
                              f"{format_duration(_corpus['_duration'])}",
                        expanded=False,
                    )

                st.session_state.results = {
                    **st.session_state.partial_results,
                    "_corpus": _corpus,
                }
                st.session_state.running = False
                # Remove checkpoint — run fully complete
                _cp = _run_dir / "checkpoint.json"
                if _cp.exists():
                    _cp.unlink()
                st.rerun()

        elif st.session_state.results:
            st.success("Analysis complete. Switch to the **Outcomes** tab to view results.")
            st.caption(f"Output: `{st.session_state.run_dir}`")

        else:
            st.info(
                "Upload transcript files on the left and click **Run Analysis** to begin.\n\n"
                "Progress is saved after each interview — you can stop at any time and resume later."
            )

# ── Outcomes tab ──────────────────────────────────────────────────────────────

with tab_outcomes:
    if not st.session_state.results:
        st.info("Run an analysis first — results will appear here.")
    else:
        results  = st.session_state.results
        run_dir: Path = Path(st.session_state.run_dir)

        dl_col1, dl_col2 = st.columns(2, gap="large")
        with dl_col1:
            st.download_button(
                "Download Word report (.docx)",
                data=generate_docx_report(run_dir, results),
                file_name=f"interview-analysis-{run_dir.name}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True,
            )
        with dl_col2:
            st.download_button(
                "Download HTML report",
                data=generate_html_report(run_dir, results).encode("utf-8"),
                file_name=f"interview-analysis-{run_dir.name}.html",
                mime="text/html",
                use_container_width=True,
            )
        st.caption(
            "Open the HTML report in any browser. "
            "Use File › Print › Save as PDF for a PDF copy."
        )

        st.subheader("Report highlights")
        st.markdown(
            f'<div class="riecs-scroll-pane">'
            f'{_report_highlights_html(results)}'
            f'</div>',
            unsafe_allow_html=True,
        )
