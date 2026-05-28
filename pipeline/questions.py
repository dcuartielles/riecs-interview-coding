"""
Workshop mode — Stage 3 — Question-driven document analysis.

Sibling to `analyse.extract_themes`: instead of mapping the document to a
labelbook, this interrogates it against a fixed list of research questions
and returns, per question, a coverage rating, an answer summary, supporting
quotes, sentiment, and any emerging themes.

The output schema is described in `output-schema/workshop_result.json`.
"""

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from analyse import _inject, _load_prompt, _stream_call


# --- Pydantic output schema ---

class QuestionFinding(BaseModel):
    question_id: str
    question_text: str
    coverage: str                       # answered | partially_answered | not_answered
    answer: str
    supporting_quotes: list[str]
    sentiment: str                      # positive | neutral | negative | mixed
    emerging_themes: list[str]


class QuestionsOutput(BaseModel):
    document_id: str
    overall_tone: str | None = None     # positive | neutral | negative | mixed
    emotional_register: str | None = None
    questions: list[QuestionFinding]
    cross_question_notes: str | None = None


# --- Question-list loading ---

def load_questions(questions_path: str | Path) -> list[dict]:
    """Read questions from a YAML file written by the UI.

    Each entry: {"id": "q01", "text": "..."}. Returns the list as-is so the
    same order and ids are forwarded to the LLM prompt.
    """
    p = Path(questions_path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        return []
    return data


# --- Stage function ---

def analyse_questions(text: str, document_id: str, cfg: dict, tick_cb=None) -> dict:
    """Run the questions stage against a single workshop document.

    Mirrors the shape of `extract_themes`: returns a JSON-compatible dict
    that is also written to disk by the orchestrator.
    """
    model   = cfg["models"].get("questions") or cfg["models"]["themes"]
    host    = cfg["ollama"]["host"]
    timeout = cfg["ollama"]["timeout_seconds"]

    questions_path = cfg.get("paths", {}).get("questions")
    if not questions_path:
        raise ValueError(
            "workshop mode requires cfg['paths']['questions'] to point at a questions.yaml file"
        )
    questions = load_questions(questions_path)
    if not questions:
        raise ValueError(f"no questions parsed from {questions_path}")

    prompt = _inject(
        _load_prompt("questions"),
        DOCUMENT_ID=document_id,
        QUESTIONS=json.dumps(questions, ensure_ascii=False, indent=2),
        TRANSCRIPT=text,
    )
    raw = _stream_call(model, host, timeout, prompt, tick_cb)
    raw.setdefault("document_id", document_id)

    # Best-effort validation; fall back to the raw dict if the model deviates,
    # mirroring the behaviour of `extract_themes` / `summarise`.
    try:
        return QuestionsOutput(**raw).model_dump()
    except ValidationError:
        return raw
