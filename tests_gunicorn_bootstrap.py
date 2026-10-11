"""Exercise the real WSGI worker lifecycle without upstream or Telegram calls."""
import os
import json
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import time

import pytest
import requests


@pytest.mark.parametrize('preload', [False, True])
def test_worker_starts_engines_and_recovers_after_crash(tmp_path, preload):
    repo = Path(__file__).resolve().parent
    fixture = tmp_path / 'worker_fixture.py'
    fixture.write_text('''import threading, time
import app
assert app.core._engine_thread is None
assert app.core._tg_thread is None
wait = threading.Event()
def engine():
    with app.core.LOCK:
        app.core.STATE.update(connected=True, last_result_received_mono=time.monotonic())
    wait.wait()
app.core.engine_loop = engine
app.core._tg_worker = wait.wait
application = app.app
@application.get('/__fixture_settings')
def fixture_settings():
    return {'timeframe': app.admin_store.cached['settings']['timeframe'],
            'market': app.admin_store.control('telegram')['settings']['engines']['market']}
''')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'PYTHONPATH': str(repo), 'PYTHONUNBUFFERED': '1',
           'ADMIN_DB_PATH': str(tmp_path / 'admin.sqlite3')}
    env.pop('GUNICORN_CMD_ARGS', None)
    command = [sys.executable, '-m', 'gunicorn', '--config', str(repo / 'gunicorn.conf.py'),
               '--bind', f'127.0.0.1:{port}', '--graceful-timeout', '2']
    if preload:
        command.append('--preload')
    command.append('worker_fixture:application')
    log_path = tmp_path / 'gunicorn.log'
    with log_path.open('w') as log:
        server = subprocess.Popen(command, cwd=tmp_path, env=env, stdout=log,
                                  stderr=log, start_new_session=True)
        try:
            def ready(expected_boots):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    boots = re.findall(r'Booting worker with pid: (\d+)', log_path.read_text())
                    try:
                        health = requests.get(f'http://127.0.0.1:{port}/api/health', timeout=1).json()
                        if (len(boots) == expected_boots and health['engine']['thread_alive']
                                and health['queues']['telegram_worker_alive']):
                            return boots
                    except (requests.RequestException, ValueError):
                        pass
                    if server.poll() is not None:
                        pytest.fail(log_path.read_text())
                    time.sleep(.05)
                pytest.fail(log_path.read_text())
            boots = ready(1)
            assert requests.head(f'http://127.0.0.1:{port}/', timeout=2).status_code == 200
            assert requests.get(f'http://127.0.0.1:{port}/', timeout=2).status_code == 200
            # Persist a settings/control change after the master was imported.
            # A restarted preloaded worker must not restore stale master caches.
            db = sqlite3.connect(tmp_path / 'admin.sqlite3')
            try:
                with db:
                    value = json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])
                    value['timeframe'] = 5
                    db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(value),))
                    value = json.loads(db.execute("SELECT value FROM controls WHERE name='telegram'").fetchone()[0])
                    value['engines']['market'] = False
                    db.execute("UPDATE controls SET value=? WHERE name='telegram'", (json.dumps(value),))
            finally:
                db.close()
            os.kill(int(boots[0]), signal.SIGKILL)
            replacement = ready(2)
            assert replacement[0] != replacement[1]
            assert requests.get(f'http://127.0.0.1:{port}/', timeout=2).status_code == 200
            assert requests.get(f'http://127.0.0.1:{port}/__fixture_settings', timeout=2).json() == {
                'timeframe': 5, 'market': False}
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=3)
