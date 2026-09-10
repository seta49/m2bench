# m2bench

Personal LLM benchmark CLI. Test models on coding, honesty, literal precision, and instruction following — then compare results head-to-head.

Supports **any OpenAI-compatible provider**: OpenCode Go, OpenAI, Anthropic, DeepSeek, Xiaomi MiMo, OpenRouter, or your own endpoint.

## Quick Start

```bash
# Validate task sets
py m2bench.py validate

# List available models from your provider
py m2bench.py models --provider opencode-go

# Run inference
py m2bench.py run --provider opencode-go --models mimo-v2.5 --set easy --name my-test

# Grade with judge
py m2bench.py grade --run my-test

# See results
py m2bench.py report --run my-test
```

## Providers

Pass `--provider` to use a preset, or `--base-url` + `--api-key` for any endpoint.

```bash
# OpenCode Go (default)
py m2bench.py run --models mimo-v2.5 --set easy --name t1

# OpenAI
py m2bench.py run --provider openai --models gpt-4o --set easy --name t1

# Anthropic
py m2bench.py run --provider anthropic --models claude-sonnet-4 --set easy --name t1

# DeepSeek
py m2bench.py run --provider deepseek --models deepseek-v4-flash --set easy --name t1

# Xiaomi MiMo
py m2bench.py run --provider xiaomi --models mimo-v2.5 --set easy --name t1

# OpenRouter
py m2bench.py run --provider openrouter --models anthropic/claude-sonnet-4 --set easy --name t1

# Custom endpoint
py m2bench.py run --base-url http://localhost:11434/v1 --api-key dummy --models llama3 --set easy --name t1
```

API keys are read from env vars: `OPENCODE_GO_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `XIAOMI_API_KEY`, `OPENROUTER_API_KEY`. Or pass `--api-key` directly.

## Task Sets

Three difficulty levels, each with 8 tasks across 4 categories:

| Set | Difficulty | What it tests |
|---|---|---|
| `easy` | Basic competence | Simple data extraction, syntax errors, obvious uncertainty |
| `medium` | One trap each | Precise extraction, async bugs, fake products, format constraints |
| `hard` | Multiple traps | False premises, race conditions, position-sensitive constraints |

**Categories:**
- **literal-precision** — extract exact numbers from data tables
- **coding-fix** — find and fix bugs in code snippets
- **honesty** — admit uncertainty, reject fake products/premises
- **id-instruction** — follow multi-constraint format rules

## Commands

```
py m2bench.py models                                    # list available models
py m2bench.py validate                                  # validate task JSONs
py m2bench.py run    --models a,b --set easy --name t1  # run inference
py m2bench.py grade  --run t1                           # grade responses
py m2bench.py pair   --run t1                           # pairwise blind compare
py m2bench.py report --run t1                           # markdown report
py m2bench.py report --run t1 --compare-to t2           # report with deltas
py m2bench.py compare --run-a t1 --run-b t2             # head-to-head comparison
py m2bench.py history                                   # list all runs
```

### Run Options

| Flag | Description |
|---|---|
| `--models` | Comma-separated model ids (required) |
| `--provider` | Provider name: `opencode-go`, `openai`, `anthropic`, `deepseek`, `xiaomi`, `openrouter` |
| `--base-url` | API base URL (overrides provider) |
| `--api-key` | API key (overrides env var) |
| `--set` | Task set: `easy`, `medium`, `hard` (default: `easy`) |
| `--name` | Run name — output goes to `data/m2bench/runs/<name>/` |
| `--reasoning` | `reasoning_effort`: `none`/`low`/`medium`/`high`/`max` |
| `--tasks` | Run specific tasks only (comma-separated ids) |
| `--workers` | Parallel API calls (default: 2) |

### Comparing Runs

**Option A — inline deltas in report:**
```bash
py m2bench.py report --run baseline --compare-to improved
```

**Option B — full head-to-head:**
```bash
py m2bench.py compare --run-a baseline --run-b improved
```
Shows summary, per-category, per-task tables, and highlights key differences (|delta| >= 0.25).

### Reasoning Effort

Compare model performance with different reasoning levels:
```bash
py m2bench.py run --models mimo-v2.5 --set hard --name test-none --reasoning none
py m2bench.py run --models mimo-v2.5 --set hard --name test-high --reasoning high
py m2bench.py grade --run test-none
py m2bench.py grade --run test-high
py m2bench.py compare --run-a test-none --run-b test-high
```

## Scoring

- **pass** = 1.0, **partial** = 0.5, **fail** = 0.0
- **DNF** (truncated/error) = 0 in aggregate
- 4 criteria per task, score averaged across all criteria
- Judge model grades independently against rubric criteria

## Setup

1. Set API key: env var (`OPENCODE_GO_API_KEY`, `OPENAI_API_KEY`, etc.) or `--api-key` flag
2. Install Python 3.10+ (no external dependencies — stdlib only)
3. Run `py m2bench.py validate` to verify task sets

## Output Structure

```
data/m2bench/runs/<name>/
├── meta.json              # run config (models, set, tasks, provider)
├── responses/             # raw model outputs
│   ├── <model>__<task>.json
├── grades/                # judge verdicts
│   ├── <judge>__<model>__<task>.json
├── pairs/                 # pairwise comparison (optional)
└── report.md              # generated report
```

## Custom Tasks

Add JSON files to `tasks/`. Each task:
```json
{
  "id": "my-task-id",
  "category": "coding-fix",
  "prompt": "Your task prompt here...",
  "criteria": [
    {"id": "c1", "text": "What counts as pass for criterion 1"},
    {"id": "c2", "text": "What counts as pass for criterion 2"},
    {"id": "c3", "text": "What counts as pass for criterion 3"},
    {"id": "c4", "text": "What counts as pass for criterion 4"}
  ]
}
```

Categories: `literal-precision`, `coding-fix`, `honesty`, `id-instruction`

Run `py m2bench.py validate` to check your tasks before benchmarking.

## License

MIT
