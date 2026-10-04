# Chart practice tools

These tools change manual chart interaction only. L1 and 12-Step signal engines, RSI rules, staking and settlement remain unchanged. This is a BIG/SMALL cumulative walk, not the TRX coin price.

## Drawing edits

Open the drawing toolbar with the palette button. Undo/Redo supports creation, endpoint/object moves, appearance changes, lock/hide, deletion, duplication, clear and validated import. Use Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y. The current browser session keeps up to 100 edits; reload starts a new history. An incoming server merge/restore starts a new history to avoid undoing another device's data. Timeframe changes do not create history entries.

DRAWINGS lists all objects, including hidden ones, with select/show/hide/lock/delete actions. Delete can be undone. Save selected preset stores its appearance locally; select a preset and draw the same tool to reuse it. Twenty local presets are supported.

## Fibonacci modes

Choose the new-drawing FIB MODE or change a selected object's mode in FIB settings:

- **တက်လှိုင်း ပြန်ကျမှု**: 0 at the higher anchor, 1 at the lower anchor.
- **ကျလှိုင်း ပြန်တက်မှု**: 0 at the lower anchor, 1 at the higher anchor.
- **Manual / Reverse**: retain direct control of the anchor direction.

Automatic modes work with either anchor order and reorient after endpoint edits. This sets the measurement direction; it does not find a valid swing or predict the next result. Existing drawings remain in manual mode.

## Replay

Open PRACTICE and select Start replay. The loaded history is frozen for that session. Choose a source-time candle, use Previous/Next candle or Play/Pause, and choose playback speed. Next advances to the next candle's final available source row for the selected timeframe. A timeframe change can show a partial historical candle at the existing cutoff; the source issue stays fixed until stepping/seeking.

The replay chart, its indicators, automatic structure and markers are calculated only from the visible history prefix. Live signal markers are excluded. Engine cards and Market Context remain LIVE and are clearly identified in the replay banner; they are not historical replay signals.

Live drawings are held aside. Replay drawings are temporary and never autosave to local/server drawings. Sync/import/backup restore controls are disabled during replay. Return to live restores the live drawings and latest received chart data. Reload also returns to live. Playback pauses when the page is hidden. Replay has only the currently loaded history, not an unlimited historical archive.

## Observation journal

Open Observation journal. Enter a note and your hypothesis for the **next one-minute result** (BIG/SMALL), then Record before next result. The source issue, chart level, timeframe, mode, note and hypothesis are locked once recorded. Results become visible only when the next consecutive issue is available. Missing next rounds are reported rather than silently scoring a later result.

Replay observations are practice. Imported observations are marked imported. Neither contributes to the live observation summary. Live results are observations, not executed trades or evidence of an edge. Archiving changes visibility and is recoverable; it does not remove a result from the live summary. Export/import provides a portable JSON backup; imports are validated and merged by ID without replacing existing entries.

The journal is local to this browser, limited to 500 entries, and has no cloud journal sync. Browser storage may be cleared. Export important observations. Drawing server durability remains dependent on the hosting storage configuration.
