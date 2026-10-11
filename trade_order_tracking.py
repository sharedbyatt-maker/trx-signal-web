"""Only explicit provider receipts can associate a local order with a result."""
import re


def receipt(payload):
    result = {}
    sources = [payload]
    for key in ('data', 'order'):
        if isinstance(payload.get(key), dict):
            sources.append(payload[key])
    for key in ('orderId', 'orderNumber'):
        values = {str(source[key]) for source in sources if type(source.get(key)) in (str, int)
                  and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', str(source[key]))}
        if len(values) > 1:
            return {}
        if values:
            result['provider_id'] = values.pop()
            break
    if 'provider_id' not in result and isinstance(payload.get('order'), dict):
        value = payload['order'].get('id')
        if type(value) in (str, int) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', str(value)):
            result['provider_id'] = str(value)
    for source in sources:
        value = source.get('issueNumber')
        if type(value) in (str, int) and re.fullmatch(r'\d{17}', str(value), re.ASCII):
            if result.get('issue') not in (None, str(value)):
                return {}
            result['issue'] = str(value)
    return result


def result_for(order, rows):
    if order['outcome'] not in ('accepted', 'unknown', 'pending'):
        return None, None
    real = [row for row in rows if row['mode'] == 'real']
    if order.get('provider_id'):
        found = [row for row in real if row.get('external_id') == order['provider_id']]
        if len(found) == 1:
            row = found[0]
            if row['side'] == order['side'] and row['stake_minor'] == order['stake'] * 100:
                return row, 'order_id'
        return None, None
    # A confirmed receipt's round + side determines WIN/LOSS, but does not
    # establish this order's payout. Never infer a round from local clock/time.
    if order['outcome'] == 'accepted' and order.get('issue'):
        found = [row for row in real if row['issue'] == order['issue'] and row['side'] == order['side'] and row['state'] in (0, 1)]
        if found and len({row['state'] for row in found}) == 1:
            return found[0], 'round'
    return None, None
