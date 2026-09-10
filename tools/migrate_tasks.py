"""Migrate mini-bench tasks.py/tasks2.py -> m2bench tasks/*.json + sanity check."""
import json
import os
import sys

SRC = r"C:\Users\athai\Hermes-Output\code\mini-bench"
OUT = r"C:\Users\athai\Hermes-Output\code\athabench\tasks"
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, SRC)
from tasks import TASKS  # noqa: E402
from tasks2 import HARD_TASKS  # noqa: E402


def validate(obj, label):
    ids = [t["id"] for t in obj]
    assert len(ids) == len(set(ids)), f"{label}: duplicate task ids"
    for t in obj:
        assert str(t.get("prompt", "")).strip(), f"{label}/{t['id']}: empty prompt"
        cids = [c["id"] for c in t["criteria"]]
        assert len(cids) == 4 == len(set(cids)), f"{label}/{t['id']}: criteria != 4 unique"
        for c in t["criteria"]:
            assert str(c.get("text", "")).strip(), f"{label}/{t['id']}/{c['id']}: empty"
    return len(obj)


def dump(obj, name):
    n = validate(obj, name)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print(f"{name}: {n} tasks OK -> {p}")


dump(TASKS, "easy.json")
dump(HARD_TASKS, "hard.json")
print("migration complete")
