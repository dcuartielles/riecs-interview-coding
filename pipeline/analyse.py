"""
Stages 2–4 — Structured summary, thematic coding, sentiment analysis.
All operate on the anonymised transcript.
"""

import json
import time
from pathlib import Path

import ollama
from pydantic import BaseModel, ValidationError


# --- Pydantic output schemas ---

class KeyTopic(BaseModel):
    topic: str
    brief_description: str

class SummaryOutput(BaseModel):
    interview_id: str
    estimated_duration_min: int | None
    word_count: int
    key_topics: list[KeyTopic]
    main_positions: list[str]
    notable_quotes: list[str]
    methodological_notes: str | None


class Theme(BaseModel):
    code: str
    label: str
    description: str
    frequency: str          # "high" | "medium" | "low"
    supporting_quotes: list[str]
    sub_themes: list[str]

class ThemesOutput(BaseModel):
    interview_id: str
    themes: list[Theme]
    new_codes_proposed: list[str]


class TopicSentiment(BaseModel):
    topic: str
    tone: str               # positive | neutral | negative | mixed
    notes: str | None

class SentimentOutput(BaseModel):
    interview_id: str
    overall_tone: str       # positive | neutral | negative | mixed
    confidence: str         # high | medium | low
    emotional_register: str
    topic_sentiments: list[TopicSentiment]
    notable_passages: list[str]


# --- Helpers ---

def _load_prompt(name: str) -> str:
    p = Path(__file__).parent.parent / "prompts" / f"{name}.txt"
    return p.read_text(encoding="utf-8")


def _stream_call(
    model: str,
    host: str,
    timeout: int,
    prompt: str,
    tick_cb=None,
) -> dict:
    """Call Ollama with streaming; invoke tick_cb(tokens, elapsed_s) every 40 tokens."""
    client = ollama.Client(host=host)
    stream = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0.0, "num_predict": 4096},
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
    return json.loads("".join(parts).strip())


def _inject(template: str, **kwargs) -> str:
    result = template
    for key, val in kwargs.items():
        result = result.replace(f"{{{{{key}}}}}", str(val))
    return result


# --- Stage functions ---

def summarise(text: str, interview_id: str, cfg: dict, tick_cb=None) -> dict:
    model   = cfg["models"]["summarise"]
    host    = cfg["ollama"]["host"]
    timeout = cfg["ollama"]["timeout_seconds"]
    prompt  = _inject(
        _load_prompt("summary"),
        INTERVIEW_ID=interview_id,
        WORD_COUNT=len(text.split()),
        TRANSCRIPT=text,
    )
    raw = _stream_call(model, host, timeout, prompt, tick_cb)
    raw.setdefault("interview_id", interview_id)
    raw.setdefault("word_count", len(text.split()))
    try:
        return SummaryOutput(**raw).model_dump()
    except ValidationError:
        return raw


def extract_themes(text: str, interview_id: str, cfg: dict, tick_cb=None) -> dict:
    model   = cfg["models"]["themes"]
    host    = cfg["ollama"]["host"]
    timeout = cfg["ollama"]["timeout_seconds"]

    codebook_str = "none — use open coding"
    codebook_path = cfg.get("paths", {}).get("codebook")
    if codebook_path:
        import yaml
        with open(codebook_path, encoding="utf-8") as f:
            codebook = yaml.safe_load(f)
        codebook_str = json.dumps(codebook, ensure_ascii=False)

    min_freq = cfg["analysis"].get("min_theme_frequency", 2)
    prompt = _inject(
        _load_prompt("themes"),
        INTERVIEW_ID=interview_id,
        CODEBOOK=codebook_str,
        MIN_FREQUENCY=min_freq,
        TRANSCRIPT=text,
    )
    raw = _stream_call(model, host, timeout, prompt, tick_cb)
    raw.setdefault("interview_id", interview_id)
    try:
        return ThemesOutput(**raw).model_dump()
    except ValidationError:
        return raw


def analyse_sentiment(text: str, interview_id: str, cfg: dict, tick_cb=None) -> dict:
    model       = cfg["models"]["sentiment"]
    host        = cfg["ollama"]["host"]
    timeout     = cfg["ollama"]["timeout_seconds"]
    granularity = cfg["analysis"].get("sentiment_granularity", "topic")
    prompt      = _inject(
        _load_prompt("sentiment"),
        INTERVIEW_ID=interview_id,
        GRANULARITY=granularity,
        TRANSCRIPT=text,
    )
    raw = _stream_call(model, host, timeout, prompt, tick_cb)
    raw.setdefault("interview_id", interview_id)
    try:
        return SentimentOutput(**raw).model_dump()
    except ValidationError:
        return raw
