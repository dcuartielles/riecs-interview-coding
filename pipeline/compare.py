"""
Stage 5 — Cross-interview corpus comparison.

Reads all per-interview summary and theme JSON files,
builds a frequency matrix, then asks the LLM to synthesise findings.
"""

import json
from collections import defaultdict
from pathlib import Path

import ollama


def _load_prompt() -> str:
    p = Path(__file__).parent.parent / "prompts" / "compare.txt"
    return p.read_text(encoding="utf-8")


def _build_theme_matrix(theme_files: list[Path]) -> dict:
    """Build { theme_code: { interview_id: frequency_label } } matrix."""
    all_codes: dict[str, dict] = defaultdict(dict)  # code -> {id: freq}
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


def build_corpus_comparison(
    summary_files: list[Path],
    theme_files: list[Path],
    cfg: dict,
) -> dict:
    model = cfg["models"]["compare"]
    host = cfg["ollama"]["host"]
    timeout = cfg["ollama"]["timeout_seconds"]

    # Build theme matrix (deterministic, no LLM needed)
    matrix = _build_theme_matrix(theme_files)

    # Assemble compact summaries for LLM synthesis prompt
    summaries_compact = []
    for sf in summary_files:
        data = json.loads(sf.read_text(encoding="utf-8"))
        summaries_compact.append({
            "id": data.get("interview_id"),
            "key_topics": [t["topic"] if isinstance(t, dict) else t for t in data.get("key_topics", [])],
            "main_positions": data.get("main_positions", []),
        })

    # Top themes (present in ≥2 interviews) for the prompt
    top_themes = [
        {"code": code, "label": info["label"], "n_interviews": info["total_interviews"]}
        for code, info in matrix["codes"].items()
        if info["total_interviews"] >= 2
    ]

    prompt_template = _load_prompt()
    prompt = (
        prompt_template
        .replace("{{N_INTERVIEWS}}", str(len(summary_files)))
        .replace("{{SUMMARIES}}", json.dumps(summaries_compact, ensure_ascii=False, indent=2))
        .replace("{{TOP_THEMES}}", json.dumps(top_themes, ensure_ascii=False, indent=2))
        .replace("{{THEME_MATRIX}}", json.dumps(matrix, ensure_ascii=False, indent=2))
    )

    client = ollama.Client(host=host)
    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "num_predict": 4096},
    )
    report_md = response.message.content.strip()

    return {"matrix": matrix, "report": report_md}
