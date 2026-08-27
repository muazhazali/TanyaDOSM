"""Diagnostic without Groq: simulate intent + run catalogue search only."""

from __future__ import annotations

from pathlib import Path
from askdosm.catalogue import Catalogue
from askdosm.models import QuestionIntent, Language, Operation
from askdosm.providers import create_embedder
from askdosm.config import get_settings

QUESTIONS = [
    ("Q12", "Compare Johor and Selangor population in 2025.", "population_state"),
    ("Q18", "Bandingkan populasi Sabah dan Sarawak pada 2024.", "population_state"),
    ("Q21", "What was Malaysia's unemployment rate in June 2025?", "lfs_month"),
    ("Q22", "Show Malaysia's monthly unemployment rate since January 2024.", "lfs_month"),
    ("Q24", "Calculate the average unemployment rate in 2024.", "lfs_month"),
    ("Q25", "What was the maximum participation rate from 2020 to 2024?", "lfs_month"),
    ("Q27", "Tunjukkan trend pengangguran bulanan Malaysia sejak 2023.", "lfs_month"),
    ("Q29", "Compare the national unemployment rate in January and December 2024.", "lfs_month"),
    ("Q30", "How many unemployed people were recorded in the latest month?", "lfs_month"),
    ("Q42", "Compare inflation in Johor and Penang during 2025.", "cpi_state_inflation"),
    ("Q47", "Bandingkan inflasi Sabah dan Sarawak pada 2025.", "cpi_state_inflation"),
]

INTENTS = {
    "Q12": dict(metric="population", domain="demography", geography_level="state", entities=["Johor","Selangor"], start_period="2025", end_period="2025", operation=Operation.COMPARE),
    "Q18": dict(metric="population", domain="demography", geography_level="state", entities=["Sabah","Sarawak"], start_period="2024", end_period="2024", operation=Operation.COMPARE, language=Language.MS),
    "Q21": dict(metric="u_rate", domain="labour", geography_level="national", start_period="2025-06", end_period="2025-06", operation=Operation.LOOKUP),
    "Q22": dict(metric="u_rate", domain="labour", geography_level="national", start_period="2024-01", operation=Operation.TREND),
    "Q24": dict(metric="u_rate", domain="labour", geography_level="national", start_period="2024", end_period="2024", operation=Operation.MEAN),
    "Q25": dict(metric="p_rate", domain="labour", geography_level="national", start_period="2020", end_period="2024", operation=Operation.MAX),
    "Q27": dict(metric="u_rate", domain="labour", geography_level="national", start_period="2023", operation=Operation.TREND, language=Language.MS),
    "Q29": dict(metric="u_rate", domain="labour", geography_level="national", start_period="2024-01", end_period="2024-12", operation=Operation.COMPARE),
    "Q30": dict(metric="lf_unemployed", domain="labour", geography_level="national", latest=True, operation=Operation.LOOKUP),
    "Q42": dict(metric="inflation_yoy", domain="prices", geography_level="state", entities=["Johor","Penang"], start_period="2025", end_period="2025", operation=Operation.COMPARE),
    "Q47": dict(metric="inflation_yoy", domain="prices", geography_level="state", entities=["Sabah","Sarawak"], start_period="2025", end_period="2025", operation=Operation.COMPARE, language=Language.MS),
}

def main():
    settings = get_settings()
    catalogue = Catalogue(Path("data/catalogue.json"))
    try:
        embedder = create_embedder(settings)
    except Exception as exc:
        print(f"WARNING: embedder unavailable ({exc}); lexical only")
        embedder = None
    cache_dir = settings.cache_dir / "embeddings"

    for qid, question, expected in QUESTIONS:
        print(f"\n{'='*70}")
        print(f"{qid}: {question}")
        print(f"  EXPECTED: {expected}")
        intent = QuestionIntent(**INTENTS[qid])
        print(f"  INTENT: metric={intent.metric} geo={intent.geography_level} "
              f"entities={intent.entities} op={intent.operation}")
        candidates = catalogue.search_hybrid(question, intent, embedder, cache_dir)
        for c in candidates[:5]:
            mark = " <==" if c.dataset_id == expected else ""
            print(f"    {c.dataset_id:30s} score={c.score:.4f}  {c.reason[:80]}{mark}")
        top = candidates[0]
        if len(candidates) > 1:
            gap = candidates[0].score - candidates[1].score
            print(f"  TOP={top.dataset_id} GAP={gap:.4f} "
                  f"PASS_floor={top.score >= 0.15} "
                  f"PASS_margin={gap >= 0.015}")

if __name__ == "__main__":
    main()