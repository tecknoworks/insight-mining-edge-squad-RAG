"""Embeddings stage: turn feedback text into vector embeddings.

Provider: open-source **sentence-transformers**, running locally — zero
per-embedding API cost. The model is read from ``EMBEDDING_MODEL`` /
``EMBEDDING_DIMENSION`` (settings), never hardcoded. ``client.py`` wraps the
model behind a narrow provider-agnostic interface; ``index.py`` maintains an
in-memory HNSW index (cosine distance) for similarity search; ``service.py``
orchestrates batching, idempotent re-runs, and job-state persistence. See
``app.api.ingestion`` for the routes that call into this package.
"""
