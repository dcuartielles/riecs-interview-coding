"""Streamlit UI for the offline interview analysis pipeline."""

import base64
import csv
import io
import json
import re
import sys
import tempfile
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


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(
    interview_paths: list[Path],
    codebook_path: Path | None,
    progress_cb,
    status_cb,
) -> tuple[Path, dict]:
    cfg = load_cfg(codebook_path)
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_dir = INSTALL_DIR / "output" / run_id
    (run_dir / "anonymised").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis").mkdir(exist_ok=True)
    entities_dir = run_dir / cfg["gdpr"]["entities_subdir"]
    entities_dir.mkdir(exist_ok=True)

    total_steps = len(interview_paths) * 4 + 1
    step = 0
    results: dict = {}

    for interview_path in interview_paths:
        iid = interview_path.stem
        results[iid] = {}
        raw_text = read_transcript(interview_path)

        status_cb(f"{iid}: anonymising…")
        anon_text, entity_map = anonymise_transcript(raw_text, cfg)
        (run_dir / "anonymised" / f"{iid}_anon.txt").write_text(anon_text, encoding="utf-8")
        (entities_dir / f"{iid}_entities.json").write_text(
            json.dumps(entity_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        step += 1
        progress_cb(step / total_steps)

        status_cb(f"{iid}: summarising…")
        summary = summarise(anon_text, iid, cfg)
        (run_dir / "analysis" / f"{iid}_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results[iid]["summary"] = summary
        step += 1
        progress_cb(step / total_steps)

        status_cb(f"{iid}: extracting themes…")
        themes = extract_themes(anon_text, iid, cfg)
        (run_dir / "analysis" / f"{iid}_themes.json").write_text(
            json.dumps(themes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results[iid]["themes"] = themes
        step += 1
        progress_cb(step / total_steps)

        status_cb(f"{iid}: analysing sentiment…")
        sentiment = analyse_sentiment(anon_text, iid, cfg)
        (run_dir / "analysis" / f"{iid}_sentiment.json").write_text(
            json.dumps(sentiment, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results[iid]["sentiment"] = sentiment
        step += 1
        progress_cb(step / total_steps)

    status_cb("Building corpus comparison…")
    corpus_dir = run_dir / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    summary_files = sorted((run_dir / "analysis").glob("*_summary.json"))
    theme_files   = sorted((run_dir / "analysis").glob("*_themes.json"))
    corpus = build_corpus_comparison(summary_files, theme_files, cfg)
    (corpus_dir / "themes_matrix.json").write_text(
        json.dumps(corpus["matrix"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (corpus_dir / "comparison_report.md").write_text(corpus["report"], encoding="utf-8")
    progress_cb(1.0)
    status_cb("Complete.")

    return run_dir, {**results, "_corpus": corpus}


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
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = DocxDoc()
    corpus     = results.get("_corpus", {})
    interviews = {k: v for k, v in results.items() if k != "_corpus"}
    now        = datetime.now().strftime("%Y-%m-%d %H:%M")

    t = doc.add_heading("Interview Analysis Report", 0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generated: {now}").italic = True
    doc.add_paragraph(f"Output: {run_dir}").italic = True

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

    with col_inputs:
        st.subheader("Transcripts")
        uploaded_txts = st.file_uploader(
            "Interview files",
            type=["txt", "docx"],
            accept_multiple_files=True,
            help="Drag and drop plain-text or Word transcript files.",
            label_visibility="collapsed",
        )

        st.subheader("Labelbook")
        uploaded_codebook = st.file_uploader(
            "Labelbook file",
            type=["xlsx", "xls", "csv", "yaml", "yml"],
            help="Excel, CSV, or YAML codebook — optional.",
            label_visibility="collapsed",
        )

        if uploaded_codebook:
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
        elif not uploaded_codebook:
            st.session_state.cb_rows    = None
            st.session_state.cb_headers = None

        st.divider()
        run_btn = st.button(
            "Run Analysis",
            type="primary",
            disabled=not uploaded_txts or st.session_state.running,
            use_container_width=True,
        )

    # ── Pipeline execution (renders into col_status) ──────────────────────────

    if run_btn and uploaded_txts:
        st.session_state.running = True
        st.session_state.results = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            interview_paths = []
            for f in uploaded_txts:
                dest = tmp / f.name
                dest.write_bytes(f.read())
                interview_paths.append(dest)

            codebook_path = None
            if st.session_state.cb_rows is not None:
                codebook_path = tmp / "codebook.yaml"
                if isinstance(st.session_state.cb_rows, (bytes, bytearray)):
                    codebook_path.write_bytes(st.session_state.cb_rows)
                else:
                    codebook_path.write_text(
                        codebook_rows_to_yaml(
                            st.session_state.cb_rows,
                            st.session_state.cb_code_col,
                            st.session_state.cb_label_col,
                            st.session_state.cb_desc_col,
                        ),
                        encoding="utf-8",
                    )

            with col_status:
                _progress = st.progress(0.0)
                with st.status("Analysis in progress…", expanded=True) as _status:
                    def _progress_cb(v: float) -> None:
                        _progress.progress(float(v))

                    def _status_cb(msg: str) -> None:
                        _status.update(label=msg)
                        st.write(msg)

                    run_dir, results = run_pipeline(
                        interview_paths,
                        codebook_path,
                        progress_cb=_progress_cb,
                        status_cb=_status_cb,
                    )
                    _status.update(label="Analysis complete", state="complete", expanded=False)
                _progress.progress(1.0)

        st.session_state.results = results
        st.session_state.run_dir = run_dir
        st.session_state.running = False
        st.rerun()

    else:
        with col_status:
            if st.session_state.results:
                st.success("Analysis complete. Switch to the **Outcomes** tab to view results.")
                st.caption(f"Output: `{st.session_state.run_dir}`")
            else:
                st.info("Upload transcript files on the left and click **Run Analysis** to begin.")

# ── Outcomes tab ──────────────────────────────────────────────────────────────

with tab_outcomes:
    if not st.session_state.results:
        st.info("Run an analysis first — results will appear here.")
    else:
        results = st.session_state.results
        run_dir: Path = st.session_state.run_dir

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
        st.caption("Open the HTML report in any browser. Use File > Print > Save as PDF for a PDF copy.")

        st.subheader("Report highlights")
        st.markdown(
            f'<div class="riecs-scroll-pane">'
            f'{_report_highlights_html(results)}'
            f'</div>',
            unsafe_allow_html=True,
        )
