"""On-demand, resumable TronGrid backfill. No writes to the provider."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from feed_utils import next_issue_number, source_time_utc


def seed_rows(history, parse_history, limit):
    if not isinstance(history, list) or not 100 <= len(history) <= limit:
        raise ValueError('Choose a chart history export with at least 100 rounds.')
    if any(
        not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str)
        or len(row[0]) != 17 or not row[0].isascii() or not row[0].isdigit()
        or type(row[1]) is not int or not 0 <= row[1] <= 9 or not isinstance(row[2], str)
        or len(row[2]) > 40
        for row in history
    ):
        raise ValueError('Chart history contains an invalid round.')
    rows = parse_history([{'issue': issue, 'number': digit, 'time': stamp} for issue, digit, stamp in history])
    if len(rows) != len(history):
        raise ValueError('Chart history contains duplicate rounds.')
    previous = None
    for row in rows[-3:]:
        stamp = source_time_utc(row['block_time'])
        if stamp is None or stamp.second != 54 or stamp.microsecond:
            raise ValueError('The final chart rounds do not have exact :54 timestamps.')
        expected = stamp.strftime('%Y%m%d') + '10301' + f'{stamp.hour * 60 + stamp.minute + 1:04d}'
        if row['issue'] != expected or (previous and next_issue_number(previous) != row['issue']):
            raise ValueError('The final chart rounds do not match the TRX issue calendar.')
        previous = row['issue']
    return rows


def extend_rows(rows, response, parse_history):
    additions = [row for row in parse_history(response.json()) if row['issue'] > rows[-1]['issue']]
    previous = rows[-1]['issue']
    for row in additions:
        if next_issue_number(previous) != row['issue']:
            raise ValueError('TronGrid returned a gap after round ' + previous + '.')
        previous = row['issue']
    return additions


def write_snapshot(path, rows):
    path = Path(path)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            json.dump([[r['issue'], r['number'], r['block_time']] for r in rows], output, separators=(',', ':'))
            output.flush()
            os.fsync(output.fileno())
            output.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def read_snapshot(path, parse_history, limit):
    with Path(path).open(encoding='utf-8') as source:
        return seed_rows(json.load(source), parse_history, limit)
