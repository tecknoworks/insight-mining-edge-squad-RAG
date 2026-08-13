"""Ingestion stage: CSV parsing, cleaning, and validation.

Entry point of the pipeline. Only ``feedback_text`` is required per row;
``date``, ``source``, and ``customer_id`` are optional and must be preserved
through the pipeline where present. ``parser.py`` handles header mapping and
per-row validation; ``service.py`` orchestrates streaming, batched
persistence, and report assembly. No logic lives here — see
``app.api.ingestion`` for the routes that call into this package.
"""
