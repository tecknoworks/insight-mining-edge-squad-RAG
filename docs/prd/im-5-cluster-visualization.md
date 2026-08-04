# IM-5 — Cluster visualization component

**Type:** Story **Epic:** Frontend **Priority:** P1
**Estimate:** 8 points **Depends on:** IM-3, IM-4
**Branch:** `feat/client/cluster-visualization`

## Context

`client/src/` is currently a scaffold: one `HomePage`, one `AppContext`, a generated API client, and
nothing that renders data. This ticket delivers the "patterns visible at a glance" promise from the
README — an interactive cluster map sized by theme volume, backed by the endpoints from IM-3 and the
labels from IM-4.

## Goal

A dashboard page that renders every feedback item as a point positioned by its 2-D coordinates,
coloured by cluster, with cluster volume legible at a glance. Selecting a cluster opens a detail
panel showing Claude's label, summary, representative quotes, and the underlying feedback items.

## Scope

**In scope**

- A dashboard page under `client/src/pages/` and components under `client/src/components/`.
- Data fetching through the **generated** client in `client/src/api/`.
- Dataset-scoped app state in `client/src/store/` (React Context + hooks — per `CLAUDE.md`).
- Loading, empty, and error states for every async surface.
- Source and date-range filters.

**Out of scope**

- The chat panel (IM-6).
- CSV upload UI — out of scope for this ticket; select an existing dataset from a dropdown fed by
  `GET /ingestion/datasets`.
- Any change to backend endpoints. If the map needs data IM-3 does not expose, raise it rather than
  adding a backend route inside a `client`-scoped branch.

## Technical approach

- **Charting library.** Recharts `ScatterChart` (already listed as a suggested stack option, and the
  lightest option that covers a scatter plot with tooltips and click handlers). If a spike shows
  Recharts cannot handle the point count at acceptable frame rates, document the finding in the spec
  before switching to Plotly or a canvas renderer — do not swap silently.
- **Two visual encodings, one chart.** Points come from `GET /clusters/map` (one point per item,
  positioned by `x`/`y`, coloured by `cluster_id`). Cluster _volume_ is conveyed by a per-cluster
  centroid bubble sized by `item_count`, overlaid on the point cloud. Noise points
  (`cluster_id === null`) render in a muted neutral grey and are excluded from the legend.
- **Point budget.** Above `MAX_PLOT_POINTS` (start at 5000), downsample the point cloud for
  rendering while keeping every centroid bubble accurate. Show an explicit "showing N of M points"
  note — never silently drop data without telling the user.
- **State.** A `DatasetContext` in `client/src/store/` holds the selected dataset, the current run,
  the fetched map, the selected cluster, and the active filters. Components read it via a hook. Do
  not thread props five levels deep, and do not add Redux.
- **Colour.** Use a categorical palette that stays distinguishable at ~12 clusters and remains
  readable for common colour-vision deficiencies; when cluster count exceeds the palette, cycle the
  palette and rely on the legend plus selection highlight to disambiguate. Never encode meaning in
  colour alone — the legend and tooltip always carry the label text.
- **Design.** Consult the `frontend-design` skill before styling. This is the product's hero screen;
  templated-default styling undersells it.
- **Accessibility.** The chart is not the only affordance: a keyboard-navigable cluster list
  (ordered by volume, always visible or in a disclosure panel) allows selecting clusters without
  the chart. **Interaction model:**
  - List is focusable via Tab; arrow keys (↑/↓) navigate between clusters.
  - Entering a cluster (Space/Enter on a list item, or clicking a point/centroid on the chart)
    selects it and opens the detail panel.
  - Selection state is synchronized bidirectionally: clicking the chart updates the list highlight,
    and navigating the list updates the chart's visual focus.
  - Noise points (unclustered) are included in the list if present.

## Acceptance criteria

1. Selecting a dataset renders a scatter plot with one point per feedback item, positioned by the
   API's `x`/`y` and coloured by cluster.
2. Cluster centroid bubbles are sized proportional to `item_count`, so a dominant theme is visually
   obvious without reading numbers.
3. Noise points (`cluster_id === null`) are visually de-emphasised, excluded from the legend, and
   labelled "Unclustered" in tooltips.
4. Hovering a point shows a tooltip with the cluster label and a truncated excerpt of the feedback
   text.
5. Clicking a point or a centroid — or selecting from the cluster list — opens the detail panel
   with the cluster's label, summary, all representative quotes, and a paginated list of its
   feedback items from `GET /clusters/{id}/items`.
6. The cluster list is keyboard-navigable via Tab + arrow keys (↑/↓ to move, Space/Enter to select).
   Selection is synchronized in both directions: list selection updates the chart focus, and chart
   clicks update the list highlight. Visual focus indicator is always visible (no hidden outline).
7. Filtering by `source` and by date range updates both the chart and the detail panel.
8. Datasets above `MAX_PLOT_POINTS` downsample the rendered cloud and display "showing N of M
   points". Centroid sizes stay accurate to the full dataset.
9. Every async surface has a distinct loading skeleton, an empty state ("no clusters yet — run
   clustering"), and an error state with a retry action. A failed fetch never renders a blank page.
10. A dataset that has been ingested but not clustered shows a clear, actionable empty state rather
    than an error.
11. **All API calls go through `client/src/api/`. That directory is not hand-edited** — `git diff`
    on it shows only `pnpm generate:api` output.
12. `pnpm --filter client build` passes (this runs `tsc -b`); no `any` in new component props.
13. Renders correctly at 1280px and 1920px widths.

## Test plan

- Component tests for: cluster selection updating the detail panel; noise points excluded from the
  legend; downsampling notice appearing above the threshold; empty/error/loading states.
- Type check via `pnpm --filter client build`.
- Manual, against a real ~2000-row dataset run through IM-1→IM-4: verify the largest bubble really
  is the largest cluster, that clicking through to quotes works, and that filters recompute.
- Manual perf: 5000 points — pan/hover stays responsive. Record the observed behaviour in the PR.
- Screenshot of the finished dashboard attached to the PR.

## Definition of done

Spec signed off → implemented → `pnpm --filter client build` green → component tests green →
screenshot in the PR → squash-merged.
