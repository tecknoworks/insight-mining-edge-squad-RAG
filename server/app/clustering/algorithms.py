"""Clustering algorithms — protocol and implementations.

All algorithms reduce to the same interface: fit vectors and return labels + 2D coordinates.
"""

from typing import Protocol

import hdbscan
import numpy as np
import umap


class ClusteringAlgorithm(Protocol):
    """Protocol for clustering implementations."""

    def fit(
        self, vectors: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Fit vectors and return (labels, x_2d, y_2d) arrays.

        labels: int array, -1 indicates noise
        x_2d, y_2d: float arrays of 2D projection coordinates
        """
        ...


class HDBSCANClusterer:
    """HDBSCAN clustering with automatic dimensionality reduction and 2D projection."""

    def __init__(
        self,
        min_cluster_size: int = 15,
        min_samples: int = 5,
        reduced_dimensions: int = 50,
        random_seed: int = 42,
    ):
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.reduced_dimensions = reduced_dimensions
        self.random_seed = random_seed

    def fit(
        self, vectors: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Fit HDBSCAN with dimensionality reduction.

        1. Reduce vectors to `reduced_dimensions` via UMAP (if > min cluster size).
        2. Run HDBSCAN on reduced vectors.
        3. Fit separate 2D UMAP on original vectors for visualization.
        4. Return labels, x_2d, y_2d.
        """
        vectors = np.asarray(vectors, dtype=np.float32)
        n_items = vectors.shape[0]

        # Reduce to working dimensionality
        # Skip UMAP for very small datasets to avoid convergence issues.
        # Clamp n_components to n_items - 2: UMAP's spectral init requires k < N.
        safe_dims = min(self.reduced_dimensions, max(n_items - 2, 2))
        vectors_reduced = vectors
        if n_items >= 15 and vectors.shape[1] > safe_dims:
            try:
                umap_reduce = umap.UMAP(
                    n_components=safe_dims,
                    random_state=self.random_seed,
                    metric="cosine",
                )
                vectors_reduced = umap_reduce.fit_transform(vectors)
            except (ValueError, RuntimeError, TypeError):
                vectors_reduced = vectors

        # Cluster on reduced vectors
        try:
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=self.min_cluster_size,
                min_samples=self.min_samples,
            )
            labels = clusterer.fit_predict(vectors_reduced)
        except (ValueError, RuntimeError):
            # If clustering fails (e.g., min_cluster_size too large), mark all as noise
            labels = np.full(n_items, -1, dtype=int)

        # 2D projection on original vectors (not first 2 axes of reduced)
        # Use a simple PCA-like approach for very small datasets
        try:
            if n_items >= 10:
                umap_2d = umap.UMAP(
                    n_components=2, random_state=self.random_seed, metric="cosine"
                )
                coords_2d = umap_2d.fit_transform(vectors)
                x_2d, y_2d = coords_2d[:, 0], coords_2d[:, 1]
            else:
                raise ValueError("Use fallback for small datasets")
        except (ValueError, RuntimeError, TypeError):
            # For tiny datasets, use first two principal components or scaled indices
            if vectors.shape[1] >= 2:
                # Use first two dimensions, normalized
                x_2d = (vectors[:, 0] - vectors[:, 0].min()) / (
                    vectors[:, 0].max() - vectors[:, 0].min() + 1e-8
                )
                y_2d = (vectors[:, 1] - vectors[:, 1].min()) / (
                    vectors[:, 1].max() - vectors[:, 1].min() + 1e-8
                )
            else:
                # Single dimension or no dimensions - use index as fallback
                x_2d = np.arange(n_items, dtype=np.float32) / max(n_items - 1, 1)
                y_2d = np.zeros(n_items, dtype=np.float32)

        return labels, x_2d, y_2d
