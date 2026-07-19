"""HTTP route handlers.

Keep pipeline logic (embedding, clustering, Claude prompts) OUT of these
handlers — they should orchestrate the ``ingestion``/``embeddings``/
``clustering``/``insights`` modules, not implement them.
"""
