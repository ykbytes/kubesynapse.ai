"""Semantic memory provider — Qdrant-backed vector search for LONG_TERM memory.

Requires qdrant-client. Falls back to built-in provider if Qdrant unavailable.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from memory.provider import MemoryProvider
from memory.types import MemoryEntry, MemoryRetention

logger = logging.getLogger(__name__)


class SemanticMemoryProvider(MemoryProvider):
    """Vector-based semantic memory using Qdrant.

    Stores memory entries with embeddings for similarity search.
    Supports LONG_TERM and PERMANENT retention tiers.
    """

    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        collection_name: str = "kubesynth_memory",
        embedding_dimension: int = 768,
        timeout: float = 5.0,
    ):
        self._qdrant_url = qdrant_url.rstrip("/")
        self._collection_name = collection_name
        self._embedding_dimension = embedding_dimension
        self._timeout = timeout
        self._client: Any | None = None
        self._available = False

    @property
    def name(self) -> str:
        return "semantic"

    @property
    def supported_retention(self) -> set[MemoryRetention]:
        return {MemoryRetention.LONG_TERM, MemoryRetention.PERMANENT}

    def is_available(self) -> bool:
        return self._available

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        try:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self._qdrant_url, timeout=self._timeout)

            # Check if collection exists, create if not
            collections = self._client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self._collection_name not in collection_names:
                from qdrant_client.models import Distance, VectorParams

                self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(
                        size=self._embedding_dimension, distance=Distance.COSINE
                    ),
                )
                logger.info("Created Qdrant collection: %s", self._collection_name)

            self._available = True
            logger.info("Semantic memory provider initialized: %s", self._qdrant_url)

        except ImportError:
            logger.warning("qdrant-client not installed, semantic memory disabled.")
        except Exception as exc:
            logger.warning("Failed to connect to Qdrant at %s: %s", self._qdrant_url, exc)

    def _generate_embedding(self, text: str) -> list[float] | None:
        """Generate embedding for text. Uses simple fallback if no model available.

        In production, this should call an embedding model (OpenAI, local, etc.).
        """
        # TODO: Replace with actual embedding model call
        # For now, return None to indicate embedding not available
        # The store method will handle this gracefully
        return None

    def store(self, entry: MemoryEntry) -> bool:
        if not self._available or not self._client:
            return False

        try:
            from qdrant_client.models import PointStruct

            # Generate embedding if not provided
            embedding = entry.embedding or self._generate_embedding(
                json.dumps(entry.content, ensure_ascii=False, default=str)
            )

            if embedding is None:
                logger.debug("No embedding available for semantic memory entry, skipping.")
                return False

            point_id = self._entry_id(entry)

            self._client.upsert(
                collection_name=self._collection_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload=entry.to_dict(),
                    )
                ],
            )
            return True

        except Exception as exc:
            logger.warning("Semantic memory store failed: %s", exc, exc_info=True)
            return False

    def recall(
        self,
        query: str,
        retention: MemoryRetention | None = None,
        limit: int = 10,
        min_relevance: float = 0.3,
    ) -> list[tuple[MemoryEntry, float]]:
        if not self._available or not self._client:
            return []

        try:
            query_embedding = self._generate_embedding(query)
            if query_embedding is None:
                return []

            results = self._client.search(
                collection_name=self._collection_name,
                query_vector=query_embedding,
                limit=limit,
                score_threshold=min_relevance,
            )

            entries: list[tuple[MemoryEntry, float]] = []
            for result in results:
                try:
                    entry = MemoryEntry.from_dict(result.payload)
                    entries.append((entry, round(result.score, 3)))
                except (KeyError, ValueError):
                    continue

            return entries

        except Exception as exc:
            logger.warning("Semantic memory recall failed: %s", exc, exc_info=True)
            return []

    def recall_by_type(self, memory_type: str, limit: int = 10) -> list[MemoryEntry]:
        if not self._available or not self._client:
            return []

        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            results = self._client.scroll(
                collection_name=self._collection_name,
                scroll_filter=Filter(
                    must=[FieldCondition(key="type", match=MatchValue(value=memory_type))]
                ),
                limit=limit,
            )

            entries: list[MemoryEntry] = []
            for point in results[0]:
                try:
                    entries.append(MemoryEntry.from_dict(point.payload))
                except (KeyError, ValueError):
                    continue

            return entries

        except Exception as exc:
            logger.warning("Semantic memory recall_by_type failed: %s", exc, exc_info=True)
            return []

    def delete(self, entry_id: str) -> bool:
        if not self._available or not self._client:
            return False

        try:
            self._client.delete(
                collection_name=self._collection_name,
                points_selector=[entry_id],
            )
            return True
        except Exception as exc:
            logger.warning("Semantic memory delete failed: %s", exc)
            return False

    def clear(self, thread_id: str | None = None) -> bool:
        if not self._available or not self._client:
            return False

        try:
            if thread_id:
                # Delete by thread_id filter
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                self._client.delete(
                    collection_name=self._collection_name,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="content.thread_id", match=MatchValue(value=thread_id)
                            )
                        ]
                    ),
                )
            else:
                # Clear entire collection
                self._client.delete_collection(self._collection_name)
                # Recreate
                from qdrant_client.models import Distance, VectorParams

                self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(
                        size=self._embedding_dimension, distance=Distance.COSINE
                    ),
                )
            return True
        except Exception as exc:
            logger.warning("Semantic memory clear failed: %s", exc)
            return False

    def compact(self, thread_id: str | None = None) -> bool:
        """Optimize Qdrant collection."""
        if not self._available or not self._client:
            return False

        try:
            self._client.optimize(self._collection_name)
            return True
        except Exception as exc:
            logger.warning("Semantic memory compact failed: %s", exc)
            return False

    def shutdown(self) -> None:
        if self._client:
            with contextlib.suppress(Exception):
                self._client.close()

    def get_stats(self) -> dict[str, Any]:
        if not self._available or not self._client:
            return {"status": "unavailable"}

        try:
            info = self._client.get_collection(self._collection_name)
            return {
                "status": "available",
                "url": self._qdrant_url,
                "collection": self._collection_name,
                "vectors_count": info.vectors_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "points_count": info.points_count,
                "dimension": self._embedding_dimension,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _entry_id(self, entry: MemoryEntry) -> str:
        """Generate deterministic ID for entry."""
        import hashlib

        content = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:32]
