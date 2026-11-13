"""Tabel side-by-side semua model yang pernah dibenchmark di m2bench.

Hanya memakai run yang di-grade judge qwen3.7-plus (id lama 'qwen3.7-plus' dan
bentuk baru 'Qwen/Qwen3.7-Plus' dianggap judge yang sama) supaya angka sebanding.
Skor = rata-rata task_score / jumlah task di set (task DNF dihitung 0), sama
seperti perhitungan report.

Jalankan: py compare_all_models.py
Output : ../data/m2bench/all-models-side-by-side.md (relatif ke Hermes-Output)
"""
import json
import glob
import os
import collections

ROOT = r"C:/Users/athai/Hermes-Output/data/m2bench/runs"
OUT = r"C:/Users/athai/Hermes-Output/data/m2bench/all-models-side-by-side.md"
JUDGES = {"qwen3.7-plus", "Qwen/Qwen3.7-Plus"}
SETS = ["easy", "medium", "hard"]


def main():
    per = collections.defaultdict(dict)   # (model, set) -> data run terbaru
    other_judge = collections.defaultdict(set)

    for mj in sorted(glob.glob(os.path.join(ROOT, "*", "meta.json"))):
        run = os.path.dirname(mj)
        meta = json.load(open(mj, encoding="utf-8"))
        grades = glob.glob(os.path.join(run, "grades", "*.json"))
        if not grades:
            continue
        judge = json.load(open(grades[0], encoding="utf-8")).get("judge")
        set_name = meta.get("set")
        tasks = meta.get("tasks", [])
        for g in grades:
            rec = json.load(open(g, encoding="utf-8"))
            if rec.get("judge") not in JUDGES:
                other_judge[(rec.get("model"), set_name)].add(rec.get("judge"))
                continue
            model = rec.get("model")
            d = per[(model, set_name)].get(os.path.basename(run))
            if d is None or meta.get("created", "") > d["created"]:
                per[(model, set_name)][os.path.basename(run)] = {
                    "created": meta.get("created", ""),
                    "scores": {},
                    "tasks": tasks,
                    "reasoning": meta.get("reasoning"),
                    "provider": meta.get("provider"),
                }
            per[(model, set_name)][os.path.basename(run)]["scores"][rec["task"]] = \
                rec.get("task_score") or 0

    # runtuhkan: satu baris per (model, set) = run terbaru
    rows = {}
    for (model, set_name), runs in per.items():
        best = max(runs.values(), key=lambda d: d["created"])
        n = len(best["tasks"]) or len(best["scores"])
        score = sum(best["scores"].values()) / n * 100 if n else 0
        dnf = n - len(best["scores"])
        rows.setdefault(model, {})[set_name] = {
            "score": score, "dnf": dnf, "n": n,
            "run": max(runs.items(), key=lambda kv: kv[1]["created"])[0],
            "reasoning": best["reasoning"], "runs": sorted(runs),
            "provider": best.get("provider"),
        }

    def key(m):
        d = rows[m]
        hard = d.get("hard", {}).get("score", -1)
        easy = d.get("easy", {}).get("score", -1)
        mid = d.get("medium", {}).get("score", -1)
        return (-hard, -mid, -easy, m)

    lines = ["# m2bench - side by side semua model (judge qwen3.7-plus)",
             "",
             "Skor = rata-rata task_score / jumlah task di set (DNF = 0). "
             "Hanya run yang di-grade judge qwen3.7-plus.",
             "Kolom `-` = model belum pernah dibenchmark di set itu. "
             "Provider = gateway run terbaru per set (dipisah `/` kalau beda antar set). "
             "avg3 = rata-rata easy+medium+hard, hanya diisi kalau ketiga set ada.",
             "",
             "| Model | Provider | easy | medium | hard | avg3 | DNF total | Run (set) |",
             "|---|---|---|---|---|---|---|---|"]
    for m in sorted(rows, key=key):
        d = rows[m]
        cells = []
        for s in SETS:
            v = d.get(s)
            cells.append(f"{v['score']:.1f}% ({v['dnf']})" if v else "-")
        dnf = sum(v["dnf"] for v in d.values())
        rn = ", ".join(f"{v['run']}" for s in SETS if (v := d.get(s)))
        provs = sorted({v["provider"] for v in d.values() if v.get("provider")})
        prov = "/".join(provs) if provs else "-"
        if all(s in d for s in SETS):
            avg3 = f"{(d['easy']['score'] + d['medium']['score'] + d['hard']['score']) / 3:.1f}%"
        else:
            avg3 = "-"
        lines.append(f"| {m} | {prov} | {cells[0]} | {cells[1]} | {cells[2]} | {avg3} | {dnf} | {rn} |")
    lines.append("")
    if other_judge:
        lines.append("## Run dengan judge lain (tidak sebanding, tidak dihitung)")
        for (model, s), js in sorted(other_judge.items()):
            lines.append(f"- {model} ({s}): {', '.join(sorted(js))}")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()
