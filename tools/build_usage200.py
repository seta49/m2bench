"""Build tasks/usage200.json from drafts/usage200/*.json + validate schema."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DRAFTS = BASE / "drafts" / "usage200"
OUT = BASE / "tasks" / "usage200.json"

EXPECTED = {
    "data-literal.json": ("data-literal", "lit", 25, 20),
    "instruction-following.json": ("instruction-following", "if", 25, 20),
    "python-coding.json": ("python-coding", "code", 25, 20),
    "iot-embedded.json": ("iot-embedded", "iot", 25, 20),
    "linux-vps-ops.json": ("linux-vps-ops", "vps", 25, 20),
    "llm-api-engineering.json": ("llm-api-engineering", "llm", 25, 21),
    "windows-dev.json": ("windows-dev", "win", 12, 10),
    "doc-web-tooling.json": ("doc-web-tooling", "doc", 12, 10),
    "nlp-corpus.json": ("nlp-corpus", "nlp", 25, 21),
    "hardware-bench.json": ("hardware-bench", "hw", 15, 11),
    "radio-audio.json": ("radio-audio", "rad", 8, 7),
    "networking-security.json": ("networking-security", "net", 25, 20),
}

REQUIRED = {"id", "category", "type", "difficulty", "usage_source", "prompt", "solution"}
TYPES = {"mcq", "numeric", "short", "code", "format"}
DIFFS = {"easy", "medium", "hard"}


def validate_task(t, expect_cat, expect_prefix, errors):
    tid = t.get("id", "<no-id>")
    missing = REQUIRED - set(t)
    if missing:
        errors.append(f"{tid}: missing fields {sorted(missing)}")
        return
    if t["category"] != expect_cat:
        errors.append(f"{tid}: category '{t['category']}' != expected '{expect_cat}'")
    if not t["id"].startswith(expect_prefix + "-"):
        errors.append(f"{tid}: id prefix != '{expect_prefix}-'")
    if t["type"] not in TYPES:
        errors.append(f"{tid}: bad type '{t['type']}'")
        return
    if t["difficulty"] not in DIFFS:
        errors.append(f"{tid}: bad difficulty '{t['difficulty']}'")

    if t["type"] == "mcq":
        opts = t.get("options")
        if not isinstance(opts, list) or len(opts) != 4:
            errors.append(f"{tid}: mcq needs exactly 4 options")
        else:
            for i, o in enumerate(opts):
                if not o.startswith("ABCD"[i] + ")"):
                    errors.append(f"{tid}: option {i} should start with '{'ABCD'[i]})'")
        if t.get("answer", {}).get("value") not in ("A", "B", "C", "D"):
            errors.append(f"{tid}: mcq answer.value must be A-D")
    elif t["type"] == "numeric":
        v = t.get("answer", {}).get("value")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            errors.append(f"{tid}: numeric answer.value must be a number")
    elif t["type"] == "short":
        if not t.get("answer", {}).get("value"):
            errors.append(f"{tid}: short answer.value empty")
    elif t["type"] == "code":
        if not t.get("entry_point"):
            errors.append(f"{tid}: code needs entry_point")
        tests = t.get("tests")
        if not isinstance(tests, list) or len(tests) < 4:
            errors.append(f"{tid}: code needs >= 4 tests")
    elif t["type"] == "format":
        checks = t.get("checks")
        if not isinstance(checks, list) or not (3 <= len(checks) <= 6):
            errors.append(f"{tid}: format needs 3-6 checks")
        else:
            for c in checks:
                if not isinstance(c, dict) or "id" not in c or "kind" not in c:
                    errors.append(f"{tid}: malformed check {c}")


def trim(tasks, quota):
    """Drop tasks to reach quota: from the largest difficulty bucket, highest id first."""
    keep = list(tasks)
    while len(keep) > quota:
        buckets = {}
        for t in keep:
            buckets.setdefault(t["difficulty"], []).append(t)
        biggest = max(buckets.values(), key=len)
        drop = max(biggest, key=lambda t: t["id"])
        keep.remove(drop)
    return keep


CLOSING = "Jawab dengan huruf pilihan saja"


def standardize_mcq(t, i):
    """Rotate options so the key spreads over A-D (round-robin), make prompt self-contained."""
    texts = [o[2:].strip() for o in t["options"]]
    old_idx = "ABCD".index(t["answer"]["value"])
    target = i % 4
    shift = (target - old_idx) % 4
    new_texts = [""] * 4
    for j, txt in enumerate(texts):
        new_texts[(j + shift) % 4] = txt
    new_opts = [f"{chr(65 + k)}) {new_texts[k]}" for k in range(4)]
    letter_map = {L: "ABCD"[("ABCD".index(L) + shift) % 4] for L in "ABCD"}

    prompt = t["prompt"]
    if re.search(r"(?m)^[A-D]\)", prompt):
        lines = prompt.split("\n")
        idxs = [k for k, ln in enumerate(lines) if re.match(r"^[A-D]\)", ln)]
        if len(idxs) == 4:
            for k, ln_i in enumerate(idxs):
                lines[ln_i] = new_opts[k]
            prompt = "\n".join(lines)
        else:
            print(f"WARN {t['id']}: inline options not exactly 4 lines, left untouched")
    else:
        block = "\n".join(new_opts)
        pos = prompt.find(CLOSING)
        if pos != -1:
            prompt = prompt[:pos].rstrip() + "\n\n" + block + "\n\n" + prompt[pos:]
        else:
            prompt = prompt.rstrip() + "\n\n" + block
    t["prompt"] = prompt
    t["options"] = new_opts
    t["answer"]["value"] = "ABCD"[(old_idx + shift) % 4]
    if shift:
        t["solution"] = re.sub(r"\b[A-D]\b", lambda m: letter_map[m.group(0)], t["solution"])
    return t


def main():
    errors = []
    all_tasks = []
    for fname, (cat, prefix, expect_n, quota) in EXPECTED.items():
        path = DRAFTS / fname
        if not path.exists():
            errors.append(f"MISSING FILE: {fname}")
            continue
        try:
            tasks = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{fname}: invalid JSON ({e})")
            continue
        if len(tasks) != expect_n:
            errors.append(f"{fname}: {len(tasks)} tasks, expected {expect_n}")
        for t in tasks:
            validate_task(t, cat, prefix, errors)
        all_tasks.extend(tasks)

    ids = [t.get("id") for t in all_tasks]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        errors.append(f"duplicate ids: {dupes}")

    print(f"candidates: {len(all_tasks)} (expected 247)")
    print("by type:    ", dict(Counter(t.get("type") for t in all_tasks)))
    print("by category:", dict(Counter(t.get("category") for t in all_tasks)))
    print("by difficulty:", dict(Counter(t.get("difficulty") for t in all_tasks)))

    if errors:
        print(f"\n{len(errors)} ERROR(S):")
        for e in errors[:60]:
            print(" -", e)
        sys.exit(1)

    final = []
    for fname, (cat, prefix, expect_n, quota) in EXPECTED.items():
        group = [t for t in all_tasks if t["category"] == cat]
        final.extend(trim(group, quota))

    mcq_i = 0
    for t in final:
        if t["type"] == "mcq":
            standardize_mcq(t, mcq_i)
            mcq_i += 1

    print(f"\nfinal: {len(final)} tasks (target 200)")
    print("final by type:    ", dict(Counter(t["type"] for t in final)))
    print("final by category:", dict(Counter(t["category"] for t in final)))
    print("final by difficulty:", dict(Counter(t["difficulty"] for t in final)))
    assert len(final) == 200, f"final count {len(final)} != 200"

    OUT.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nOK -> {OUT}")


if __name__ == "__main__":
    main()
