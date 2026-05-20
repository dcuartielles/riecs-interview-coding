# RIECS Interview Analysis — Ollama Benchmark

**Date:** 2026-05-20
**Machine:** Mac mini M4 Pro, 64 GB unified memory
**Pipeline:** riecs-interview-coding — full 5-stage pipeline

## Summary

This report records a measured wall-clock benchmark of the offline interview-analysis
pipeline running entirely on a Mac mini M4 Pro (64 GB), using Ollama with a hybrid
`llama3.1:8b` / `llama3.1:70b` model configuration. A single realistic interview
transcript of 5,385 words was processed end-to-end through all five pipeline stages.

**The full pipeline completed in 837.5 seconds (about 14 minutes).** Normalised to a
6,000-word "one-hour interview" — the reference length used in the project's planning
documents — this corresponds to approximately **15–16 minutes per interview**.

A Word version of this report is available as a download at the [end of this page](#download).

## Test environment

### Hardware

- Mac mini, Apple M4 Pro (10 performance + 4 efficiency cores)
- 64 GB unified memory
- macOS Tahoe 26.2
- Memory bandwidth ≈ 273 GB/s — this is the binding performance constraint for local inference

### Software

- Ollama 0.24.0
- Models: `llama3.1:8b` (Q4_K_M, 4.9 GB) and `llama3.1:70b` (Q4_K_M, 42 GB)
- Python virtual environment with the pipeline dependencies (streamlit, ollama,
  pydantic, pyyaml, rich, openpyxl, python-docx)

### Pipeline configuration (hybrid)

The `config.yaml` model assignment used for this benchmark:

| Stage | Model |
|---|---|
| anonymise | `llama3.1:8b` |
| summarise | `llama3.1:8b` |
| themes | `llama3.1:70b` |
| sentiment | `llama3.1:8b` |
| compare | `llama3.1:70b` |

Rationale (per `00-hardware-scenarios.md`): the fast 8b model handles the structured
and extractive stages, while the higher-quality 70b model is reserved for thematic
coding and corpus comparison, where nuance matters most.

### Context-length cap

The 70b model required `OLLAMA_CONTEXT_LENGTH=16384`. Ollama's default context window
for the 70b model on this machine is 131072 (128K) tokens, which inflates the
key/value cache so that the total memory footprint reaches roughly 102 GB. That
exceeds the 64 GB of unified memory, spills the model to the CPU, and crashes the
model runner. Capping the context to 16,384 tokens — ample for this pipeline, which
chunks transcripts at 4,000 words — brings the footprint down to about 49 GB, fully
resident on the GPU. The cap is set in `~/.zprofile` and in both launcher scripts.

## Methodology

- **Input:** one synthetic but realistic research-interview transcript, 5,385 words
  (approximately 7,500 tokens). The project planning documents define ~6,000 words as
  a typical 45–60 minute interview, so this input is close to a "one-hour interview."
  The transcript deliberately contained 15 items of personally identifiable
  information (names, organisations, places, an e-mail address) so the anonymisation
  stage performed representative work.
- **Run:** the complete pipeline via `run-analysis.sh` — anonymise, summarise, themes,
  sentiment, and corpus comparison.
- **Timing:** wall-clock measured with `/usr/bin/time`, cross-checked against the
  pipeline's own per-interview timer and the per-stage timestamps recorded in
  `run_log.jsonl`.

## Measured token throughput

| Model | Generation speed | Notes |
|---|---|---|
| `llama3.1:8b` | ≈ 47 tokens/s | ~85% of the ~55 t/s memory-bandwidth ceiling |
| `llama3.1:70b` | ≈ 6 tokens/s | at the ~6.5 t/s memory-bandwidth ceiling |

These rates are memory-bandwidth-limited. A Q4 model of size *S* on a machine with
273 GB/s of bandwidth cannot generate faster than roughly 273 / *S* tokens per second.
The 8B-Q4 model (~4.9 GB) has a ceiling near 55 t/s; the 70B-Q4 model (~42 GB) has a
ceiling near 6.5 t/s.

## Results

Full pipeline, one 5,385-word interview:

| Stage | Model | Duration |
|---|---|---|
| Anonymise | `llama3.1:8b` | ≈ 4 min 52 s |
| Summarise | `llama3.1:8b` | 37 s |
| Themes | `llama3.1:70b` | ≈ 6 min 00 s |
| Sentiment | `llama3.1:8b` | 42 s |
| Corpus comparison (1 interview) | `llama3.1:70b` | ≈ 1 min 47 s |
| **Total** | | **837.5 s — 13 min 58 s** |

All outputs were produced correctly: 15 PII entities anonymised, a structured summary,
6 themes, a sentiment analysis, and a corpus comparison report.

### Observations

1. **The 70b stages dominate.** Themes and comparison together took 467 s — 56% of
   total runtime — for just 2 of the 5 stages.
2. **Anonymisation is generation-bound.** Even on the fast 8b model it took about
   5 minutes, because the stage rewrites the entire transcript (~7,500 output tokens)
   rather than emitting a short classification.
3. **Model thrashing.** The stage order is 8b, 8b, 70b, 8b, 70b, so the 42 GB 70b
   model is loaded from disk twice. Reordering the pipeline so the 70b stages run
   consecutively would save one cold load (~45 s).

## Projections

| Scenario | Per interview (~6,000 words) | 20-interview batch |
|---|---|---|
| Hybrid (8b + 70b) — current config | ~14–16 min | ~4–4.5 hours |
| 8b-only (themes & compare reverted to 8b) | ~7–8 min | ~2.5 hours |

## Comparison with documented estimates

`00-hardware-scenarios.md` lists the following figures for the Mac mini M4 Pro 64 GB
(its "Tier 3c"):

| Metric | Documented | Measured |
|---|---|---|
| `llama3.1:8b` throughput | 100–130 t/s | ≈ 47 t/s |
| `llama3.1:70b` throughput | 25–40 t/s | ≈ 6 t/s |
| 20 interviews, hybrid | ~45–60 min | ~4–4.5 hours |

The documented figures are roughly 2.5–5× optimistic. The discrepancy is explained by
memory bandwidth: the throughput rates in the documentation would require three to six
times the M4 Pro's 273 GB/s bandwidth and are not physically achievable on this chip.
The figures in this report should be treated as the realistic baseline for an
M4 Pro 64 GB machine.

## Recommendations

- For one-off studies or small batches where thematic-coding quality is the priority,
  the hybrid configuration is reasonable at roughly 15 minutes per interview.
- For large or recurring batches, the 8b-only configuration roughly halves runtime,
  at some cost to thematic nuance.
- Reordering the pipeline so the 70b stages run consecutively would remove one model
  reload per interview.
- Treat the `00-hardware-scenarios.md` timing tables as aspirational; use the figures
  in this report for capacity planning on M4 Pro hardware.

## Download

[Download the Word version of this report](20260520-RIECS-interview-analysis-ollama-benchmark.docx)
