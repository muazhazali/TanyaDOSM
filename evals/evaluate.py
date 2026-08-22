"""Offline structural checks for the fixed TanyaDOSM benchmark."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def main() -> None:
    path = Path(__file__).with_name("questions.json")
    questions = json.loads(path.read_text(encoding="utf-8"))
    if len(questions) != 50:
        raise SystemExit(f"Expected 50 benchmark questions, found {len(questions)}")
    required = {"id", "question", "category", "language", "expected_dataset", "answerable"}
    for case in questions:
        missing = required - set(case)
        if missing:
            raise SystemExit(f"{case.get('id', '<unknown>')} is missing {sorted(missing)}")
    print("Benchmark cases: 50")
    print("Categories:", dict(sorted(Counter(case["category"] for case in questions).items())))
    print("Languages:", dict(sorted(Counter(case["language"] for case in questions).items())))


if __name__ == "__main__":
    main()
