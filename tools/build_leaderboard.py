"""Generate a self-contained interactive benchmark leaderboard (HTML + JSON) from m2bench runs.

Reuses m2bench.aggregate_run() across all graded runs in data/m2bench/runs/
and writes:
  - data/m2bench/leaderboard.json
  - data/m2bench/leaderboard.html

Usage:
  py tools/build_leaderboard.py
"""
import json
import os
import sys

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODE_DIR)
import m2bench  # noqa: E402

OUT_JSON = os.path.join(m2bench.DATA_DIR, "leaderboard.json")
OUT_HTML = os.path.join(m2bench.DATA_DIR, "leaderboard.html")
SET_ORDER = ["frontier", "expert", "daily_plus", "hard", "medium", "easy"]


def collect_entries():
    """Aggregate every graded (run, model) record across RUNS_DIR."""
    if not os.path.isdir(m2bench.RUNS_DIR):
        return []

    tmap_cache = {}
    entries = []

    for run_name in sorted(os.listdir(m2bench.RUNS_DIR)):
        rdir = os.path.join(m2bench.RUNS_DIR, run_name)
        meta_p = os.path.join(rdir, "meta.json")
        if not os.path.exists(meta_p):
            continue
        meta = m2bench.load_json(meta_p)
        set_name = meta.get("set", "")
        if set_name not in tmap_cache:
            try:
                tmap_cache[set_name] = m2bench.task_map(m2bench.load_set(set_name))
            except SystemExit:
                tmap_cache[set_name] = None
        tmap = tmap_cache[set_name]
        if not tmap:
            continue

        gdir = os.path.join(rdir, "grades")
        if not os.path.isdir(gdir) or not any(f.endswith(".json") for f in os.listdir(gdir)):
            continue

        _, tids, models, cats, grades, resp, agg = m2bench.aggregate_run(rdir, tmap)
        if not grades:
            continue

        judges = sorted({g.get("judge", "") for g in grades.values() if g.get("judge")})

        for model in models:
            st = agg[model]
            graded_n = sum(1 for t in tids if (model, t) in grades)
            if graded_n == 0 and st["dnf"] == 0:
                continue

            tot_s = sum(st["times"])
            avg_s = round(tot_s / len(st["times"]), 1) if st["times"] else None
            tps = round(st["ctok"] / tot_s, 1) if (st["ctok"] and tot_s > 0) else None
            n_tasks = len(tids) or 1
            completed_scores = [grades[(model, t)]["task_score"] for t in tids if (model, t) in grades]
            non_dnf_avg = round(sum(completed_scores) / len(completed_scores) * 100, 1) if completed_scores else 0.0
            strict_count = sum(1 for s in completed_scores if s == 1.0)
            strict_pct = round(st.get("strict", strict_count / n_tasks * 100), 1)

            per_task = []
            for t in tids:
                r = resp.get((model, t))
                g = grades.get((model, t))
                if r and r.get("error"):
                    status, sc = "DNF", None
                elif g:
                    status, sc = "OK", round(g["task_score"], 2)
                else:
                    status, sc = "-", None
                per_task.append({
                    "id": t,
                    "cat": tmap[t].get("category", "?"),
                    "status": status,
                    "score": sc,
                })

            entries.append({
                "run": run_name,
                "set": set_name,
                "date": meta.get("created", ""),
                "model": model,
                "provider": meta.get("provider") or "unknown",
                "reasoning": meta.get("reasoning") or "default",
                "temp": "default" if meta.get("temperature") is None else meta.get("temperature"),
                "judges": judges,
                "score": round(st["score"], 1),
                "strict": strict_pct,
                "strict_count": strict_count,
                "non_dnf_avg": non_dnf_avg,
                "dnf": st["dnf"],
                "completed": len(completed_scores),
                "total_tasks": len(tids),
                "avg_s": avg_s,
                "tps": tps,
                "avg_ptok": round(st["ptok"] / n_tasks) if st["ptok"] else None,
                "avg_ctok": round(st["ctok"] / n_tasks) if st["ctok"] else None,
                "categories": {c: round(st["cat"].get(c, 0), 1) for c in cats},
                "tasks": per_task,
            })

    return entries


HTML_TEMPLATE = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>m2bench — Personal Open-Source LLM Leaderboard</title>
<style>
  :root {
    --bg: #0b0f17;
    --panel: #121826;
    --panel-2: #182032;
    --border: #253047;
    --text: #e6edf7;
    --muted: #8b9bb4;
    --accent: #4f8cff;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
    --font: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: var(--font); line-height: 1.45;
  }
  .wrap { max-width: 1320px; margin: 0 auto; padding: 24px 20px 60px; }
  header {
    display: flex; flex-wrap: wrap; gap: 16px;
    justify-content: space-between; align-items: flex-end;
    margin-bottom: 20px;
  }
  h1 { margin: 0; font-size: 1.55rem; letter-spacing: -0.02em; }
  .sub { color: var(--muted); font-size: 0.9rem; margin-top: 4px; }
  .stats { display: flex; gap: 12px; flex-wrap: wrap; }
  .stat-card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 14px; min-width: 130px;
  }
  .stat-card .k { font-size: 0.75rem; color: var(--muted); }
  .stat-card .v { font-size: 1.15rem; font-weight: 700; margin-top: 2px; }

  .tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
  .tab {
    background: var(--panel); border: 1px solid var(--border);
    color: var(--muted); padding: 8px 14px; border-radius: 8px;
    cursor: pointer; font-weight: 600; font-size: 0.88rem;
  }
  .tab.active {
    background: var(--accent); border-color: var(--accent); color: #fff;
  }

  .controls {
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; margin-bottom: 18px;
  }
  input[type="search"], select {
    background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 7px;
    padding: 7px 10px; font-size: 0.88rem;
  }
  input[type="search"] { min-width: 220px; flex: 1; max-width: 340px; }
  label.toggle {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 0.86rem; color: var(--text); cursor: pointer;
    margin-left: auto;
  }

  .grid-charts {
    display: grid; grid-template-columns: 1.1fr 1fr; gap: 16px;
    margin-bottom: 18px;
  }
  @media (max-width: 960px) { .grid-charts { grid-template-columns: 1fr; } }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 16px;
  }
  .card h2 {
    margin: 0 0 12px; font-size: 0.95rem; color: var(--muted);
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
  }

  .bar-row {
    display: grid; grid-template-columns: 180px 1fr 56px;
    gap: 10px; align-items: center; margin-bottom: 8px; font-size: 0.85rem;
  }
  .bar-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
  .bar-track {
    height: 12px; background: var(--bg); border-radius: 999px; overflow: hidden;
    border: 1px solid var(--border);
  }
  .bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #3b82f6, #22c55e); }
  .bar-val { text-align: right; font-family: var(--mono); font-weight: 700; }

  .table-wrap {
    overflow-x: auto; background: var(--panel);
    border: 1px solid var(--border); border-radius: 12px;
  }
  table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
  th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }
  th {
    background: var(--panel-2); color: var(--muted); font-weight: 600;
    white-space: nowrap; cursor: pointer; user-select: none;
    position: sticky; top: 0;
  }
  th:hover { color: var(--text); }
  tr.data-row { cursor: pointer; transition: background 0.12s; }
  tr.data-row:hover { background: rgba(79, 140, 255, 0.08); }
  .num { text-align: right; font-family: var(--mono); }
  .model-title { font-weight: 700; color: var(--text); }
  .run-meta { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
  .pill {
    display: inline-block; padding: 1px 7px; border-radius: 999px;
    font-size: 0.72rem; border: 1px solid var(--border);
    background: var(--bg); color: var(--muted); margin-right: 4px;
  }
  .score-good { color: var(--green); font-weight: 700; }
  .score-mid { color: var(--amber); font-weight: 700; }
  .score-bad { color: var(--red); font-weight: 700; }

  dialog {
    background: var(--panel); color: var(--text);
    border: 1px solid var(--border); border-radius: 12px;
    max-width: 820px; width: 92vw; max-height: 82vh; padding: 0;
  }
  dialog::backdrop { background: rgba(0,0,0,0.65); }
  .dlg-head {
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 18px; border-bottom: 1px solid var(--border);
    position: sticky; top: 0; background: var(--panel);
  }
  .dlg-body { padding: 14px 18px; overflow-y: auto; max-height: calc(82vh - 60px); }
  .close-btn {
    background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); border-radius: 7px;
    padding: 5px 10px; cursor: pointer;
  }
  svg.scatter { width: 100%; height: 220px; display: block; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>m2bench — Personal LLM Leaderboard</h1>
      <div class="sub" id="subtitle"></div>
    </div>
    <div class="stats" id="summaryCards"></div>
  </header>

  <div class="tabs" id="setTabs"></div>

  <div class="controls">
    <input type="search" id="searchBox" placeholder="Cari model atau nama run..." />
    <select id="metricMode">
      <option value="strict">Ranking: Strict Pass (100%)</option>
      <option value="score">Ranking: Avg Score</option>
    </select>
    <select id="providerFilter"><option value="">Semua provider</option></select>
    <select id="judgeFilter"><option value="">Semua judge</option></select>
    <label class="toggle">
      <input type="checkbox" id="latestOnly" checked />
      Run terbaru per model saja
    </label>
  </div>

  <div class="grid-charts">
    <div class="card">
      <h2 id="barTitle">Top Strict Pass (100% Task Score)</h2>
      <div id="barChart"></div>
    </div>
    <div class="card">
      <h2 id="scatterTitle">Strict Pass vs Speed (t/s)</h2>
      <svg class="scatter" id="scatterSvg" viewBox="0 0 460 220"></svg>
    </div>
  </div>

  <div class="table-wrap">
    <table>
      <thead id="tableHead"></thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
</div>

<dialog id="taskDialog">
  <div class="dlg-head">
    <div>
      <strong id="dlgTitle"></strong>
      <div class="run-meta" id="dlgMeta"></div>
    </div>
    <button class="close-btn" id="dlgClose">Tutup</button>
  </div>
  <div class="dlg-body">
    <table>
      <thead><tr><th>Task</th><th>Kategori</th><th class="num">Skor</th></tr></thead>
      <tbody id="dlgBody"></tbody>
    </table>
  </div>
</dialog>

<script>
const DATA = __LEADERBOARD_JSON__;
const SET_ORDER = __SET_ORDER__;

let activeSet = SET_ORDER.find(s => DATA.entries.some(e => e.set === s)) || DATA.sets[0] || "";
let metricMode = "strict";
let sortKey = "strict";
let sortDesc = true;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function scoreClass(v) {
  if (v >= 85) return "score-good";
  if (v >= 60) return "score-mid";
  return "score-bad";
}

function getFiltered() {
  const q = document.getElementById("searchBox").value.trim().toLowerCase();
  const prov = document.getElementById("providerFilter").value;
  const judge = document.getElementById("judgeFilter").value;
  const latest = document.getElementById("latestOnly").checked;

  let rows = DATA.entries.filter(e => e.set === activeSet);
  if (prov) rows = rows.filter(e => e.provider === prov);
  if (judge) rows = rows.filter(e => e.judges.includes(judge));
  if (q) rows = rows.filter(e => (e.model + " " + e.run).toLowerCase().includes(q));

  if (latest) {
    const best = new Map();
    for (const r of rows) {
      const prev = best.get(r.model);
      if (!prev || r.date > prev.date) best.set(r.model, r);
    }
    rows = [...best.values()];
  }

  rows.sort((a, b) => {
    let av = sortKey.startsWith("cat:") ? (a.categories[sortKey.slice(4)] ?? -1) : (a[sortKey] ?? -1);
    let bv = sortKey.startsWith("cat:") ? (b.categories[sortKey.slice(4)] ?? -1) : (b[sortKey] ?? -1);
    if (typeof av === "string" || typeof bv === "string") {
      return sortDesc ? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
    }
    return sortDesc ? (bv - av) : (av - bv);
  });
  return rows;
}

function renderFilters() {
  const setEntries = DATA.entries.filter(e => e.set === activeSet);
  const provSel = document.getElementById("providerFilter");
  const curP = provSel.value;
  const provs = [...new Set(setEntries.map(e => e.provider))].sort();
  provSel.innerHTML = '<option value="">Semua provider</option>' +
    provs.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
  if (provs.includes(curP)) provSel.value = curP;

  const judgeSel = document.getElementById("judgeFilter");
  const curJ = judgeSel.value;
  const judges = [...new Set(setEntries.flatMap(e => e.judges))].sort();
  judgeSel.innerHTML = '<option value="">Semua judge</option>' +
    judges.map(j => `<option value="${esc(j)}">${esc(j)}</option>`).join("");
  if (judges.includes(curJ)) judgeSel.value = curJ;
}

function renderTabs() {
  const available = SET_ORDER.filter(s => DATA.entries.some(e => e.set === s));
  for (const s of DATA.sets) if (!available.includes(s)) available.push(s);
  document.getElementById("setTabs").innerHTML = available.map(s => {
    const cnt = new Set(DATA.entries.filter(e => e.set === s).map(e => e.model)).size;
    return `<button class="tab ${s === activeSet ? "active" : ""}" data-set="${esc(s)}">${esc(s)} (${cnt})</button>`;
  }).join("");
  document.querySelectorAll(".tab").forEach(btn => {
    btn.onclick = () => {
      activeSet = btn.dataset.set;
      renderTabs();
      renderFilters();
      renderAll();
    };
  });
}

function activeVal(r) {
  return metricMode === "strict" ? r.strict : r.score;
}

function renderCharts(rows) {
  const isStrict = metricMode === "strict";
  document.getElementById("barTitle").textContent = isStrict
    ? "Top Strict Pass (100% Task Score)"
    : "Top Avg Score (Overall %)";
  document.getElementById("scatterTitle").textContent = isStrict
    ? "Strict Pass vs Speed (t/s)"
    : "Avg Score vs Speed (t/s)";

  const top = [...rows].sort((a, b) => activeVal(b) - activeVal(a) || b.score - a.score).slice(0, 8);
  document.getElementById("barChart").innerHTML = top.length ? top.map(r => {
    const val = activeVal(r);
    return `
    <div class="bar-row">
      <div class="bar-name" title="${esc(r.model)} (${esc(r.run)})">${esc(r.model)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, val)}%"></div></div>
      <div class="bar-val">${val.toFixed(1)}%</div>
    </div>`;
  }).join("") : '<div class="sub">Tidak ada data cocok dengan filter.</div>';

  const svg = document.getElementById("scatterSvg");
  const pts = rows.filter(r => r.tps !== null && r.tps > 0);
  if (!pts.length) {
    svg.innerHTML = '<text x="230" y="110" text-anchor="middle" fill="#8b9bb4" font-size="12">Belum ada data t/s di filter ini</text>';
    return;
  }
  const maxTps = Math.max(...pts.map(p => p.tps), 10);
  const padL = 42, padR = 24, padT = 16, padB = 28;
  const W = 460 - padL - padR, H = 220 - padT - padB;
  let out = `<line x1="${padL}" y1="${padT}" x2="${padL}" y2="${padT+H}" stroke="#253047"/>` +
            `<line x1="${padL}" y1="${padT+H}" x2="${padL+W}" y2="${padT+H}" stroke="#253047"/>`;
  for (const yv of [0, 50, 100]) {
    const y = padT + H - (yv / 100) * H;
    out += `<line x1="${padL}" y1="${y}" x2="${padL+W}" y2="${y}" stroke="#1c2538" stroke-dasharray="3,3"/>` +
           `<text x="${padL-6}" y="${y+4}" text-anchor="end" fill="#8b9bb4" font-size="10">${yv}%</text>`;
  }
  for (const frac of [0, 0.5, 1]) {
    const xv = Math.round(maxTps * frac);
    const x = padL + frac * W;
    out += `<text x="${x}" y="${padT+H+16}" text-anchor="middle" fill="#8b9bb4" font-size="10">${xv} t/s</text>`;
  }
  for (const p of pts) {
    const yVal = activeVal(p);
    const x = padL + (p.tps / maxTps) * W;
    const y = padT + H - (yVal / 100) * H;
    const col = yVal >= 85 ? "#22c55e" : (yVal >= 60 ? "#f59e0b" : "#4f8cff");
    out += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" fill="${col}" fill-opacity="0.88" stroke="#0b0f17" stroke-width="1.5">` +
           `<title>${esc(p.model)} (${esc(p.run)}): Strict ${p.strict}% · Avg ${p.score}% @ ${p.tps} t/s</title></circle>` +
           `<text x="${Math.min(padL+W-4, x+7).toFixed(1)}" y="${(y+3).toFixed(1)}" fill="#e6edf7" font-size="9.5">${esc(p.model)}</text>`;
  }
  svg.innerHTML = out;
}

function renderTable(rows) {
  const cats = [...new Set(rows.flatMap(r => Object.keys(r.categories)))].sort();
  const cols = [
    { key: "model", label: "Model & Run", num: false },
    { key: "strict", label: "Strict Pass", num: true },
    { key: "score", label: "Avg Score", num: true },
    { key: "non_dnf_avg", label: "Non-DNF", num: true },
    { key: "dnf", label: "DNF", num: true },
    { key: "tps", label: "Speed (t/s)", num: true },
    { key: "avg_s", label: "Time/Task", num: true },
    ...cats.map(c => ({ key: "cat:" + c, label: c, num: true })),
    { key: "date", label: "Tanggal", num: false },
  ];

  document.getElementById("tableHead").innerHTML = "<tr><th>#</th>" + cols.map(c => {
    const arrow = sortKey === c.key ? (sortDesc ? " ▼" : " ▲") : "";
    return `<th class="${c.num ? "num" : ""}" data-sort="${esc(c.key)}">${esc(c.label)}${arrow}</th>`;
  }).join("") + "</tr>";

  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.onclick = () => {
      const k = th.dataset.sort;
      if (sortKey === k) sortDesc = !sortDesc;
      else { sortKey = k; sortDesc = true; }
      renderAll();
    };
  });

  document.getElementById("tableBody").innerHTML = rows.map((r, i) => {
    const catCells = cats.map(c => {
      const val = r.categories[c];
      return `<td class="num">${val !== undefined ? val.toFixed(0) + "%" : "-"}</td>`;
    }).join("");
    const pills = [
      r.provider,
      r.reasoning !== "default" ? "reasoning=" + r.reasoning : "reasoning=default",
      r.temp !== "default" ? "temp=" + r.temp : "temp=default",
      r.judges.length ? "judge=" + r.judges.join(",") : "",
    ].filter(Boolean).map(p => `<span class="pill">${esc(p)}</span>`).join("");

    return `<tr class="data-row" data-idx="${i}">
      <td class="num">${i + 1}</td>
      <td>
        <div class="model-title">${esc(r.model)}</div>
        <div class="run-meta">${esc(r.run)} · ${pills}</div>
      </td>
      <td class="num ${scoreClass(r.strict)}">${r.strict.toFixed(1)}% <span class="sub">(${r.strict_count}/${r.total_tasks})</span></td>
      <td class="num ${scoreClass(r.score)}">${r.score.toFixed(1)}%</td>
      <td class="num">${r.non_dnf_avg.toFixed(1)}%</td>
      <td class="num">${r.dnf}</td>
      <td class="num">${r.tps !== null ? r.tps.toFixed(1) : "-"}</td>
      <td class="num">${r.avg_s !== null ? r.avg_s.toFixed(0) + "s" : "-"}</td>
      ${catCells}
      <td>${esc(r.date)}</td>
    </tr>`;
  }).join("");

  document.querySelectorAll("tr.data-row").forEach(tr => {
    tr.onclick = () => openModal(rows[Number(tr.dataset.idx)]);
  });
}

function openModal(r) {
  document.getElementById("dlgTitle").textContent = `${r.model} — ${r.run}`;
  document.getElementById("dlgMeta").textContent =
    `Set: ${r.set} | Strict Pass: ${r.strict}% (${r.strict_count}/${r.total_tasks}) | Avg: ${r.score}% | Non-DNF: ${r.non_dnf_avg}% | DNF: ${r.dnf}/${r.total_tasks} | Speed: ${r.tps ?? "-"} t/s`;
  document.getElementById("dlgBody").innerHTML = r.tasks.map(t => {
    const sc = t.status === "DNF" ? '<span class="score-bad">DNF</span>' :
               t.score !== null ? `<span class="${scoreClass(t.score * 100)}">${t.score.toFixed(2)}</span>` : "-";
    return `<tr><td>${esc(t.id)}</td><td>${esc(t.cat)}</td><td class="num">${sc}</td></tr>`;
  }).join("");
  document.getElementById("taskDialog").showModal();
}

function renderAll() {
  const rows = getFiltered();
  const uniqueModels = new Set(DATA.entries.map(e => e.model)).size;
  const isStrict = metricMode === "strict";
  const topVal = rows.length ? Math.max(...rows.map(activeVal)).toFixed(1) + "%" : "-";
  document.getElementById("subtitle").textContent =
    `Generated: ${DATA.generated_at} · ${DATA.entries.length} hasil run ter-grade dari ${uniqueModels} model`;
  document.getElementById("summaryCards").innerHTML = `
    <div class="stat-card"><div class="k">Model di tab ini</div><div class="v">${rows.length}</div></div>
    <div class="stat-card"><div class="k">${isStrict ? "Strict Pass tertinggi" : "Avg Score tertinggi"}</div><div class="v">${topVal}</div></div>
    <div class="stat-card"><div class="k">Total model tersimpan</div><div class="v">${uniqueModels}</div></div>
  `;
  renderCharts(rows);
  renderTable(rows);
}

document.getElementById("metricMode").addEventListener("change", e => {
  metricMode = e.target.value;
  if (sortKey === "strict" || sortKey === "score") {
    sortKey = metricMode;
    sortDesc = true;
  }
  renderAll();
});
["searchBox", "providerFilter", "judgeFilter", "latestOnly"].forEach(id => {
  document.getElementById(id).addEventListener("input", renderAll);
  document.getElementById(id).addEventListener("change", renderAll);
});
document.getElementById("dlgClose").onclick = () => document.getElementById("taskDialog").close();
renderTabs();
renderFilters();
renderAll();
</script>
</body>
</html>
"""


def main():
    import datetime
    entries = collect_entries()
    sets = sorted({e["set"] for e in entries}, key=lambda s: (SET_ORDER.index(s) if s in SET_ORDER else 99, s))
    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sets": sets,
        "entries": entries,
    }
    m2bench.save_json(OUT_JSON, payload)
    safe_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__LEADERBOARD_JSON__", safe_json)
    html = html.replace("__SET_ORDER__", json.dumps(SET_ORDER))
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved {len(entries)} graded entries across sets {sets}:")
    print(f"  JSON: {OUT_JSON}")
    print(f"  HTML: {OUT_HTML}")


if __name__ == "__main__":
    main()
