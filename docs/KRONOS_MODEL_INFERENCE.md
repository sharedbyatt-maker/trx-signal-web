# Kronos BIG/SMALL real-model inference (experimental)
This is an actual inference adapter for the official `shiyu-coder/Kronos` model, NOT a predictive-accuracy guarantee. BIG/SMALL synthetic-walk candles are out-of-distribution for Kronos, and can behave randomly.

## Windows / CPU one-time setup
Python 3.10–3.12 recommended. From an ordinary terminal:
```powershell
git clone https://github.com/shiyu-coder/Kronos.git D:\\app\\Kronos
py -3.12 -m venv .venv-kronos
.venv-kronos\\Scripts\\python -m pip install --upgrade pip
.venv-kronos\\Scripts\\python -m pip install torch pandas numpy einops huggingface_hub safetensors tqdm
```
The first run needs internet to download free open weights from Hugging Face. With 8 GB RAM start with `--model mini`; small is optional.
```powershell
.venv-kronos\\Scripts\\python research/kronos/forecast.py --kronos-dir D:\\app\\Kronos --history-url "https://trx-signal-web.onrender.com/api/history?days=30" --model mini --timeframe 1 --horizon 12 --output static/data/kronos_latest.json
```
The website will automatically fetch `/static/data/kronos_latest.json` **when that file is included in a deployed commit**. Uploading local files does not change Render. Snapshot origin must exactly match the latest round in the viewer or it will be rejected as stale; snapshots become stale quickly. For realtime one-click predictions a running CPU service or scheduled compute/deploy pipeline is required. Do NOT put heavy PyTorch in the existing free Render web process.

## Safety and validation
The existing server and trade system are unchanged. This tool never places orders. Model output is not a backtested signal; compare predictions against held-out future results, majority, persistence and random baselines first. Do not claim accuracy or confidence until measured. Verify feed freshness and timestamp grouping before using forecasts.
