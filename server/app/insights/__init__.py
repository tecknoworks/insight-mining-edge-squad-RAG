"""Insights stage: Claude-powered summarization and chat-with-data.

Two Claude usages live here: batch cluster summarization (label a theme + pick
representative quotes) and chat-with-data (RAG over the corpus). Always read the
model from ``Settings.anthropic_summarization_model`` /
``anthropic_chat_model`` — never hardcode a model ID. Consult the ``claude-api``
skill before writing any Claude call. No implementation yet — added via spec.
"""
