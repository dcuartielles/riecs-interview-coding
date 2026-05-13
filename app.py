"""Streamlit UI for the offline interview analysis pipeline."""

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

INSTALL_DIR = Path(__file__).parent
PIPELINE_DIR = INSTALL_DIR / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from anonymise import anonymise_transcript  # noqa: E402
from analyse import summarise, extract_themes, analyse_sentiment  # noqa: E402
from compare import build_corpus_comparison  # noqa: E402


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
        # carry remaining non-empty columns through so the LLM sees full context
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

        status_cb(f"{iid}: anonymising...")
        anon_text, entity_map = anonymise_transcript(raw_text, cfg)
        (run_dir / "anonymised" / f"{iid}_anon.txt").write_text(anon_text, encoding="utf-8")
        (entities_dir / f"{iid}_entities.json").write_text(
            json.dumps(entity_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        step += 1
        progress_cb(step / total_steps)

        status_cb(f"{iid}: summarising...")
        summary = summarise(anon_text, iid, cfg)
        (run_dir / "analysis" / f"{iid}_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results[iid]["summary"] = summary
        step += 1
        progress_cb(step / total_steps)

        status_cb(f"{iid}: extracting themes...")
        themes = extract_themes(anon_text, iid, cfg)
        (run_dir / "analysis" / f"{iid}_themes.json").write_text(
            json.dumps(themes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results[iid]["themes"] = themes
        step += 1
        progress_cb(step / total_steps)

        status_cb(f"{iid}: analysing sentiment...")
        sentiment = analyse_sentiment(anon_text, iid, cfg)
        (run_dir / "analysis" / f"{iid}_sentiment.json").write_text(
            json.dumps(sentiment, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results[iid]["sentiment"] = sentiment
        step += 1
        progress_cb(step / total_steps)

    status_cb("Building corpus comparison...")
    corpus_dir = run_dir / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    summary_files = sorted((run_dir / "analysis").glob("*_summary.json"))
    theme_files = sorted((run_dir / "analysis").glob("*_themes.json"))
    corpus = build_corpus_comparison(summary_files, theme_files, cfg)
    (corpus_dir / "themes_matrix.json").write_text(
        json.dumps(corpus["matrix"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (corpus_dir / "comparison_report.md").write_text(corpus["report"], encoding="utf-8")
    progress_cb(1.0)
    status_cb("Complete.")

    return run_dir, {**results, "_corpus": corpus}


# ── Report ────────────────────────────────────────────────────────────────────

_CSS = """
body{font-family:system-ui,sans-serif;max-width:960px;margin:40px auto;padding:0 24px;
     color:#222;line-height:1.6}
h1{color:#1a1a2e}
h2{color:#16213e;border-bottom:2px solid #ddd;padding-bottom:6px;margin-top:40px}
h3{color:#333;margin-top:28px}
h4{color:#444;margin-top:20px}
blockquote{margin:8px 0;padding:8px 16px;border-left:4px solid #ccc;
           color:#555;background:#fafafa}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:.9em}
th{background:#f0f0f0;text-align:left;padding:6px 10px;border:1px solid #ccc}
td{padding:6px 10px;border:1px solid #ddd}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;
       font-size:.8em;font-weight:600}
.positive{background:#d4edda;color:#155724}
.negative{background:#f8d7da;color:#721c24}
.neutral{background:#e2e3e5;color:#383d41}
.mixed{background:#fff3cd;color:#856404}
.meta{color:#666;font-size:.85em}
code{background:#f4f4f4;padding:1px 5px;border-radius:3px}
"""


def _md_to_html(text: str) -> str:
    text = re.sub(r"^### (.+)$", r"<h4>\1</h4>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
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


def generate_html_report(run_dir: Path, results: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    corpus = results.get("_corpus", {})
    interviews = {k: v for k, v in results.items() if k != "_corpus"}

    parts = [
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<title>Interview Analysis Report — {now}</title>'
        f'<style>{_CSS}</style></head><body>'
        f'<h1>Interview Analysis Report</h1>'
        f'<p class="meta">Generated {now} &mdash; {len(interviews)} interview(s)'
        f' &mdash; output: {run_dir}</p>'
    ]

    if corpus.get("report"):
        parts.append(f'<h2>Executive Summary</h2>{_md_to_html(corpus["report"])}')

    matrix_codes = corpus.get("matrix", {}).get("codes", {})
    if matrix_codes:
        iids = sorted({iid for c in matrix_codes.values() for iid in c["by_interview"]})
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
        parts.append(f'<h2>Theme Matrix</h2><table>{header}{rows}</table>')

    for iid, data in interviews.items():
        parts.append(f'<h2>Interview: {iid}</h2>')

        s = data.get("summary", {})
        if s:
            parts.append(
                f'<h3>Summary</h3>'
                f'<p><strong>Estimated duration:</strong> {s.get("estimated_duration_min", "&mdash;")} min'
                f' &nbsp;|&nbsp; <strong>Word count:</strong> {s.get("word_count", "&mdash;")}</p>'
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
                parts.append(f'<p><em>Methodological notes: {s["methodological_notes"]}</em></p>')

        t = data.get("themes", {})
        if t.get("themes"):
            parts.append("<h3>Themes</h3>")
            for theme in t["themes"]:
                sub = (f'<p class="meta">Sub-themes: {", ".join(theme["sub_themes"])}</p>'
                       if theme.get("sub_themes") else "")
                quotes = "".join(
                    f"<blockquote>{q}</blockquote>"
                    for q in theme.get("supporting_quotes", [])[:3]
                )
                parts.append(
                    f'<h4>{theme.get("label", theme.get("code",""))}'
                    f' <code>{theme.get("code","")}</code>'
                    f' <span class="meta">({theme.get("frequency","")})</span></h4>'
                    f'<p>{theme.get("description","")}</p>{sub}{quotes}'
                )
            if t.get("new_codes_proposed"):
                parts.append(f'<p><em>New codes proposed: {", ".join(t["new_codes_proposed"])}</em></p>')

        sent = data.get("sentiment", {})
        if sent:
            tone = sent.get("overall_tone", "neutral")
            parts.append(
                f'<h3>Sentiment</h3>'
                f'<p>Overall tone: <span class="badge {tone}">{tone}</span>'
                f' &nbsp; Confidence: {sent.get("confidence","&mdash;")}'
                f' &nbsp; Register: {sent.get("emotional_register","&mdash;")}</p>'
            )
            if sent.get("topic_sentiments"):
                rows = "".join(
                    f'<tr><td>{ts.get("topic","")}</td>'
                    f'<td><span class="badge {ts.get("tone","neutral")}">{ts.get("tone","")}</span></td>'
                    f'<td>{ts.get("notes","")}</td></tr>'
                    for ts in sent["topic_sentiments"]
                )
                parts.append(
                    f'<table><tr><th>Topic</th><th>Tone</th><th>Notes</th></tr>{rows}</table>'
                )
            if sent.get("notable_passages"):
                passages = "".join(f"<blockquote>{p}</blockquote>" for p in sent["notable_passages"])
                parts.append(f'<h4>Notable passages</h4>{passages}')

    parts.append("</body></html>")
    return "\n".join(parts)


# ── Streamlit app ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="Interview Analyser", layout="wide")
st.title("Interview Analyser")
st.caption("Fully offline — all processing happens on this machine.")

for key, default in [
    ("results", None), ("run_dir", None), ("running", False),
    ("cb_rows", None), ("cb_headers", None),
    ("cb_code_col", None), ("cb_label_col", None), ("cb_desc_col", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    st.header("Inputs")
    uploaded_txts = st.file_uploader(
        "Interview transcripts (.txt, .docx)",
        type=["txt", "docx"],
        accept_multiple_files=True,
        help="Drag and drop plain-text or Word transcript files.",
    )

    uploaded_codebook = st.file_uploader(
        "Labelbook — optional",
        type=["xlsx", "xls", "csv", "yaml", "yml"],
        help="Excel, CSV, or YAML codebook for guided theme coding. Leave blank for open coding.",
    )

    # Parse spreadsheet on upload and show column mapping
    if uploaded_codebook:
        ext = Path(uploaded_codebook.name).suffix.lower()
        if ext in (".xlsx", ".xls", ".csv"):
            file_bytes = uploaded_codebook.read()
            rows, headers = parse_spreadsheet(file_bytes, uploaded_codebook.name)
            if rows and headers:
                # Re-detect defaults only when a new file is uploaded
                if st.session_state.cb_headers != headers:
                    st.session_state.cb_rows = rows
                    st.session_state.cb_headers = headers
                    st.session_state.cb_code_col  = headers[_auto_detect(headers, "code")]
                    st.session_state.cb_label_col = headers[_auto_detect(headers, "label")]
                    st.session_state.cb_desc_col  = headers[_auto_detect(headers, "description")]

                with st.expander(f"Labelbook — {len(rows)} codes", expanded=True):
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
                    st.write("**Preview (first 3 codes)**")
                    for r in rows[:3]:
                        code  = r.get(st.session_state.cb_code_col, "")
                        label = r.get(st.session_state.cb_label_col, "")
                        st.write(f"- `{code}` — {label}")
            else:
                st.warning("Could not read rows from the uploaded file.")
        else:
            # YAML / YML — store raw bytes for direct use
            st.session_state.cb_rows = uploaded_codebook.read()
            st.session_state.cb_headers = None

    elif not uploaded_codebook:
        # Clear stored codebook state when file is removed
        st.session_state.cb_rows = None
        st.session_state.cb_headers = None

    st.divider()
    run_btn = st.button(
        "Run Analysis",
        type="primary",
        disabled=not uploaded_txts or st.session_state.running,
        use_container_width=True,
    )

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
                # Raw YAML uploaded directly
                codebook_path.write_bytes(st.session_state.cb_rows)
            else:
                # Spreadsheet parsed — convert to YAML
                codebook_yaml = codebook_rows_to_yaml(
                    st.session_state.cb_rows,
                    st.session_state.cb_code_col,
                    st.session_state.cb_label_col,
                    st.session_state.cb_desc_col,
                )
                codebook_path.write_text(codebook_yaml, encoding="utf-8")

        st.subheader("Analysis in progress")
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        run_dir, results = run_pipeline(
            interview_paths,
            codebook_path,
            progress_cb=lambda v: progress_bar.progress(float(v)),
            status_cb=lambda s: status_text.text(s),
        )

    st.session_state.results = results
    st.session_state.run_dir = run_dir
    st.session_state.running = False
    st.rerun()

if st.session_state.results:
    results = st.session_state.results
    run_dir: Path = st.session_state.run_dir
    interviews = {k: v for k, v in results.items() if k != "_corpus"}
    corpus = results.get("_corpus", {})

    tab_corpus, tab_interviews, tab_export = st.tabs(
        ["Corpus overview", "Per-interview", "Export"]
    )

    with tab_corpus:
        if corpus.get("report"):
            st.markdown(corpus["report"])
        matrix_codes = corpus.get("matrix", {}).get("codes", {})
        if matrix_codes:
            st.subheader("Theme matrix")
            iids = sorted({iid for c in matrix_codes.values() for iid in c["by_interview"]})
            rows = [
                {
                    "Theme": info["label"],
                    "Code": code,
                    **{iid: info["by_interview"].get(iid, "—") for iid in iids},
                    "# Interviews": info["total_interviews"],
                }
                for code, info in matrix_codes.items()
            ]
            st.dataframe(rows, use_container_width=True)

    with tab_interviews:
        if interviews:
            selected = st.selectbox("Interview", list(interviews.keys()))
            data = interviews[selected]
            col_l, col_r = st.columns(2)

            with col_l:
                s = data.get("summary", {})
                if s:
                    st.subheader("Summary")
                    m1, m2 = st.columns(2)
                    m1.metric("Duration (est.)", f"{s.get('estimated_duration_min', '—')} min")
                    m2.metric("Word count", s.get("word_count", "—"))
                    if s.get("key_topics"):
                        st.write("**Key topics**")
                        for t in s["key_topics"]:
                            if isinstance(t, dict):
                                st.write(f"- **{t['topic']}**: {t.get('brief_description','')}")
                            else:
                                st.write(f"- {t}")
                    if s.get("main_positions"):
                        st.write("**Main positions**")
                        for p in s["main_positions"]:
                            st.write(f"- {p}")
                    if s.get("notable_quotes"):
                        st.write("**Notable quotes**")
                        for q in s["notable_quotes"]:
                            st.markdown(f"> {q}")

                sent = data.get("sentiment", {})
                if sent:
                    st.subheader("Sentiment")
                    st.metric("Overall tone", sent.get("overall_tone", "—"))
                    st.write(
                        f"Confidence: **{sent.get('confidence','—')}**"
                        f" | Register: **{sent.get('emotional_register','—')}**"
                    )
                    if sent.get("topic_sentiments"):
                        for ts in sent["topic_sentiments"]:
                            notes = f" — {ts['notes']}" if ts.get("notes") else ""
                            st.write(f"- **{ts.get('topic','')}**: {ts.get('tone','')}{notes}")
                    if sent.get("notable_passages"):
                        st.write("**Notable passages**")
                        for p in sent["notable_passages"]:
                            st.markdown(f"> {p}")

            with col_r:
                t = data.get("themes", {})
                if t.get("themes"):
                    st.subheader("Themes")
                    for theme in t["themes"]:
                        label = (
                            f"{theme.get('label', theme.get('code',''))}"
                            f"  [{theme.get('frequency','')}]"
                        )
                        with st.expander(label):
                            st.write(f"**Code:** `{theme.get('code','')}`")
                            st.write(theme.get("description", ""))
                            if theme.get("sub_themes"):
                                st.write("Sub-themes: " + ", ".join(theme["sub_themes"]))
                            for q in theme.get("supporting_quotes", []):
                                st.markdown(f"> {q}")
                    if t.get("new_codes_proposed"):
                        st.info("New codes proposed: " + ", ".join(t["new_codes_proposed"]))

    with tab_export:
        st.subheader("Export")
        html = generate_html_report(run_dir, results)
        st.download_button(
            "Download HTML report",
            data=html.encode("utf-8"),
            file_name=f"interview-analysis-{run_dir.name}.html",
            mime="text/html",
            use_container_width=True,
        )
        st.caption(
            "Open in any browser. Use File > Print > Save as PDF to generate a PDF copy."
        )
        st.write(f"Raw output directory: `{run_dir}`")

elif not st.session_state.running and not uploaded_txts:
    st.info("Upload transcript files in the sidebar to get started.")
