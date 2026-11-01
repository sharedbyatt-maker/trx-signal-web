"""Causal, append-only target evaluations; retain 30 Bangkok calendar days.

No Flask imports or database writes. Original forecast files are never edited.
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

SOURCE = ZoneInfo('Asia/Yangon')
REPORT_TZ = ZoneInfo('Asia/Bangkok')


def utc(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (result.replace(tzinfo=SOURCE) if result.tzinfo is None else result).astimezone(timezone.utc)


def random_error(n, actual):
    mode = n // 2
    total, error, weight = 1., abs(2 * mode - n - actual), 1.
    for k in range(mode, n):
        weight *= (n-k)/(k+1)
        total += weight
        error += weight * abs(2*(k+1)-n-actual)
    weight = 1.
    for k in range(mode, 0, -1):
        weight *= k/(n-k+1)
        total += weight
        error += weight * abs(2*(k-1)-n-actual)
    return error / total


def evaluate(snapshot, rows, file, now, *, retrospective_as_of=None):
    """Only fully observed, contiguous, post-generation target buckets qualify."""
    if snapshot.get('schema') != 'kronos-round-snapshot-v1' or snapshot.get('data_source') != 'big-small-walk' or snapshot.get('source') != 'official-kronos-inference-cpu':
        raise ValueError('Unsupported forecast provenance')
    tf = snapshot['timeframe_minutes']
    if tf not in (1,5,15,60) or snapshot.get('source_timezone') != 'Asia/Yangon':
        raise ValueError('Unsupported source/timeframe')
    generation = utc(snapshot['generated_at_utc'])
    if generation > now or snapshot.get('research_only') is not True:
        raise ValueError('Invalid generation metadata')
    origin = next((i for i,r in enumerate(rows) if str(r[0]) == snapshot['origin_issue']), None)
    if origin is None:
        return []
    origin_time = utc(rows[origin][2])
    local = origin_time.astimezone(SOURCE).replace(tzinfo=None)
    bucket = local.replace(minute=local.minute-local.minute%tf,second=0,microsecond=0)
    if snapshot.get('origin_bar_time_local') != bucket.isoformat():
        raise ValueError('Origin timestamp mismatch')
    if origin_time > generation:
        raise ValueError('Input origin is after publication')
    # Only the isolated historical backtest supplies a simulated cutoff. Its
    # results never enter the ledger of genuinely pre-published forecasts.
    if retrospective_as_of is not None:
        if not origin_time <= retrospective_as_of <= generation:
            raise ValueError('Invalid retrospective cutoff')
        generation = retrospective_as_of
    lookback = snapshot['lookback_bars'] * tf
    training = rows[max(0,origin-lookback+1):origin+1]
    majority = sum(1 if int(r[1])>=5 else -1 for r in training)
    majority = (majority>0)-(majority<0)
    # A missing minute makes the resulting cumulative walk unknowable. Stop
    # instead of scoring an incomplete actual path as a complete result.
    future = []
    previous_minute = int(origin_time.timestamp()//60)
    delta = 0
    final_end=(bucket+timedelta(minutes=tf*(len(snapshot['forecast_delta'])+1))).replace(tzinfo=SOURCE).astimezone(timezone.utc)
    for row in rows[origin+1:]:
        when = utc(row[2])
        if when >= final_end:
            break
        minute = int(when.timestamp()//60)
        if minute != previous_minute+1:
            break
        delta += 1 if int(row[1])>=5 else -1
        future.append((when,delta))
        previous_minute = minute
    output=[]
    for index,prediction in enumerate(snapshot['forecast_delta']):
        if not isinstance(prediction,(int,float)) or not math.isfinite(prediction):
            raise ValueError('Invalid projection')
        start=(bucket+timedelta(minutes=tf*(index+1))).replace(tzinfo=SOURCE).astimezone(timezone.utc)
        end=start+timedelta(minutes=tf)
        if start <= generation or end > now:
            continue
        observed=[p for p in future if p[0] < end]
        # Require every minute through the target's final source minute.
        if not observed or int(observed[-1][0].timestamp()//60) != int(end.timestamp()//60)-1:
            continue
        actual=observed[-1][1]
        n=len(observed)
        output.append({'id':f'{file}:{index}','forecast':file,'timeframe':tf,
                       'horizon':index+1,
                       'target_end_utc':end.isoformat(),'model':snapshot['model'],
                       'error':abs(prediction-actual),'persistence':abs(actual),
                       'random':random_error(n,actual),'majority':abs(majority*n-actual)})
    return output


def build(root, manifest, raw_rows, previous, now=None):
    now=now or datetime.now(timezone.utc)
    cutoff=(now.astimezone(REPORT_TZ)-timedelta(days=29)).date().isoformat()
    # Reject conflicting records and reverse timestamps without silently
    # replacing previously measured actuals.
    unique={}
    for row in raw_rows:
        issue=str(row[0]); digit=int(row[1]); when=utc(row[2])
        if not issue.isdigit() or not 0<=digit<=9:
            raise ValueError('Invalid round')
        if issue in unique and unique[issue] != row:
            raise ValueError('Conflicting round')
        unique[issue]=row
    rows=sorted(unique.values(),key=lambda r:int(r[0]))
    if any(utc(a[2])>=utc(b[2]) for a,b in zip(rows,rows[1:])):
        raise ValueError('Out-of-order source times')
    points={p['id']:p for p in previous.get('points',[]) if utc(p['target_end_utc']).astimezone(REPORT_TZ).date().isoformat()>=cutoff}
    unavailable=0
    import json
    for entry in manifest.get('forecasts',[]):
        file=entry['file']; path=PurePosixPath(file)
        if path.parent != PurePosixPath('forecasts') or path.suffix != '.json':
            unavailable+=1;continue
        try:
            snapshot=json.loads((root/file).read_text())
            for point in evaluate(snapshot,rows,file,now):
                if utc(point['target_end_utc']).astimezone(REPORT_TZ).date().isoformat()>=cutoff:
                    points.setdefault(point['id'],point)
        except (OSError,ValueError,KeyError,TypeError):
            unavailable+=1
    by_tf=defaultdict(list)
    for point in points.values():
        by_tf[point['timeframe']].append(point)
    retained=sorted((p for group in by_tf.values() for p in sorted(group,key=lambda p:(p['target_end_utc'],p['id']))[-20000:]),key=lambda p:(p['target_end_utc'],p['id']))
    daily=defaultdict(list)
    for point in retained:
        daily[(utc(point['target_end_utc']).astimezone(REPORT_TZ).date().isoformat(),point['timeframe'],point['model'])].append(point)
    days=[]
    for (day,tf,model), group in sorted(daily.items()):
        horizons=[]
        for horizon in (1,3,6,12):
            selected=[p for p in group if int(p['id'].rsplit(':',1)[1])+1 == horizon]
            if selected:
                horizons.append({'horizon':horizon,'targets':len(selected),
                                 'forecasts':sorted(set(p['forecast'] for p in selected)),
                                 **{key:sum(p[key] for p in selected) for key in ('error','persistence','random','majority')}})
        days.append({'day_local':day,'timeframe':tf,'model':model,'targets':len(group),
                     'horizons':horizons,
                     'forecasts':sorted(set(p['forecast'] for p in group)),
                     **{key:sum(p[key] for p in group) for key in ('error','persistence','random','majority')}})
    return {'schema':'kronos-evaluation-ledger-v1','points':retained}, {
        'schema':'kronos-daily-reports-v1','updated_at_utc':now.isoformat(),
        'calendar':'Asia/Bangkok','retention_days':30,'unavailable_forecasts':unavailable,
        'days':days,'note':'MAE in walk steps; overlapping targets are correlated. No next-round accuracy claim.'}
