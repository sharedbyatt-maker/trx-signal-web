from pathlib import Path

draw = Path('static/js/draw.js').read_text(encoding='utf-8')
chart = Path('static/js/chart.js').read_text(encoding='utf-8')
core = (Path('core_config.py').read_text(encoding='utf-8') +
        Path('app_core.py').read_text(encoding='utf-8'))

# Phase 1 feature contracts
for token in ['handleHit(', 'nearestOHLC(', 'setPointerCapture', 'pointercancel',
              'toggleLock(', 'toggleHide(', 'duplicateSelected(', 'showAll(',
              'extendLeft', 'extendRight', 'dashed', 'dotted', 'MAGNET']:
    assert token in draw, token
assert 'bars: curBars' in chart
assert 'trx_drawings_v3' in draw  # backward-compatible storage key

# Strategy and staking contracts must remain unchanged
assert 'RSI_STRAT_OVERSOLD = 32.0' in core
assert 'RSI_STRAT_OVERBOUGHT = 68.0' in core
assert '[200, 400, 600, 1200]' in core
assert '[2500, 5000, 10000, 20000]' in core
assert '[40000, 80000, 160000, 320000]' in core
print('DRAWING V2 CONTRACT TESTS: ALL PASSED')
