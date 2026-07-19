"""Ingestion stage: CSV parsing, cleaning, and validation.

Entry point of the pipeline. Only ``feedback_text`` is required per row;
``date``, ``source``, and ``customer_id`` are optional and must be preserved
through the pipeline where present. No implementation yet — added via spec.
"""
