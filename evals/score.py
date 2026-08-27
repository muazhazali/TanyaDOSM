"""Live accuracy scorer for the TanyaDOSM benchmark.

Runs the full LangGraph pipeline for each of the 50 benchmark questions against
the configured Groq model and reports per-question and summary accuracy. Requires
ASKDOSM_GROQ_API_KEY (and optional Cloudflare credentials for semantic search).

Usage:
    uv run python evals/score.py [--detailed]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any


def _extract_selected_dataset(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("type") == "selection":
            payload = event.get("payload") or {}
            return payload.get("dataset_id")
    return None


def run_one(service, question: str) -> tuple[str | None, str, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []

    def sink(event: dict[str, Any]) -> None:
        events.append(event)

    answer = service.ask(question, event_sink=sink)
    selected = _extract_selected_dataset(events)
    final_status = ""
    for event in reversed(events):
        if event.get("type") == "node.completed" and event.get("node") == "generate_response":
            final_status = "complete"
            break
        if event.get("type") == "node.completed" and event.get("node") == "graceful_failure":
            final_status = "failed"
            break
    if not final_status:
        final_status = "failed" if answer.error else "complete"
    return selected, final_status, events


def main() -> int:
    parser = argparse.ArgumentParser(description="Live benchmark scorer")
    parser.add_argument("--detailed", action="store_true", help="print per-question detail")
    args = parser.parse_args()

    from askdosm.agent.graph import TanyaDOSMService

    cases = json.loads(Path("evals/questions.json").read_text(encoding="utf-8"))
    service = TanyaDOSMService()

    total = len(cases)
    correct = 0
    dataset_correct = 0
    answered = 0
    failed = 0
    rows: list[dict[str, Any]] = []

    for index, case in enumerate(cases, 1):
        question = case["question"]
        expected = case["expected_dataset"]
        answerable = case["answerable"]
        started = time.perf_counter()
        try:
            selected, status, events = run_one(service, question)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            rows.append({
                "id": case["id"], "question": question, "expected": expected,
                "selected": None, "status": f"error:{type(exc).__name__}",
                "elapsed": elapsed, "correct": False,
            })
            if args.detailed:
                print(f"[{index:>2}/50] {case['id']} ERROR {type(exc).__name__}: {exc}")
            failed += 1
            continue
        elapsed = time.perf_counter() - started

        if answerable:
            dataset_match = selected == expected
            is_correct = dataset_match and status == "complete"
            if dataset_match:
                dataset_correct += 1
            if is_correct:
                correct += 1
                answered += 1
            else:
                failed += 1
        else:
            is_correct = status in ("unsupported", "failed") or selected is None
            if is_correct:
                correct += 1
            else:
                failed += 1

        rows.append({
            "id": case["id"], "question": question, "expected": expected,
            "selected": selected, "status": status, "elapsed": elapsed,
            "correct": is_correct,
        })
        if args.detailed:
            mark = "OK" if is_correct else "X"
            print(f"[{index:>2}/50] {case['id']} {mark} expected={expected} got={selected} status={status} ({elapsed:.1f}s)")

        if index < total:
            delay = random.uniform(15.0, 25.0)
            time.sleep(delay)

    print()
    print("=" * 60)
    print(f"Overall accuracy:       {correct}/{total}  ({correct/total:.1%})")
    print(f"Dataset selection only: {dataset_correct}/{sum(1 for c in cases if c['answerable'])} answerable  ({dataset_correct/max(1, sum(1 for c in cases if c['answerable'])):.1%})")
    print(f"Answered correctly:     {answered}/{sum(1 for c in cases if c['answerable'])} answerable")
    print(f"Failed/unsupported:     {failed}")
    avg_latency = sum(r["elapsed"] for r in rows) / len(rows)
    print(f"Avg latency per question: {avg_latency:.2f}s")
    print("=" * 60)

    failures = [r for r in rows if not r["correct"]]
    if failures:
        print(f"\n{len(failures)} failing cases:")
        for row in failures:
            print(f"  {row['id']} expected={row['expected']} got={row['selected']} status={row['status']}")
            print(f"      Q: {row['question']}")

    out_path = Path("evals/score_results.json")
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDetailed results written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())