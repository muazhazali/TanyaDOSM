"""Diagnostic: dump intent, candidates, and selection for specific questions."""

from __future__ import annotations

import json
import random
import time
from askdosm.agent.graph import TanyaDOSMService
from askdosm.agent.state import AgentState

QUESTIONS = [
    ("Q12", "Compare Johor and Selangor population in 2025."),
    ("Q18", "Bandingkan populasi Sabah dan Sarawak pada 2024."),
    ("Q21", "What was Malaysia's unemployment rate in June 2025?"),
    ("Q22", "Show Malaysia's monthly unemployment rate since January 2024."),
    ("Q24", "Calculate the average unemployment rate in 2024."),
    ("Q25", "What was the maximum participation rate from 2020 to 2024?"),
    ("Q27", "Tunjukkan trend pengangguran bulanan Malaysia sejak 2023."),
    ("Q29", "Compare the national unemployment rate in January and December 2024."),
    ("Q30", "How many unemployed people were recorded in the latest month?"),
    ("Q42", "Compare inflation in Johor and Penang during 2025."),
    ("Q47", "Bandingkan inflasi Sabah dan Sarawak pada 2025."),
]

def main():
    service = TanyaDOSMService()
    for i, (qid, question) in enumerate(QUESTIONS):
        if i > 0:
            delay = random.uniform(30.0, 45.0)
            time.sleep(delay)
        print(f"\n{'='*70}")
        print(f"{qid}: {question}")
        events = []
        def sink(e, _events=events):
            _events.append(e)
        try:
            service.ask(question, event_sink=sink)
        except Exception as exc:
            print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
        for e in events:
            t = e.get("type")
            if t == "intent":
                payload = e.get("payload", {})
                print(f"  INTENT: metric={payload.get('metric')} domain={payload.get('domain')} "
                      f"geo={payload.get('geography_level')} entities={payload.get('entities')} "
                      f"op={payload.get('operation')} latest={payload.get('latest')} "
                      f"ambiguous={payload.get('ambiguous')} multi={payload.get('multi_dataset')} "
                      f"start={payload.get('start_period')} end={payload.get('end_period')}")
            elif t == "selection":
                payload = e.get("payload", {})
                print(f"  SELECTION: dataset={payload.get('dataset_id')} "
                      f"status={payload.get('status')} reason={payload.get('reason')}")
            elif t == "candidates":
                payload = e.get("payload", {})
                items = payload.get("items", [])[:4]
                for c in items:
                    print(f"    CANDIDATE: {c.get('dataset_id')} score={c.get('score'):.4f}")
            elif t == "retry":
                payload = e.get("payload", {})
                print(f"  RETRY: attempt={payload.get('attempt')} errors={payload.get('errors')}")

if __name__ == "__main__":
    main()