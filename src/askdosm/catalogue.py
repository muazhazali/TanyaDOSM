"""Curated dataset registry and hybrid metadata search."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Protocol

import numpy as np
from pydantic import TypeAdapter

from askdosm.models import DatasetCandidate, DatasetDefinition, QuestionIntent


logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Catalogue:
    def __init__(self, path: Path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        datasets = TypeAdapter(list[DatasetDefinition]).validate_python(raw)
        self._datasets = {item.dataset_id: item for item in datasets}

    def all(self) -> list[DatasetDefinition]:
        return list(self._datasets.values())

    def get(self, dataset_id: str) -> DatasetDefinition:
        try:
            return self._datasets[dataset_id]
        except KeyError as exc:
            raise ValueError(f"Unsupported dataset ID: {dataset_id}") from exc

    def search_lexical(self, query: str, intent: QuestionIntent | None = None) -> list[DatasetCandidate]:
        tokens = set(re.findall(r"[\w.-]+", query.casefold()))
        candidates: list[DatasetCandidate] = []
        for dataset in self.all():
            haystack = dataset.searchable_text.casefold()
            matched = sorted(token for token in tokens if len(token) > 2 and token in haystack)
            score = min(0.65, len(matched) * 0.08)
            reasons = [f"matched: {', '.join(matched[:6])}"] if matched else []
            if intent:
                if intent.geography_level == dataset.geography_level:
                    score += 0.2
                    reasons.append("geography matched")
                if intent.domain and intent.domain.casefold() in {dataset.domain.casefold(), haystack}:
                    score += 0.15
                    reasons.append("domain matched")
                if intent.metric and intent.metric.casefold() in haystack:
                    score += 0.25
                    reasons.append("metric matched")
                if intent.metric:
                    metric_cf = intent.metric.casefold()
                    aliases_cf = {a.casefold() for a in dataset.aliases} | {dataset.title.casefold()}
                    if metric_cf in aliases_cf:
                        score += 0.15
                        reasons.append("exact metric alias match")
            candidates.append(
                DatasetCandidate(dataset_id=dataset.dataset_id, score=min(score, 1.0), reason="; ".join(reasons) or "weak metadata match")
            )
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)

    def search_hybrid(
        self,
        query: str,
        intent: QuestionIntent | None,
        embedder: Embedder | None,
        cache_dir: Path,
    ) -> list[DatasetCandidate]:
        lexical = {candidate.dataset_id: candidate for candidate in self.search_lexical(query, intent)}
        if embedder is None:
            return sorted(lexical.values(), key=lambda candidate: candidate.score, reverse=True)

        try:
            datasets = self.all()
            texts = [dataset.searchable_text for dataset in datasets]
            embedder_identity = f"{type(embedder).__module__}.{type(embedder).__qualname__}:{getattr(embedder, 'model', '')}"
            digest = hashlib.sha256(f"{embedder_identity}\n{'\n'.join(texts)}".encode()).hexdigest()[:16]
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / f"catalogue-embeddings-{digest}.json"
            if cache_file.exists():
                vectors = json.loads(cache_file.read_text(encoding="utf-8"))
            else:
                vectors = embedder.embed_documents(texts)
                cache_file.write_text(json.dumps(vectors), encoding="utf-8")
            query_vector = np.asarray(embedder.embed_query(query), dtype=float)
            query_norm = np.linalg.norm(query_vector)
            for dataset, vector in zip(datasets, vectors, strict=True):
                candidate_vector = np.asarray(vector, dtype=float)
                denominator = query_norm * np.linalg.norm(candidate_vector)
                similarity = float(np.dot(query_vector, candidate_vector) / denominator) if denominator else 0.0
                existing = lexical[dataset.dataset_id]
                existing.score = min(1.0, existing.score * 0.65 + max(similarity, 0.0) * 0.35)
                existing.reason += f"; semantic similarity {similarity:.2f}"
        except Exception as exc:
            # Embeddings improve ranking but are not required for catalogue lookup.
            # In particular, provider response validation errors should not abort a run
            # when the deterministic metadata search can still select a dataset.
            logger.warning("Semantic catalogue search failed; using lexical ranking: %s", exc)
        return sorted(lexical.values(), key=lambda candidate: candidate.score, reverse=True)
