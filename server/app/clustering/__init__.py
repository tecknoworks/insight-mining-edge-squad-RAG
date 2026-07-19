"""Clustering stage: unsupervised grouping of embeddings into themes.

Groups feedback by meaning (HDBSCAN or k-means) so semantically similar items
land in the same theme regardless of wording. Keep this logic out of route
handlers. No implementation yet — added via spec.
"""
