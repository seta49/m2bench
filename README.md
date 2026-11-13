# m2bench

**Personal LLM benchmark CLI + local web leaderboard.** Evaluate open-weight and API models across practical engineering skills — bug-fixing without false positives, honesty under fake premises, strict Indonesian instruction following, long-context needle retrieval, and multi-turn consistency — using **Python stdlib only** (zero external dependencies).

> Supports **Ollama** (local or Google Colab GPU), **OpenAI**, **Anthropic**, **DeepSeek**, **OpenRouter**, **Xiaomi MiMo**, **OpenCode Go**, **CommandCode**, and any custom OpenAI-compatible endpoint.

---

## Why `m2bench`?

- **4-Criterion Rubrics, Not Regex Guessing:** Every task is scored against 4 explicit criteria (`pass = 1.0`, `partial = 0.5`, `fail = 0.0`, `DNF = 0`) with anti-false-positive traps so models cannot pass by nitpicking valid code.
- **Hybrid Deterministic + LLM-Judge Grading:** Format, JSON validity, word-count, and exact-substring constraints are verified programmatically (`_eval_check`), while reasoning and fixes are graded by a judge model.
- **Honesty & Hallucination Resistance:** Dedicated prompts with fake APIs, nonexistent journals/DOIs, impossible hardware specs, and scam listings test whether models admit uncertainty or play along.
- **Local Web Leaderboard (`leaderboard.html`):** Generates a self-contained dashboard with category breakdowns, Intelligence vs Speed (`t/s`) scatter plot, and per-task drilldown from your own runs.

---

## Task Sets

| Set | Tasks | Focus & Categories | Status |
|---|---|---|---|
| **`expert`** *(default)* | 50 | `literal-precision` (12), `coding-fix` (13), `honesty` (12), `id-instruction` (13) | Active |
| **`daily_plus`** | 8 | `long-context` (2), `multi-turn` (2), `coding-fix` (2), `structured-json` (2) | Active |
| `usage200` | 200 | High-volume stress-test suite (skipped by default `validate`) | Experimental |
| `easy` / `medium` / `hard` | 8 each | Historical 8-task benchmark sets kept for legacy run reproducibility | Legacy |

---

## Sample Results (`expert` Set)

Snapshot from personal runs on `expert` (50 tasks, `DNF = 0`):

| Model | Provider | Score | DNF | Speed | Context / Mode |
|---|---|---:|---:|---|---|
| `mimo-v2.6-pro` | `xiaomi` | **97.5%** | 0 | 26.2 t/s | `reasoning=high` |
| `mimo-v2.6-flash` | `xiaomi` | **94.8%** | 0 | 40.5 t/s | `reasoning=high` |
| `gemma4:26b` | `ollama` (L4) | **94.2%** | 0 | **85.9 t/s** | 16k ctx, `temp=default` |
| `mimo-v2.5-pro` | `xiaomi` | **91.5%** | 0 | 67.4 t/s | `reasoning=high` |
| `mimo-v2.5` | `xiaomi` | **90.2%** | 0 | 29.2 t/s | `reasoning=high` |
| `qwen3.5-4b-128k` | `ollama` | **67.2%** | 0 | - | 128k ctx, `reasoning=none` |

---

## Quick Start

### 1. Validate task sets
```bash
py m2bench.py validate
```

### 2. Run a standardized benchmark
Use `--temp -1` so each model uses its own recommended sampling defaults (important for reasoning/thinking models like Gemma 4, Qwen 3.5, and LFM3), and set `OLLAMA_CONTEXT_LENGTH=16384` (or higher) when serving via Ollama so reasoning chains do not hit Ollama's default 4096 context cap:

```bash
# Ollama (Linux / Colab)
OLLAMA_CONTEXT_LENGTH=16384 ollama serve &
python3 m2bench.py run --provider ollama --models gemma4:26b,qwen3.5:9b --set expert,daily_plus --name l4-std --temp -1 --workers 1

# OpenRouter / Cloud API
py m2bench.py run --provider openrouter --models vendor/model-name --set expert,daily_plus --name cloud-std --temp -1 --workers 4

# Resume an interrupted run (skips completed tasks, retries DNF/errors)
py m2bench.py run --provider ollama --models gemma4:26b --set expert --name l4-std --temp -1 --workers 1 --resume
```

### 3. Grade, report, and build the web leaderboard
```bash
py m2bench.py grade   --run l4-std-expert --provider openai --judge <judge-model>
py m2bench.py report  --run l4-std-expert
py m2bench.py compare --run-a baseline-run --run-b l4-std-expert
py tools/build_leaderboard.py
```

`tools/build_leaderboard.py` scans every graded run in `data/m2bench/runs/` and outputs:
- `data/m2bench/leaderboard.html` — self-contained interactive web UI (tabs, sorting, filters, SVG Intelligence vs Speed scatter plot, and per-task modal)
- `data/m2bench/leaderboard.json` — structured JSON snapshot for downstream scripts

---

## CLI Reference

Running `py m2bench.py` with no arguments launches the interactive TUI menu.

| Command | Purpose |
|---|---|
| `py m2bench.py models --provider <p>` | List available models from a provider |
| `py m2bench.py validate` | Validate task JSON schemas and IDs |
| `py m2bench.py run ...` | Run inference on a task set (supports `--set`, `--tasks`, `--temp`, `--reasoning`, `--resume`, `--no-guardrail`) |
| `py m2bench.py grade --run <name>` | Auto-check deterministic rules + grade rubric criteria via judge model |
| `py m2bench.py pair --run <name>` | Blind pairwise A/B evaluation across models |
| `py m2bench.py report --run <name>` | Generate `report.md` (with optional `--compare-to`) |
| `py m2bench.py compare --run-a <a> --run-b <b>` | Head-to-head comparison of the same model across two runs |
| `py m2bench.py history` | Print summary table of all local runs |

---

## Supported Providers

Configured in `providers.json`: `ollama` (keyless local), `opencode-go`, `openai`, `anthropic`, `deepseek`, `xiaomi`, `openrouter`, `commandcode`, and `custom` (`--base-url` + `--api-key`).

API keys are read automatically from environment variables (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, etc.) or passed inline with `--api-key`. Set `Hermes_Output` to redirect run data (useful when saving directly to Google Drive on Colab).

---

## Benchmark Guardrails

Every inference call injects a uniform system guardrail (`--no-guardrail` to disable):
- **No web search or browsing**
- **No code execution or external tools**
- **Single final response per turn**

---

## Repository Layout

```text
m2bench/
├── m2bench.py              # Core benchmark CLI & interactive TUI (stdlib only)
├── providers.json          # Provider endpoints & auth env var registry
├── tasks/                  # Task sets (expert.json, daily_plus.json, legacy sets)
├── tools/
│   ├── build_leaderboard.py    # Generates leaderboard.html + leaderboard.json
│   ├── build_expert_set.py     # Builds expert.json from drafts/
│   ├── compare_all_models.py   # Legacy cross-run Markdown table
│   └── ...
└── drafts/                 # Modular task source files
```

Output runs live outside the repo under `data/m2bench/runs/<run-name>/` (`meta.json`, `responses/`, `grades/`, `pairs/`, `report.md`).

## License

MIT
