"""1m research every scheduled run; preserve hourly 5m inference and backtests."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from forecast import get_history
from pipeline import run as publish, write_json
from reports import utc


def due(timestamp, now):
    try:
        return (now-utc(timestamp)).total_seconds() >= 55*60
    except (ValueError, TypeError):
        return True


def run(args):
    root=Path(args.output)
    now=datetime.now(timezone.utc)
    errors=[]
    statuses={}
    def attempt(tf):
        try:
            rows=get_history(args.history_url)
            publish(SimpleNamespace(**vars(args),timeframe=tf),history_rows=rows)
        except Exception as exc:
            errors.append(f'{tf}m inference: {exc}')
            write_json(root/f'status-{tf}m.json',{'attempt_at_utc':datetime.now(timezone.utc).isoformat(),
                       'status':'failed','timeframe':tf,'reason':str(exc)[:300]})
        statuses[str(tf)]=json.loads((root/f'status-{tf}m.json').read_text())
    try:
        manifest=json.loads((root/'index.json').read_text()) if (root/'index.json').exists() else {'forecasts':[]}
        for tf in (1,5):
            path=root/f'status-{tf}m.json'
            if path.exists():statuses[str(tf)]=json.loads(path.read_text())
        recent=next((entry for entry in manifest['forecasts'] if entry['timeframe']==5),None)
        if not recent or due(recent['generated_at_utc'],now):
            attempt(5)
        # Retrospective samples refresh hourly per timeframe, rather than on
        # every five-minute publication. Existing 5m output keeps its identity.
        for tf,file in ((1,'backtest-1m.json'),(5,'backtest.json')):
            if errors:
                continue
            target=root/file
            previous=json.loads(target.read_text()) if target.exists() else {}
            if not due(previous.get('generated_at_utc'),now):
                continue
            try:
                subprocess.run([sys.executable,str(Path(__file__).with_name('backtest.py')),
                                '--history-url',args.history_url,'--kronos-dir',args.kronos_dir,
                                '--timeframe',str(tf),'--output',str(target)],check=True,timeout=600)
            except Exception as exc:
                errors.append(f'{tf}m retrospective: {exc}')
        # Freeze a fresh 1m input after slow hourly work, immediately before
        # publication. Backtests must not hold a newly generated 1m forecast.
        attempt(1)
    except Exception as exc:
        errors.append(str(exc))
        if not statuses:
            for tf in (1,5):
                statuses[str(tf)]={'attempt_at_utc':now.isoformat(),'status':'failed',
                                   'timeframe':tf,'reason':str(exc)[:300]}
                write_json(root/f'status-{tf}m.json',statuses[str(tf)])
    finally:
        status={'attempt_at_utc':now.isoformat(),'status':'failed' if errors else 'ready',
                'timeframes':statuses,'schedule_minutes':5,'reason':'; '.join(errors)[:500]}
        write_json(root/'status.json',status)
    if errors:
        raise RuntimeError('; '.join(errors))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--history-url',required=True)
    parser.add_argument('--kronos-dir',required=True)
    parser.add_argument('--output',required=True)
    run(parser.parse_args())
