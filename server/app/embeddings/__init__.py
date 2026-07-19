"""Embeddings stage: turn feedback text into vector embeddings.

Provider: **Voyage AI** (hosted, Anthropic-recommended) — reads ``VOYAGE_API_KEY``
from settings. Keep this module a thin provider interface so the rest of the
pipeline stays agnostic to the embedding backend. No implementation yet — added
via spec.
"""
