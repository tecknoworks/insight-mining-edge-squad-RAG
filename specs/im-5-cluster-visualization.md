# Feature: IM-5 — Cluster visualization component

## Goal

Deliver an interactive cluster map dashboard that visualizes every feedback item as a point positioned by its 2D coordinates, colored by cluster, with cluster volume legible at a glance. Selecting a cluster opens a detail panel showing Claude's label, summary, representative quotes, and the underlying feedback items. This realizes the "patterns visible at a glance" promise from the README by combining the cluster map from IM-3 and labels from IM-4.

## Acceptance Criteria

1. Selecting a dataset renders a scatter plot with one point per feedback item, positioned by the API's `x`/`y` coordinates and colored by cluster.
2. Cluster centroid bubbles are sized proportional to `item_count`, so a dominant theme is visually obvious without reading numbers.
3. Noise points (`cluster_id === null`) are visually de-emphasized, excluded from the legend, and labeled "Unclustered" in tooltips.
4. Hovering a point shows a tooltip with the cluster label and a truncated excerpt of the feedback text.
5. Clicking a point or centroid — or selecting from the cluster list — opens the detail panel with the cluster's label, summary, all representative quotes, and a paginated list of its feedback items.
6. The cluster list is keyboard-navigable via Tab + arrow keys (↑/↓ to move, Space/Enter to select). Selection is synchronized in both directions: list selection updates the chart focus, and chart clicks update the list highlight. Visual focus indicator is always visible.
7. Filtering by `source` and by date range updates both the chart and the detail panel.
8. Datasets above `MAX_PLOT_POINTS` (start at 5000) downsample the rendered cloud and display "showing N of M points". Centroid sizes remain accurate to the full dataset.
9. Every async surface has a distinct loading skeleton, an empty state, and an error state with a retry action. A failed fetch never renders a blank page.
10. A dataset that has been ingested but not clustered shows a clear, actionable empty state rather than an error.
11. All API calls go through `client/src/api/` (generated, never hand-edited).
12. `pnpm --filter client build` passes with no `any` in new component props.
13. Renders correctly at 1280px and 1920px widths.

## Technical Approach

### Chart Library

- Use **Recharts `ScatterChart`** — the lightest option that covers a scatter plot with tooltips and click handlers.
- If a spike shows Recharts cannot handle the point count at acceptable frame rates, document the finding in the spec before switching to Plotly or a canvas renderer (do not swap silently).

### Visual Encoding

- **Points** come from `GET /clusters/map` — one point per item, positioned by `x`/`y`, colored by `cluster_id`.
- **Cluster volume** is conveyed by per-cluster centroid bubbles sized by `item_count`, overlaid on the point cloud.
- **Noise points** (`cluster_id === null`) render in muted neutral grey and are excluded from the legend.

### Point Budget & Downsampling

- Above `MAX_PLOT_POINTS` (start at 5000), downsample the point cloud for rendering while keeping every centroid bubble accurate.
- Show an explicit "showing N of M points" note — never silently drop data without telling the user.

### State Management

- A `DatasetContext` in `client/src/store/` holds the selected dataset, current run, fetched map, selected cluster, and active filters.
- Components read it via a hook. Do not thread props five levels deep; do not add Redux.

### Styling & Accessibility

- Use a **categorical palette** that stays distinguishable at ~12 clusters and remains readable for common color-vision deficiencies.
- When cluster count exceeds the palette, cycle the palette and rely on the legend plus selection highlight to disambiguate.
- Never encode meaning in color alone — the legend and tooltip always carry the label text.
- Consult the `frontend-design` skill before styling; this is the product's hero screen.
- The chart is not the only affordance: a keyboard-navigable cluster list (ordered by volume, always visible or in a disclosure panel) allows selecting clusters without the chart.

### Interaction Model

- List is focusable via Tab; arrow keys (↑/↓) navigate between clusters.
- Entering a cluster (Space/Enter on a list item, or clicking a point/centroid on the chart) selects it and opens the detail panel.
- Selection state is synchronized bidirectionally: clicking the chart updates the list highlight, and navigating the list updates the chart's visual focus.
- Noise points (unclustered) are included in the list if present.

## Edge Cases / Constraints

- **Empty dataset**: If a dataset has been ingested but not yet clustered, show "no clusters yet — run clustering" rather than an error.
- **Very large point clouds** (above `MAX_PLOT_POINTS`): Downsampling must preserve centroid accuracy; the "showing N of M" note must be visible and clear.
- **High cluster count** (exceeds categorical palette): Cycle colors and rely on legend + selection highlight; never silently reuse colors without disambiguation.
- **Dataset selection**: Users select from an existing dataset dropdown fed by `GET /ingestion/datasets` (CSV upload UI is out of scope for this ticket).
- **Out of scope**: The chat panel (IM-6), CSV upload UI, and any changes to backend endpoints. If the map needs data IM-3 does not expose, raise it rather than adding a route inside this branch.

## Files to Modify / Create

### Create

- `client/src/pages/DashboardPage.tsx` — main dashboard page component
- `client/src/components/ClusterMap.tsx` — Recharts ScatterChart wrapper with tooltip, click handling, and downsampling logic
- `client/src/components/ClusterList.tsx` — keyboard-navigable cluster list sidebar
- `client/src/components/ClusterDetail.tsx` — detail panel showing label, summary, quotes, paginated items
- `client/src/components/FilterBar.tsx` — source and date-range filter controls
- `client/src/components/LoadingStates.ts` — loading skeletons for map, detail, list
- `client/src/components/EmptyStates.ts` — empty states for no datasets, not clustered, no clusters
- `client/src/components/ErrorStates.ts` — error boundaries with retry logic
- `client/src/store/DatasetContext.tsx` — React Context + hooks for dataset/map/filter state

### Modify

- `client/src/App.tsx` — wire up DashboardPage as the main view (HomePage is a scaffold)
- `client/src/index.css` or design tokens — add categorical color palette for clusters, focus indicators
- (No backend changes needed — use existing IM-3 and IM-4 endpoints)

## Test Plan

### Component Tests

- Cluster selection updates the detail panel with correct label, summary, and quotes.
- Noise points are excluded from the legend.
- Downsampling notice appears and disappears above/below `MAX_PLOT_POINTS`.
- Empty/error/loading states render with correct messaging and retry affordances.
- Keyboard navigation: Tab focuses list, arrow keys move focus, Space/Enter selects and opens detail.
- Selection sync: clicking a point highlights the corresponding list item; navigating the list highlights the chart point/centroid.

### Type Checking

- `pnpm --filter client build` passes (this runs `tsc -b`).
- No `any` in new component props or state.

### Manual Testing

- Against a real ~2000-row dataset run through IM-1→IM-4:
  - Verify the largest bubble really is the largest cluster.
  - Click through to quotes and verify they match `GET /clusters/{id}/items`.
  - Apply source and date-range filters; verify both the chart and detail panel recompute.
  - Test at 1280px and 1920px widths; verify layout is readable at both.
- Performance: 5000 points — pan/hover stays responsive. Record observed behavior in PR.

### Artifacts

- Screenshot of the finished dashboard attached to the PR.

## Definition of Done

1. Spec signed off.
2. Implementation complete.
3. `pnpm --filter client build` green.
4. Component tests green.
5. Screenshot in the PR.
6. Squash-merged.
