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


# Filler words that carry no statistical meaning. Without this filter, common
# words like "you", "data", "the" or "how" inflate lexical scores and let
# off-topic questions clear the match floor.
STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "you", "your", "data", "what",
    "which", "how", "many", "much", "can", "could", "would", "should", "have",
    "has", "had", "get", "give", "show", "tell", "about", "with", "from",
    "that", "this", "these", "those", "please", "want", "need", "know", "any",
    "all", "some", "its", "their", "our", "not", "but", "out", "here", "there",
    "ada", "anda", "saya", "apa", "yang", "untuk", "dan", "atau", "boleh",
    "tolong", "berapa", "mana", "tahu", "mahu", "ini", "itu", "dengan", "pada",
    "adalah", "tak", "tidak", "kita", "mereka", "dia",
}


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
        tokens = {token for token in re.findall(r"[\w.-]+", query.casefold()) if token not in STOPWORDS}
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
                if intent.metric:
                    metric_cf = intent.metric.casefold()
                    measure_terms = {dataset.title.casefold()}
                    for measure in dataset.measures:
                        measure_terms.add(measure.name.casefold())
                        measure_terms.update(alias.casefold() for alias in measure.aliases)
                    aliases_cf = {alias.casefold() for alias in dataset.aliases} | {dataset.title.casefold()}
                    if metric_cf in measure_terms:
                        # The metric names an actual measure here: the strongest signal.
                        score += 0.35
                        reasons.append("metric matched")
                    elif metric_cf in haystack:
                        # The metric only appears somewhere in the metadata: weak.
                        score += 0.1
                        reasons.append("metric mentioned")
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
            return self._rank(lexical, intent)

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
        return self._rank(lexical, intent)

    def _rank(
        self,
        candidates: dict[str, DatasetCandidate],
        intent: QuestionIntent | None,
    ) -> list[DatasetCandidate]:
        """Rank candidates deterministically.

        Ties on score are common because same-topic datasets differ only by
        geography. When scores are effectively equal, prefer the geography the
        intent named, then national, then state, then district, and finally fall
        back to the dataset id so the order is stable rather than arbitrary.
        """
        geography_priority = {"national": 0, "state": 1, "district": 2}
        requested = intent.geography_level if intent else None

        def sort_key(candidate: DatasetCandidate) -> tuple:
            dataset = self._datasets.get(candidate.dataset_id)
            geography = dataset.geography_level if dataset else "district"
            geography_rank = geography_priority.get(geography, 3)
            # Named geography first; otherwise prefer the broadest (national) so a
            # vague question yields a sensible default.
            geography_pref = 0 if requested and geography == requested else 1
            return (-round(candidate.score, 4), geography_pref, geography_rank, candidate.dataset_id)

        return sorted(candidates.values(), key=sort_key)
