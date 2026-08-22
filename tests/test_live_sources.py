import os
from pathlib import Path

import pytest

from askdosm.catalogue import Catalogue
from askdosm.data import DatasetCache, validate_schema


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("ASKDOSM_RUN_LIVE_TESTS") != "1", reason="live tests are opt-in"),
]


def test_all_official_parquet_sources_match_registry(tmp_path):
    catalogue = Catalogue(Path("data/catalogue.json"))
    cache = DatasetCache(tmp_path, ttl_hours=0)
    for definition in catalogue.all():
        frame = cache.load(definition, force_refresh=True)
        validate_schema(frame, definition)
        assert not frame.empty
