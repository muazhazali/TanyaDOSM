from pathlib import Path

from askdosm.catalogue import Catalogue
from askdosm.models import QuestionIntent


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

