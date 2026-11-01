#!/usr/bin/env python3
"""Offline Kronos forecast generator for TRX/Round BIG/SMALL research.

Use separately from Render; does not place trades or alter production services.
Install official Kronos repository and CPU PyTorch locally. Model is out-of-domain.
"""
import argparse
import json
import math
import hashlib
import time
from zoneinfo import ZoneInfo
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


def walk_bars(rows, tf, *, require_contiguous=False, lookback=256):
    """Match frontend base=100 and BIG +1 / SMALL -1; aggregate by time bucket."""
    if tf not in (1, 5, 15, 60):
        raise ValueError("Unsupported timeframe")
    parsed = {}
    for entry in rows:
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        issue, number, raw_time = map(str, entry[:3])
        if not issue.isdigit():
            continue
        try:
            if not number.isdigit():
                continue
            digit = int(number)
            when = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if when.tzinfo is not None:
                when = when.astimezone(ZoneInfo("Asia/Yangon")).replace(tzinfo=None)
        except ValueError:
            continue
        if not 0 <= digit <= 9:
            continue
        if issue in parsed and parsed[issue] != (when, digit):
            raise ValueError("Conflicting duplicate round")
        parsed[issue] = (when, digit)
    ordered = sorted(parsed.items(), key=lambda row: int(row[0]))[-10000:]  # match the public chart history window exactly
    if len(ordered) < 128:
        raise ValueError("At least 128 valid rounds required")
    if any(a[1][0] >= b[1][0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Round timestamps must increase with issue")
    if require_contiguous:
        # A synthetic walk cannot reconstruct a missing round. Do not pass
        # compressed/gapped source history to the model as a regular series.
        recent = ordered[-(lookback+1)*tf:]
        minutes = [when.replace(second=0, microsecond=0) for _, (when, _) in recent]
        if any(b-a != timedelta(minutes=1) for a,b in zip(minutes, minutes[1:])):
            raise ValueError("Source history has a missing or duplicate minute in the inference window")
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


def load_predictor(args):
    # Heavy dependencies imported only for real inference, not validation.
    import numpy as np
    import pandas as pd
    import torch
    if args.kronos_dir:
        sys.path.insert(0, str(Path(args.kronos_dir).resolve()))
    from model import Kronos, KronosTokenizer, KronosPredictor

    model_slug = "Kronos-mini" if args.model == "mini" else "Kronos-small"
    tokenizer_slug = "Kronos-Tokenizer-2k" if args.model == "mini" else "Kronos-Tokenizer-base"
    print(f"Loading genuine {model_slug} and tokenizer on CPU; first use downloads model weights.")
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/" + tokenizer_slug, revision=args.tokenizer_revision)
    model = Kronos.from_pretrained("NeoQuasar/" + model_slug, revision=args.model_revision)
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512 if args.model == "small" else 2048)
    return predictor


def predict_bars(predictor, bars, timeframe, horizon=12, lookback=256):
    import numpy as np
    import pandas as pd
    import torch
    torch.manual_seed(0)
    np.random.seed(0)
    lookback = min(lookback, len(bars))
    selected = bars[-lookback:]
    df = pd.DataFrame([{k: b[k] for k in ("open", "high", "low", "close")} for b in selected])
    x_timestamp = pd.Series(pd.to_datetime([b["time"] for b in selected]))
    y_timestamp = pd.Series(pd.to_datetime([bars[-1]["time"] + timedelta(minutes=timeframe * i) for i in range(1, horizon + 1)]))
    prediction = predictor.predict(df=df, x_timestamp=x_timestamp, y_timestamp=y_timestamp,
                                   pred_len=horizon, T=1.0, top_p=0.9, sample_count=1,
                                   verbose=False)
    closes = [float(v) for v in prediction["close"].tolist()]
    if len(closes) != horizon or not all(math.isfinite(v) for v in closes):
        raise ValueError("Kronos produced invalid close values")
    return closes, lookback


def generate(args):
    import torch
    started = time.monotonic()
    raw = json.loads(Path(args.history_file).read_text())["history"] if args.history_file else get_history(args.history_url)
    bars, origin_issue = walk_bars(raw, args.timeframe, require_contiguous=True, lookback=args.lookback)
    predictor = load_predictor(args)
    closes, lookback = predict_bars(predictor, bars, args.timeframe, args.horizon, args.lookback)
    model_slug = "Kronos-mini" if args.model == "mini" else "Kronos-small"
    # Preserve the input anchor: viewer windows move, so absolute levels cannot be reused.
    origin_time = bars[-1]["time"].isoformat()
    input_hash = hashlib.sha256(json.dumps(raw, separators=(",", ":")).encode()).hexdigest()
    snapshot = {
        "schema": "kronos-round-snapshot-v1", "data_source": "big-small-walk",
        "model": model_slug, "timeframe_minutes": args.timeframe, "origin_issue": origin_issue,
        "forecast_close": [round(v, 4) for v in closes],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": 0, "torch_version": torch.__version__,
        "model_revision": args.model_revision, "tokenizer_revision": args.tokenizer_revision,
        "origin_bar_time_local": origin_time, "source_timezone": "Asia/Yangon",
        "origin_close": bars[-1]["close"], "input_sha256": input_hash,
        "forecast_delta": [round(v - bars[-1]["close"], 4) for v in closes],
        "inference_seconds": round(time.monotonic() - started, 3),
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
    ap.add_argument("--history-file", help="Frozen compact history JSON for isolated jobs")
    ap.add_argument("--history-url", help="https://your-existing-site/api/history?days=30")
    ap.add_argument("--kronos-dir", required=True, help="Directory of cloned shiyu-coder/Kronos repository")
    ap.add_argument("--output", default="static/data/kronos_latest.json")
    ap.add_argument("--model-revision", default=None)
    ap.add_argument("--tokenizer-revision", default=None)
    ap.add_argument("--model", choices=["mini", "small"], default="mini")
    ap.add_argument("--timeframe", type=int, choices=[1, 5, 15, 60], default=1)
    ap.add_argument("--horizon", type=int, default=12)
    ap.add_argument("--lookback", type=int, default=256)
    args = ap.parse_args()
    args.model_revision = args.model_revision or ("f4e68697d9d5aed55cef5c96aabc3376bcad9f81" if args.model == "mini" else "main")
    args.tokenizer_revision = args.tokenizer_revision or ("26966d0035065a0cae0ebad7af8ece35bc1fb51c" if args.model == "mini" else "main")
    if not 1 <= args.horizon <= 60 or not 64 <= args.lookback <= 512:
        ap.error("horizon must be 1..60; lookback must be 64..512")
    if not args.history_file and not args.history_url:
        ap.error("history-url or history-file is required")
    generate(args)


if __name__ == "__main__":
    main()
