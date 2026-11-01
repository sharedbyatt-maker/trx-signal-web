"""Bounded retrospective walk-forward research; never publishes live forecasts."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from forecast import get_history, load_predictor, predict_bars, walk_bars
from reports import SOURCE, build, evaluate, utc

HORIZONS = (1, 3, 6, 12)


def run(rows, infer, *, now=None, timeframe=5, max_origins=8, lookback=256):
    now = now or datetime.now(timezone.utc)
    if timeframe not in (1, 5, 15, 60) or not 1 <= max_origins <= 8:
        raise ValueError('Unsupported backtest bounds')
    # Reuse the strict conflict/timestamp validation, without reading forecasts.
    build(Path('.'), {'forecasts': []}, rows, {'points': []}, now)
    rows = sorted({str(row[0]): row for row in rows}.values(), key=lambda row: int(row[0]))[-10000:]
    origins = []
    for index in range(len(rows)-12*timeframe-1, lookback*timeframe-2, -1):
        when = utc(rows[index][2])
        local = when.astimezone(SOURCE)
        if local.minute % timeframe != timeframe-1:
            continue
        if origins and utc(rows[origins[-1]][2])-when < timedelta(minutes=13*timeframe):
            continue
        origins.append(index)
        if len(origins) == max_origins:
            break
    points, cutoffs = [], []
    for index in reversed(origins):
        # Only the prefix is given to both the adapter and model. Future rows
        # become visible solely to the evaluator after inference returns.
        prefix = rows[:index+1]
        bars, issue = walk_bars(prefix, timeframe)
        if len(bars) < lookback:
            continue
        selected = bars[-lookback:]
        if any(b['time']-a['time'] != timedelta(minutes=timeframe) for a,b in zip(selected, selected[1:])):
            continue
        context=[row for row in prefix if utc(row[2]) >= selected[0]['time'].replace(tzinfo=SOURCE).astimezone(timezone.utc)]
        if len(context) != lookback*timeframe or any(utc(b[2])-utc(a[2]) != timedelta(minutes=1) for a,b in zip(context,context[1:])):
            continue
        closes = infer(selected, timeframe)
        cutoff = utc(prefix[-1][2])+timedelta(seconds=1)
        snapshot = {'schema':'kronos-round-snapshot-v1','data_source':'big-small-walk',
                    'source':'official-kronos-inference-cpu','research_only':True,
                    'source_timezone':'Asia/Yangon','model':'Kronos-mini',
                    'timeframe_minutes':timeframe,'origin_issue':issue,
                    'origin_bar_time_local':bars[-1]['time'].isoformat(),
                    'lookback_bars':lookback,'generated_at_utc':now.isoformat(),
                    'forecast_delta':[round(value-bars[-1]['close'],4) for value in closes]}
        if len(closes) != 12:
            raise ValueError('Expected twelve genuine predicted closes')
        measured = evaluate(snapshot, rows, 'retrospective/'+issue, now, retrospective_as_of=cutoff)
        # Compare horizons on the same completely observed origin set.
        if {p['horizon'] for p in measured} != set(range(1,13)):
            continue
        points.extend(measured)
        cutoffs.append({'origin_issue':issue,'input_end_utc':utc(prefix[-1][2]).isoformat(),
                        'simulated_issue_utc':cutoff.isoformat(),
                        'last_target_end_utc':measured[-1]['target_end_utc']})
    horizons=[]
    for horizon in HORIZONS:
        selected=[p for p in points if p['horizon']==horizon]
        horizons.append({'horizon':horizon,'targets':len(selected),
                         **{key:sum(p[key] for p in selected) for key in ('error','persistence','random','majority')}})
    return {'schema':'kronos-walk-forward-v1','retrospective_only':True,
            'generated_at_utc':now.isoformat(),'timeframe':timeframe,'model':'Kronos-mini',
            'origins':cutoffs,'horizons':horizons,'lookback_bars':lookback,
            'model_revision':'f4e68697d9d5aed55cef5c96aabc3376bcad9f81',
            'note':'Retrospective inference from frozen prefixes; not predictions published before outcomes. Non-overlapping target windows; small, dependent samples do not establish predictive value.'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--history-url',required=True)
    parser.add_argument('--kronos-dir',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    rows=get_history(args.history_url)  # one frozen feed read for all origins
    model_args=SimpleNamespace(kronos_dir=args.kronos_dir,model='mini',
        model_revision='f4e68697d9d5aed55cef5c96aabc3376bcad9f81',
        tokenizer_revision='26966d0035065a0cae0ebad7af8ece35bc1fb51c')
    predictor=load_predictor(model_args)
    result=run(rows,lambda bars,tf:predict_bars(predictor,bars,tf,12,256)[0])
    from pipeline import write_json
    write_json(Path(args.output),result)


if __name__=='__main__':
    main()
