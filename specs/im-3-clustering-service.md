# Feature: Clustering service

`IM-3` · Epic: Clustering · Branch: `feat/server/clustering-service` · Source PRD:
`docs/prd/im-3-clustering-service.md` · Depends on: IM-2

## Goal

Transform semantic embeddings into actionable themes by running unsupervised clustering over a
dataset's feedback vectors. Every cluster represents a distinct theme (e.g., "payment issues" vs.
"shipping delays"), with outliers preserved as noise rather than forced into nearest neighbors.
Clusters are persisted with stable 2-D coordinates for visualization (IM-5), and the pipeline
supports both **incremental clustering** (cost-optimized: re-cluster only when new embeddings
exceed a threshold) and **on-demand clustering** (explicit re-compute). Cluster labels and summaries
are IM-4's responsibility — clusters ship here with `label = NULL`.

## Acceptance Criteria

1. `POST /clusters/runs` over an embedded dataset produces a `clustering_runs` row, ≥1 `clusters`
   row, and exactly one `cluster_assignments` row per embedded feedback item.
2. Items HDBSCAN labels as noise are persisted with `cluster_id = NULL` and counted in
   `noise_count`. They are **not** assigned to a nearest cluster and **not** dropped.
3. Two runs with identical embeddings, parameters, and seed produce byte-identical cluster
   assignments (determinism via fixed `CLUSTERING_RANDOM_SEED`).
4. Every assignment has finite, non-null `x` and `y` coordinates — including noise points.
5. On a hand-built fixture containing two semantically distinct groups (e.g. payment complaints vs
   shipping complaints), the run produces ≥2 clusters and no cluster mixes the two groups. This
   proves semantic grouping works — do not skip this test.
6. A dataset with zero embedded items returns **409** with an actionable error message.
7. A dataset with fewer items than `min_cluster_size` returns a successful run with
   `cluster_count: 0` and all items as noise — no exception.
8. A second run on the same dataset flips `is_current` so exactly one run per dataset is current;
   the prior run's rows are retained (run history is recoverable).
9. `GET /clusters?dataset_id=<id>` returns only the current run's clusters, ordered by `item_count`
   descending.
10. `GET /clusters/{cluster_id}/items` paginates and returns `feedback_text`, `source`,
    `submitted_at`, and `customer_id` for each item in the cluster.
11. `GET /clusters/map?dataset_id=<id>` returns one point per item (`feedback_item_id`,
    `cluster_id | null`, `x`, `y`) as a flat array, plus the cluster list with `item_count`. No
    nested per-item text — payload must be lean for the visualization hot path.
12. **Incremental clustering** (default): `POST /clusters/runs` with fewer than
    `CLUSTERING_INCREMENTAL_THRESHOLD` new embeddings since the last run returns the current run
    **without recomputing** (no new `clustering_runs` row, no HDBSCAN invocation).
13. **On-demand clustering**: `POST /clusters/runs` with `mode: "on_demand"` always re-clusters,
    regardless of the incremental threshold.
14. **`app/clustering/` does not import `anthropic`** and no cluster is written with a non-null
    `label`.
15. No clustering logic in `app/api/clusters.py` — routes only call into `app/clustering/` and
    translate results to status codes.
16. `client/src/api/` regenerated and committed with new clustering endpoints.

## Technical Approach

- **Algorithm & Config** (`app/core/config.py` + `server/.env.example`):
  - Use **HDBSCAN** from the `hdbscan` package (preferred) or `sklearn.cluster.HDBSCAN` if
    available in the scikit-learn version — pick one in implementation and justify it. HDBSCAN is
    chosen over k-means because it discovers the cluster count automatically and explicitly labels
    outliers, which matches messy feedback data.
  - Add configuration:
    - `clustering_min_cluster_size: int = 15` / `CLUSTERING_MIN_CLUSTER_SIZE`
    - `clustering_min_samples: int = 5` / `CLUSTERING_MIN_SAMPLES`
    - `clustering_reduced_dimensions: int = 50` / `CLUSTERING_REDUCED_DIMENSIONS`
    - `clustering_random_seed: int = 42` / `CLUSTERING_RANDOM_SEED`
    - `clustering_incremental_threshold: int = 10` / `CLUSTERING_INCREMENTAL_THRESHOLD` (number
      of new embeddings required to trigger re-clustering in incremental mode)
  - Request body `params` (optional) may override per run; defaults come from settings.

- **Dimensionality Reduction** — cosine distance degrades in high dimensions (embedding space is
  typically 384D):
  - Apply **UMAP** to a configurable working dimensionality (default 50) before clustering, using
    a fixed `random_state` from `CLUSTERING_RANDOM_SEED`. UMAP is chosen over `TruncatedSVD` for
    better preservation of local and global structure.
  - Separate **2-D projection**: fit a second UMAP (also seeded) to `n_components=2`, stored as
    `cluster_assignments.x` / `.y`. Do **not** reuse the first 2 axes of the 50-D reduction — they
    are not a good 2-D layout for visualization.

- **Models** (`app/models/db.py`):
  - New `ClusteringRun` model, table `clustering_runs`:
    - `id` (UUID pk), `dataset_id` (FK), `algorithm` (str, e.g. "hdbscan"), `params` (JSONB,
      holds `min_cluster_size`, `min_samples`, `reduced_dimensions`), `random_seed` (int),
      `cluster_count` (int), `noise_count` (int), `is_current` (bool, exactly one per dataset),
      `created_at` (DateTime).
  - New `Cluster` model, table `clusters`:
    - `id` (UUID pk), `run_id` (FK), `cluster_index` (int, algorithm-local cluster label),
      `item_count` (int), `label` (text, **nullable** — IM-4 fills it), `summary` (text,
      nullable), `created_at`.
  - New `ClusterAssignment` model, table `cluster_assignments`:
    - `id` (UUID pk), `run_id` (FK), `feedback_item_id` (FK), `cluster_id` (FK, **nullable** =
      noise), `x` (float), `y` (float). Unique constraint on `(run_id, feedback_item_id)`.

- **Schemas** (`app/models/schemas.py`):
  - `ClusteringRun` pydantic: `id`, `dataset_id`, `algorithm`, `params`, `random_seed`,
    `cluster_count`, `noise_count`, `is_current`, `created_at`.
  - `Cluster`: `id`, `run_id`, `cluster_index`, `item_count`, `label`, `summary`.
  - `ClusterSummary` (for GET endpoint): `id`, `cluster_index`, `item_count`, `label`.
  - `ClusterAssignmentPoint`: `feedback_item_id`, `cluster_id | null`, `x`, `y`.
  - `ClusterMap`: `points: list[ClusterAssignmentPoint]`, `clusters: list[ClusterSummary]`.

- **Core Logic** (`app/clustering/`):
  - `app/clustering/algorithms.py` — protocol-driven design:

    ```python
    class ClusteringAlgorithm(Protocol):
        def fit(self, vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            # Returns (labels, x_2d, y_2d)
            ...
    ```

    `HDBSCANClusterer` wraps the `hdbscan.HDBSCAN` instance, accepts `min_cluster_size` and
    `min_samples` in `__init__`, and in `fit()`:
    - Reduce vectors from embedding dimension (384D) to `reduced_dimensions` (50D) via UMAP.
    - Fit HDBSCAN on the reduced vectors, returning raw cluster labels (including `-1` for noise).
    - Fit a separate UMAP to 2D on the original vectors (not the 50D reduction) for visualization.
    - Return `(labels, x_2d, y_2d)` arrays.

  - `app/clustering/service.py` — business logic:
    - `should_cluster(db: Session, dataset_id: UUID, mode: str, threshold: int) -> bool` —
      check if re-clustering is needed:
      - If `mode == "on_demand"`, return `True`.
      - If `mode == "incremental"` (default), check if there's a current run; if not, return
        `True`. If there is, count un-embedded feedback items added since the last run and
        return `count >= threshold`.
    - `run_clustering(db: Session, dataset_id: UUID, algorithm: ClusteringAlgorithm,
params: dict) -> ClusteringRun` —
      - Load all embedded feedback items for the dataset; 409 if zero.
      - Extract embedding vectors; apply the algorithm (which handles dimensionality reduction
        and 2D projection internally).
      - Mark the previous current run `is_current=False`.
      - Create a new `ClusteringRun` row with `is_current=True`.
      - For each unique label in the output (excluding `-1`), create a `Cluster` row and compute
        `item_count`.
      - For each item, create a `ClusterAssignment` row with its label (or `NULL` if label is
        `-1`), `cluster_id` (or `NULL`), and 2D coordinates.
      - Commit and return the run.
    - Handle the degenerate case: fewer items than `min_cluster_size` → create a run with zero
      clusters, all items marked noise, no exception.

- **Routes** (`app/api/clusters.py`, thin handlers only):
  - `POST /clusters/runs` — body: `{dataset_id, mode?: "on_demand"|"incremental", params?: {...}}`.
    - Call `should_cluster()` with the mode and threshold.
    - If not clustering (incremental + threshold not met), return the current run with 202.
    - If clustering, instantiate the algorithm, call `run_clustering()`, return the new run with 202.
    - 404 if dataset not found, 409 if dataset has no embeddings.
  - `GET /clusters/runs/{run_id}` — return the `ClusteringRun` row.
  - `GET /clusters?dataset_id=<id>` — load the current run for that dataset; return only its
    clusters as `list[ClusterSummary]`, ordered by `item_count` descending. 404 if no run exists.
  - `GET /clusters/{cluster_id}/items?limit=50&offset=0` — paginate the cluster's items, return
    `feedback_text`, `source`, `submitted_at`, `customer_id`.
  - `GET /clusters/map?dataset_id=<id>` — load the current run's assignments; return a
    `ClusterMap` with flat `points` array and `clusters` list.

- **Migration** — `uv run alembic revision --autogenerate -m "add clustering"`: creates the three
  new tables.

- **Dependencies**: add `hdbscan` and `umap-learn` via `uv add` (both pull in `numpy` and
  `scikit-learn` transitively).

## Edge Cases / Constraints

- **Noise is first-class:** HDBSCAN's `-1` label is not an error. Noise items are persisted with
  `cluster_id = NULL`, counted in `noise_count`, and included in `cluster_assignments` with valid
  2D coordinates. Do not force them into the nearest cluster or drop them.
- **Determinism:** Every stochastic step (UMAP, HDBSCAN) is seeded with `CLUSTERING_RANDOM_SEED`.
  Two runs over the same embeddings and parameters must produce identical assignments — tests depend
  on this.
- **Degenerate inputs:** Fewer items than `min_cluster_size` → return a valid run with
  `cluster_count: 0` and all items as noise, not a crash. Zero embeddings → 409.
- **2D projection:** The separate 2D UMAP fit is on the **original** embedding vectors, not the
  50D-reduced vectors. The first two axes of the 50D reduction are not a good 2D layout.
- **Re-runs:** A new run immediately supersedes the previous one (`is_current` flipped). Run
  history is kept so a bad parameter change is recoverable — old runs and their assignments remain
  queryable by `run_id`.
- **No incremental re-clustering within a run:** A run re-clusters the entire dataset. Incremental
  re-clustering (e.g., only add new items to existing clusters) is out of scope per the PRD.
- **BackgroundTasks ceiling (inherited from IM-2):** if the server process is killed mid-run, the
  `ClusteringRun` row stays in an incomplete state. This is not fixed here (same as the embedding
  job's limitation); a real fix needs a worker/queue (future work).
- **UMAP/HDBSCAN memory footprint:** `umap-learn` can be memory-hungry on large datasets. The team
  should document actual footprint if issues arise; substitution with `TruncatedSVD` is not
  preemptive.

## Files to Modify

- `server/app/core/config.py` (modify) — add the five `clustering_*` config values.
- `server/.env.example` (modify) — document the five new env vars.
- `server/app/models/db.py` (modify) — add `ClusteringRun`, `Cluster`, `ClusterAssignment` models.
- `server/app/models/schemas.py` (modify) — add pydantic schemas listed above.
- `server/app/clustering/__init__.py` (create) — module docstring.
- `server/app/clustering/algorithms.py` (create) — `ClusteringAlgorithm` protocol,
  `HDBSCANClusterer` implementation.
- `server/app/clustering/service.py` (create) — `should_cluster()`, `run_clustering()`, helper
  functions.
- `server/app/api/clusters.py` (create) — five route handlers (thin, logic-free).
- `server/app/main.py` (modify) — register the `/clusters` router from `app/api/clusters`.
- `server/alembic/versions/xxxx_add_clustering.py` (create, via autogenerate).
- `server/pyproject.toml` (modify) — add `hdbscan`, `umap-learn`.
- `server/tests/test_clustering.py` (create) — unit tests using stub data (no real embeddings):
  deterministic seeding, noise handling, `min_cluster_size` boundary, dimensionality reduction
  pipeline shape, separate 2D projection validation.
- `server/tests/test_api_clusters.py` (create) — integration tests via `TestClient`: full pipeline
  (ingest → embed → cluster → read all endpoints); semantic fixture test; incremental vs.
  on-demand modes; 404/409 error cases.
- `client/src/api/**` (regenerate, commit the diff) — via `pnpm --filter client generate:api`.

## Test Plan

- **Unit** (`server/tests/test_clustering.py`) with stub vectors and no real model inference:
  - Deterministic seeding: same vectors + same seed → identical assignments across runs.
  - Noise handling: items labeled `-1` are persisted with `cluster_id = NULL`, counted in
    `noise_count`, included in assignments.
  - `min_cluster_size` boundary: fewer items than `min_cluster_size` → zero clusters, all noise,
    no crash.
  - Dimensionality reduction: vectors reduced to 50D before clustering, separate 2D projection is
    not the first 2 axes of the 50D reduction.
  - 2D coordinates: every assignment (including noise) has finite `x` and `y`.

- **Semantic Fixture Test** (the critical one): ~60 synthetic feedback strings across three
  obvious, non-overlapping themes (e.g., "payment issues", "shipping delays", "feature requests").
  - Embed with a stubbed deterministic embedder (committed fixture vectors; do not call Voyage in
    tests).
  - Assert the run produces ≥2 clusters.
  - Assert no cluster mixes items from different themes.
  - This test proves semantic grouping actually works — do not skip or water down.

- **Integration** (`server/tests/test_api_clusters.py`) via `TestClient`, mocking embeddings:
  - Ingest a fixture CSV (IM-1) → embed (IM-2, mocked) → `POST /clusters/runs` → `GET
/clusters/runs/{run_id}` shows correct counts.
  - `GET /clusters?dataset_id=` returns current run's clusters, ordered by `item_count` descending.
  - `GET /clusters/{cluster_id}/items` paginates correctly.
  - `GET /clusters/map?dataset_id=` returns flat points array + cluster list.
  - **Incremental clustering**: second `POST` with fewer new embeddings than threshold returns the
    current run without recomputing (stub can verify zero HDBSCAN calls).
  - **On-demand clustering**: second `POST` with `mode: "on_demand"` re-clusters regardless of
    threshold.
  - **Error cases**: 404 on unknown dataset, 409 on dataset with zero embeddings.
  - **Degenerate input**: dataset with fewer items than `min_cluster_size` returns a run with zero
    clusters, all noise.
  - **Re-run flips `is_current`**: second run on the same dataset marks the first run
    `is_current=False`.

- **Performance**: 10k items completes in under 60 seconds on a typical developer laptop. Record
  the actual wall time in the PR description.

- **Migration**: `uv run alembic upgrade head` → `downgrade -1` → `upgrade head` on a scratch DB
  pre-populated with IM-1/IM-2 data.

## Definition of Done

As IM-1 and IM-2, plus:

- `CLUSTERING_MIN_CLUSTER_SIZE`, `CLUSTERING_MIN_SAMPLES`, `CLUSTERING_REDUCED_DIMENSIONS`,
  `CLUSTERING_RANDOM_SEED`, and `CLUSTERING_INCREMENTAL_THRESHOLD` documented in
  `server/.env.example`.
- Dependencies added: `hdbscan`, `umap-learn` (via `uv add`).
- PR description includes measured wall time for a 10k-item cluster run on a typical dev machine.
- All acceptance criteria verified (especially the semantic fixture test).
- `ruff`, `mypy --strict`, `pytest` all green; `pnpm --filter client generate:api` run and its
  diff committed; `pnpm --filter client build` green; PR opened with `/git-pr` and squash-merged.
