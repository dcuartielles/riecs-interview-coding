# System Architecture — Offline Interview Analysis

## Overview

A fully local, GDPR-compliant pipeline that takes plain-text interview transcripts, anonymises them, extracts structured analysis, and produces cross-interview comparison reports — all without any network calls.

```
interviews/          (raw transcripts, restricted access)
    interview_001.txt
    interview_002.txt
    ...
        |
        v
[ Pipeline ]
        |
        +---> output/YYYY-MM-DD_HH-MM/
                    anonymised/
                        interview_001_anon.txt        <- distributable
                        interview_001_entities.json   <- confidential, keep separate
                    analysis/
                        interview_001_summary.json
                        interview_001_themes.json
                        interview_001_sentiment.json
                    corpus/
                        themes_matrix.json
                        comparison_report.md
                    run_log.jsonl
```

---

## Components

### Runtime layer

| Component | Role | Version |
|---|---|---|
| **Ollama** | Local LLM server, model management, GPU routing | ≥ 0.3 |
| **Python** | Pipeline orchestration, file I/O, JSON handling | ≥ 3.11 |
| `ollama` Python SDK | HTTP client to local Ollama server | ≥ 0.3 |
| `pydantic` | Output schema validation | ≥ 2.0 |
| `rich` | Progress display in terminal | ≥ 13 |
| `pyyaml` | Config file parsing | ≥ 6 |

No external API calls are made. The Ollama server binds to `127.0.0.1` only.

---

### Model selection (configurable in `config.yaml`)

| Stage | Default model | Rationale |
|---|---|---|
| Anonymisation | `llama3.1:8b` | Deterministic replacement task; 8B reliable |
| Structured summary | `llama3.1:8b` | JSON schema adherence; 8B sufficient |
| Thematic coding | `llama3.1:8b` | Upgradeable to 70B for richer codes |
| Sentiment analysis | `llama3.1:8b` | Classification task; 8B accurate |
| Corpus comparison | `llama3.1:8b` | Synthesis; upgrade to 70B if available |

The model for each stage can be overridden in `config.yaml` independently — e.g., run anonymisation at 8B speed and corpus comparison at 70B quality.

---

### Pipeline stages

#### Stage 1 — Anonymisation

Input: raw transcript  
Output: `*_anon.txt` + `*_entities.json`

The model receives the full transcript and a strict instruction to:
1. Identify all personally identifiable information (PII): names, organisations, specific locations, phone numbers, emails, ID numbers, dates that could be identifying
2. Replace each unique entity with a consistent coded placeholder (`[PERSON_1]`, `[ORG_2]`, `[PLACE_3]`, `[DATE_4]`)
3. Return the anonymised text **and** a JSON entity map `{ "[PERSON_1]": "original value", ... }`

Long transcripts (>6,000 words) are processed in overlapping chunks to maintain placeholder consistency across chunks.

#### Stage 2 — Structured summary

Input: anonymised transcript  
Output: `*_summary.json` — validated against `output-schema/interview_result.json`

Fields: `interview_id`, `word_count`, `estimated_duration_min`, `key_topics[]`, `main_positions[]`, `notable_quotes[]`, `methodological_notes`

#### Stage 3 — Thematic coding

Input: anonymised transcript  
Output: `*_themes.json`

Fields per theme: `code` (short slug), `label`, `description`, `frequency` (approximate count), `supporting_quotes[]`, `sub_themes[]`

A predefined codebook can be supplied in `config.yaml`; the model then maps to existing codes and may propose new ones.

#### Stage 4 — Sentiment and tone

Input: anonymised transcript  
Output: `*_sentiment.json`

Fields: `overall_tone` (positive/neutral/negative/mixed), `confidence_score`, `emotional_register` (formal/conversational/distressed/etc.), `topic_sentiments[]` (per key topic), `notable_passages[]`

#### Stage 5 — Corpus comparison (batch)

Input: all `*_summary.json` + `*_themes.json` files  
Output: `corpus/themes_matrix.json` + `corpus/comparison_report.md`

Builds a theme-frequency matrix across interviews, identifies consensus and divergent positions, and writes a synthesis narrative. Runs once after all interviews are processed.

---

## Data flow and security

```
raw transcripts  ──read──>  pipeline  ──write──>  anonymised/  (shareable)
                                                   analysis/    (shareable)
                                                   entities/    (confidential — separate storage)
```

- All files are written to a timestamped output directory; the pipeline never modifies source files
- Entity maps (`*_entities.json`) contain original PII; they should be stored on an encrypted, access-controlled volume separate from the anonymised outputs
- The pipeline logs each stage result to `run_log.jsonl`; this log does not contain PII (only file names, stage names, token counts, and timestamps)
- Ollama is started with `OLLAMA_NO_ANALYTICS=1` and bound to localhost; no external connections are made

---

## Configuration overview (`config.yaml`)

```yaml
models:
  anonymise: llama3.1:8b
  summarise: llama3.1:8b
  themes:    llama3.1:8b
  sentiment: llama3.1:8b
  compare:   llama3.1:8b

paths:
  interviews: ./interviews
  output:     ./output

chunking:
  max_words_per_chunk: 4000
  overlap_words: 200

analysis:
  codebook: null          # path to YAML codebook, or null for open coding
  language: en
  anonymise_dates: true   # set false to keep relative time references

gdpr:
  entities_subdir: entities_CONFIDENTIAL   # kept outside anonymised/
  log_pii: false
```

---

## Directory layout (installed system)

```
interview-analyser/
├── config.yaml
├── requirements.txt
├── main.py               <- entry point: python main.py
├── anonymise.py
├── analyse.py
├── compare.py
├── prompts/
│   ├── anonymise.txt
│   ├── summary.txt
│   ├── themes.txt
│   ├── sentiment.txt
│   └── compare.txt
├── output-schema/
│   ├── interview_result.json
│   └── corpus_result.json
├── interviews/           <- place .txt transcripts here
└── output/               <- generated; contains timestamped run dirs
```
