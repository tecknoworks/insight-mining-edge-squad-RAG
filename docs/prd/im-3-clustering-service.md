# IM-3 — Clustering service

**Type:** Story **Epic:** Clustering **Priority:** P0
**Estimate:** 13 points **Depends on:** IM-2
**Branch:** `feat/server/clustering-service`

## Context

This is the feature the product is named for: grouping feedback by meaning rather than keywords, so
"can't pay" and "checkout failed" land in the same theme. Everything downstream — summaries,
the visualization, the dashboard — reads the output of this stage.

## Goal

Run unsupervised clustering over a dataset's embeddings, persist the resulting clusters and
per-item assignments, and produce a stable 2-D coordinate per item so IM-5 can plot the map without
recomputing anything. Support both **incremental clustering** (only re-cluster after new embeddings
exceed a threshold) and **on-demand clustering** (trigger on explicit request).

## Scope

**In scope**

- Clustering in `app/clustering/` (HDBSCAN primary; k-means fallback path).
- Optional dimensionality reduction before clustering.
- 2-D projection stored per item, for visualization.
- `clusters` + `cluster_assignments` tables and migration.
- Run-trigger and read endpoints in `app/api/clusters.py`.

**Out of scope**

- Cluster labels and summaries — **IM-4 owns all Claude calls.** This ticket must not import
  `anthropic`. A cluster ships from here with `label = NULL`.
- Any charting code (IM-5).
- Incremental/streaming re-clustering. A run re-clusters the whole dataset.

## Technical approach

- **Algorithm.** HDBSCAN (`hdbscan`, or `sklearn.cluster.HDBSCAN` if the installed scikit-learn
  version provides it — pick one in the spec and justify it). HDBSCAN is chosen over k-means
  because it discovers the cluster count and explicitly labels outliers, which matches messy
  feedback data. Expose `min_cluster_size` and `min_samples` as configuration.
- **Noise is a first-class outcome.** HDBSCAN labels outliers `-1`. Persist those items with
  `cluster_id = NULL` and report the count. Do not force them into the nearest cluster and do not
  drop them.
- **Dimensionality reduction.** Cosine distance degrades in high dimensions. Reduce with **UMAP**
  to a configurable working dimensionality (default 50) before clustering, using a fixed
  `random_state` (default `CLUSTERING_RANDOM_SEED`). UMAP is chosen over `TruncatedSVD` for better
  preservation of local and global structure in high-dimensional spaces. **Constraint:** UMAP requires
  `umap-learn` (add via `uv add`); the first team member to hit memory/disk issues should document
  the footprint and revisit this choice, but do not preemptively substitute `TruncatedSVD`.
- **2-D projection.** A **separate** UMAP fit to `n_components=2`, stored as
  `cluster_assignments.x` / `.y`. Do not reuse the 50-D reduction's first two axes — they are not a
  good 2-D layout.
- **Determinism.** Every stochastic step takes a seed from `CLUSTERING_RANDOM_SEED`. Two runs over
  the same embeddings with the same parameters must produce identical assignments — tests depend
  on it.
- **Degenerate inputs.** Fewer items than `min_cluster_size` → return a valid run with zero
  clusters and all items marked noise, not a crash. Zero embedded items → `409`.
- **Re-runs.** A new run supersedes the previous one for that dataset. Keep run history
  (`clustering_runs`) so a bad parameter change is recoverable; mark exactly one run per dataset as
  current.
- **Incremental vs. on-demand clustering.** Add a mode flag to the run request:
  - `mode: "on_demand"` — always re-cluster the entire dataset regardless of how many new embeddings exist.
  - `mode: "incremental"` (default) — only re-cluster if the number of unembed items since the last run
    exceeds `CLUSTERING_INCREMENTAL_THRESHOLD` (env var). If the threshold is not met, return the
    current run without recomputing (cost optimization for frequent API calls). Track the threshold
    in the env var and allow per-request overrides in the request body.

## Data model

- `clustering_runs`: `id`, `dataset_id` (FK), `algorithm`, `params` (JSONB), `random_seed`,
  `cluster_count`, `noise_count`, `is_current` (bool), `created_at`.
- `clusters`: `id`, `run_id` (FK), `cluster_index` (int, algorithm-local), `item_count`,
  `label` (text, **nullable** — IM-4 fills it), `summary` (text, nullable), `created_at`.
- `cluster_assignments`: `id`, `run_id` (FK), `feedback_item_id` (FK), `cluster_id` (FK,
  **nullable** = noise), `x` (float), `y` (float). Unique on `(run_id, feedback_item_id)`.

## API contract

```
POST /clusters/runs                       → 202 ClusteringRun    body: {dataset_id, mode?, params?}
                                          → 409 dataset has no embedded items
GET  /clusters/runs/{run_id}              → 200 ClusteringRun (state + counts)
GET  /clusters?dataset_id=<id>            → 200 list[ClusterSummary]   (current run)
GET  /clusters/{cluster_id}/items         → 200 paginated list[FeedbackItem]
GET  /clusters/map?dataset_id=<id>        → 200 ClusterMap  (points for IM-5)
```

`mode` in POST body: `"on_demand"` (always re-cluster) or `"incremental"` (default, only if new embeddings exceed threshold).

`ClusterMap` returns one point per item — `{feedback_item_id, cluster_id | null, x, y}` — plus the
cluster list with `item_count`. Keep this endpoint's payload lean; it is the visualization's hot
path.

## New configuration

`CLUSTERING_MIN_CLUSTER_SIZE` (default `15`), `CLUSTERING_MIN_SAMPLES` (default `5`),
`CLUSTERING_REDUCED_DIMENSIONS` (default `50`), `CLUSTERING_RANDOM_SEED` (default `42`).
Request-body `params` may override per run; defaults come from settings.

## Acceptance criteria

1. `POST /clusters/runs` over an embedded dataset produces a `clustering_runs` row, ≥1 `clusters`
   row, and exactly one `cluster_assignments` row per embedded feedback item.
2. Items HDBSCAN labels as noise are persisted with `cluster_id = NULL` and counted in
   `noise_count`. They are **not** assigned to a nearest cluster and **not** dropped.
3. Two runs with identical embeddings, parameters, and seed produce byte-identical cluster
   assignments.
4. Every assignment has finite, non-null `x` and `y` — including noise points.
5. On a hand-built fixture containing two semantically distinct groups (e.g. payment complaints vs
   shipping complaints), the run produces ≥2 clusters and no cluster mixes the two groups. This is
   the test that proves semantic grouping actually works — do not skip it.
6. A dataset with zero embedded items returns **409** with an actionable message.
7. A dataset with fewer items than `min_cluster_size` returns a successful run with
   `cluster_count: 0` and all items as noise — no exception.
8. A second run on the same dataset flips `is_current` so exactly one run per dataset is current;
   the prior run's rows are retained.
9. `GET /clusters?dataset_id=` returns only the current run's clusters, ordered by `item_count`
   descending.
10. `GET /clusters/{id}/items` paginates and returns the item's `feedback_text`, `source`,
    `submitted_at`, and `customer_id`.
11. `GET /clusters/map` returns one point per item and the payload is a flat array — no nested
    per-item text (that would blow up the frontend payload).
12. **Incremental clustering** (default): calling `POST /clusters/runs` with fewer than
    `CLUSTERING_INCREMENTAL_THRESHOLD` new embeddings since the last run returns the current run
    **without recomputing** (no new `clustering_runs` row, no HDBSCAN invocation).
13. **On-demand clustering**: calling `POST /clusters/runs` with `mode: "on_demand"` always
    re-clusters, regardless of the incremental threshold.
14. **`app/clustering/` does not import `anthropic`** and no cluster is written with a non-null
    `label`.
15. No clustering logic in `app/api/clusters.py`.
16. `client/src/api/` regenerated and committed.

## Test plan

- Unit: deterministic seeding; noise handling; `min_cluster_size` boundary; the reduce-then-cluster
  pipeline shape; the separate 2-D projection is not the 50-D truncation.
- **Semantic fixture test** (the important one): ~60 synthetic feedback strings across three
  obvious themes with deliberately non-overlapping vocabulary between themes. Embed with a stubbed
  deterministic embedder (or committed fixture vectors — do not call Voyage in tests) and assert
  the themes separate.
- Integration: ingest → embed (mocked) → cluster → read all four GET endpoints.
- Performance: 10k items completes in under 60 s on a developer laptop; record the actual number in
  the PR.

## Definition of done

As IM-1, plus `hdbscan`/`umap-learn`/`scikit-learn` added via `uv add` (never a `requirements.txt`)
and the measured 10k-item runtime noted in the PR description.
