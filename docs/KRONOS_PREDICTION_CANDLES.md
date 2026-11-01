# Kronos prediction candles

New inference snapshots preserve the pinned model's `open`, `high`, `low` and
`close` outputs in an optional `forecast_ohlc` array. Close forecasts, delta
anchors, existing snapshot identity and close-based reports remain compatible.
The backtest's `predict_bars` API still returns the original close series.
On the next publisher run, a legacy latest 5m snapshot requests one fresh OHLC
inference even if the normal hourly refresh is not yet due. The legacy file
itself remains unchanged; after the new snapshot exists the hourly rule resumes.

The Kronos chart defaults to **Candles · OHLC**, with **Line · Close** as an
alternative. Prediction candles have a translucent body, purple border and
purple wick; observed candles retain their green/red appearance. Each target
uses its existing UTC candle-start timestamp. Inspection shows the target time
range and the four model values in the current viewer's relative walk scale.
The candle's close refers to the end of that interval. Wicks are predicted
high/low values, not a confidence interval or an intrabar path.

The viewer rebases all four model values using the frozen `origin_close` and
the same reconstructed origin anchor used by the close line. It validates
finite bounds, horizon length, high/low ordering and consistency with the
recorded close/delta values. It never derives wicks from closes, normalizes
invalid high/low values, copies future actual candles or edits a forecast.

Old snapshots without OHLC retain their close line with an explicit notice.
Each genuine model candle is checked independently. Valid candles are drawn;
an invalid target has a whitespace time slot, with a visible valid/total count
and omission notice. Its raw values remain unchanged in the snapshot. All
close predictions remain available using Line. If none of the OHLC candles
are valid, the viewer falls back to the complete close line. Display style does
not change target eligibility or close MAE.

Forecast visibility, archived/imported snapshots, refresh, replay, unavailable
states and timeframe request isolation apply to both projection series. There
are no changes to the main chart, source API, L1, 12-step, admin or order paths.
