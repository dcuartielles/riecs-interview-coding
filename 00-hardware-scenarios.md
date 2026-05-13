# Hardware Scenarios for Offline Interview Analysis

## Context

This document supports procurement arguments for an air-gapped interview analysis system.  
All inference runs locally via [Ollama](https://ollama.com) — no data leaves the machine.  
Input: plain-text interview transcripts (English).  
Pipeline stages per interview: anonymisation → structured summary → thematic coding → sentiment analysis.  
Corpus stage: cross-interview theme comparison (runs once after all interviews are processed).

---

## Benchmark assumptions

| Parameter | Value used |
|---|---|
| Interview length | ~6,000 words (~8,400 tokens) — typical 45–60 min interview |
| Pipeline calls per interview | 4 (anonymise, summarise, themes, sentiment) |
| Total output tokens per interview | ~9,800 (anonymised text + 3 × JSON analyses) |
| Corpus comparison call | 1 call per run, input scales with number of interviews |
| Parallelism | Single interview at a time (sequential) |

Timings are **wall-clock estimates for a medium interview**. Actual speed depends on OS, thermal throttling, background load, and model quantisation level.

---

## Tier 1 — CPU-only laptop (minimum viable)

**Target hardware**
- Any modern laptop: Intel Core i7-12th gen / AMD Ryzen 7 or equivalent, 16 GB RAM
- No dedicated GPU required
- Examples: Dell Latitude 5540, Lenovo ThinkPad X1, MacBook Air M1 8 GB

**Recommended model**
- `llama3.2:3b` (Q4_K_M quantisation, ~2.0 GB RAM)
- Quality: adequate for anonymisation and structured summaries; thematic coding is coarser

**Performance**
| Metric | Estimate |
|---|---|
| Output token speed | 15–25 tokens/sec |
| Time per medium interview | 7–12 minutes |
| Time per short interview (2,000 words) | 2–4 minutes |
| Time per long interview (12,000 words) | 15–25 minutes |
| 20 interviews (medium) | 2.5–4 hours |
| Corpus comparison (20 interviews) | 5–10 minutes |

**Notes**
- Laptop will run hot; use on mains power, not battery
- RAM must be free — close all other applications
- The 3B model sometimes loses track of long transcripts; consider chunking interviews >8,000 words

---

## Tier 2 — Consumer workstation or Apple Silicon (recommended baseline)

**Target hardware**
- **Mac**: MacBook Pro 14″ M2 Pro 18 GB, or Mac mini M2 Pro 16 GB
- **Windows**: Desktop/workstation with NVIDIA RTX 3070 (8 GB VRAM) + 32 GB system RAM

**Recommended model**
- `llama3.1:8b` (Q4_K_M, ~5.0 GB VRAM/RAM)
- Quality: good — reliable JSON output, solid thematic coding, handles long transcripts well

**Performance**
| Metric | Mac M2 Pro | RTX 3070 |
|---|---|---|
| Output token speed | 45–65 t/s | 65–90 t/s |
| Time per medium interview | 2.5–4 min | 1.8–3 min |
| Time per short interview | 45 s–1.5 min | 35 s–1 min |
| Time per long interview | 5–8 min | 4–6 min |
| 20 interviews (medium) | 50–80 min | 35–60 min |
| Corpus comparison | 2–4 min | 1.5–3 min |

**Notes**
- The 8B model fits entirely in GPU/unified memory — no system-RAM spilling
- Apple Silicon: power efficient, fanless on M2 Pro mini; good for sustained runs
- RTX 3070: requires Windows driver installation prior to air-gapping

---

## Tier 3 — High-memory workstation or Mac Studio (recommended for production)

**Target hardware**
- **Mac**: Mac Studio M2 Max (32–96 GB), or Mac Studio M2 Ultra (64–192 GB)
- **Windows**: Workstation with RTX 4090 (24 GB VRAM) + 64 GB system RAM

**Recommended models**
- `llama3.1:8b` for fast turnaround (anonymisation, summaries)
- `mistral-small:22b` (Q4_K_M ~13 GB) for higher-quality thematic analysis and comparison
- On M2 Ultra: `llama3.1:70b` (Q4_K_M ~40 GB) fully fits in unified memory

**Performance — `llama3.1:8b`**
| Metric | Mac Studio M2 Max | RTX 4090 |
|---|---|---|
| Output token speed | 80–110 t/s | 150–200 t/s |
| Time per medium interview | 1.5–2 min | 50 s–1.2 min |
| 20 interviews (medium) | 30–40 min | 17–25 min |

**Performance — `llama3.1:70b` Q4 (M2 Ultra only)**
| Metric | Mac Studio M2 Ultra |
|---|---|
| Output token speed | 35–55 t/s |
| Time per medium interview | 3–5 min |
| 20 interviews (medium) | 60–100 min |
| Quality gain | Substantially better nuanced thematic coding and cross-interview synthesis |

**Notes**
- RTX 4090: 70B model does NOT fit in 24 GB VRAM; use 8B or 22B model on Windows single-GPU
- For RTX 4090 with 70B: possible with CPU offload (~64 GB system RAM), but speed drops to ~8–15 t/s

---

## Tier 3c — Mac mini M4 Pro 64 GB (best value for 70B)

**Target hardware**
- Mac mini with M4 Pro chip, 64 GB unified memory
- Approximate cost: €2,200–2,700 (depending on storage)
- Fanless, compact, no driver complexity

**Why it stands out**  
The M4 Pro has ~273 GB/s memory bandwidth. 64 GB unified memory means `llama3.1:70b` Q4_K_M (~40 GB) loads entirely into on-chip memory with ~24 GB to spare — no CPU offloading, no VRAM limit. This gives 70B-quality analysis at a price point closer to Tier 2 than Mac Studio.

**Recommended models**
- `llama3.1:8b` for fast per-stage turnaround
- `llama3.1:70b` Q4_K_M for highest-quality thematic coding and corpus comparison

**Performance**
| Metric | llama3.1:8b | llama3.1:70b Q4 |
|---|---|---|
| Output token speed | 100–130 t/s | 25–40 t/s |
| Time per medium interview | 1.3–1.7 min | 4–6.5 min |
| Time per short interview (2,000 words) | 25–40 s | 1–2 min |
| Time per long interview (12,000 words) | 3–4 min | 9–14 min |
| 20 interviews (medium) | 26–34 min | 80–130 min |
| Corpus comparison (20 interviews) | 1–2 min | 3–6 min |

**Suggested hybrid strategy**  
Run anonymisation and summary with `llama3.1:8b` (fast, reliable JSON), then switch to `llama3.1:70b` for thematic coding and corpus comparison (where nuance matters most). Configure per-stage models in `config.yaml`:

```yaml
models:
  anonymise: llama3.1:8b
  summarise:  llama3.1:8b
  themes:     llama3.1:70b
  sentiment:  llama3.1:8b
  compare:    llama3.1:70b
```

This gives 70B quality where it counts while cutting total processing time roughly in half compared to running 70B for all stages.

**Notes**
- Requires macOS Sequoia (15) or later for full Metal GPU acceleration with Ollama
- M4 (base, 16/24 GB) does NOT fit 70B — the 64 GB M4 Pro configuration is required
- Power draw under load: ~35–45 W — suitable for sustained overnight batch runs

---

## Tier 4 — Multi-GPU server (best throughput at 70B quality)

**Target hardware**
- 2× NVIDIA RTX 4090 (48 GB combined VRAM) — consumer-grade, lower cost
- Or: 1× NVIDIA A100 80 GB — professional-grade, highest reliability
- Host: tower/rack workstation with 128 GB RAM, Ubuntu 22.04 LTS or Windows Server

**Recommended model**
- `llama3.1:70b` Q4_K_M (~40 GB) — fits entirely in VRAM, no CPU spill

**Performance**
| Metric | 2× RTX 4090 | A100 80 GB |
|---|---|---|
| Output token speed | 50–75 t/s | 80–120 t/s |
| Time per medium interview | 2–3.5 min | 1.5–2 min |
| 20 interviews (medium) | 40–70 min | 30–40 min |
| Corpus comparison | 3–6 min | 2–4 min |

**Notes**
- Multi-GPU on Windows requires Ollama ≥0.2 with CUDA multi-GPU support
- A100 is datacenter-class: requires appropriate power (400 W), PCIe slot, and cooling
- Total system cost: 2× RTX 4090 build ~€5,000–7,000; A100 card alone ~€8,000–15,000

---

## Summary comparison table

| Tier | Hardware example | Model | Time / interview | 20 interviews | Approx. cost |
|---|---|---|---|---|---|
| 1 — CPU laptop | i7/16 GB RAM | llama3.2:3b | 7–12 min | 2.5–4 h | existing hardware |
| 2 — Consumer GPU / M2 | RTX 3070 or M2 Pro | llama3.1:8b | 2–4 min | 50–80 min | €800–1,500 new |
| 3a — Pro workstation | RTX 4090 | llama3.1:8b | 50 s–1.5 min | 17–30 min | €2,000–3,500 |
| 3b — Mac Studio | M2 Ultra 192 GB | llama3.1:70b | 3–5 min | 60–100 min | €5,500–7,000 |
| **3c — Mac mini M4 Pro** | **M4 Pro 64 GB** | **llama3.1:70b** | **4–6.5 min** | **80–130 min** | **€2,200–2,700** |
| 3c — Mac mini M4 Pro | M4 Pro 64 GB | llama3.1:8b | 1.3–1.7 min | 26–34 min | €2,200–2,700 |
| 4 — Server | 2× RTX 4090 | llama3.1:70b | 2–3.5 min | 40–70 min | €5,000–7,000 |
| 4 — Server | A100 80 GB | llama3.1:70b | 1.5–2 min | 30–40 min | €10,000–18,000 |

---

## Recommendation for phased deployment

**Phase 1 (pilot, ≤20 interviews):** Tier 2 — a Mac mini M2 Pro or a Windows workstation with RTX 3070. Cost-effective, handles the workload in a half-day batch run.

**Phase 2 (production, 50–200 interviews / ongoing):** Tier 3c — **Mac mini M4 Pro 64 GB** is the standout option here. It runs `llama3.1:70b` fully in unified memory, costs ~€2,200–2,700, and requires zero GPU driver setup. For 20 interviews in hybrid mode (8B for anonymisation/summary, 70B for themes/comparison) expect ~45–60 min total. Alternatively, Tier 3a (RTX 4090 Windows) if faster 8B throughput is the priority and 70B quality is not required.

**If highest analytical rigour is required:** Tier 4 with A100, justified when interview data informs high-stakes decisions (policy, HR, clinical).

---

## GDPR / air-gap compliance checklist

- [ ] Machine has no Wi-Fi or Ethernet connected during processing
- [ ] Ollama's telemetry disabled: set env var `OLLAMA_NO_ANALYTICS=1`
- [ ] Models downloaded on a separate machine and transferred via USB/internal media before air-gapping
- [ ] Output directory (including entity maps) stored on encrypted volume (BitLocker / FileVault)
- [ ] Entity-to-replacement mapping (`*_entities.json`) stored separately from anonymised texts
- [ ] Log files reviewed and purged before any output is moved off the machine
