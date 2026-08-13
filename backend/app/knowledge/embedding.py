"""Embedding generation for the Knowledge RAG pipeline.

The actual embedding logic now lives in :mod:`app.infrastructure.embedding` so
that Knowledge and Memory share the exact same model and dimension. This module
re-exports the shared helpers to avoid breaking existing imports.
"""
from app.infrastructure.embedding import (  # noqa: F401
    EMBEDDING_DIM,
    embed_text,
    embed_texts,
)
