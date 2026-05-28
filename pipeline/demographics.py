"""
Workshop mode — Stage 3b — Demographic extraction.

Sibling to `questions.analyse_questions`: produces structured demographic
facts (participant counts, gender breakdown, stakeholder groups, modality,
age buckets) from a workshop description sheet.

The per-document output is consumed by the corpus comparison + report
renderers to build the Demographics section of the workshop report.

Schema: `output-schema/demographics_result.json`.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from analyse import _inject, _load_prompt, _stream_call


# --- Pydantic output schema ---

class GenderBreakdown(BaseModel):
    female:      int | None = None
    male:        int | None = None
    non_binary:  int | None = None
    unspecified: int | None = None


class StakeholderRow(BaseModel):
    group: str
    n: int


class AgeBucketRow(BaseModel):
    bucket: str
    n: int


class DemographicsOutput(BaseModel):
    document_id: str
    n_participants: int | None = None
    gender: GenderBreakdown | None = None
    stakeholder_groups: list[StakeholderRow] = []
    modality: str | None = None        # on_site | online | hybrid | unspecified
    age_buckets: list[AgeBucketRow] = []
    notes: str | None = None


# --- Stage function ---

def extract_demographics(text: str, document_id: str, cfg: dict, tick_cb=None) -> dict:
    """Run the demographics stage on a single workshop document.

    Returns a JSON-compatible dict matching
    output-schema/demographics_result.json. Falls back to the raw LLM
    output if validation fails, so a partial extraction is still useful.
    """
    model = (
        cfg["models"].get("demographics")
        or cfg["models"].get("questions")
        or cfg["models"]["themes"]
    )
    host    = cfg["ollama"]["host"]
    timeout = cfg["ollama"]["timeout_seconds"]

    prompt = _inject(
        _load_prompt("demographics"),
        DOCUMENT_ID=document_id,
        TRANSCRIPT=text,
    )
    raw = _stream_call(model, host, timeout, prompt, tick_cb)
    raw.setdefault("document_id", document_id)

    try:
        return DemographicsOutput(**raw).model_dump()
    except ValidationError:
        return raw
