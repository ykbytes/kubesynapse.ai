"""MCP RAG sidecar — index documents and perform semantic search via Qdrant."""

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-rag",
    "Retrieve-Augmented Generation — index documents and semantic search via Qdrant vector DB.",
)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "agent_docs")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MAX_OUTPUT_CHARS = 12000

_model_cache = {}


def _get_model():
    if "model" not in _model_cache:
        from fastembed import TextEmbedding
        _model_cache["model"] = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _model_cache["model"]


def _get_qdrant():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL)


def _ensure_collection(client, vector_size: int):
    from qdrant_client.models import Distance, VectorParams
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


@server.tool()
def index_documents(texts: list[str], metadata: list[str] | None = None) -> str:
    """Index a list of text chunks into the vector database.

    texts: list of text strings to index.
    metadata: optional list of source labels (same length as texts).
    """
    try:
        from qdrant_client.models import PointStruct
        model = _get_model()
        embeddings = list(model.embed(texts))
        client = _get_qdrant()
        _ensure_collection(client, len(embeddings[0]))
        points = []
        for i, (text, emb) in enumerate(zip(texts, embeddings)):
            point_id = hashlib.md5(text.encode()).hexdigest()[:16]
            payload = {"text": text}
            if metadata and i < len(metadata):
                payload["source"] = metadata[i]
            vec = emb.tolist() if hasattr(emb, 'tolist') else list(emb)
            points.append(PointStruct(
                id=int(point_id, 16) % (2**63),
                vector=vec,
                payload=payload,
            ))
        client.upsert(COLLECTION_NAME, points)
        return f"Indexed {len(points)} documents into '{COLLECTION_NAME}'"
    except ImportError as e:
        return f"ERROR: Missing dependency: {e}"
    except Exception as e:
        return f"ERROR: Indexing failed: {e}"


@server.tool()
def semantic_search(query: str, top_k: int = 5) -> str:
    """Search for documents similar to the query text."""
    try:
        model = _get_model()
        query_embedding = list(model.embed([query]))[0]
        qvec = query_embedding.tolist() if hasattr(query_embedding, 'tolist') else list(query_embedding)
        client = _get_qdrant()
        results = client.search(
            COLLECTION_NAME,
            query_vector=qvec,
            limit=min(top_k, 20),
        )
        if not results:
            return "No matching documents found."
        lines = []
        for r in results:
            score = f"{r.score:.3f}"
            text = r.payload.get("text", "")[:500]
            source = r.payload.get("source", "")
            header = f"[{score}] {source}" if source else f"[{score}]"
            lines.append(f"{header}\n{text}\n")
        return "\n".join(lines)[:MAX_OUTPUT_CHARS]
    except ImportError as e:
        return f"ERROR: Missing dependency: {e}"
    except Exception as e:
        return f"ERROR: Search failed: {e}"


@server.tool()
def collection_info() -> str:
    """Get info about the current Qdrant collection."""
    try:
        client = _get_qdrant()
        info = client.get_collection(COLLECTION_NAME)
        return (
            f"Collection: {COLLECTION_NAME}\n"
            f"Points: {info.points_count}\n"
            f"Vectors: {info.vectors_count}\n"
            f"Status: {info.status}"
        )
    except Exception as e:
        return f"ERROR: {e}"


if __name__ == "__main__":
    run_server(server)
