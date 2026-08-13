"""Shared embedding generation via the configured embedding model.

This module is the single source of truth for embedding generation across the
project. Both the Knowledge RAG pipeline (document chunk embedding) and the
Memory subsystem (memory embedding) MUST reuse the embedding logic and the
``EMBEDDING_DIM`` constant defined here, so that every vector stored in
PostgreSQL/pgvector uses the same model and dimension.

The model and base URL are supplied through the EMBEDDING_MODEL /
EMBEDDING_BASE_URL environment variables (see backend/.env). For this project
the model is `doubao-embedding-vision`, which outputs 2048-dim vectors.
"""
from openai import OpenAI

from app.config import settings

# Must match the configured embedding model's output dimension
# (doubao-embedding-vision -> 2048). All pgvector columns rely on this.
EMBEDDING_DIM = 2048


def _client() -> OpenAI:
    if not settings.embedding_base_url:
        raise ValueError("EMBEDDING_BASE_URL is not configured")
    return OpenAI(base_url=settings.embedding_base_url, api_key=settings.openai_api_key)


def embed_text(text: str) -> list[float]:
    """Return an embedding for a single text using the configured model."""
    if not settings.embedding_model:
        raise ValueError("EMBEDDING_MODEL is not configured")
    client = _client()
    resp = client.embeddings.create(model=settings.embedding_model, input=text)
    return list(resp.data[0].embedding)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return embeddings for many texts."""
    return [embed_text(t) for t in texts]
