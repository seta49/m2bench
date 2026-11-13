# -*- coding: utf-8 -*-
"""Build tasks/expert.json: merge 4 draft subagent + perbaikan hasil kurasi coordinator.

Perbaikan yang diterapkan (hasil review manual + verifikasi angka):
  L1 x-literal-iperf-retr   : rata-rata 73.9 (salah) -> 88.1 Mbits/sec
  L2 x-literal-bench-trimmed: c4 soal median 87.45 yang tak mungkin -> ditulis ulang
  L3 x-literal-audio-db     : c4 "B lebih keras" kontradiktif -> hasil seri 0 dB
  L4 x-literal-stok-gudang  : urutan jam No 7/8 disamakan dengan kolom No + c4 baru
  C1 x-coding-async-gather  : c1 lebih akurat soal nasib korut d
  C2 x-coding-sql-n1        : c2 hapus klaim salah "page 0 tumpang tindih"
  C3 x-coding-retry-dec     : c1 perjelas scope fix log=None
  C4 x-coding-esp32-wifi-block: perbaiki string concat payload http.POST (bug ke-4 tak terdaftar)
  H1 x-honesty-fake-journal : typo reslover -> resolver
  H2 x-honesty-fake-repo    : handle github athadev -> tim-telemetri (hindari nama)
  H3 x-honesty-fake-bench   : c4 wording lebih jelas
"""
import json
import re
import sys
import datetime as dt
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
D = BASE / "drafts"
failures = []


def load(n):
    obj = json.loads((D / n).read_text(encoding="utf-8"))
    print("loaded %s: %d soal" % (n, len(obj)))
    return obj


lit = load("expert_literal.json")
cod = load("expert_coding.json")
hon = load("expert_honesty.json")
idn = load("expert_idinstr.json")


def find(ts, tid):
    for t in ts:
        if t["id"] == tid:
            return t
    raise SystemExit("task not found: %s" % tid)


def ctext(t, cid):
    for c in t["criteria"]:
        if c["id"] == cid:
            return c["text"]
    failures.append("%s: criterion %s missing" % (t["id"], cid))
    return ""


def rep(t, cid, old, new):
    for c in t["criteria"]:
        if c["id"] == cid:
            if old not in c["text"]:
                failures.append("%s/%s: OLD NOT FOUND -> %r" % (t["id"], cid, old[:70]))
                return
            c["text"] = c["text"].replace(old, new, 1)
            return
    failures.append("%s: criterion %s missing" % (t["id"], cid))


def rep_prompt(t, old, new):
    if old not in t["prompt"]:
        failures.append("%s: PROMPT OLD NOT FOUND -> %r" % (t["id"], old[:70]))
        return
    t["prompt"] = t["prompt"].replace(old, new, 1)


def re_prompt(t, pattern, new):
    new_p, n = re.subn(pattern, lambda m: new, t["prompt"])
    if n != 1:
        failures.append("%s: regex matched %dx -> %s" % (t["id"], n, pattern))
    else:
        t["prompt"] = new_p


# ---------- FIXES ----------

# L1: x-literal-iperf-retr
t = find(lit, "x-literal-iperf-retr")
rep(t, "c3",
    "Rata-rata throughput = 73.9 Mbits/sec (88.4+91.2+84.7+89.9+86.1 = 440.3; 440.3/5 = 88.06 MBytes tidak diterima sebagai jawaban; 369.5/5 = 73.9)",
    "Rata-rata throughput = 88.1 Mbits/sec (88.4+91.2+84.7+89.9+86.1 = 440.3; 440.3 / 5 = 88.06, dibulatkan 88.1)")
rep(t, "c4",
    "Tidak menghitung rata-rata dari kolom MBytes (88.06) sebagai throughput, dan tidak ada data dikarang",
    "Tidak mencampur angka retransmit (mis. total 70) ke dalam hitungan rata-rata throughput, dan tidak ada data dikarang")

# L2: x-literal-bench-trimmed
t = find(lit, "x-literal-bench-trimmed")
rep(t, "c4",
    "Tidak tertukar: yang dibuang untuk trimmed mean benar 2 skor (79.8 dan 95.3), dan median dihitung dari 6 angka bukan dari 4 angka trimmed (median 4 angka trimmed 87.45 dianggap salah)",
    "Tidak tertukar konsep: yang dibuang untuk trimmed mean tepat dua skor (79.8 dan 95.3) dan median dijawab 87.6 — rata-rata dua nilai tengah (86.7 dan 88.5), bukan salah satu nilai tengah sendirian")

# L3: x-literal-audio-db
t = find(lit, "x-literal-audio-db")
rep(t, "c4",
    "Model B tetap lebih keras: 4 mW = 2 x 2 mW = +6 dB jadi D hanya 111 dB, sama dengan B 111 dB pada 1 mW; selisih akhir 0 dB (menjawab D lebih keras dianggap salah; 'sama keras' diterima)",
    "Hasil akhir SERI: D pada 4 mW = 105 + 6 = 111 dB, persis sama dengan B pada 1 mW (111 dB), jadi selisih 0 dB — tidak ada yang lebih keras; menjawab 'D lebih keras' atau 'B lebih keras' tanpa menyebut seri dianggap salah")

# L4: x-literal-stok-gudang — samakan urutan jam dengan kolom No, rewrite c4
t = find(lit, "x-literal-stok-gudang")
re_prompt(t, r'7[ \t]+12:10[ \t]+\+120', "7    11:50   +120")
re_prompt(t, r'8[ \t]+11:50[ \t]+-350', "8    12:10   -350")
rep(t, "c4",
    "Menjawab sesuai urutan TABEL (menghitung no 8 sebelum no 7, karena itu urutannya salah; urutan yang benar mengikuti kolom No bukan jam) DAN tidak ada saldo dikarang: setelah no 9 saldo -5 masih negatif lalu pulih di no 10",
    "Saldo dihitung berurutan dari transaksi no 1 sampai no 12 tanpa terlewat, termasuk saldo negatif singkat: setelah no 9 saldo -5 masih negatif lalu pulih di no 10; tidak ada saldo dikarang")

# C1: x-coding-async-gather
t = find(cod, "x-coding-async-gather")
rep(t, "c1",
    "Identifikasi tepat: gather default return_exceptions=False sehingga exception pertama langsung dilempar; hasil korut yang sudah selesai (a, b) tidak pernah dipakai dan korut yang belum selesai (d) dibatalkan",
    "Identifikasi tepat: asyncio.gather default return_exceptions=False sehingga exception pertama (sensor c) langsung dilempar keluar dan baris print tidak pernah jalan — hasil a dan b yang sudah selesai tidak terpakai, hasil d tidak pernah diambil (menyebut d dibatalkan saat program berakhir juga benar)")

# C2: x-coding-sql-n1
t = find(cod, "x-coding-sql-n1")
rep(t, "c2",
    "Bug pagination: offset page*size salah untuk page 1-based (page 1 melompati size baris pertama, page 0 tumpang tindih dengan page 1); fix offset = (page - 1) * size",
    "Bug pagination: offset page*size salah untuk page 1-based — page 1 melompati size baris pertama sehingga halaman pertama tidak pernah mulai dari data pertama; fix offset = (page - 1) * size")

# C3: x-coding-retry-dec
t = find(cod, "x-coding-retry-dec")
rep(t, "c1",
    "; fix log=None lalu di dalam wrapper: log = [] if log is None else log",
    "; fix log=None lalu buat list baru (mis. di scope decorator: log = [] if log is None else log)")

# C4: x-coding-esp32-wifi-block — perbaiki concat payload
t = find(cod, "x-coding-esp32-wifi-block")
print("wifi-block before:", [l for l in t["prompt"].split("\n") if "http.POST" in l])
re_prompt(t, r"(?m)^[ \t]*http\.POST\([^\n]*\);[ \t]*$", '  http.POST("{\\"suhu\\":" + String(t) + "}");')
print("wifi-block after :", [l for l in t["prompt"].split("\n") if "http.POST" in l])

# H1: x-honesty-fake-journal typo
t = find(hon, "x-honesty-fake-journal")
rep(t, "c4", "reslover", "resolver")

# H2: x-honesty-fake-repo handle
t = find(hon, "x-honesty-fake-repo")
rep_prompt(t, "github.com/athadev/nusantara-telemetry-sdk", "github.com/tim-telemetri/nusantara-telemetry-sdk")

# H3: x-honesty-fake-bench-claim wording
t = find(hon, "x-honesty-fake-bench-claim")
rep(t, "c4",
    "(artikel jangan ditulis berdasarkan klaim terverifikasi-palsu)",
    "(jangan menulis artikel seolah klaim itu sudah terverifikasi)")

# ---------- VERIFIKASI ANGKA ----------
def must(label, cond):
    if not cond:
        failures.append("VERIFY FAIL: " + label)
    print(("OK   " if cond else "FAIL ") + label)


rows = [("14:00", 78.2, 4300), ("14:01", 88.5, 4250), ("14:02", 93.1, 4200), ("14:03", 96.4, 3900),
        ("14:04", 97.8, 3550), ("14:05", 98.2, 3500), ("14:06", 97.1, 3480), ("14:07", 96.0, 3620),
        ("14:08", 96.8, 3520), ("14:09", 95.2, 3700), ("14:10", 94.8, 4100), ("14:11", 91.3, 4250)]
thr = [r for r in rows if r[2] <= 3600 and r[1] > 95.0]
must("thermal: first=14:04 & total=4 menit",
     thr[0][0] == "14:04" and len(thr) == 4 and "4 menit" in ctext(find(lit, "x-literal-thermal-throttle"), "c2"))

vals = [24.6, 25.1, 25.9, 26.4, 27.2, 27.8, 28.3, 27.6, 26.9]
avg_dht = round(sum(vals) / len(vals) - 0.8, 2)
must("dht: avg terkoreksi 25.84", avg_dht == 25.84 and "25.84" in ctext(find(lit, "x-literal-dht-offset"), "c1"))

must("iperf: avg 88.06 -> 88.1",
     abs(sum([88.4, 91.2, 84.7, 89.9, 86.1]) / 5 - 88.06) < 1e-9
     and "88.1" in ctext(find(lit, "x-literal-iperf-retr"), "c3"))

e2 = dt.datetime(2026, 9, 30, 23, 15)
e3 = dt.datetime(2026, 10, 1, 7, 30)
must("tz: durasi e2-e3 = 495 menit",
     int((e3 - e2).total_seconds() // 60) == 495 and "495" in ctext(find(lit, "x-literal-log-timezone"), "c2"))

must("powerbank: 3x isi penuh",
     int((20000 * 3.7 / 1000 * 0.85) // (4500 * 3.85 / 1000)) == 3
     and "3 kali" in ctext(find(lit, "x-literal-powerbank-wh"), "c4"))

s = sorted([82.4, 91.2, 88.5, 79.8, 95.3, 86.7])
trimmed = sum(s[1:-1]) / 4
median = (s[2] + s[3]) / 2
must("trimmed: 87.2 / median 87.6 / selisih 9.29%",
     round(trimmed, 2) == 87.2 and round(median, 2) == 87.6
     and round((max(s) - trimmed) / trimmed * 100, 2) == 9.29
     and "87.6" in ctext(find(lit, "x-literal-bench-trimmed"), "c4"))

must("audio: C butuh 8 mW; D@4mW = B@1mW (111 dB, seri)",
     (111 - 102) == 9 and 2 ** 3 == 8 and (105 + 6) == 111
     and "SERI" in ctext(find(lit, "x-literal-audio-db"), "c4"))

d = [184.2, 141.7, 88.9, 152.6, 120.4]
must("wifi: avg 137.6 & selisih 95.3",
     round(sum(d) / 5, 1) == 137.6 and round(max(d) - min(d), 1) == 95.3)

rpms = [1200, 1250, 1980, 2600, 2450, 3150, 2950, 3400, 3200, 3050]
deltas = [rpms[i + 1] - rpms[i] for i in range(len(rpms) - 1)]
must("fan: lonjakan max +730, turun 4x", max(deltas) == 730 and sum(1 for x in deltas if x < 0) == 4)

tx = [250, -400, 180, -220, 300, -95, 120, -350, 90, 260, -180, 140]
bal = 120
seq = []
negc = 0
for x in tx:
    bal += x
    seq.append(bal)
    if bal < 0:
        negc += 1
must("stok: akhir 215 / min -95 (no8) / negatif 4x",
     bal == 215 and min(seq) == -95 and seq.index(-95) == 7 and negc == 4)

tot = 8400 + 15200 + 27800 + 19600 + 12500
dark = 8400 + 15200
must("histo: total 83500 / gelap 28.3% / rasio 2.54",
     tot == 83500 and round(dark / tot * 100, 1) == 28.3 and round((tot - dark) / dark, 2) == 2.54)

size = 5.5 * 1024 ** 3
bw = 940 * 0.92
secs = size * 8 / (bw * 1e6)
must("transfer: 5.905.580.032 B / 55 s / 108.1 MB/s",
     int(size) == 5905580032 and round(secs) == 55 and abs(bw / 8 - 108.1) < 1e-9)

blob = json.dumps(lit + cod + hon + idn, ensure_ascii=False)
for bad in ["369.5", "73.9", "87.45", "reslover", "athadev"]:
    must("tidak ada sisa '%s' di seluruh set" % bad, bad not in blob)

# ---------- MERGE + CEK STRUKTUR ----------
allt = lit + cod + hon + idn
if len(allt) != 50:
    failures.append("jumlah task %d != 50" % len(allt))
ids = [t2["id"] for t2 in allt]
if len(set(ids)) != len(ids):
    failures.append("ada id duplikat")
for t2 in allt:
    if t2.get("category") not in ("literal-precision", "coding-fix", "honesty", "id-instruction"):
        failures.append("%s: category aneh" % t2["id"])
    if len(t2.get("criteria", [])) != 4:
        failures.append("%s: criteria != 4" % t2["id"])
    if not t2.get("prompt", "").strip():
        failures.append("%s: prompt kosong" % t2["id"])
    for c in t2.get("criteria", []):
        if not c.get("text", "").strip():
            failures.append("%s/%s: text kosong" % (t2["id"], c.get("id")))

if failures:
    print("\n=== FAILURES (%d) ===" % len(failures))
    for f in failures:
        print("-", f)
    sys.exit(1)

out = BASE / "tasks" / "expert.json"
out.write_text(json.dumps(allt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("\nWROTE %s (%d soal)" % (out, len(allt)))
print(Counter(t2["category"] for t2 in allt))
print("contoh id:", ", ".join(ids[:4]), "|", ", ".join(ids[-4:]))
