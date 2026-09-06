from pathlib import Path


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"patch anchor missing: {label}")
    return text.replace(old, new, 1)


p = Path("app_core.py")
s = p.read_text(encoding="utf-8")

s = replace_once(s,
'''        new_file = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
''',
'''        new_file = (not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
''', "empty trade log header")

s = replace_once(s,
'''def append_signal_history(entry):
    new_file = not os.path.exists(HIST_FILE)
    try:
''',
'''def append_signal_history(entry):
    try:
        new_file = (not os.path.exists(HIST_FILE) or os.path.getsize(HIST_FILE) == 0)
''', "empty signal history header")

s = replace_once(s,
'''        if raw_issue and num_val is not None and raw_issue not in seen:
            try:
                num = int(num_val)
                seen.add(raw_issue)
''',
'''        if raw_issue and raw_issue.isdigit() and num_val is not None and raw_issue not in seen:
            try:
                num = int(num_val)
                if num < 0 or num > 9:
                    continue
                seen.add(raw_issue)
''', "history validation")

anchor = '''def trim_full_history(rows, days=FULL_HISTORY_DAYS):
'''
helper = '''def newest_raw_slice(data_list, limit=MAX_FULL_ROWS):
    """Keep the newest raw rounds regardless of upstream ascending/descending order."""
    rows = list(data_list or [])
    if len(rows) <= limit:
        return rows

    def issue_num(item):
        if not isinstance(item, dict):
            return None
        raw = str(item.get("issueNumber") or item.get("issue") or "")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    first = issue_num(rows[0])
    last = issue_num(rows[-1])
    if first is not None and last is not None and first > last:
        return rows[:limit]
    return rows[-limit:]


def issue_relation(completed_issue, target_issue):
    """Compare completed issue with target: exact / before / after / mismatch."""
    current = str(completed_issue or "")
    target = str(target_issue or "")
    if current and target and current == target:
        return "exact"
    try:
        a, b = int(current), int(target)
        if a == b:
            return "exact"
        return "before" if a < b else "after"
    except (TypeError, ValueError):
        return "mismatch"


''' + anchor
s = replace_once(s, anchor, helper, "history helpers")

s = replace_once(s,
'''                if not have_full and len(data_list) > MAX_FULL_ROWS:
                    data_list = data_list[-MAX_FULL_ROWS:]
                parsed = parse_history(data_list)
''',
'''                if not have_full and len(data_list) > MAX_FULL_ROWS:
                    data_list = newest_raw_slice(data_list, MAX_FULL_ROWS)
                parsed = parse_history(data_list)
                if not have_full and len(parsed) > MAX_FULL_ROWS:
                    parsed = parsed[-MAX_FULL_ROWS:]
''', "order-independent full snapshot")

s = replace_once(s,
'''def resolve_pending(latest):
    global pending, units, lose_streak, cooldown
    if pending and pending["issue"] == latest["issue"]:
        win = latest["type"] == pending["signal"]
''',
'''def resolve_pending(latest):
    global pending, units, lose_streak, cooldown
    relation = issue_relation(latest.get("issue"), (pending or {}).get("issue")) if pending else None
    if pending and relation == "exact":
        win = latest["type"] == pending["signal"]
''', "pending exact target relation")

s = replace_once(s,
'''        pending = None
    elif cooldown > 0:
        cooldown -= 1


def engine_loop():
''',
'''        pending = None
    elif pending and relation in ("after", "mismatch"):
        missed = pending.get("issue")
        print(f"[ENGINE] pending target {missed} missed; resynced without settlement", flush=True)
        pending = None
    elif pending and relation == "before":
        return
    elif cooldown > 0:
        cooldown -= 1


def reconcile_strat_pending_issue(latest):
    """Allow 12-step settlement only on the exact armed issue; gaps are financially inert."""
    global strat_pending
    if strat_pending is None:
        return False
    relation = issue_relation(latest.get("issue"), strat_pending.get("issue"))
    if relation == "exact":
        return True
    if relation in ("after", "mismatch"):
        missed = strat_pending.get("issue")
        strat_state["pending"] = None
        strat_state["last_result"] = f"MISSED TARGET {missed} — resynced without settlement"
        strat_pending = None
        print(f"[STAKE] pending target {missed} missed; resynced without result", flush=True)
    return False


def engine_loop():
''', "pending gap and strat reconciler")

s = replace_once(s,
'''                        if unresolved_signal and unresolved_signal["issue"] == latest["issue"]:
                            traded = unresolved_signal["signal"] in ("BIG", "SMALL")
''',
'''                        if unresolved_signal:
                            relation = issue_relation(latest["issue"], unresolved_signal.get("issue"))
                            if relation in ("after", "mismatch"):
                                unresolved_signal["result_number"] = None
                                unresolved_signal["result_type"] = None
                                unresolved_signal["outcome"] = "MISSED"
                                append_signal_history(unresolved_signal)
                                unresolved_signal = None
                        if unresolved_signal and issue_relation(latest["issue"], unresolved_signal.get("issue")) == "exact":
                            traded = unresolved_signal["signal"] in ("BIG", "SMALL")
''', "unresolved signal gap")

s = replace_once(s,
'''                        if strat_pending is not None:
                            sp = strat_pending
''',
'''                        if reconcile_strat_pending_issue(latest):
                            sp = strat_pending
''', "12-step exact target settlement")

s = replace_once(s,
'''        rows = parse_history(res.json())
        if not rows:
''',
'''        payload = res.json()
        raw = payload if isinstance(payload, list) else (payload.get("data", []) if isinstance(payload, dict) else [])
        rows = parse_history(raw)
        if not rows:
''', "rsi extremes wrapped response")

p.write_text(s, encoding="utf-8")

p = Path("robust_audit.py")
s = p.read_text(encoding="utf-8")
s = replace_once(s,
'''    history = normalize_history(rows)
    history.sort(key=lambda x: int(x["issue"]) if x["issue"].isdigit() else x["issue"])
    return history
''',
'''    history = normalize_history(rows)
    history.sort(key=lambda x: (0, int(x["issue"])) if str(x["issue"]).isdigit() else (1, str(x["issue"])))
    return history
''', "robust audit mixed-key sort")
p.write_text(s, encoding="utf-8")
