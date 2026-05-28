"""
Stage 5 — Cross-document corpus comparison.

Mode-aware:
  * interviews — reads `*_themes.json`, builds a theme matrix keyed by code,
    asks the LLM to synthesise findings using `prompts/compare.txt`.
  * workshop   — reads `*_questions.json`, builds a question matrix keyed by
    question_id (same shape — codes → questions, by_interview → by_document),
    uses `prompts/compare_workshop.txt`.

The matrix shape is identical across modes, so the chart and report code
need no awareness of which it received.
"""

import json
import time
from collections import defaultdict
from pathlib import Path

import ollama


def _load_prompt(name: str) -> str:
    p = Path(__file__).parent.parent / "prompts" / f"{name}.txt"
    return p.read_text(encoding="utf-8")


# Default pointers from aggregate questions to the Demographics tables. The
# UI can override these by adding a `pointer:` field next to `kind: aggregate`
# in questions.yaml.
_AGGREGATE_POINTER_HINT = {
    "stakeholder_groups": "See the **Demographics → Stakeholder groups** table.",
    "participants":       "See the **Demographics → Participants & modality** table.",
    "modality":           "See the **Demographics → Participants & modality** table (modality counts).",
    "age":                "See the **Demographics → Age distribution** chart.",
    "gender":             "See the **Demographics → Gender distribution** table.",
}


def _classify_aggregate_hint(question_text: str) -> str:
    """Best-effort pointer when the user hasn't supplied one explicitly."""
    t = (question_text or "").lower()
    if "age" in t:
        return _AGGREGATE_POINTER_HINT["age"]
    if "gender" in t or "female" in t or "male " in t:
        return _AGGREGATE_POINTER_HINT["gender"]
    if "online" in t and ("on-site" in t or "onsite" in t or "in-person" in t):
        return _AGGREGATE_POINTER_HINT["modality"]
    if "stakeholder" in t or "sh group" in t:
        return _AGGREGATE_POINTER_HINT["stakeholder_groups"]
    if "participant" in t and ("how many" in t or "number" in t):
        return _AGGREGATE_POINTER_HINT["participants"]
    return "Corpus-level question — see the **Demographics** section for the relevant figures."


def _trim_answer(text: str, max_chars: int = 260) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    # Trim on a word boundary so excerpts don't cut mid-word.
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:.- ") + "…"


def _build_per_question_synthesis(
    matrix_codes: dict,
    questions: list[dict],
    n_documents: int,
) -> str:
    """Build the Per-Question Synthesis section in Markdown, from real data.

    For each question:
      * aggregate kind → one-line pointer to the Demographics section.
      * per_document kind → coverage counts, up to three real answer excerpts
        (prefer fully-answered, fall back to partially), sentiment breakdown,
        and a list of documents that did not address it.

    The output never invents quotes or workshop IDs — every cited workshop_id
    comes from the per-document `*_questions.json` files via the matrix
    `entries` list.
    """
    lines: list[str] = ["## Per-Question Synthesis", ""]

    for q in questions:
        qid   = q.get("id") or q.get("question_id") or "q?"
        qtext = q.get("text") or q.get("question_text") or ""
        kind  = (q.get("kind") or "per_document").lower()
        info  = matrix_codes.get(qid, {})

        lines.append(f"### {qid}: {qtext}")
        lines.append("")

        if kind == "aggregate":
            pointer = q.get("pointer") or _classify_aggregate_hint(qtext)
            lines.append(f"_Aggregate question._  {pointer}")
            lines.append("")
            continue

        entries  = info.get("entries") or []
        answered = [e for e in entries
                    if e.get("coverage") == "answered" and e.get("answer")]
        partial  = [e for e in entries
                    if e.get("coverage") == "partially_answered" and e.get("answer")]
        not_ans  = [e for e in entries if e.get("coverage") == "not_answered"]
        n_ans     = len(answered)
        n_partial = len(partial)
        n_not_ans = len(not_ans)

        lines.append(
            f"**Coverage:** {n_ans} answered, {n_partial} partially answered, "
            f"{n_not_ans} not answered  (of {n_documents} documents)."
        )

        picks: list[dict] = []
        seen_docs: set[str] = set()
        for e in answered + partial:
            if e["doc_id"] in seen_docs:
                continue
            picks.append(e); seen_docs.add(e["doc_id"])
            if len(picks) >= 3:
                break

        if picks:
            lines.append("")
            lines.append("**Excerpts from the per-document analysis:**")
            for e in picks:
                wid = e.get("workshop_id") or e["doc_id"]
                ans = _trim_answer(e["answer"])
                cov = (e["coverage"] or "").replace("_", " ")
                lines.append(f"- *[{wid}]* ({cov}) — {ans}")

        sentiments = {}
        for e in entries:
            s = e.get("sentiment")
            if s:
                sentiments[s] = sentiments.get(s, 0) + 1
        if sentiments:
            ordered = sorted(sentiments.items(), key=lambda kv: -kv[1])
            lines.append("")
            lines.append(
                "**Sentiment across all documents:** "
                + ", ".join(f"{k} ({v})" for k, v in ordered)
            )

        if not_ans:
            ids = [(e.get("workshop_id") or e["doc_id"]) for e in not_ans]
            lines.append("")
            preview = ", ".join(sorted(ids)[:8])
            if len(ids) > 8:
                preview += f", … (+{len(ids) - 8} more)"
            lines.append(f"**Did not address this question** ({len(ids)} document(s)): {preview}")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# Both heading styles models tend to emit for the section that comes after
# Per-Question Synthesis. We try them in order when inserting the section.
_INSERT_BEFORE_PATTERNS = [
    r"^\s*##\s+Documents With Notable Gaps\b",
    r"^\s*\*\*Documents With Notable Gaps\*\*\s*$",
    r"^\s*##\s+Emerging Cross-Cutting Themes\b",
    r"^\s*\*\*Emerging Cross-Cutting Themes\*\*\s*$",
    r"^\s*##\s+Analytical Notes\b",
]


def _inject_per_question_synthesis(report_md: str, synthesis_md: str) -> str:
    """Insert the deterministic Per-Question Synthesis into the LLM report.

    Tries to slot it before 'Documents With Notable Gaps' (or the next
    section if that's missing). Falls back to appending at the end so the
    section never disappears.
    """
    import re as _re
    for pat in _INSERT_BEFORE_PATTERNS:
        m = _re.search(pat, report_md, flags=_re.MULTILINE)
        if m:
            before = report_md[:m.start()].rstrip() + "\n\n"
            after  = report_md[m.start():]
            return before + synthesis_md + "\n" + after
    # Strip any stray section the model wrote anyway, then append at the end.
    cleaned = _re.sub(
        r"(?:^##\s+Per[- ]Question Synthesis\b.*?(?=^##\s+|\Z))"
        r"|(?:^\*\*Per[- ]Question Synthesis\*\*\s*$.*?(?=^\*\*|\Z))",
        "",
        report_md,
        flags=_re.MULTILINE | _re.DOTALL,
    )
    return cleaned.rstrip() + "\n\n" + synthesis_md


def _build_theme_matrix(theme_files: list[Path]) -> dict:
    all_codes: dict[str, dict] = defaultdict(dict)
    code_labels: dict[str, str] = {}

    for tf in theme_files:
        data = json.loads(tf.read_text(encoding="utf-8"))
        interview_id = data.get("interview_id", tf.stem.replace("_themes", ""))
        for theme in data.get("themes", []):
            code = theme.get("code", "unknown")
            code_labels[code] = theme.get("label", code)
            all_codes[code][interview_id] = theme.get("frequency", "low")

    return {
        "codes": {
            code: {
                "label": code_labels.get(code, code),
                "by_interview": freqs,
                "total_interviews": len(freqs),
            }
            for code, freqs in sorted(all_codes.items(), key=lambda x: -len(x[1]))
        }
    }


def _build_question_matrix(
    question_files: list[Path],
    workshop_ids: dict[str, str] | None = None,
) -> dict:
    """Workshop-mode parallel of _build_theme_matrix.

    Same shape as the theme matrix so charts and reports stay reusable:
        codes -> {key (q01 etc.): {label, by_interview, total_interviews,
                                    sentiments, entries}}

    `by_interview` keys are document IDs that answered or partially_answered
    the question (consistent with the chart / heatmap semantics).

    `entries` is the full per-document record — workshop_id, coverage,
    sentiment, the actual answer text, and supporting quotes — used by the
    deterministic Per-Question Synthesis renderer to ground citations in real
    data rather than letting the comparison LLM invent quotes.
    """
    workshop_ids = workshop_ids or {}
    all_q: dict[str, dict] = defaultdict(dict)
    q_labels: dict[str, str] = {}
    q_sentiments: dict[str, dict] = defaultdict(dict)
    q_entries: dict[str, list[dict]] = defaultdict(list)
    q_order: list[str] = []

    for qf in question_files:
        data = json.loads(qf.read_text(encoding="utf-8"))
        doc_id = data.get("document_id", qf.stem.replace("_questions", ""))
        wid = workshop_ids.get(doc_id, "")
        for q in data.get("questions", []):
            qid = q.get("question_id", "unknown")
            if qid not in q_labels:
                q_labels[qid] = q.get("question_text", qid)
                q_order.append(qid)
            coverage = q.get("coverage") or "not_answered"
            if coverage and coverage != "not_answered":
                all_q[qid][doc_id] = coverage
            q_sentiments[qid][doc_id] = q.get("sentiment", "neutral")
            q_entries[qid].append({
                "doc_id":      doc_id,
                "workshop_id": wid,
                "coverage":    coverage,
                "sentiment":   q.get("sentiment", "neutral"),
                "answer":      (q.get("answer") or "").strip(),
                "quotes":      list(q.get("supporting_quotes") or []),
            })

    return {
        "codes": {
            qid: {
                "label": q_labels.get(qid, qid),
                "by_interview": all_q.get(qid, {}),
                "total_interviews": len(all_q.get(qid, {})),
                "sentiments": dict(q_sentiments.get(qid, {})),
                "entries": q_entries.get(qid, []),
            }
            for qid in q_order
        }
    }


def _build_document_register(
    summary_files: list[Path],
    workshop_ids: dict[str, str] | None,
    is_workshop: bool,
) -> str:
    """Render a plain-text register of the document IDs the LLM may cite.

    The point of the register is anti-hallucination: the model is told to
    pick IDs only from this list, never invent them. For workshop mode we
    also surface the assigned `workshop_NN` next to each file stem.
    """
    lines: list[str] = []
    workshop_ids = workshop_ids or {}
    for sf in summary_files:
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            doc_id = data.get("interview_id") or sf.stem.replace("_summary", "")
        except Exception:
            doc_id = sf.stem.replace("_summary", "")
        if is_workshop:
            wid = workshop_ids.get(doc_id, "")
            lines.append(f"  - {wid} | {doc_id}" if wid else f"  - {doc_id}")
        else:
            lines.append(f"  - {doc_id}")
    return "\n".join(lines) if lines else "  (no documents)"


def build_corpus_comparison(
    summary_files: list[Path],
    theme_files: list[Path],
    cfg: dict,
    tick_cb=None,
    *,
    potential_duplicates: list[dict] | None = None,
    workshop_ids: dict[str, str] | None = None,
) -> dict:
    """Run the corpus comparison for the configured mode.

    In workshop mode, `theme_files` is interpreted as the list of
    `*_questions.json` files, `potential_duplicates` (clusters of
    similarly-named files identified by the UI) is folded into the prompt
    so the LLM can verify and discuss them in the executive summary, and
    `workshop_ids` maps file stems to their assigned `workshop_NN`.
    """
    mode    = (cfg.get("mode") or "interviews").lower()
    is_workshop = mode == "workshop"
    model   = cfg["models"]["compare"]
    host    = cfg["ollama"]["host"]
    timeout = cfg["ollama"]["timeout_seconds"]

    if is_workshop:
        matrix = _build_question_matrix(theme_files, workshop_ids)
    else:
        matrix = _build_theme_matrix(theme_files)

    summaries_compact = []
    for sf in summary_files:
        data = json.loads(sf.read_text(encoding="utf-8"))
        doc_id = data.get("interview_id") or sf.stem.replace("_summary", "")
        entry: dict = {
            "id": doc_id,
            "key_topics": [t["topic"] if isinstance(t, dict) else t
                           for t in data.get("key_topics", [])],
            "main_positions": data.get("main_positions", []),
        }
        if is_workshop and workshop_ids and workshop_ids.get(doc_id):
            entry["workshop_id"] = workshop_ids[doc_id]
        summaries_compact.append(entry)

    # Compute the FIXED FACTS the prompt instructs the model to copy verbatim.
    n_documents = len(summary_files)
    n_workshops = (
        len({workshop_ids.get(s["id"], s["id"]) for s in summaries_compact})
        if is_workshop and workshop_ids else n_documents
    )
    document_register = _build_document_register(
        summary_files, workshop_ids, is_workshop
    )

    if is_workshop:
        # Build the per-question list from the matrix, then merge in `kind`
        # (per_document / aggregate) from questions.yaml if available so the
        # deterministic Per-Question Synthesis renderer knows which mode to use
        # for each question.
        from questions import load_questions
        qpath = (cfg.get("paths") or {}).get("questions")
        user_questions: list[dict] = load_questions(qpath) if qpath else []
        user_by_id = {q.get("id"): q for q in user_questions if q.get("id")}
        questions = []
        for qid, info in matrix["codes"].items():
            user_q = user_by_id.get(qid) or {}
            questions.append({
                "id":   qid,
                "text": info["label"],
                "kind": (user_q.get("kind") or "per_document").lower(),
                "pointer": user_q.get("pointer"),
            })
        n_questions = len(questions)
        prompt_template = _load_prompt("compare_workshop")
        prompt = (
            prompt_template
            .replace("{{N_DOCUMENTS}}", str(n_documents))
            .replace("{{N_WORKSHOPS}}", str(n_workshops))
            .replace("{{N_QUESTIONS}}", str(n_questions))
            .replace("{{DOCUMENT_REGISTER}}", document_register)
            .replace("{{SUMMARIES}}", json.dumps(summaries_compact, ensure_ascii=False, indent=2))
            .replace("{{QUESTIONS}}", json.dumps(questions, ensure_ascii=False, indent=2))
            .replace("{{QUESTION_MATRIX}}", json.dumps(matrix, ensure_ascii=False, indent=2))
            .replace(
                "{{POTENTIAL_DUPLICATES}}",
                json.dumps(potential_duplicates or [], ensure_ascii=False, indent=2),
            )
        )
    else:
        top_themes = [
            {"code": code, "label": info["label"], "n_interviews": info["total_interviews"]}
            for code, info in matrix["codes"].items()
            if info["total_interviews"] >= 2
        ]
        prompt_template = _load_prompt("compare")
        prompt = (
            prompt_template
            .replace("{{N_INTERVIEWS}}", str(n_documents))
            .replace("{{DOCUMENT_REGISTER}}", document_register)
            .replace("{{SUMMARIES}}", json.dumps(summaries_compact, ensure_ascii=False, indent=2))
            .replace("{{TOP_THEMES}}", json.dumps(top_themes, ensure_ascii=False, indent=2))
            .replace("{{THEME_MATRIX}}", json.dumps(matrix, ensure_ascii=False, indent=2))
        )

    client = ollama.Client(host=host)
    stream = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "num_predict": 4096},
        stream=True,
    )
    parts: list[str] = []
    n = 0
    t0 = time.time()
    for chunk in stream:
        delta = chunk.message.content
        if delta:
            parts.append(delta)
            n += 1
            if tick_cb and n % 40 == 0:
                tick_cb(n, round(time.time() - t0))
    if tick_cb:
        tick_cb(n, round(time.time() - t0))

    report_md = "".join(parts).strip()

    # Inject the deterministic Per-Question Synthesis built from the actual
    # *_questions.json data — never trust the comparison LLM to summarise
    # per-question content, since it sees only coverage labels in the prompt
    # and tends to invent quotes that no document contains.
    if is_workshop:
        synthesis = _build_per_question_synthesis(
            matrix["codes"], questions, len(summary_files)
        )
        report_md = _inject_per_question_synthesis(report_md, synthesis).rstrip()

    return {"matrix": matrix, "report": report_md}
