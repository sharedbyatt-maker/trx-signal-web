#!/usr/bin/env python3
"""Offline Kronos forecast generator for TRX/Round BIG/SMALL research.

Use separately from Render; does not place trades or alter production services.
Install official Kronos repository and CPU PyTorch locally. Model is out-of-domain.
"""
import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def get_history(url):
    if not url.lower().startswith("https://") and not url.startswith("http://127.0.0.1"):
        raise ValueError("History URL must use HTTPS (localhost allowed)")
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "KronosRoundResearch/1.0"})
    with urlopen(req, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data.get("history"), list):
        raise ValueError("Expected /api/history compact history array")
    return data["history"]


def walk_bars(rows, tf):
    """Match frontend base=100 and BIG +1 / SMALL -1; aggregate by time bucket."""
    parsed = {}
    for entry in rows:
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        issue, number, raw_time = map(str, entry[:3])
        if not issue.isdigit():
            continue
        try:
            digit = int(number)
            when = datetime.strptime(raw_time[:16].replace("T", " "), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if not 0 <= digit <= 9:
            continue
        parsed[issue] = (when, digit)
    ordered = sorted(parsed.items(), key=lambda row: row[0])[-10000:]  # match the public chart history window exactly
    if len(ordered) < 128:
        raise ValueError("At least 128 valid rounds required")
    level = 100.0
    bars = []
    for issue, (when, number) in ordered:
        nxt = level + (1 if number >= 5 else -1)
        bucket_min = when.hour * 60 + when.minute
        bucket_min -= bucket_min % tf
        bucket = when.replace(hour=bucket_min // 60, minute=bucket_min % 60, second=0, microsecond=0)
        if bars and bars[-1]["time"] == bucket:
            bar = bars[-1]
            bar["high"] = max(bar["high"], nxt)
            bar["low"] = min(bar["low"], nxt)
            bar["close"] = nxt
        else:
            bars.append({"time": bucket, "open": level, "high": max(level, nxt),
                         "low": min(level, nxt), "close": nxt})
        level = nxt
    if len(bars) < 64:
        raise ValueError("Not enough OHLC bars for forecasting")
    return bars, ordered[-1][0]


def generate(args):
    # Heavy dependencies imported only for real inference, not validation.
    import numpy as np
    import pandas as pd
    if args.kronos_dir:
        sys.path.insert(0, str(Path(args.kronos_dir).resolve()))
    from model import Kronos, KronosTokenizer, KronosPredictor

    raw = get_history(args.history_url)
    bars, origin_issue = walk_bars(raw, args.timeframe)
    model_slug = "Kronos-mini" if args.model == "mini" else "Kronos-small"
    tokenizer_slug = "Kronos-Tokenizer-2k" if args.model == "mini" else "Kronos-Tokenizer-base"
    print(f"Loading genuine {model_slug} and tokenizer on CPU; first use downloads model weights.")
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/" + tokenizer_slug)
    model = Kronos.from_pretrained("NeoQuasar/" + model_slug)
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512 if args.model == "small" else 2048)
    lookback = min(args.lookback, len(bars))
    selected = bars[-lookback:]
    df = pd.DataFrame([{k: b[k] for k in ("open", "high", "low", "close")} for b in selected])
    x_timestamp = pd.Series(pd.to_datetime([b["time"] for b in selected]))
    y_timestamp = pd.Series(pd.to_datetime([bars[-1]["time"] + timedelta(minutes=args.timeframe * i) for i in range(1, args.horizon + 1)]))
    prediction = predictor.predict(df=df, x_timestamp=x_timestamp, y_timestamp=y_timestamp,
                                   pred_len=args.horizon, T=1.0, top_p=0.9, sample_count=1,
                                   verbose=False)
    closes = [float(v) for v in prediction["close"].tolist()]
    if len(closes) != args.horizon or not all(math.isfinite(v) for v in closes):
        raise ValueError("Kronos produced invalid close values")
    # The frontend does not certify the origin; verifies latest issue upon loading.
    snapshot = {
        "schema": "kronos-round-snapshot-v1", "data_source": "big-small-walk",
        "model": model_slug, "timeframe_minutes": args.timeframe, "origin_issue": origin_issue,
        "forecast_close": [round(v, 4) for v in closes],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "lookback_bars": lookback, "source": "official-kronos-inference-cpu",
        "research_only": True,
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"Real model inference saved to {target}; origin issue {origin_issue}.")
    print("This is experimental model output, NOT validated predictive performance.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-url", required=True, help="https://your-existing-site/api/history?days=30")
    ap.add_argument("--kronos-dir", required=True, help="Directory of cloned shiyu-coder/Kronos repository")
    ap.add_argument("--output", default="static/data/kronos_latest.json")
    ap.add_argument("--model", choices=["mini", "small"], default="mini")
    ap.add_argument("--timeframe", type=int, choices=[1, 5, 15, 60], default=1)
    ap.add_argument("--horizon", type=int, default=12)
    ap.add_argument("--lookback", type=int, default=256)
    args = ap.parse_args()
    if not 1 <= args.horizon <= 60 or not 64 <= args.lookback <= 512:
        ap.error("horizon must be 1..60; lookback must be 64..512")
    generate(args)


if __name__ == "__main__":
    main()
