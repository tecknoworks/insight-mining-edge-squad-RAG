# Implementation Checklist

Work through these in order when implementing a spec.

## Before writing code

- Locate the spec file under `/specs` that matches the requested feature.
- Confirm the spec is signed off — if it still reads as a draft or is missing sections, stop and flag it rather than guessing.
- Re-read "Acceptance Criteria", "Files to Modify", and "Test Plan" — these define done.

## While building

- Change only the files listed under "Files to Modify". If another file must change, surface it and get agreement before proceeding.
- Follow the module boundaries in CLAUDE.md: keep embedding/clustering logic out of route handlers, and keep Claude prompt logic in `app/insights/`.
- Build to the "Technical Approach" as written; do not introduce design decisions the spec did not make.
- Handle every item under "Edge Cases / Constraints".

## Before reporting done

- Verify each "Acceptance Criteria" item independently — it should be true, not just plausibly true.
- Run the "Test Plan" and report actual results (including any failures) rather than assuming.
- Note anything you deviated from or left out.
