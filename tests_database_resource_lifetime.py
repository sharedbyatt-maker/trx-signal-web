"""Native SQLite resources must not depend on delayed Python garbage collection."""
import gc
import sqlite3
import io

import pytest

from admin_dashboard import AdminStore
from engine_checkpoint import EngineCheckpoint


@pytest.mark.parametrize('store_type', [AdminStore, EngineCheckpoint])
def test_connections_close_after_commit_and_rollback(tmp_path, store_type):
    store = store_type(tmp_path / 'db.sqlite3')
    with store.connect() as successful:
        successful.execute('CREATE TABLE lifetime(value INTEGER)')
        successful.execute('INSERT INTO lifetime VALUES(1)')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        successful.execute('SELECT 1')
    with pytest.raises(RuntimeError, match='rollback fixture'):
        with store.connect() as failed:
            failed.execute('INSERT INTO lifetime VALUES(2)')
            raise RuntimeError('rollback fixture')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        failed.execute('SELECT 1')
    with store.connect() as db:
        assert db.execute('SELECT value FROM lifetime').fetchall() == [(1,)]


def test_continuous_feed_settings_reads_release_resources_without_gc(tmp_path, monkeypatch):
    store = AdminStore(tmp_path / 'admin.sqlite3')
    native_connect = sqlite3.connect
    connections = []

    def track(*args, **kwargs):
        db = native_connect(*args, **kwargs)
        connections.append(db)
        return db

    monkeypatch.setattr(sqlite3, 'connect', track)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(1000):
            assert store.private_get('feed_config') == {'revision': 0, 'value': None}
        assert len(connections) == 1000
        for db in connections:
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                db.execute('SELECT 1')
    finally:
        if was_enabled:
            gc.enable()


def test_resource_diagnostics_parse_linux_units_and_handle_missing_proc(monkeypatch):
    import app
    monkeypatch.setattr('builtins.open', lambda *a, **k: io.StringIO('VmRSS:\t102400 kB\nVmHWM:\t153600 kB\n'))
    monkeypatch.setattr(app.os, 'listdir', lambda *a: ['1', '2', '3'])
    assert app._process_resources() == {'rss_mb': 100.0, 'peak_rss_mb': 150.0, 'open_fds': 3}

    def unavailable(*a, **k):
        raise OSError('proc unavailable')

    monkeypatch.setattr('builtins.open', unavailable)
    assert app._process_resources() == {'rss_mb': None, 'peak_rss_mb': None, 'open_fds': None}
