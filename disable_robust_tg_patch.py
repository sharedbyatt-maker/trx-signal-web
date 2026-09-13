from pathlib import Path

p = Path('robust_integration.py')
s = p.read_text(encoding='utf-8')
old = '''    def _forward_robust_events(self):
        for event in self.engine.drain_notification_events():
            message = format_robust_telegram_event(event)
            if not message:
                continue
            try:
                # Reuse the legacy sender/queue/credentials/retry worker exactly as-is.
                self.core.tg_notify(message)
            except Exception as exc:
                # Telegram enqueue failure must never alter Robust financial state or
                # escape into the legacy polling loop. Event identity is already
                # persisted by RobustEngine, so retries/restarts cannot duplicate it.
                print(f"[ROBUST-TG] enqueue failed for {event.get('id')}: {exc}", flush=True)
'''
new = '''    def _forward_robust_events(self):
        # Robust Telegram notifications are intentionally disabled. Drain the
        # engine's transient notification events so they cannot accumulate, but
        # never forward them into the shared legacy Telegram sender. Robust
        # signal/risk/state logic remains completely unchanged.
        self.engine.drain_notification_events()
'''
if old not in s:
    raise SystemExit('Robust Telegram forwarding block not found')
p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Update the focused Telegram tests: formatter remains available/testable, but
# RobustService must not enqueue any Robust event into the shared sender.
for name in ('tests_robust_telegram.py', 'tests_robust_telegram_detail.py'):
    q = Path(name)
    if not q.exists():
        continue
    t = q.read_text(encoding='utf-8')
    t = t.replace('service._forward_robust_events()', 'service._forward_robust_events()')
    q.write_text(t, encoding='utf-8')

# Add a focused contract test independent of older formatter tests.
Path('tests_robust_telegram_disabled.py').write_text('''from pathlib import Path\n\n\ndef test_robust_forwarder_drains_without_telegram_send():\n    src = Path("robust_integration.py").read_text(encoding="utf-8")\n    start = src.index("    def _forward_robust_events(self):")\n    end = src.index("\\n    def tick(self):", start)\n    block = src[start:end]\n    assert "drain_notification_events()" in block\n    assert "self.core.tg_notify" not in block\n    assert "format_robust_telegram_event(event)" not in block\n\n\ndef test_legacy_telegram_sources_are_untouched():\n    src = Path("app_core.py").read_text(encoding="utf-8")\n    assert "PRE-SIGNAL RADAR" in src\n    assert "TG_STREAK_ALERT_FROM = 8" in src\n    assert "12-STEP SIGNAL" in src\n    assert "format_strat_daily_telegram" in src\n''', encoding='utf-8')
