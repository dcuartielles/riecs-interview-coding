"""
Stage 1 — Anonymisation.

Processes a transcript in chunks (to handle long texts),
replacing PII with consistent placeholders and returning
an entity map for potential re-identification by authorised parties.
"""

import json
import re
import time
from pathlib import Path

import ollama


def _load_prompt() -> str:
    p = Path(__file__).parent.parent / "prompts" / "anonymise.txt"
    return p.read_text(encoding="utf-8")


def _chunk_text(text: str, max_words: int, overlap: int) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        end = min(i + max_words, len(words))
        chunks.append(" ".join(words[i:end]))
        i += max_words - overlap
    return chunks


def _merge_entity_maps(*maps: dict) -> dict:
    merged: dict[str, str] = {}
    reverse: dict[str, str] = {}
    counters: dict[str, int] = {}

    for m in maps:
        for placeholder, original in m.items():
            if original in reverse:
                continue
            match = re.match(r"\[([A-Z]+)_", placeholder)
            prefix = match.group(1) if match else "ENTITY"
            counters[prefix] = counters.get(prefix, 0) + 1
            new_placeholder = f"[{prefix}_{counters[prefix]}]"
            reverse[original] = new_placeholder
            merged[new_placeholder] = original

    return merged


def _call_llm(
    prompt_template: str,
    text: str,
    model: str,
    host: str,
    timeout: int,
    tick_cb=None,
) -> tuple[str, dict]:
    prompt = prompt_template.replace("{{TRANSCRIPT}}", text)
    client = ollama.Client(host=host)
    stream = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0.0, "num_predict": 8192},
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

    raw = "".join(parts).strip()
    try:
        data = json.loads(raw)
        anon_text  = data.get("anonymised_text", text)
        entity_map = data.get("entity_map", {})
        return anon_text, entity_map
    except json.JSONDecodeError:
        return text, {}


def anonymise_transcript(
    text: str,
    cfg: dict,
    tick_cb=None,
) -> tuple[str, dict]:
    """
    Returns (anonymised_text, entity_map).
    entity_map: { "[PERSON_1]": "John Smith", ... }
    tick_cb(tokens, elapsed_s) is called every 40 tokens during each LLM call.
    """
    model     = cfg["models"]["anonymise"]
    host      = cfg["ollama"]["host"]
    timeout   = cfg["ollama"]["timeout_seconds"]
    max_words = cfg["chunking"]["max_words_per_chunk"]
    overlap   = cfg["chunking"]["overlap_words"]

    prompt_template = _load_prompt()
    word_count = len(text.split())

    if word_count <= max_words:
        return _call_llm(prompt_template, text, model, host, timeout, tick_cb)

    # Long transcript: process in overlapping chunks
    chunks = _chunk_text(text, max_words, overlap)
    anon_chunks: list[str] = []
    all_maps: list[dict] = []
    known_replacements: dict[str, str] = {}

    for i, chunk in enumerate(chunks):
        # Wrap tick_cb to prefix chunk info
        chunk_tick = None
        if tick_cb:
            def chunk_tick(n, elapsed, _i=i, _total=len(chunks)):
                tick_cb(n, elapsed, note=f"chunk {_i + 1}/{_total}")

        if known_replacements:
            known_str = json.dumps(
                {v: k for k, v in known_replacements.items()}, ensure_ascii=False
            )
            preamble = (
                f"EXISTING REPLACEMENTS (reuse these exact placeholders for these values):\n"
                f"{known_str}\n\n"
            )
            chunk_prompt = prompt_template.replace("{{TRANSCRIPT}}", preamble + chunk)
        else:
            chunk_prompt = prompt_template.replace("{{TRANSCRIPT}}", chunk)

        anon_chunk, entity_map = _call_llm(
            chunk_prompt, chunk, model, host, timeout, chunk_tick
        )
        anon_chunks.append(anon_chunk)
        all_maps.append(entity_map)

        for placeholder, original in entity_map.items():
            if original not in known_replacements:
                known_replacements[original] = placeholder

    merged_map  = _merge_entity_maps(*all_maps)
    merged_text = "\n\n".join(anon_chunks)
    return merged_text, merged_map
