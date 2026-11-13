"""Bangun data/m2bench/all-benchmarks-combined.md — gabungan SEMUA hasil m2bench.

Sumber:
- runs/*/meta.json + runs/*/grades/*.json  (semua run, semua provider, semua judge)
- all-models-side-by-side.md (tabel utama: run terbaru per model+set)

Isi dokumen:
  1. Tabel utama  = embed all-models-side-by-side.md (semua model, semua provider)
  2. Lintas sumber = tabel kurasi model yang sama di beberapa provider/run
  3. Riwayat lengkap = semua run yang punya skor (semua judge, ditandai)
  4. Run tanpa grade = daftar eksperimen yang tidak punya file grade

Jalankan: py build_combined_all.py
"""
import json
import glob
import os
import collections
import time

ROOT = r"C:/Users/athai/Hermes-Output/data/m2bench/runs"
SBS = r"C:/Users/athai/Hermes-Output/data/m2bench/all-models-side-by-side.md"
OUT = r"C:/Users/athai/Hermes-Output/data/m2bench/all-benchmarks-combined.md"

QJ = {"qwen3.7-plus", "Qwen/Qwen3.7-Plus"}


def judge_label(j):
    if j in QJ:
        return "Qwen3.7-Plus"
    if j and "ling-3.0" in j:
        return "ling-3.0"
    return str(j)


CROSS = """## 2. Model yang sama di beberapa provider / run (digabung)

Skor tetap per sumber (run yang berbeda tidak dirata-rata). Judge semua baris = Qwen3.7-Plus kecuali yang
ditandai. Catatan: run opencode-go 10 Sep hanya menguji easy & hard; medium baru diuji belakangan.

| Model (digabung) | Sumber | easy | medium | hard |
|---|---|---:|---:|---:|
| Qwen3.8-Flash | opencode-go · 10 Sep (batch8-rh, hard-qwen) | 100.0% | – | 98.4% |
| Qwen3.8-Flash | commandcode · 30 Sep (flash3way-rh) | 100.0% | 93.8% | 90.6% |
| GLM-5.3-Flash | opencode-go · 10 Sep (batch2-rh, hard-glm) | 100.0% | – | 98.4% |
| GLM-5.3-Flash | commandcode · 30 Sep (flash3way-rh) | 96.9% | 100.0% | 92.2% |
| MiMo V2.6 Pro | xiaomi · 23 Sep (mimo26-rh) | 100.0% | 100.0% | 87.5% † |
| MiMo V2.6 Pro | xiaomi · 23 Sep (mimo26pro-rh2) | 95.3% | 100.0% | 100.0% |
| MiMo V2.6 Pro | xiaomi · 30 Sep (mimo26pair-rh) | 98.4% | 100.0% | 100.0% |
| MiMo V2.6 Flash | xiaomi · 23 Sep (mimo26-rh) | 96.9% | 100.0% | 96.9% |
| MiMo V2.6 Flash | xiaomi · 30 Sep (mimo26pair-rh) | 96.9% | 100.0% | 100.0% |
| MiMo V2.5 | opencode-go · 10 Sep (batch5-rh, mimo25-rh, hard-misc1, mimo-hard-high, compare_r2) | 95.3–96.9% | 96.9% | 90.6–96.9% |
| MiMo V2.5 | xiaomi · 12 Sep — judge ling-3.0 (mimo25-*-on/off) | 89.1–96.9% | 98.4% | 67.2–92.2% |
| MiMo V2.5 Pro | opencode-go · 10 Sep (batch5-rh, mimo25pro-rh, hard-misc1, compare_r2) | 96.9% | – | 92.2–95.3% |
| MiMo V2.5 Pro | xiaomi · 12 Sep — judge ling-3.0 (vsoff) | – | – | 89.1% |
| DeepSeek V4 (family) | opencode-go · 10 Sep — flash e98.4/h94.6 · v4-flash e95.3/h95.3 · v4-flash-vision-exp e98.4/h96.9 · v4-pro e90.6/h93.8 | 90.6–98.4% | – | 93.8–96.9% |
| DeepSeek V4.1 Flash | commandcode · 30 Sep (flash3way-rh) | 100.0% | 96.9% | 95.3% |
| hy3 | opencode-go · 10 Sep — easy: 90.6% (hy3-rh) vs 98.4% (batch3-rh) · hard 78.1% (hard-hykimi) | 90.6–98.4% | – | 78.1% |

† 87.5% karena 1 task DNF dihitung 0 (7/8 task dinilai — reasoning kehabisan budget 24576 token; run ulang dengan budget 65536 selesai penuh).
Model yang mirip nama tapi beda (mis. Qwen3.8-Max vs Qwen3.8-27B vs Qwen3.8-Flash) tidak digabung; deepseek v4 vs v4.1 juga dipisah karena versi beda."""


def main():
    history = []
    nograde = []
    for run in sorted(os.listdir(ROOT)):
        rd = os.path.join(ROOT, run)
        mp = os.path.join(rd, "meta.json")
        if not os.path.exists(mp):
            nograde.append(run)
            continue
        meta = json.load(open(mp, encoding="utf-8"))
        gdir = os.path.join(rd, "grades")
        grades = glob.glob(os.path.join(gdir, "*.json")) if os.path.isdir(gdir) else []
        if not grades:
            nograde.append(run)
            continue
        by = collections.defaultdict(list)
        for g in grades:
            d = json.load(open(g, encoding="utf-8"))
            by[(d.get("model"), d.get("judge"))].append(d.get("task_score") or 0)
        tasks = meta.get("tasks") or []
        for (m, j), sc in sorted(by.items()):
            tot = len(tasks) or len(sc)
            history.append({
                "created": meta.get("created") or "",
                "run": run,
                "provider": meta.get("provider") or "?",
                "set": meta.get("set") or "?",
                "model": m,
                "judge": judge_label(j),
                "score": sum(sc) / tot * 100,
                "n": len(sc),
                "tot": tot,
            })
    history.sort(key=lambda r: (r["created"], r["run"], r["model"]))

    sbs_lines = open(SBS, encoding="utf-8").read().splitlines()
    start = next(i for i, l in enumerate(sbs_lines) if l.startswith("| Model"))
    end = next(i for i, l in enumerate(sbs_lines) if l.startswith("## Run dengan judge lain"))
    main_table = "\n".join(sbs_lines[start:end]).rstrip()

    hrows = []
    for r in history:
        nsuf = "" if r["n"] == r["tot"] else " ({}/{})".format(r["n"], r["tot"])
        hrows.append("| {} | {} | {} | {} | {} | {:.1f}%{} | {} |".format(
            r["created"][:10], r["run"], r["provider"], r["set"], r["model"],
            r["score"], nsuf, r["judge"]))
    nrows = "\n".join("- `{}`".format(r) for r in nograde)

    today = time.strftime("%Y-%m-%d")
    doc = "\n".join([
        "# m2bench - gabungan SEMUA hasil benchmark (semua provider)",
        "",
        "Kompilasi: " + today + " | sumber: `data/m2bench/runs` + `all-models-side-by-side.md`.",
        "Konvensi skor sama dengan harness: rata-rata task_score (pass=1, partial=0.5, fail=0) ",
        "dibagi jumlah task di set; task tanpa grade / DNF dihitung 0 (ditandai `(n/total)`).",
        "Semua provider ikut (opencode-go, commandcode, xiaomi, openrouter); run yang judge-nya ",
        "berbeda (ling-3.0) ikut masuk riwayat lengkap dan ditandai — tidak ada yang dibuang.",
        "",
        "## 1. Tabel utama - data terbaru per model + set",
        "",
        "Sumber: `all-models-side-by-side.md` (regenerate: `py tools/compare_all_models.py`).",
        "Kolom Provider = gateway run terbaru per set.",
        "",
        main_table,
        "",
        CROSS,
        "",
        "## 3. Riwayat lengkap - semua run yang punya skor",
        "",
        "| Tanggal | Run | Provider | Set | Model | Skor (n/total) | Judge |",
        "|---|---|---|---|---|---|---|",
        "\n".join(hrows),
        "",
        "## 4. Run tanpa grade (eksperimen / tidak dilanjutkan)",
        "",
        nrows,
        "",
    ])
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print("written:", OUT)
    print("history rows:", len(history), "| nograde:", len(nograde))


if __name__ == "__main__":
    main()
