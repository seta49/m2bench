"""m2bench v2 - personal LLM benchmark CLI.

Commands:
  py m2bench.py models
  py m2bench.py validate
  py m2bench.py run    --models a,b --set easy --name test1 [--tasks id,id]
                       [--runs 1] [--workers 2] [--reasoning high]
                       [--provider opencode-go] [--base-url URL] [--api-key KEY]
  py m2bench.py grade  --run test1 [--judge qwen3.7-plus] [--models a,b]
  py m2bench.py pair   --run test1 [--judge qwen3.7-plus] [--models a,b]
  py m2bench.py report --run test1 [--compare-to other-run]
  py m2bench.py compare --run-a run1 --run-b run2
  py m2bench.py history

Task = JSON file in tasks/ (easy.json, medium.json, hard.json).
Each task has 4 criteria (id, text) defining pass/partial/fail.
Each run = folder data/m2bench/runs/<name>/ with meta.json, responses/,
grades/, pairs/, report.md. Re-running auto-skips cached files.

Scoring: pass=1 partial=0.5 fail=0; DNF (truncated/error) = 0 in aggregate.
Stdlib only. API key from env var or --api-key flag (never printed).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ENV_PATH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", ".env")
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_DIR = os.path.join(CODE_DIR, "tasks")
DATA_DIR = os.path.join(os.environ.get("Hermes_Output",
    os.path.join(os.environ.get("USERPROFILE", ""), "Hermes-Output")), "data", "m2bench")
RUNS_DIR = os.path.join(DATA_DIR, "runs")
PRICES_PATH = os.path.join(CODE_DIR, "prices.json")
PROVIDERS_PATH = os.path.join(CODE_DIR, "providers.json")

VERDICT_W = {"pass": 1.0, "partial": 0.5, "fail": 0.0}
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ANSI colors for terminal output
_COLOR = {
    "pass": "\033[92m",     # green
    "partial": "\033[93m",  # yellow
    "fail": "\033[91m",     # red
    "ok": "\033[92m",       # green
    "err": "\033[91m",      # red
    "dim": "\033[90m",      # gray
    "bold": "\033[1m",      # bold
    "reset": "\033[0m",     # reset
}
_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def colorize(text, style):
    """Wrap text in ANSI color codes if terminal supports it."""
    if not _USE_COLOR:
        return text
    return f"{_COLOR.get(style, '')}{text}{_COLOR['reset']}"

JUDGE_SYSTEM = (
    "You are a strict, objective grading judge for an AI benchmark. "
    "Grade each rubric criterion INDEPENDENTLY against the model's answer only. "
    "Verdicts: \"pass\" = fully satisfied, \"partial\" = partially satisfied, "
    "\"fail\" = not satisfied. Be literal: criterion asks for exact number -> "
    "check the number exactly. Do not reward effort. "
    "Respond with ONLY a JSON array, one object per criterion, in order: "
    "[{\"id\":\"c1\",\"verdict\":\"pass|partial|fail\",\"reason\":\"max 15 words\"}]. "
    "No markdown fences, no other text."
)
PAIR_SYSTEM = (
    "You are an impartial benchmark judge comparing two anonymous answers "
    "(labeled A and B) to the same task. Judge primarily on correctness and "
    "factual accuracy, then instruction compliance, then helpfulness/completeness. "
    "Do not reward longer answers or nicer formatting unless the task demands it. "
    "Choose winner \"A\", \"B\", or \"tie\" (tie ONLY if genuinely equal quality). "
    "Respond ONLY with JSON: "
    "{\"winner\":\"A|B|tie\",\"reason\":\"max 25 words\"}. No fences, no other text."
)


# ---------- provider ----------

def load_providers():
    """Load provider registry from providers.json."""
    if os.path.exists(PROVIDERS_PATH):
        return load_json(PROVIDERS_PATH)
    return {}


def load_dotenv():
    """Load env vars from .env file into os.environ (no override)."""
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                if k and k not in os.environ:
                    os.environ[k] = v


def resolve_provider(args):
    """Resolve provider config from CLI args + providers.json.
    Returns dict: base_url, api_key, reasoning_effort_support.
    Priority: --api-key > env var > hardcoded.
    """
    load_dotenv()
    providers = load_providers()
    pname = getattr(args, "provider", "") or ""
    base_url = getattr(args, "base_url", "") or ""
    api_key = getattr(args, "api_key", "") or ""

    if not pname and not base_url:
        sys.exit("provider required. use --provider <name> or --base-url <url>. "
                 "see providers.json for available providers.")
    if pname:
        if pname not in providers:
            avail = [k for k in providers if not k.startswith("_")]
            sys.exit(f"unknown provider '{pname}'. available: {', '.join(avail)}")
        cfg = providers[pname]
        if not base_url:
            base_url = cfg.get("base_url", "")
        if not api_key:
            env_var = cfg.get("auth_env", "")
            if env_var:
                api_key = os.environ.get(env_var, "")
    if not base_url:
        sys.exit("--base-url is required (or use --provider with a known provider)")
    if not api_key:
        sys.exit("no API key found. set --api-key or the provider's env var")
    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "provider": pname or "custom",
    }


# ---------- io helpers ----------

def read_key():
    """Read OPENCODE_GO_API_KEY from .env (legacy fallback)."""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*OPENCODE_GO_API_KEY\s*=\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip("\"'")
    return ""


def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def save_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------- task set ----------

def validate_set(obj, label):
    errs = []
    ids = []
    for t in obj:
        tid = str(t.get("id", "")).strip()
        ids.append(tid)
        if not tid:
            errs.append(f"{label}: task without id")
            continue
        if not str(t.get("prompt", "")).strip():
            errs.append(f"{tid}: empty prompt")
        crit = t.get("criteria") or []
        if len(crit) != 4:
            errs.append(f"{tid}: criteria={len(crit)} (must be 4)")
        cids = [str(c.get("id", "")).strip() for c in crit]
        if len(set(cids)) != len(cids) or not all(cids):
            errs.append(f"{tid}: duplicate/empty criteria ids")
        for c in crit:
            if not str(c.get("text", "")).strip():
                errs.append(f"{tid}/{c.get('id')}: empty criterion")
    if len(set(ids)) != len(ids):
        errs.append(f"{label}: duplicate task ids")
    return errs


def load_set(name):
    path = os.path.join(TASKS_DIR, f"{name}.json")
    if not os.path.exists(path):
        avail = [f[:-5] for f in os.listdir(TASKS_DIR) if f.endswith(".json")] \
            if os.path.isdir(TASKS_DIR) else []
        sys.exit(f"task set '{name}' not found. available: {', '.join(avail) or '-'}")
    obj = load_json(path)
    errs = validate_set(obj, name)
    if errs:
        sys.exit("task set invalid:\n  " + "\n  ".join(errs))
    return obj


def task_map(tasks):
    return {t["id"]: t for t in tasks}


# ---------- API ----------

def run_stream(model, messages, max_tokens, provider, reasoning_effort=None):
    """curl SSE; temp-file payload (WinError 206 on inline); retry 5xx/429."""
    body = {"model": model, "messages": messages,
            "max_tokens": max_tokens, "stream": True}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    payload = json.dumps(body, ensure_ascii=False)
    session_id = f"m2bench-{int(time.time() * 1000)}-{safe(model)}"
    base = provider["base_url"]
    key = provider["api_key"]

    def once():
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=tempfile.gettempdir())
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            cmd = ["curl", "-s", "-N", "--max-time", "480", "-X", "POST",
                   f"{base}/chat/completions",
                   "-H", "Content-Type: application/json",
                   "-H", f"x-opencode-session: {session_id}",
                   "-H", f"Authorization: Bearer {key}",
                   "--data-binary", f"@{tmp}",
                   "-w", "\n__HTTP__%{http_code}"]
            t0 = time.perf_counter()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    encoding="utf-8", errors="replace", bufsize=1)
            content, reasoning, raw = [], [], []
            usage = cost = finish = None
            http_code = None
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("__HTTP__"):
                    http_code = line[8:]
                    break
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                raw.append(data)
                try:
                    j = json.loads(data)
                except Exception:
                    continue
                if j.get("cost") is not None:
                    cost = j["cost"]
                if j.get("usage"):
                    usage = j["usage"]
                ch = j.get("choices") or []
                if not ch:
                    continue
                d = ch[0].get("delta") or {}
                if d.get("reasoning_content"):
                    reasoning.append(d["reasoning_content"])
                if d.get("content"):
                    content.append(d["content"])
                if ch[0].get("finish_reason"):
                    finish = ch[0]["finish_reason"]
            proc.wait()
            total_ms = (time.perf_counter() - t0) * 1000
            if http_code != "200":
                return {"error": f"HTTP {http_code}", "detail": "".join(raw)[:300]}
            return {"content": "".join(content), "reasoning": "".join(reasoning),
                    "usage": usage, "cost": cost, "finish": finish,
                    "total_ms": total_ms}
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    last = None
    for attempt in range(4):
        res = once()
        if not res.get("error"):
            return res
        last = res
        code = res.get("error", "")
        if code.startswith(("HTTP 4", "HTTP no-")) and "HTTP 429" not in code:
            break
        time.sleep(5 * (attempt + 1))
    return last


def answer_text(rec):
    c = rec.get("content") or ""
    return c if c.strip() else (rec.get("reasoning") or "")


def tokens_of(rec):
    u = rec.get("usage") or {}
    return (u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0)


# ---------- JSON extraction ----------

def extract_verdicts(text):
    t = re.sub(r"```(?:json)?", "", text or "").strip()
    def try_parse(s):
        try:
            return json.loads(s)
        except Exception:
            return None
    j = try_parse(t)
    if j is None:
        m = re.search(r"\[.*\]", t, re.S)
        if m:
            j = try_parse(m.group(0))
    if j is None:
        objs = re.findall(r"\{[^{}]*\}", t)
        merged = []
        for o in objs:
            k = try_parse(o)
            if isinstance(k, dict) and "verdict" in k:
                merged.append(k)
        j = merged if merged else None
    out = {}
    if isinstance(j, dict) and "verdict" in j:
        j = [j]
    if not isinstance(j, list):
        return None
    for item in j:
        if not isinstance(item, dict):
            continue
        vid = str(item.get("id", "")).strip()
        verd = str(item.get("verdict", "")).strip().lower()
        if vid and verd in VERDICT_W:
            out[vid] = {"verdict": verd, "reason": str(item.get("reason", ""))[:120]}
    return out or None


def extract_winner(text):
    t = (text or "").strip().replace("```json", "").replace("```", "").strip()
    j = None
    try:
        j = json.loads(t)
    except Exception:
        m = re.search(r"\{[^{}]*\"winner\"[^{}]*\}", t, re.S)
        if m:
            try:
                j = json.loads(m.group(0))
            except Exception:
                pass
    if isinstance(j, dict):
        w = str(j.get("winner", "")).upper()
        if w in ("A", "B", "TIE"):
            return w, str(j.get("reason", ""))[:150]
    m = re.search(r"\"winner\"\s*:\s*\"(A|B|TIE)\"", t, re.I)
    if m:
        return m.group(1).upper(), "(regex fallback)"
    return None, t[:150]


# ---------- prices (optional) ----------

def cost_estimate(model, prompt_t, completion_t):
    try:
        prices = load_json(PRICES_PATH)
        p = prices.get(model)
        if p:
            return (prompt_t * p.get("prompt", 0)
                    + completion_t * p.get("completion", 0)) / 1e6
    except Exception:
        pass
    return None


# ---------- shared aggregation ----------

def aggregate_run(rdir, tmap):
    """Return per-model stats dict for a run."""
    meta = load_json(os.path.join(rdir, "meta.json"))
    tids = meta["tasks"]
    models = meta["models"]
    _, resp, grades = collect_run(rdir, tmap)
    cats = sorted({tmap[t].get("category", "?") for t in tids})
    agg = {}
    for m in models:
        scores, dnf, times, ptok, ctok, costs = [], 0, [], 0, 0, []
        for t in tids:
            g = grades.get((m, t))
            r = resp.get((m, t))
            if r and r.get("error"):
                dnf += 1
                scores.append(0.0)
            elif g:
                scores.append(g["task_score"])
            else:
                continue
            if r and not r.get("error"):
                times.append(r.get("total_ms", 0) / 1000)
                p_, c_ = tokens_of(r)
                ptok += p_
                ctok += c_
                c = cost_estimate(m, p_, c_)
                if c is not None:
                    costs.append(c)
        n = len(tids)
        sc = sum(scores) / n * 100 if n else 0
        agg[m] = {
            "scores": scores, "dnf": dnf, "score": sc,
            "times": times, "ptok": ptok, "ctok": ctok, "costs": costs,
            "cat": {},
        }
        for c in cats:
            vals = [g["task_score"] for (mm, t), g in grades.items()
                    if mm == m and tmap[t].get("category") == c]
            n_c = sum(1 for t in tids if tmap[t].get("category") == c)
            agg[m]["cat"][c] = sum(vals) / n_c * 100 if n_c else 0
    return meta, tids, models, cats, grades, resp, agg


# ---------- commands ----------

def cmd_models(args):
    provider = resolve_provider(args)
    out = subprocess.run(
        ["curl", "-s", "--max-time", "60", f"{provider['base_url']}/models",
         "-H", f"Authorization: Bearer {provider['api_key']}"],
        capture_output=True, encoding="utf-8", errors="replace").stdout
    try:
        ids = sorted(m["id"] for m in json.loads(out).get("data", []))
    except Exception:
        sys.exit("failed to parse /models:\n" + out[:500])
    print("\n".join(ids))
    print(f"-- {len(ids)} models ({provider['provider']})", file=sys.stderr)


def cmd_validate(_args):
    if not os.path.isdir(TASKS_DIR):
        sys.exit("tasks/ folder not found")
    ok = True
    for f in sorted(os.listdir(TASKS_DIR)):
        if not f.endswith(".json"):
            continue
        name = f[:-5]
        try:
            obj = load_json(os.path.join(TASKS_DIR, f))
        except Exception as e:
            print(f"[BAD ] {name}: invalid JSON ({e})")
            ok = False
            continue
        errs = validate_set(obj, name)
        if errs:
            ok = False
            print(f"[BAD ] {name} ({len(obj)} tasks):")
            for e in errs:
                print(f"       - {e}")
        else:
            cats = sorted({t.get("category", "?") for t in obj})
            print(f"[OK  ] {name}: {len(obj)} tasks, categories: {', '.join(cats)}")
    print("all valid" if ok else "HAS ERRORS", file=sys.stderr)
    sys.exit(0 if ok else 1)


def unique_run_dir(base):
    d = os.path.join(RUNS_DIR, base)
    if not os.path.exists(d):
        return d
    i = 2
    while os.path.exists(os.path.join(RUNS_DIR, f"{base}_r{i}")):
        i += 1
    return os.path.join(RUNS_DIR, f"{base}_r{i}")


def progress_line(done, total, label=""):
    """Render a simple progress indicator: [===>      ] 5/8 model · task."""
    pct = done / total if total else 1
    bar_w = 20
    filled = int(bar_w * pct)
    bar = "=" * filled + ">" + " " * (bar_w - filled - 1)
    return f"\r{colorize(f'[{bar}]', 'bold')} {done}/{total}{label}"


def cmd_run(args):
    provider = resolve_provider(args)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    # support comma-separated sets: --set easy,medium,hard
    sets = [s.strip() for s in args.set.split(",") if s.strip()]
    reasoning = args.reasoning or None

    for set_name in sets:
        tasks = load_set(set_name)
        tmap = task_map(tasks)
        tids = [t.strip() for t in args.tasks.split(",") if t.strip()] \
            if args.tasks else [t["id"] for t in tasks]
        bad = [t for t in tids if t not in tmap]
        if bad:
            sys.exit(f"unknown task ids: {', '.join(bad)}")

        for rep in range(1, args.runs + 1):
            # suffix run name with set if multiple sets
            run_name = args.name
            if len(sets) > 1:
                run_name = f"{args.name}-{set_name}"
            base = run_name if args.runs == 1 else f"{run_name}_r{rep}"
            rdir = unique_run_dir(base)
            save_json(os.path.join(rdir, "meta.json"), {
                "name": os.path.basename(rdir), "set": set_name,
                "models": models, "tasks": tids, "created": time.strftime("%Y-%m-%d %H:%M"),
                "reasoning": reasoning, "provider": provider["provider"],
                "base_url": provider["base_url"],
            })
            jobs = [(m, t) for m in models for t in tids]
            total = len(jobs)
            print(f"== run {os.path.basename(rdir)}: {total} jobs ==")

            def do(model, tid):
                p = os.path.join(rdir, "responses", f"{safe(model)}__{safe(tid)}.json")
                if os.path.exists(p):
                    return "cached", model, tid
                res = run_stream(model, [{"role": "user", "content": tmap[tid]["prompt"]}],
                                 max_tokens=24576, provider=provider, reasoning_effort=reasoning)
                rec = {"model": model, "task": tid, **res}
                if not rec.get("error") and rec.get("finish") == "length" \
                        and not (rec.get("content") or "").strip():
                    rec["error"] = "DNF: truncated (reasoning ate max_tokens)"
                save_json(p, rec)
                status = "err" if rec.get("error") else "ok"
                return status, model, tid

            done = 0
            fails = 0
            cancelled = 0
            try:
                with ThreadPoolExecutor(max_workers=args.workers) as ex:
                    futs = {ex.submit(do, m, t): (m, t) for m, t in jobs}
                    for fut in as_completed(futs):
                        status, model, tid = fut.result()
                        done += 1
                        icon = colorize("ok", "ok") if status == "ok" \
                            else colorize("ERR", "err") if status == "err" \
                            else colorize("skip", "dim")
                        print(f"  {icon} [{model}] {tid}  {progress_line(done, total)}")
                        if status == "err":
                            fails += 1
            except KeyboardInterrupt:
                print(f"\n{colorize('Interrupted!', 'err')} cancelling remaining jobs...")
                for fut in futs:
                    fut.cancel()
                cancelled = total - done
            print(f"-- {os.path.basename(rdir)}: {done - fails}/{total} ok"
                  + (f" ({cancelled} cancelled)" if cancelled else "") + "\n")


def run_dir_of(name):
    d = os.path.join(RUNS_DIR, name)
    if not os.path.exists(d):
        sys.exit(f"run '{name}' not found. run: py m2bench.py history")
    return d


def iter_responses(rdir, only_models=None):
    rd = os.path.join(rdir, "responses")
    if not os.path.isdir(rd):
        return
    for fn in sorted(os.listdir(rd)):
        if not fn.endswith(".json"):
            continue
        rec = load_json(os.path.join(rd, fn))
        if only_models and rec.get("model") not in only_models:
            continue
        yield rec


def cmd_grade(args):
    provider = resolve_provider(args)
    rdir = run_dir_of(args.run)
    meta = load_json(os.path.join(rdir, "meta.json"))
    tmap = task_map(load_set(meta["set"]))
    judge = args.judge
    only = [m.strip() for m in args.models.split(",") if m.strip()] \
        if args.models else None
    recs = [r for r in iter_responses(rdir, only)]
    n_ok = sum(1 for r in recs if not r.get("error"))
    total = len(recs)
    print(f"grade {args.run}: {total} responses ({n_ok} ok) judge={judge}")

    def do(rec):
        p = os.path.join(rdir, "grades",
                         f"{safe(judge)}__{safe(rec['model'])}__{safe(rec['task'])}.json")
        if os.path.exists(p):
            return "cached", rec["model"], rec["task"], None
        if rec.get("error"):
            return "skip", rec["model"], rec["task"], rec["error"][:40]
        task = tmap[rec["task"]]
        crit = "\n".join(f"- id {c['id']}: {c['text']}" for c in task["criteria"])
        user = (f"# TASK PROMPT\n{task['prompt']}\n\n# RUBRIC CRITERIA\n{crit}\n\n"
                f"# MODEL ANSWER\n{answer_text(rec)}")
        res = run_stream(judge, [{"role": "system", "content": JUDGE_SYSTEM},
                                 {"role": "user", "content": user}],
                         max_tokens=16384, provider=provider)
        verd = extract_verdicts(answer_text(res)) if not res.get("error") else None
        if not verd:
            res = run_stream(judge, [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user",
                 "content": user + "\n\nIMPORTANT: reply ONLY the JSON array."}],
                max_tokens=16384, provider=provider)
            verd = extract_verdicts(answer_text(res)) if not res.get("error") else None
        if not verd:
            return "err", rec["model"], rec["task"], "judge JSON unparseable"
        score = sum(VERDICT_W[v["verdict"]] for v in verd.values()) / len(task["criteria"])
        save_json(p, {"judge": judge, "model": rec["model"], "task": rec["task"],
                      "verdicts": verd, "task_score": round(score, 4)})
        return "scored", rec["model"], rec["task"], score

    done = 0
    fails = 0
    cancelled = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(do, r): r for r in recs}
            for fut in as_completed(futs):
                status, model, tid, info = fut.result()
                done += 1
                if status == "cached":
                    tag = colorize("cached", "dim")
                elif status == "skip":
                    tag = colorize(f"skip ({info})", "dim")
                elif status == "err":
                    tag = colorize(f"ERR {info}", "err")
                    fails += 1
                else:
                    score = info
                    style = "pass" if score >= 0.99 else "partial" if score >= 0.5 else "fail"
                    tag = colorize(f"score={score:.2f}", style)
                print(f"  {tag} [{model}] {tid}  {progress_line(done, total)}")
    except KeyboardInterrupt:
        print(f"\n{colorize('Interrupted!', 'err')} cancelling remaining jobs...")
        for fut in futs:
            fut.cancel()
        cancelled = total - done
    print(f"-- grade done, {fails} failed"
          + (f", {cancelled} cancelled" if cancelled else ""))


def cmd_pair(args):
    provider = resolve_provider(args)
    rdir = run_dir_of(args.run)
    meta = load_json(os.path.join(rdir, "meta.json"))
    tmap = task_map(load_set(meta["set"]))
    judge = args.judge
    models = [m.strip() for m in args.models.split(",") if m.strip()] \
        if args.models else meta["models"]
    if len(models) < 2:
        sys.exit("pair requires at least 2 models")
    pairs = [(models[i], models[j]) for i in range(len(models))
             for j in range(i + 1, len(models))]
    resp = {(r["model"], r["task"]): r for r in iter_responses(rdir)}
    jobs = [(a, b, tid, o) for a, b in pairs for tid in meta["tasks"]
            for o in (1, 2)]
    print(f"pair {args.run}: {len(jobs)} comparisons, models={models}")

    def do(a, b, tid, order):
        p = os.path.join(rdir, "pairs",
                         f"{safe(judge)}__{safe(a)}__vs__{safe(b)}__{safe(tid)}__o{order}.json")
        if os.path.exists(p):
            return f"{tid} o{order}: cached"
        ra, rb = resp.get((a, tid)), resp.get((b, tid))
        if not ra or not rb or ra.get("error") or rb.get("error"):
            return f"{tid} o{order}: skip (resp missing/error)"
        task = tmap[tid]
        crit = "\n".join(f"- {c['text']}" for c in task["criteria"])
        first, second = (a, b) if order == 1 else (b, a)
        user = (f"# TASK\n{task['prompt']}\n\n"
                f"# QUALITY SIGNALS (checklist of a correct answer)\n{crit}\n\n"
                f"# ANSWER A\n{answer_text(ra if order == 1 else rb)}\n\n"
                f"# ANSWER B\n{answer_text(rb if order == 1 else ra)}\n\n"
                f"Which answer is better? ONLY the JSON verdict.")
        res = run_stream(judge, [{"role": "system", "content": PAIR_SYSTEM},
                                 {"role": "user", "content": user}],
                         max_tokens=16384, provider=provider)
        if res.get("error"):
            return f"{tid} o{order}: ERR {res['error']}"
        w, reason = extract_winner(answer_text(res))
        if not w:
            return f"{tid} o{order}: ERR unparseable"
        a_model = first if w == "A" else (second if w == "B" else None)
        save_json(p, {"judge": judge, "task": tid, "order": order,
                      "pair": [a, b], "a_model": first, "b_model": second,
                      "winner_label": w,
                      "winner_model": a_model,
                      "reason": reason})
        return f"{tid} o{order}: {w} ({reason[:50]})"

    total = len(jobs)
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(do, *j): j for j in jobs}
            for fut in as_completed(futs):
                done += 1
                print(f"  {fut.result()}  {progress_line(done, total)}")
    except KeyboardInterrupt:
        print(f"\n{colorize('Interrupted!', 'err')} cancelling remaining jobs...")
        for fut in futs:
            fut.cancel()
        cancelled = total - done
        print(f"-- pair interrupted, {done}/{total} done, {cancelled} cancelled")
        return
    print("-- pair done")


def collect_run(rdir, tmap):
    meta = load_json(os.path.join(rdir, "meta.json"))
    grades = {}
    gd = os.path.join(rdir, "grades")
    if os.path.isdir(gd):
        for fn in sorted(os.listdir(gd)):
            if fn.endswith(".json"):
                g = load_json(os.path.join(gd, fn))
                grades[(g["model"], g["task"])] = g
    resp = {(r["model"], r["task"]): r for r in iter_responses(rdir)}
    return meta, resp, grades


def _delta_str(a, b):
    """Format delta as +X.X / -X.X."""
    d = b - a
    if abs(d) < 0.05:
        return "= "
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.1f}"


def cmd_report(args):
    rdir = run_dir_of(args.run)
    meta = load_json(os.path.join(rdir, "meta.json"))
    tmap = task_map(load_set(meta["set"]))
    meta_r, tids, models, cats, grades, resp, agg = aggregate_run(rdir, tmap)

    comp = None
    if args.compare_to:
        rdir2 = run_dir_of(args.compare_to)
        meta2, tids2, models2, cats2, grades2, resp2, agg2 = aggregate_run(rdir2,
            task_map(load_set(load_json(os.path.join(rdir2, "meta.json"))["set"])))
        comp = {"meta": meta2, "grades": grades2, "agg": agg2, "resp": resp2,
                "tids": tids2, "models": models2}

    def fmt_cost(m, pt, ct):
        c = cost_estimate(m, pt, ct)
        return f"${c:.4f}" if c is not None else "-"

    rname = os.path.basename(rdir)
    lines = [f"# m2bench - {rname}", "",
             f"set: {meta['set']} ({len(tids)} task) | created: {meta['created']} | "
             f"scoring: pass=1 partial=0.5 fail=0, DNF=0 | "
             f"graded: {len(grades)}", ""]

    if comp:
        lines += ["| Model | Score | Delta | DNF | Time/Task | Tok (p/c)/Task |",
                  "|---|---|---|---|---|---|"]
    else:
        lines += ["| Model | Score | DNF | Time/Task | Tok (p/c)/Task | Est.Cost/Task |",
                  "|---|---|---|---|---|---|"]

    for m in models:
        n = len(tids)
        sc = agg[m]["score"]
        tm = f"{sum(agg[m]['times']) / len(agg[m]['times']):.0f}s" if agg[m]["times"] else "-"
        tok = f"{agg[m]['ptok'] / n:.0f}k/{agg[m]['ctok'] / n:.0f}k" if n and agg[m]["ptok"] else "-"
        ct = fmt_cost(m, agg[m]["ptok"], agg[m]["ctok"]) if agg[m]["costs"] else "-"
        dnf = agg[m]["dnf"]
        if comp:
            sc2 = comp["agg"].get(m, {}).get("score", None)
            if sc2 is not None:
                delta = _delta_str(sc2, sc)
                lines.append(f"| {m} | {sc:.1f}% | {delta} | {dnf} | {tm} | {tok} |")
            else:
                lines.append(f"| {m} | {sc:.1f}% | - | {dnf} | {tm} | {tok} |")
        else:
            lines.append(f"| {m} | {sc:.1f}% | {dnf} | {tm} | {tok} | {ct} |")

    lines += ["", "## Per category (%)", "",
              "| Model | " + " | ".join(cats) + " |",
              "|---|" + "---|" * len(cats)]
    for m in models:
        cells = []
        for c in cats:
            val = agg[m]["cat"].get(c, 0)
            cell = f"{val:.0f}"
            if comp:
                val2 = comp["agg"].get(m, {}).get("cat", {}).get(c, None)
                if val2 is not None:
                    d = _delta_str(val2, val)
                    cell += f" ({d})"
            cells.append(cell)
        lines.append(f"| {m} | " + " | ".join(cells) + " |")

    lines += ["", "## Per task", "",
              "| Task (category) | " + " | ".join(models) + " |",
              "|---|" + "---|" * len(models)]
    for t in tids:
        cells = []
        for m in models:
            g = grades.get((m, t))
            r = resp.get((m, t))
            cell = ""
            if g:
                cell = f"{g['task_score']:.2f}"
            elif r and r.get("error"):
                cell = "DNF"
            else:
                cell = "-"
            if comp:
                g2 = comp["grades"].get((m, t))
                if g2:
                    d = _delta_str(g2["task_score"], g["task_score"] if g else 0)
                    cell += f" ({d})"
            cells.append(cell)
        lines.append(f"| {t} ({tmap[t].get('category', '?')}) | "
                     + " | ".join(cells) + " |")

    failcnt = {}
    for (m, t), g in grades.items():
        for cid, v in g["verdicts"].items():
            if v["verdict"] != "pass":
                key = (t, cid, v["verdict"])
                failcnt[key] = failcnt.get(key, 0) + 1
    if failcnt:
        lines += ["", "## Frequently failing criteria (task / criterion / verdict / count)", ""]
        for (t, cid, v), n in sorted(failcnt.items(), key=lambda x: -x[1])[:10]:
            txt = next((c["text"][:90] for c in tmap[t]["criteria"] if c["id"] == cid), "")
            lines.append(f"- {t} / {cid} / {v} / {n}x — {txt}")

    report = "\n".join(lines) + "\n"
    save_text(os.path.join(rdir, "report.md"), report)
    print(report)
    print(f"saved: {os.path.join(rdir, 'report.md')}", file=sys.stderr)


def cmd_compare(args):
    """Head-to-head comparison of two runs."""
    rdir_a = run_dir_of(args.run_a)
    rdir_b = run_dir_of(args.run_b)
    meta_a = load_json(os.path.join(rdir_a, "meta.json"))
    meta_b = load_json(os.path.join(rdir_b, "meta.json"))
    tmap_a = task_map(load_set(meta_a["set"]))
    tmap_b = task_map(load_set(meta_b["set"]))

    meta_a, tids_a, models_a, cats_a, grades_a, resp_a, agg_a = aggregate_run(rdir_a, tmap_a)
    meta_b, tids_b, models_b, cats_b, grades_b, resp_b, agg_b = aggregate_run(rdir_b, tmap_b)

    name_a = os.path.basename(rdir_a)
    name_b = os.path.basename(rdir_b)

    print(f"# compare: {name_a} vs {name_b}\n")

    print("## Summary\n")
    print(f"| | **{name_a}** | **{name_b}** |")
    print("|---|---|---|")
    for m in agg_b:
        sc_a = agg_a.get(m, {}).get("score", 0)
        sc_b = agg_b[m]["score"]
        dnf_a = agg_a.get(m, {}).get("dnf", 0)
        dnf_b = agg_b[m]["dnf"]
        t_a = agg_a.get(m, {}).get("times", [])
        t_b = agg_b[m]["times"]
        avg_a = f"{sum(t_a) / len(t_a):.0f}s" if t_a else "-"
        avg_b = f"{sum(t_b) / len(t_b):.0f}s" if t_b else "-"
        delta = _delta_str(sc_a, sc_b)
        print(f"| {m} score | {sc_a:.1f}% | {sc_b:.1f}% ({delta}) |")
        print(f"| {m} DNF | {dnf_a} | {dnf_b} |")
        print(f"| {m} avg time | {avg_a} | {avg_b} |")
    print()

    print("## Per category\n")
    print(f"| Category | {name_a} | {name_b} | Delta |")
    print("|---|---|---|---|")
    all_cats = sorted(set(list(agg_a.get(list(agg_a.keys())[0], {}).get("cat", {}).keys())
                          + list(cats_b)) if agg_a else cats_b)
    for m in agg_b:
        for c in all_cats:
            val_a = agg_a.get(m, {}).get("cat", {}).get(c, 0)
            val_b = agg_b[m]["cat"].get(c, 0)
            delta = _delta_str(val_a, val_b)
            print(f"| {m} / {c} | {val_a:.0f}% | {val_b:.0f}% | {delta} |")
    print()

    print("## Per task\n")
    print(f"| Task | {name_a} | {name_b} | Delta |")
    print("|---|---|---|---|")
    for t in tids_b:
        for m in models_b:
            g_a = grades_a.get((m, t))
            g_b = grades_b.get((m, t))
            sc_a = g_a["task_score"] if g_a else 0
            sc_b = g_b["task_score"] if g_b else 0
            r_a = resp_a.get((m, t))
            r_b = resp_b.get((m, t))
            sc_a_str = "DNF" if (r_a and r_a.get("error")) else f"{sc_a:.2f}"
            sc_b_str = "DNF" if (r_b and r_b.get("error")) else f"{sc_b:.2f}"
            delta = _delta_str(sc_a, sc_b)
            print(f"| {t} ({tmap_b[t].get('category', '?')}) | {sc_a_str} | {sc_b_str} | {delta} |")
    print()

    diffs = []
    for t in tids_b:
        for m in models_b:
            g_a = grades_a.get((m, t))
            g_b = grades_b.get((m, t))
            if g_a and g_b:
                d = g_b["task_score"] - g_a["task_score"]
                if abs(d) >= 0.25:
                    direction = "BETTER" if d > 0 else "WORSE"
                    diffs.append((t, m, g_a["task_score"], g_b["task_score"], d, direction))
    if diffs:
        print("## Key differences (|delta| >= 0.25)\n")
        for t, m, sa, sb, d, direction in sorted(diffs, key=lambda x: -abs(x[4])):
            arrow = "+" if d > 0 else "-"
            print(f"- **{t}** ({m}): {sa:.2f} -> {sb:.2f} ({arrow} {abs(d):.2f}) -- {direction}")
    print()


def cmd_history(_args):
    if not os.path.isdir(RUNS_DIR):
        print("no runs yet")
        return
    print("| Run | Set | Date | Model: Score (DNF) |")
    print("|---|---|---|---|")
    for name in sorted(os.listdir(RUNS_DIR)):
        rdir = os.path.join(RUNS_DIR, name)
        meta_p = os.path.join(rdir, "meta.json")
        if not os.path.exists(meta_p):
            continue
        meta = load_json(meta_p)
        tmap = task_map(load_set(meta["set"]))
        _, resp, grades = collect_run(rdir, tmap)
        cells = []
        for m in meta["models"]:
            sc, dnf, n = 0.0, 0, len(meta["tasks"])
            for t in meta["tasks"]:
                r = resp.get((m, t))
                if r and r.get("error"):
                    dnf += 1
                g = grades.get((m, t))
                if g:
                    sc += g["task_score"]
            cells.append(f"{m}: {sc / n * 100:.0f}% ({dnf} DNF)")
        reasoning = meta.get("reasoning")
        rtag = f" [reasoning={reasoning}]" if reasoning else ""
        prov = meta.get("provider", "")
        ptag = f" [{prov}]" if prov else ""
        print(f"| {meta['name']}{rtag}{ptag} | {meta['set']} | {meta['created']} | "
              + " | ".join(cells) + " |")


def main():
    # common provider flags
    def add_provider_args(parser):
        parser.add_argument("--provider", default="",
                            help="provider name from providers.json (e.g. opencode-go, openai, anthropic)")
        parser.add_argument("--base-url", default="",
                            help="API base URL (overrides provider)")
        parser.add_argument("--api-key", default="",
                            help="API key (overrides provider env var)")

    p = argparse.ArgumentParser(
        description="m2bench v2 -- personal LLM benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  py m2bench.py run --models mimo-v2.5 --set hard --name test1\n"
               "  py m2bench.py run --models gpt-4o --provider openai --set easy --name test2\n"
               "  py m2bench.py run --models claude-sonnet-4 --provider anthropic --name test3\n"
               "  py m2bench.py grade --run test1\n"
               "  py m2bench.py compare --run-a test1 --run-b test2\n"
               "  py m2bench.py report --run test1 --compare-to test2\n")
    sub = p.add_subparsers(dest="cmd")

    m = sub.add_parser("models", help="list available models")
    add_provider_args(m)

    sub.add_parser("validate", help="validate all task JSON files")

    r = sub.add_parser("run", help="run inference on tasks")
    add_provider_args(r)
    r.add_argument("--models", required=True, help="comma-separated model ids")
    r.add_argument("--set", default="easy", help="task set(s): easy, medium, hard (comma-separated for multiple)")
    r.add_argument("--name", required=True, help="run name (output folder)")
    r.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    r.add_argument("--runs", type=int, default=1, help="repeat N times")
    r.add_argument("--workers", type=int, default=2, help="parallel workers")
    r.add_argument("--reasoning", default="",
                    help="reasoning_effort: none/low/medium/high/max")

    g = sub.add_parser("grade", help="grade responses with a judge model")
    add_provider_args(g)
    g.add_argument("--run", required=True, help="run name to grade")
    g.add_argument("--judge", default="qwen3.7-plus", help="judge model")
    g.add_argument("--models", default="", help="grade only these models")
    g.add_argument("--workers", type=int, default=2, help="parallel workers")

    pr = sub.add_parser("pair", help="pairwise blind comparison")
    add_provider_args(pr)
    pr.add_argument("--run", required=True, help="run name")
    pr.add_argument("--judge", default="qwen3.7-plus", help="judge model")
    pr.add_argument("--models", default="", help="models to compare")
    pr.add_argument("--workers", type=int, default=2, help="parallel workers")

    rep = sub.add_parser("report", help="generate markdown report")
    rep.add_argument("--run", required=True, help="run name")
    rep.add_argument("--compare-to", default="",
                     help="compare to another run (shows deltas)")

    cmp = sub.add_parser("compare", help="head-to-head comparison of two runs")
    cmp.add_argument("--run-a", required=True, help="first run name")
    cmp.add_argument("--run-b", required=True, help="second run name")

    sub.add_parser("history", help="list all past runs")
    sub.add_parser("tui", help="interactive menu (default if no command)")

    args = p.parse_args()
    if args.cmd is None:
        cmd_tui()
    else:
        {"models": cmd_models, "validate": cmd_validate, "run": cmd_run,
         "grade": cmd_grade, "pair": cmd_pair, "report": cmd_report,
         "compare": cmd_compare, "history": cmd_history,
         "tui": lambda _a: cmd_tui()}[args.cmd](args)


def _input(prompt, default=""):
    """Prompt with default value display."""
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def _pick_number(title, options, default=1):
    """Show numbered menu, return selected option."""
    print(f"\n{colorize(title, 'bold')}")
    for i, opt in enumerate(options, 1):
        print(f"  {colorize(str(i), 'bold')}. {opt}")
    while True:
        raw = input(f"\n> ").strip()
        if not raw:
            return options[default - 1]
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        print(f"  {colorize('invalid choice', 'err')}")


def cmd_tui():
    """Interactive menu-based TUI for m2bench."""
    print(colorize("\n  m2bench v2 — Personal LLM Benchmark", "bold"))
    print(colorize("  " + "=" * 40, "dim"))

    action = _pick_number("Main Menu", [
        "Run benchmark",
        "Grade responses",
        "Compare two runs",
        "View history",
        "Validate task sets",
        "List models",
        "Exit",
    ], default=7)

    if action == "Exit":
        print("bye!")
        return

    if action == "Validate task sets":
        print()
        cmd_validate(None)
        return

    if action == "View history":
        print()
        cmd_history(None)
        return

    if action == "List models":
        pname = _pick_number("Provider", [
            "opencode-go", "openai", "anthropic",
            "deepseek", "xiaomi", "openrouter", "custom"
        ])
        base_url = ""
        api_key = ""
        if pname == "custom":
            base_url = _input("Base URL")
            api_key = _input("API key")
        ns = argparse.Namespace(provider=pname, base_url=base_url, api_key=api_key)
        print()
        cmd_models(ns)
        return

    # --- Run / Grade / Compare need provider first ---
    if action in ("Run benchmark", "Grade responses", "Compare two runs"):
        pname = _pick_number("Provider", [
            "opencode-go", "openai", "anthropic",
            "deepseek", "xiaomi", "openrouter", "custom"
        ])
        base_url = ""
        api_key = ""
        if pname == "custom":
            base_url = _input("Base URL")
            api_key = _input("API key")

    if action == "Run benchmark":
        models = _input("Model(s) (comma-separated)")
        if not models:
            print(colorize("model is required", "err"))
            return
        set_name = _input("Task set", "easy")
        run_name = _input("Run name", f"run-{time.strftime('%H%M%S')}")
        reasoning = _input("Reasoning effort [none/low/medium/high/max, Enter=skip]", "")
        workers = _input("Workers", "2")
        print()
        ns = argparse.Namespace(
            provider=pname, base_url=base_url, api_key=api_key,
            models=models, set=set_name, name=run_name, tasks="",
            runs=1, workers=int(workers), reasoning=reasoning,
        )
        cmd_run(ns)
        return

    if action == "Grade responses":
        run_name = _input("Run name")
        if not run_name:
            print(colorize("run name is required", "err"))
            return
        judge = _input("Judge model", "qwen3.7-plus")
        workers = _input("Workers", "2")
        print()
        ns = argparse.Namespace(
            provider=pname, base_url=base_url, api_key=api_key,
            run=run_name, judge=judge, models="", workers=int(workers),
        )
        cmd_grade(ns)
        return

    if action == "Compare two runs":
        run_a = _input("Run A (baseline)")
        run_b = _input("Run B (challenger)")
        if not run_a or not run_b:
            print(colorize("both run names are required", "err"))
            return
        print()
        ns = argparse.Namespace(run_a=run_a, run_b=run_b)
        cmd_compare(ns)
        return


if __name__ == "__main__":
    main()
