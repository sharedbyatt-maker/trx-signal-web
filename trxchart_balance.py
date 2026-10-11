"""Extract only an explicit REAL account balance; never derive it from history."""
import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

BALANCE_KEYS = ('real_balance', 'realBalance', 'userBalance', 'accountBalance',
                'walletBalance', 'availableBalance', 'balance')
BALANCE_IDS = {'realbalance', 'balance', 'userbalance', 'accountbalance',
               'walletbalance', 'availablebalance', 'balanceamount', 'walletamount', 'bal', 'betbalanceval'}


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip().replace('\u00a0', ' ')
    text = re.sub(r'^(?:(?:real\s+)?(?:account\s+)?balance|wallet)\s*:?\s*', '', text, flags=re.I)
    text = re.sub(r'^(?:MMK|Ks)\s*|\s*(?:MMK|Ks)$', '', text, flags=re.I).strip()
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', text):
        return None
    try:
        number = Decimal(text.replace(',', ''))
        if not number.is_finite() or not 0 <= number <= Decimal('90071992547409.91'):
            return None
        return format(number.quantize(Decimal('0.01')), 'f')
    except InvalidOperation:
        return None


def from_json(value):
    if not isinstance(value, dict) or value.get('mode') == 'demo' or value.get('logged_out'):
        return None
    for key in BALANCE_KEYS:
        if key in value:
            parsed = amount(value[key])
            if parsed is not None:
                return parsed
    for key in ('account', 'user', 'wallet', 'data'):
        nested = value.get(key)
        if isinstance(nested, dict) and nested is not value:
            parsed = from_json(nested)
            if parsed is not None:
                return parsed
    return None


class BalanceHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.values = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        label = ' '.join(str(attrs.get(k) or '') for k in ('id', 'class', 'data-mode', 'aria-label')).lower()
        demo = any(x['demo'] for x in self.stack) or bool(re.search(r'demo|virtual|simulation', label))
        identity = re.sub(r'[^a-z]', '', str(attrs.get('id') or '').lower())
        match = not demo and identity in BALANCE_IDS
        if not demo:
            for key in ('data-real-balance', 'data-account-balance', 'data-wallet-balance', 'data-balance'):
                if key in attrs:
                    parsed = amount(attrs[key])
                    if parsed is not None:
                        self.values.append(parsed)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append({'tag': tag, 'demo': demo, 'match': match,
                               'json': tag == 'script' and attrs.get('type') == 'application/json' and not demo, 'parts': []})

    def handle_data(self, text):
        for node in self.stack:
            if node['match'] or node['json']:
                node['parts'].append(text)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['tag'] != tag:
                continue
            for node in self.stack[index:]:
                text = ''.join(node['parts']).strip()
                parsed = amount(text) if node['match'] else None
                if node['json']:
                    try:
                        parsed = from_json(json.loads(text))
                    except (ValueError, RecursionError):
                        parsed = None
                if parsed is not None:
                    self.values.append(parsed)
            del self.stack[index:]
            break


def from_page(page):
    parser = BalanceHTML()
    parser.feed(page)
    values = set(parser.values)
    # Literal initial account fields are accepted; JavaScript is never executed.
    for found in re.finditer(r'\b(?:const|let|var)\s+(?:_BALANCE|_BAL|realBalance|userBalance|initialBalance)\s*=\s*[\'\"]?(\d+(?:\.\d{1,2})?)(?=[\'\";\s,])', page):
        parsed = amount(found[1])
        if parsed is not None:
            values.add(parsed)
    # Conflicting values are unavailable rather than a guess about which wallet.
    return next(iter(values)) if len(values) == 1 else None
