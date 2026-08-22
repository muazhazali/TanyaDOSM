from pathlib import Path

import pandas as pd

from askdosm.catalogue import Catalogue
from askdosm.data import DatasetCache
from askdosm.monitor import CatalogueMonitor


def test_monitor_baselines_catalogue_then_discovers_new_dosm_dataset(tmp_path, monkeypatch):
    catalogue = Catalogue(Path("data/catalogue.json"))
    cache = DatasetCache(tmp_path / "datasets")
    monitor = CatalogueMonitor(catalogue, cache, tmp_path / "monitor.json")
    headers = {"etag": '"v1"', "last_modified": "today", "content_length": "10"}
    entries = [{"name": "population_malaysia.json", "type": "file"}]
    monkeypatch.setattr(monitor, "_remote_headers", lambda url: headers)
    monkeypatch.setattr(monitor, "_request_json", lambda url: entries)

    baseline = monitor.check()

    assert baseline.known_catalogue_ids == ["population_malaysia"]
    assert baseline.discovered == []
    entries.append({"name": "new_dosm_table.json", "type": "file"})

    def request_json(url):
        if url.endswith("new_dosm_table.json"):
            return {"title_en": "New DOSM Table", "data_source": ["DOSM"]}
        return entries

    monkeypatch.setattr(monitor, "_request_json", request_json)
    updated = monitor.check()

    assert [item.dataset_id for item in updated.discovered] == ["new_dosm_table"]
    assert monitor.read_state().discovered[0].title == "New DOSM Table"


def test_monitor_refreshes_registered_dataset_when_remote_file_changes(tmp_path, monkeypatch):
    catalogue = Catalogue(Path("data/catalogue.json"))
    cache = DatasetCache(tmp_path / "datasets")
    monitor = CatalogueMonitor(catalogue, cache, tmp_path / "monitor.json")
    versions = iter(['"v1"', '"v2"'])
    current = {'etag': '"v1"'}
    monkeypatch.setattr(
        monitor, "_remote_headers",
        lambda url: {"etag": current["etag"], "last_modified": None, "content_length": None},
    )
    monkeypatch.setattr(
        monitor, "_request_json",
        lambda url: [{"name": f"{item.dataset_id}.json", "type": "file"} for item in catalogue.all()],
    )
    monitor.check()
    definition = catalogue.get("population_malaysia")
    destination = cache.path_for(definition.dataset_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "date": ["2025-01-01"], "sex": ["both"], "age": ["overall"],
        "ethnicity": ["overall"], "population": [1.0],
    }).to_parquet(destination)

    def refresh(selected, force_refresh=False):
        assert selected.dataset_id == definition.dataset_id
        assert force_refresh
        frame = pd.read_parquet(destination)
        frame["population"] = 2.0
        frame.to_parquet(destination)
        return frame

    monkeypatch.setattr(cache, "load", refresh)
    current["etag"] = next(versions)
    current["etag"] = next(versions)
    state = monitor.check()

    assert state.registered[definition.dataset_id].status == "updated"
