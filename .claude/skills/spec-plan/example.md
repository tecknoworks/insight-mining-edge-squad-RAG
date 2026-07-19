# Feature: CSV Support

## Goal

Enable users to export their dashboard data as CSV so they can analyze it in their spreadsheet tool of choice.

## Acceptance Criteria

- Users can click "Export CSV" in the dashboard header
- The CSV includes all visible columns in the current view
- Date filters are applied to the exported data
- The download starts immediately with a browser-native download dialog
- File name format: "{dashboard-name}\_{YYYY-MM-DD}.csv"

## Technical Approach

- Add `exportCsv` utility function to `/lib/utils/csv.ts`
- Add "Export CSV" button to `DashboardHeader` component
- Wire up click handler to trigger download via API endpoint
- New API route: `POST /api/dashboard/export`

## Edge Cases / Constraints

- Empty dashboard: export should produce a header-only CSV
- Large datasets (>100K rows): show a warning before generating
- Special characters in data: must be properly escaped for CSV
- User must be authenticated to export

## Files to Modify

- `src/lib/utils/csv.ts` (create)
- `src/components/DashboardHeader.tsx` (modify)
- `src/app/api/dashboard/export/route.ts` (create)
- `src/lib/services/dashboard.ts` (modify)

## Test Plan

- Unit test: CSV generation with edge cases (empty, special chars)
- Integration test: full export flow with mocked API
- Manual test: verify download on Chrome, Safari, Firefox
