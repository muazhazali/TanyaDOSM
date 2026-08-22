import json
from pathlib import Path


def test_benchmark_has_50_well_formed_cases():
    cases = json.loads(Path("evals/questions.json").read_text(encoding="utf-8"))
    assert len(cases) == 50
    assert len({case["id"] for case in cases}) == 50
    assert {case["language"] for case in cases} == {"en", "ms"}
    assert sum(not case["answerable"] for case in cases) >= 2

