"""Isolated inference publication. Never imports the production application."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from forecast import get_history, walk_bars
from reports import build as build_reports


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def run(args, *, history_rows=None):
    root = Path(args.output)
    now = datetime.now(timezone.utc)
    status = {'attempt_at_utc': now.isoformat(), 'status': 'failed', 'timeframe': args.timeframe}
    try:
        rows = get_history(args.history_url) if history_rows is None else history_rows
        # Source timestamps are explicitly Asia/Yangon in the existing API.
        bars, origin_issue = walk_bars(rows, args.timeframe, require_contiguous=True)
        latest = max(datetime.fromisoformat(str(r[2]).replace('Z', '+00:00')).replace(tzinfo=ZoneInfo('Asia/Yangon'))
                     if datetime.fromisoformat(str(r[2]).replace('Z', '+00:00')).tzinfo is None
                     else datetime.fromisoformat(str(r[2]).replace('Z', '+00:00')) for r in rows)
        age = (now - latest.astimezone(timezone.utc)).total_seconds()
        if not -60 <= age <= 300:
            raise ValueError('Source feed is stale or future-dated; no inference published')
        manifest_path = root / 'index.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'schema': 'kronos-index-v1', 'forecasts': []}
        # Evaluate previously published predictions before generating new ones.
        ledger_path = root / 'evaluation_ledger.json'
        previous = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'points': []}
        ledger, report = build_reports(root, manifest, rows, previous, now)
        write_json(ledger_path, ledger)
        write_json(root / 'reports.json', report)
        existing = next((item for item in manifest['forecasts'] if item['origin_issue'] == origin_issue and item['timeframe'] == args.timeframe), None)
        if existing:
            status.update(status='ready', latest_file=existing['file'], duplicate_skipped=True)
            return
        # Freeze the read-only input for this run; no second network read mid-inference.
        input_path = root / 'input.json'
        write_json(input_path, {'history': rows})
        tmp = root / 'candidate.json'
        command = [sys.executable, str(Path(__file__).with_name('forecast.py')),
                   '--history-file', str(input_path), '--kronos-dir', args.kronos_dir,
                   '--timeframe', str(args.timeframe), '--lookback', '256', '--horizon', '12', '--output', str(tmp)]
        subprocess.run(command, check=True, timeout=900)
        snap = json.loads(tmp.read_text())
        snap['run_url'] = os.getenv('KRONOS_RUN_URL', '')
        snap['code_revision'] = os.getenv('GITHUB_SHA', '')
        digest = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]
        name = f"{snap['origin_issue']}-{args.timeframe}-{digest}.json"
        target = root / 'forecasts' / name
        if target.exists():
            raise ValueError('Forecast identity already exists')
        write_json(target, snap)
        entries = [{'file': 'forecasts/' + name, 'timeframe': args.timeframe,
                    'origin_issue': snap['origin_issue'], 'generated_at_utc': snap['generated_at_utc']}] + manifest['forecasts']
        # Faster 1m publications must not evict the slower 5m archive.
        counts = {}
        manifest['forecasts'] = []
        for entry in entries:
            tf = entry['timeframe']
            counts[tf] = counts.get(tf, 0) + 1
            if counts[tf] <= 720:
                manifest['forecasts'].append(entry)
        write_json(manifest_path, manifest)
        # Working-tree retention only. Git history preserves original forecast bytes.
        retained = {Path(item['file']).name for item in manifest['forecasts']}
        for old in (root / 'forecasts').glob('*.json'):
            if old.name not in retained:
                old.unlink()
        status.update(status='ready', latest_file='forecasts/' + name)
    except Exception as exc:
        status['reason'] = f'{type(exc).__name__}: {str(exc)[:300]}'
        raise
    finally:
        for name in ('input.json', 'candidate.json'):
            (root / name).unlink(missing_ok=True)
        write_json(root / 'status.json', status)
        write_json(root / f'status-{args.timeframe}m.json', status)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--history-url', required=True)
    parser.add_argument('--kronos-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--timeframe', type=int, choices=[1, 5, 15, 60], default=5)
    run(parser.parse_args())
