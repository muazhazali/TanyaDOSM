from pathlib import Path

from askdosm.catalogue import Catalogue
from askdosm.models import QuestionIntent


class FailingEmbedder:
    def embed_documents(self, texts):
        raise RuntimeError("embedding provider unavailable")

    def embed_query(self, text):
        raise RuntimeError("embedding provider unavailable")


def test_catalogue_contains_exactly_five_registered_datasets():
    catalogue = Catalogue(Path("data/catalogue.json"))
    assert {item.dataset_id for item in catalogue.all()} == {
        "population_malaysia",
        "population_state",
        "lfs_month",
        "lfs_qtr_state",
        "cpi_state_inflation",
    }


def test_lexical_search_uses_metric_and_geography():
    catalogue = Catalogue(Path("data/catalogue.json"))
    intent = QuestionIntent(metric="population", geography_level="state")
    results = catalogue.search_lexical("Compare Selangor and Johor population", intent)
    assert results[0].dataset_id == "population_state"
    assert results[0].score > results[1].score


def test_unknown_dataset_is_rejected():
    catalogue = Catalogue(Path("data/catalogue.json"))
    try:
        catalogue.get("invented_dataset")
    except ValueError as exc:
        assert "Unsupported dataset ID" in str(exc)
    else:
        raise AssertionError("Unknown dataset ID was accepted")


def test_hybrid_search_falls_back_when_embedding_provider_fails(tmp_path):
    catalogue = Catalogue(Path("data/catalogue.json"))
    intent = QuestionIntent(
        domain="demography", metric="population", geography_level="national", latest=True
    )

    results = catalogue.search_hybrid(
        "What is Malaysia's latest population?", intent, FailingEmbedder(), tmp_path
    )

    assert results[0].dataset_id == "population_malaysia"
    assert "metric matched" in results[0].reason
