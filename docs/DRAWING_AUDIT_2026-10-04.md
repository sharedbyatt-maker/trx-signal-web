# Drawing tool stability audit — 2026-10-04

Scope: all six manual tools and their editing, appearance, local persistence and optional server-sync controls. No engine, indicator, market-feed, stake or settlement changes.

## Reproduced baseline defects

Baseline main: `3a064c8b05db0fbd2d93220f6674feaba5794822`.
Baseline browser run: `37175934172` (100 passed, 9 failed, 11 intentional viewport skips).

- Clicking extension/settings controls inside the chart went through the drawing capture handler, clearing the selected object before its button action. Reproduced on desktop and mobile.
- Fibonacci settings were defined but their panel was never built at initialization. Opening settings produced no panel on either viewport.
- Cancelling an object drag left modified geometry in memory. A subsequent style save persisted that cancelled change. Reproduced on both viewports.
- A move and release within one animation frame saved old geometry; the queued move then ran after the gesture was cleared. Reproduced on both viewports.
- The narrow-phone Fibonacci configuration path was unusable. Initialization and panel layout are corrected together; the panels now stack rather than overlap.

## Fixes

- Ignore chart overlay controls and links in drawing pointer handling.
- Build the Fibonacci panel, position it below the object toolbar and constrain it to a scrollable chart-height area; recompute on resize.
- Flush the release coordinate before committing edits and cancel pending animation callbacks.
- Capture original geometry for endpoint and whole-object drags; restore it on pointer cancellation.
- Keep the opacity slider mounted during its input gesture; persist changes without rebuilding its DOM.
- Reject empty custom-level input, cap Fibonacci levels at the same 64-level persistence limit and normalize nonfinite appearance values.
- Resolve supported blank future slots through logical chart coordinates and retain issue anchors for future points across data refreshes.
- Wait for active sync writes before local/server backup restoration and cancel pending autosaves before restoring.
- Reject null/boolean imported prices instead of coercing them into a valid zero price.
- Cache-bust the drawing script to version 46.

## Browser coverage

The additional drawing suite covers real mouse/touch placement of Trend, Ray, Horizontal Line, Vertical Line, Rectangle and Fibonacci; 1m/5m/15m changes and reload; width/style/color/extensions; lock/hide/show/duplicate/delete/undo; Fibonacci levels, reverse, label position, right extension, opacity and custom levels; narrow-phone panel geometry; drag release/cancellation; export/import/invalid files; magnet preference; sync conflicts, safe merge, local recovery, server backup restoration and expired authentication.

Existing chart, stability and engine regressions remain required release checks.

## Practical limits

- Undo removes the last created drawing (or cancels an unfinished placement); it is not a complete edit-history undo system.
- Local persistence depends on the browser allowing storage and keeping that browser's data. Export remains the portable backup.
- Server sync requires a configured token. Cross-device merge and backup paths are tested with isolated mock endpoints; no production server drawing records are overwritten for acceptance.
- Host-filesystem server backups require durable hosting storage to survive redeploys. This audit does not provision infrastructure.
