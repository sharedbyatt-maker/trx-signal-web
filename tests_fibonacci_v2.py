from pathlib import Path
s = Path("static/js/draw.js").read_text(encoding="utf-8")
assert "FIB_EXT_LEVELS = [1.272, 1.414, 1.618, 2.0]" in s
assert "normalizeFibLevels" in s and "activeFibLevels" in s and "fibPrice" in s
assert "fibReverse" in s and "fibLabelSide" in s and "fibFill" in s and "fibExtendRight" in s
assert 'id="fib-v2-panel"' in s
assert '"FIB ⚙"' in s
assert 'CUSTOM LEVELS' in s and '+ ADD' in s
assert 'REVERSE ✓' in s and 'LABEL ${d.fibLabelSide' in s and 'EXT RIGHT ✓' in s
assert 'localStorage.setItem(STORE_KEY' in s
# Phase 1 safety contracts remain present.
for token in ["handleHit", "nearestOHLC", "toggleLock", "duplicateSelected", "setPointerCapture"]:
    assert token in s, token
print("FIBONACCI V2 TESTS: ALL PASSED")
