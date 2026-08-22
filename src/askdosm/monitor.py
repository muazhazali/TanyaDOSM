"""Background monitoring for registered files and new official catalogue entries."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from askdosm.catalogue import Catalogue
from askdosm.data import DatasetCache


CATALOGUE_CONTENTS_URL = "https://api.github.com/repos/data-gov-my/datagovmy-meta/contents/data-catalogue"


class DatasetMonitorStatus(BaseModel):
    dataset_id: str
    last_checked: datetime | None = None
    last_changed: datetime | None = None
    status: str = "pending"
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_length: str | None = None


class DiscoveredDataset(BaseModel):
    dataset_id: str
    title: str | None = None
    source_url: str | None = None
    discovered_at: datetime


class MonitorState(BaseModel):
    last_checked: datetime | None = None
    registered: dict[str, DatasetMonitorStatus] = Field(default_factory=dict)
    known_catalogue_ids: list[str] = Field(default_factory=list)
    discovered: list[DiscoveredDataset] = Field(default_factory=list)
    discovery_error: str | None = None


class CatalogueMonitor:
    def __init__(self, catalogue: Catalogue, cache: DatasetCache, state_path: Path):
        self.catalogue = catalogue
        self.cache = cache
        self.state_path = state_path

    def read_state(self) -> MonitorState:
        if not self.state_path.exists():
            return MonitorState()
        try:
            return MonitorState.model_validate_json(self.state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return MonitorState()

    def _write_state(self, state: MonitorState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=self.state_path.parent) as temp:
            temp.write(state.model_dump_json(indent=2))
            temp_path = Path(temp.name)
        os.replace(temp_path, self.state_path)

    @staticmethod
    def _request_json(url: str) -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": "AskDOSM/0.2"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    @staticmethod
    def _remote_headers(url: str) -> dict[str, str | None]:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "AskDOSM/0.2"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return {
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "content_length": response.headers.get("Content-Length"),
            }

    def check(self) -> MonitorState:
        state = self.read_state()
        now = datetime.now(UTC)
        for definition in self.catalogue.all():
            previous = state.registered.get(definition.dataset_id)
            try:
                headers = self._remote_headers(str(definition.parquet_url))
                changed = previous is not None and any(
                    getattr(previous, key) is not None and getattr(previous, key) != value
                    for key, value in headers.items() if value is not None
                )
                status = "unchanged"
                changed_at = previous.last_changed if previous else None
                if changed:
                    old_mtime = self.cache.path_for(definition.dataset_id).stat().st_mtime if self.cache.path_for(definition.dataset_id).exists() else None
                    self.cache.load(definition, force_refresh=True)
                    new_mtime = self.cache.path_for(definition.dataset_id).stat().st_mtime
                    if old_mtime is not None and new_mtime == old_mtime:
                        raise RuntimeError("The updated file failed validation; retained the previous cache")
                    status, changed_at = "updated", now
                state.registered[definition.dataset_id] = DatasetMonitorStatus(
                    dataset_id=definition.dataset_id, last_checked=now, last_changed=changed_at,
                    status=status, **headers,
                )
            except Exception as exc:
                fallback = previous or DatasetMonitorStatus(dataset_id=definition.dataset_id)
                fallback.last_checked = now
                fallback.status = "error"
                fallback.error = str(exc)
                state.registered[definition.dataset_id] = fallback

        try:
            entries = self._request_json(CATALOGUE_CONTENTS_URL)
            current = sorted(
                item["name"][:-5] for item in entries
                if item.get("type") == "file" and item.get("name", "").endswith(".json")
            )
            if state.known_catalogue_ids:
                registered_ids = {item.dataset_id for item in self.catalogue.all()}
                already_discovered = {item.dataset_id for item in state.discovered}
                for dataset_id in sorted(set(current) - set(state.known_catalogue_ids)):
                    if dataset_id in registered_ids or dataset_id in already_discovered:
                        continue
                    metadata = self._request_json(
                        f"https://raw.githubusercontent.com/data-gov-my/datagovmy-meta/main/data-catalogue/{dataset_id}.json"
                    )
                    if "DOSM" in metadata.get("data_source", []):
                        state.discovered.append(DiscoveredDataset(
                            dataset_id=dataset_id, title=metadata.get("title_en"),
                            source_url=f"https://data.gov.my/data-catalogue/{dataset_id}", discovered_at=now,
                        ))
            state.known_catalogue_ids = current
            state.discovery_error = None
        except Exception as exc:
            state.discovery_error = str(exc)
        state.last_checked = now
        self._write_state(state)
        return state
