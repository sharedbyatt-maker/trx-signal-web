from pathlib import Path


def test_robust_forwarder_drains_without_telegram_send():
    src = Path("robust_integration.py").read_text(encoding="utf-8")
    start = src.index("    def _forward_robust_events(self):")
    end = src.index("\n    def tick(self):", start)
    block = src[start:end]
    assert "drain_notification_events()" in block
    assert "self.core.tg_notify" not in block
    assert "format_robust_telegram_event(event)" not in block


def test_legacy_telegram_sources_are_untouched():
    src = Path("app_core.py").read_text(encoding="utf-8")
    assert "PRE-SIGNAL RADAR" in src
    assert "TG_STREAK_ALERT_FROM = 8" in src
    assert "12-STEP SIGNAL" in src
    assert "format_strat_daily_telegram" in src
