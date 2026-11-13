# Skema Soal Usage200 (judge-free)

Setiap soal = satu objek JSON dalam array. Semua soal berbahasa Indonesia (kasual-teknis wajar,
bukan hasil terjemahan). Skenario harus grounded di area pemakaian nyata Atha (lihat brief per
batch), BUKAN hasil comot dari benchmark lain — format penilaian saja yang boleh mengikuti standar
umum (MCQ exact-letter, `#### jawaban`, unit test, checker IFEval).

## Field wajib semua soal

```json
{
  "id": "<prefix>-NNN",              // nomor urut 001.. dari batch, unik global
  "category": "<domain>",            // persis nama domain batch
  "type": "mcq|numeric|short|code|format",
  "difficulty": "easy|medium|hard",
  "usage_source": "<satu baris: area pemakaian mana yang jadi dasar soal ini>",
  "prompt": "<teks soal lengkap, self-contained>",
  "solution": "<ringkas: langkah/menuju jawaban, untuk verifikasi manual>"
}
```

## Field per type

### mcq
- `options`: array tepat 4 string, format `"A) ..."`, `"B) ..."`, `"C) ..."`, `"D) ..."`
- `answer.value`: huruf saja, `"A"`..`"D"`
- Prompt diakhiri kalimat: *"Jawab dengan huruf pilihan saja. Akhiri jawaban dengan baris `#### <huruf>`."*
- Distractor harus plausible (jebakan yang memang sering salah), bukan opsi konyol.

### numeric
- `answer.value`: angka (number), opsional `answer.unit` (string) dan `answer.tolerance` (number, default 0)
- Prompt diakhiri: *"Akhiri jawaban dengan baris `#### <angka>` (dalam satuan yang diminta)."*
- Angka harus benar-benar bisa dihitung dari data di prompt. `solution` WAJIB memuat perhitungan
  lengkap sehingga bisa diverifikasi ulang.

### short
- `answer.value`: string jawaban (huruf kecil, tanpa spasi berlebih), opsional `answer.accept`: array
  alias yang juga dianggap benar (mis. `"systemctl"` vs `"systemctl start"`, `"DHT22"` vs `"AM2302"`)
- Prompt diakhiri: *"Jawab singkat. Akhiri jawaban dengan baris `#### <jawaban>`."*
- Normalisasi penilaian: lowercase, trim, tanpa tanda baca di ujung.

### code
- `entry_point`: nama fungsi yang harus dibuat
- `tests`: array string, tiap string satu pernyataan Python valid yang HARUS lolos (assert sederhana,
  stdlib saja, mis. `assert hitung([1,2,3]) == 6`). Minimal 4 test, minimal 1 edge case.
- `answer.value`: `""` (dinilai dari tests)
- Prompt: jelaskan spesifikasi fungsi (input/output/edge case), minta kode final dalam code fence
  ```python. Jangan menaruh jawaban/contoh hasil yang membocorkan test case di prompt.

### format (IFEval-style)
- `checks`: array checker, tiap checker `{"id": "cN", "kind": <jenis>, "param": ..., "value": ...}`
- Jenis checker yang boleh dipakai (kosong saja yang tidak perlu):
  - `word_max` / `word_min` — value: int
  - `line_count_exact` — value: int (baris non-kosong)
  - `bullet_count_exact` — value: int (baris yang diawali `-` atau `*`)
  - `contains` / `not_contains` — value: string (case-sensitive kecuali disebut lain)
  - `regex` — value: pola regex yang harus match
  - `count_exact` — param: string yang dihitung, value: int kemunculan
  - `ends_with` — value: string yang harus jadi akhir respons
  - `no_emoji` — value: true
  - `json_valid` — value: true (respons harus JSON valid)
  - `json_field` — param: path field (mis. `"0.kategori"`), value: nilai yang diharapkan
- Setiap soal minimal 3 checker, maksimal 6. Prompt harus menyebut SEMUA konstrain secara eksplisit
  dan menambahkan: *"Cek ulang seluruh konstrain sebelum menjawab."*
- Jangan pakai konstrain yang butuh penilaian subjektif ("bahasa santai", "menarik").

## Aturan umum

- Larangan mutlak: nama asli user, kredensial/API key nyata, kasus pribadi (penipuan dst.), alamat
  rumah/kos, nomor HP. IP/host fiktif untuk soal teknis itu boleh.
- Soal harus original — bukan salinan/frasa dari MMLU, GSM8K, HumanEval, IFEval, dll. Konteks dan
  angka dibuat sendiri.
- Setiap soal punya tepat SATU jawaban benar yang tidak ambigu.
- Jaga proporsi difficulty per batch: ~30% easy, ~45% medium, ~25% hard.
- Satu soal = satu konsep yang diuji. Traps boleh (edge case, salah kaprah umum), tapi jangan
  multi-part raksasa.

## Validasi sebelum selesai

File harus JSON array valid. Jalankan:

```
py -c "import json;d=json.load(open('<file>',encoding='utf-8'));print(len(d),[t['type'] for t in d].count('mcq'))"
```

Pastikan jumlah soal sesuai target, semua id unik, semua field wajib terisi.
