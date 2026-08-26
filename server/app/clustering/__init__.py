"""Semantic clustering of feedback items.

Runs unsupervised clustering over embeddings to group feedback by meaning.
Supports both incremental (threshold-based) and on-demand (explicit) re-clustering.
Uses HDBSCAN for automatic cluster count discovery and explicit noise handling.
Dimensionality reduction (UMAP) happens before clustering and for 2D visualization.
"""
