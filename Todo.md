# To-Do List

## Priority: Review Workflow
- [x] **Pre-select duplicates**: Auto-select every item in a group except the suggested keep; leave groups with no suggested keep unselected; toolbar toggle to turn it off; show "N selected on this page".
- [x] **Page-scoped selection**: Select all / clear / pre-select affect only the current page, in results and in History.
- [x] **Click-to-select cards**: Whole card toggles selection with a clear selected state (border, tint, checkmark); inner buttons (play, show in folder, open) don't toggle; Space/Enter support; optional shift-click range.
- [x] **Moved items leave the list**: Remove moved items from the view immediately; recompute the group; hide groups left with one file and stop flagging the survivor as a duplicate; restoring from History brings the group back; update counts and pagination so pages don't end up half empty.
- [x] **History pagination**: Paginate the History view, with page-scoped select for large move histories (4k+ items).
- [x] **Directory in metadata**: Show the folder path as text on each card, middle-truncated with the full path on hover; highlight the part that differs from other files in the group (same image, different folder); keep Show in folder.
- [x] Tests: page-scoped select, groups with no suggested keep, moved-item group cleanup, restore, history paging.

## Scan Progress with Percent
- [x] Two stages: indeterminate discovery with a live "found N files" count, then a real percent once the total is known (no extra directory walk, per Phase 1 rule).
- [x] Count cached files as done immediately so mostly-cached rescans jump ahead; percent never goes backward; "preparing results" returns to indeterminate.
- [x] Show processed/total, percent, elapsed time, and rough time remaining (e.g. "1,240 / 4,012 · 31% · ~1m left") in `#scan-state`.
- [x] Use a page-flip book loader as `.page-loader`, colors driven by project variables (`--green`, `--gold`, `--muted`); remove `-webkit-` duplicates; static fallback under `prefers-reduced-motion`; stop on completion or failure.
- [x] Put the percent/count text in a separate throttled `aria-live="polite"` element, outside the animated parts.
- [x] Test with a ~4k-file scan, a cached-only rescan, and a failure mid-scan.

## Media controls and result tabs
- [x] Prioritize errors, then duplicate candidates, then remaining files in All media before pagination; label error/duplicate cards and preserve the selected sort within priorities.
- [x] Group filters and review settings under Images, Audio, and Videos; retain per-type filter choices.
- [x] Keep image/video similarity and blur thresholds independent; describe fixed audio matching rules.
- [x] Put Duplicates, All media, and Errors tabs beside Grid/List, including an error count.
- [x] Reveal results after each scan; open Errors when no duplicates were found but files failed, otherwise All media.
- [x] Ignore orientation and blur filters when browsing errors so missing metadata cannot hide failed files.

## Implementation Roadmap

Music similarity and deep comparison remain advisory; broader real-media calibration and public release source materials are still pending.

### Phase 3 — Similar Music Detection
- [ ] Calibrate thresholds on a broader real-music collection, including alternate recordings.

### Phase 5 — Deep Comparison for Edited Clips
- [ ] Expand real-video coverage for reordered scenes, unrelated videos sharing music, and difficult edits.

## Packaging and Release Decisions
- [ ] Prepare corresponding source and build materials for the exact bundled tools and their included libraries before public redistribution.

## Validation — 2026-09-29
- [ ] Identify the sender of the reported unexpected shutdown; existing terminal output does not identify it.
## Completed validation — 2026-11-19
- Review and progress regressions include a generated 4,000-file scan, cached-only and mixed rescans, discovery failure, processing interruption, 4,001-entry History paging, and move/restore group cleanup.
- UI tests cover page-scoped selection, keeper protection across overlapping groups, groups without suggestions, card keyboard controls, folder differences, pagination repair, and loader shutdown on failure.
- Validation: 47 Python tests and 17 Node UI tests passed. Browser verification used generated media and an isolated database.
