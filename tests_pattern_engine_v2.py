from pathlib import Path
s=Path('static/js/chart.js').read_text()
for token in [
 'function patternMark(', 'function firstCloseBreak(', 'function breakoutOutcome(',
 'Pattern Engine v2', 'BO+RT↑', 'BO+RT↓', 'FB↓', 'FB↑',
 'const shoulderSym=', 'const spacingSym=', 'const confirmed=br>=0',
 'q>=55', 'MOM↑×', 'MOM↓×'
]: assert token in s, token
assert 'DT ▼' not in s[s.index('function detectPatterns'):s.index('Auto Support / Resistance v2')]
assert 'DB ▲' not in s[s.index('function detectPatterns'):s.index('Auto Support / Resistance v2')]
for f in ['decision.py','l1_capital.py','app_core.py','drawings_persistence.py']:
    assert Path(f).exists()
print('Pattern Engine v2 contract OK')
