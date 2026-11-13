"""Bandingkan hasil m2bench Qwen3.8-27B (commandcode) dengan run terdahulu.

Read-only terhadap run lama. Output: data/m2bench/qwen38-27b-benchmark-2026-09-18.md
"""
import json
import os
import re

DATA = os.path.join(os.environ.get("USERPROFILE", ""), "Hermes-Output", "data", "m2bench")
RUNS = os.path.join(DATA, "runs")
TASKS = os.path.join(os.environ.get("USERPROFILE", ""), "Hermes-Output", "code", "athabench", "tasks")
JUDGE_PREF = "Qwen_Qwen3.7-Plus"

# set -> list of (run_name, model_id, display_label)
PLAN = {
    "easy": [
        ("qwen38-27b-cc-easy", "Qwen/Qwen3.8-27B", "Qwen3.8-27B (commandcode)"),
        ("batch8-rh", "qwen3.8-flash", "qwen3.8-flash"),
        ("batch8-rh", "qwen3.8-max", "qwen3.8-max"),
        ("batch1-rh", "deepseek-v4-flash", "deepseek-v4-flash"),
        ("mimo25-rh", "mimo-v2.5", "mimo-v2.5"),
    ],
    "medium": [
        ("qwen38-27b-cc", "Qwen/Qwen3.8-27B", "Qwen3.8-27B (commandcode)"),
        ("mimo25-medium-on", "mimo-v2.5", "mimo-v2.5"),
    ],
    "hard": [
        ("qwen38-27b-cc-hard", "Qwen/Qwen3.8-27B", "Qwen3.8-27B (commandcode)"),
        ("hard-qwen", "qwen3.8-flash", "qwen3.8-flash"),
        ("hard-qwen", "qwen3.8-max", "qwen3.8-max"),
        ("hard-deepseek", "deepseek-v4-flash", "deepseek-v4-flash"),
        ("mimo-hard-high", "mimo-v2.5", "mimo-v2.5"),
    ],
}


def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s))


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def task_meta(set_name):
    obj = load(os.path.join(TASKS, f"{set_name}.json"))
    return {t["id"]: t.get("category", "?") for t in obj}, [t["id"] for t in obj]


def grade_for(run, model, task):
    gdir = os.path.join(RUNS, run, "grades")
    if not os.path.isdir(gdir):
        return None
    want = f"__{safe(model)}__{safe(task)}.json"
    cands = [f for f in os.listdir(gdir) if f.endswith(want)]
    if not cands:
        return None
    pref = [f for f in cands if f.startswith(JUDGE_PREF)]
    pick = (pref or cands)[0]
    g = load(os.path.join(gdir, pick))
    g["_judge"] = pick.split("__")[0]
    return g


def stats(run, model, tids, cat):
    scores, times, dnf, judge = [], [], 0, set()
    per_task = {}
    for t in tids:
        rp = os.path.join(RUNS, run, "responses", f"{safe(model)}__{safe(t)}.json")
        g = grade_for(run, model, t)
        r = load(rp) if os.path.exists(rp) else None
        if r and r.get("error"):
            dnf += 1
            s = 0.0
        elif g:
            s = g["task_score"]
            judge.add(g["_judge"])
        else:
            per_task[t] = None
            continue
        scores.append(s)
        per_task[t] = ("DNF" if (r and r.get("error")) else s)
        if r and not r.get("error"):
            times.append(r.get("total_ms", 0) / 1000)
    total = len(tids)
    overall = sum(scores) / total * 100 if total else 0.0
    cats = {}
    for c in sorted(set(cat.values())):
        vals = [per_task[t] for t in tids if cat[t] == c and isinstance(per_task.get(t), (int, float))]
        n_c = sum(1 for t in tids if cat[t] == c)
        cats[c] = sum(vals) / n_c * 100 if n_c else 0.0
    return {
        "score": overall,
        "dnf": dnf,
        "avg_time": (sum(times) / len(times)) if times else 0.0,
        "cats": cats,
        "per_task": per_task,
        "judge": ", ".join(sorted(judge)) or "-",
        "n_graded": len(scores),
    }


out = ["# Benchmark Qwen3.8-27B (commandcode) vs hasil terdahulu", ""]
out.append("Tanggal run: 2026-09-18 | model: `Qwen/Qwen3.8-27B` | provider: commandcode "
           "(`api.commandcode.ai/provider/v1`) | reasoning_effort: high | workers: 3")
out.append("")
out.append("Set: easy / medium / hard, masing-masing 8 task dengan 4 kriteria (pass=1, partial=0.5, "
           "fail=0, DNF=0). Judge run baru: `Qwen/Qwen3.7-Plus` di commandcode (model judge yang sama "
           "dengan run lama `qwen3.7-plus`). Run lama masuk apa adanya dari folder `data/m2bench/runs`.")
out.append("")

res = {}
for set_name, rows in PLAN.items():
    cat, tids = task_meta(set_name)
    for run, model, label in rows:
        res[(set_name, label)] = stats(run, model, tids, cat)

labels = ["Qwen3.8-27B (commandcode)", "qwen3.8-flash", "qwen3.8-max", "deepseek-v4-flash", "mimo-v2.5"]
out.append("## Skor total per set")
out.append("")
out.append("| Model | easy | medium | hard |")
out.append("|---|---:|---:|---:|")
for lb in labels:
    cells = []
    for s in ("easy", "medium", "hard"):
        d = res.get((s, lb))
        cells.append(f"{d['score']:.1f}% ({d['dnf']} DNF)" if d else "belum ada")
    out.append(f"| {lb} | " + " | ".join(cells) + " |")
out.append("")

out.append("## Waktu rata-rata per task dan judge yang dipakai")
out.append("")
out.append("| Set | Model | Avg time/task | Task dinilai | Judge |")
out.append("|---|---|---:|---:|---|")
for s in ("easy", "medium", "hard"):
    for lb in labels:
        d = res.get((s, lb))
        if not d:
            continue
        out.append(f"| {s} | {lb} | {d['avg_time']:.0f}s | {d['n_graded']}/8 | {d['judge']} |")
out.append("")

out.append("## Per kategori")
out.append("")
for s in ("easy", "medium", "hard"):
    avail = [(lb, res[(s, lb)]) for lb in labels if (s, lb) in res]
    cats = sorted({c for _, d in avail for c in d["cats"]})
    out.append(f"### {s}")
    out.append("")
    out.append("| Model | " + " | ".join(cats) + " |")
    out.append("|---" * (len(cats) + 1) + "|")
    for lb, d in avail:
        out.append(f"| {lb} | " + " | ".join(f"{d['cats'].get(c, 0):.0f}" for c in cats) + " |")
    out.append("")

out.append("## Per task")
out.append("")
for s in ("easy", "medium", "hard"):
    cat, tids = task_meta(s)
    avail = [(lb, res[(s, lb)]) for lb in labels if (s, lb) in res]
    out.append(f"### {s}")
    out.append("")
    out.append("| Task | kategori | " + " | ".join(lb for lb, _ in avail) + " |")
    out.append("|---|---|" + "---|" * len(avail))
    for t in tids:
        cells = []
        for _, d in avail:
            v = d["per_task"].get(t)
            cells.append("DNF" if v == "DNF" else ("-" if v is None else f"{v:.2f}"))
        out.append(f"| {t} | {cat[t]} | " + " | ".join(cells) + " |")
    out.append("")

# delta vs qwen3.8 siblings
out.append("## Selisih vs qwen3.8-flash dan qwen3.8-max")
out.append("")
out.append("| Set | vs qwen3.8-flash | vs qwen3.8-max |")
out.append("|---|---:|---:|")
for s in ("easy", "medium", "hard"):
    me = res.get((s, "Qwen3.8-27B (commandcode)"))
    f = res.get((s, "qwen3.8-flash"))
    m = res.get((s, "qwen3.8-max"))
    df = f"{me['score'] - f['score']:+.1f}%" if (me and f) else "belum ada"
    dm = f"{me['score'] - m['score']:+.1f}%" if (me and m) else "belum ada"
    out.append(f"| {s} | {df} | {dm} |")
out.append("")

# kriteria yang jatuh untuk model baru
out.append("## Kriteria yang tidak pass di run baru")
out.append("")
any_fail = False
for s in ("easy", "medium", "hard"):
    cat, tids = task_meta(s)
    d = res.get((s, "Qwen3.8-27B (commandcode)"))
    for t in tids:
        g = grade_for("qwen38-27b-cc" + ("" if s == "medium" else f"-{s}"), "Qwen/Qwen3.8-27B", t)
        if not g:
            continue
        bad = [(cid, v) for cid, v in g["verdicts"].items() if v["verdict"] != "pass"]
        for cid, v in bad:
            any_fail = True
            out.append(f"- {s} / {t} / {cid}: {v['verdict']} - {v['reason']}")
if not any_fail:
    out.append("- tidak ada, semua kriteria pass di ketiga set")
out.append("")

path = os.path.join(DATA, "qwen38-27b-benchmark-2026-09-18.md")
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(out))
print("written:", path)
print("\n".join(out[:40]))
