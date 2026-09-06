"""Shared final signal-decision policy for live engine and backtests.

This module is deliberately pure: given the score and guard inputs, it always
returns the same decision and never reads mutable application state.
"""


def decide_signal(score, trend_diff, last_move, mtf, trade_threshold=40, watch_threshold=22):
    """Return the final signal decision used by both live and backtest paths.

    Args:
        score: Combined confluence score.
        trend_diff: fast EMA minus slow EMA at decision time.
        last_move: +1 for BIG, -1 for SMALL for the latest known round.
        mtf: dict with x5/x15 trend signs (-1, 0, +1).
        trade_threshold: absolute score required for a trade.
        watch_threshold: absolute score required for watch zone.

    Returns a dict with:
        signal: BIG / SMALL / SKIP / SKIP (WATCH) / SKIP (REVERSAL GUARD)
        kind: trade / watch / skip / reversal_guard / mtf_guard
        want: +1 / -1 according to score direction
        mtf_ok: whether both MTF guards agree or are neutral
    """
    want = 1 if score > 0 else -1
    mtf = mtf or {"x5": 0, "x15": 0}
    x5 = mtf.get("x5", 0)
    x15 = mtf.get("x15", 0)
    mtf_ok = (x5 in (0, want)) and (x15 in (0, want))
    magnitude = abs(score)

    if magnitude >= trade_threshold:
        signal = "BIG" if score > 0 else "SMALL"
        if trend_diff * last_move < -0.004:
            return {
                "signal": "SKIP (REVERSAL GUARD)",
                "kind": "reversal_guard",
                "want": want,
                "mtf_ok": mtf_ok,
            }
        if not mtf_ok and magnitude < trade_threshold + 15:
            return {
                "signal": "SKIP (WATCH)",
                "kind": "mtf_guard",
                "want": want,
                "mtf_ok": False,
            }
        return {"signal": signal, "kind": "trade", "want": want, "mtf_ok": mtf_ok}

    if magnitude >= watch_threshold:
        return {"signal": "SKIP (WATCH)", "kind": "watch", "want": want, "mtf_ok": mtf_ok}

    return {"signal": "SKIP", "kind": "skip", "want": want, "mtf_ok": mtf_ok}
