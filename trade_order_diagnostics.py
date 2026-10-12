"""Fixed, non-sensitive order diagnostics; never expose provider response text."""

REASONS = {
    'invalid_request': 'The provider refused the request parameters or trading rules. The exact reason is unavailable.',
    'invalid_direction': 'The provider reported an invalid direction. The order API contract needs checking.',
    'invalid_amount': 'The provider reported an invalid amount. Check its permitted stake size.',
    'insufficient_balance': 'The provider reported insufficient REAL balance.',
    'round_closed': 'The provider reported that betting for this round is closed.',
    'duplicate_order': 'The provider reported an existing or duplicate order. Check REAL history.',
    'session_expired': 'The provider refused the account session or API token. Reconnect the account.',
    'permission_denied': 'The provider refused order access. A working history connection does not prove order permission.',
    'rate_limited': 'The provider rate limit was reached. Wait and check REAL history.',
    'provider_conflict': 'The provider reported a conflict. Check REAL history and the current round.',
    'endpoint_unavailable': 'The provider order endpoint was not found. The order API contract needs checking.',
    'provider_rejected': 'The provider rejected the order without a recognized reason.',
}

# Exact recognized phrases/codes only. Untrusted response strings are discarded.
ALIASES = {
    'invalid_direction': ('invalid direction', 'direction must be big or small'),
    'invalid_amount': ('invalid amount', 'amount must be a positive integer'),
    'insufficient_balance': ('insufficient balance', 'insufficient funds', 'not enough balance'),
    'round_closed': ('round closed', 'betting closed', 'betting is closed', 'betting time is over'),
    'duplicate_order': ('duplicate bet', 'order already exists', 'already bet this round'),
    'session_expired': ('invalid token', 'invalid api token', 'token expired', 'session expired', 'unauthorized'),
    'permission_denied': ('permission denied', 'forbidden'),
    'rate_limited': ('rate limited', 'too many requests'),
}
LOOKUP = {phrase: code for code, phrases in ALIASES.items() for phrase in (code, *phrases)}


def reason_for(status, data=None):
    if status == 401 or type(status) is int and 300 <= status < 400:
        return 'session_expired'
    if status == 403:
        default = 'permission_denied'
    elif status == 429:
        return 'rate_limited'
    else:
        default = {400: 'invalid_request', 422: 'invalid_request', 404: 'endpoint_unavailable',
                   409: 'provider_conflict'}.get(status, 'provider_rejected')
    if isinstance(data, dict):
        values = [data.get(key) for key in ('code', 'error', 'message', 'msg')]
        if isinstance(data.get('error'), dict):
            values.extend(data['error'].get(key) for key in ('code', 'message'))
        codes = {LOOKUP[v.strip().casefold()] for v in values
                 if isinstance(v, str) and len(v) <= 160 and v.strip().casefold() in LOOKUP}
        if len(codes) == 1:
            return codes.pop()
    return default


def diagnosis(outcome, status, reason=None):
    if outcome != 'rejected':
        return None, None
    code = reason if reason in REASONS else reason_for(status)
    http = f' (HTTP {status})' if type(status) is int and 100 <= status <= 599 else ''
    return code, 'TRXChart rejected the order' + http + '. ' + REASONS[code] + ' This request will not be resent.'
