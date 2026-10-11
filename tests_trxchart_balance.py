"""Balance fixtures have no credentials or live provider requests."""
import pytest
from trxchart_balance import amount, from_json, from_page


@pytest.mark.parametrize('raw,want', [(0, '0.00'), ('12,500.50 MMK', '12500.50'),
    ('Ks 100', '100.00'), ('Real account balance: 120.2', '120.20')])
def test_exact_amount(raw, want):
    assert amount(raw) == want


@pytest.mark.parametrize('raw', [True, -1, 'NaN', 'Infinity', '12,50', '1.234',
    {'balance': 1}, 'Profit: 120', '1e3', '90071992547409.92'])
def test_invalid_amount_is_unavailable(raw):
    assert amount(raw) is None


def test_page_extracts_real_wallet_without_demo_or_history_totals():
    page = '<section class="demo"><span id="balance">9999</span></section><span id="real-balance">12,500.50 MMK</span><div id="profit">96</div>'
    assert from_page(page) == '12500.50'
    assert from_page('<div id="profit">96</div><div>Total stakes: 5900</div>') is None
    assert from_page('<div id="balance">10</div><span id="walletBalance">20</span>') is None
    assert from_page('<span id="real-balance">0 MMK</span>') == '0.00'
    assert from_page('<span id="betBalanceVal" class="bet-balance-val">101,471.65 MMK</span>') == '101471.65'


def test_json_and_literal_fields_are_read_without_executing_scripts():
    assert from_json({'data': {'wallet': {'balance': '12500.50'}}}) == '12500.50'
    assert from_json({'mode': 'demo', 'balance': 9999}) is None
    assert from_json({'logged_out': True, 'balance': 120}) is None
    assert from_page('<script type="application/json">{"account":{"realBalance":120}}</script>') == '120.00'
    assert from_page('<script>const _BALANCE = 120.50; throw new Error("never execute");</script>') == '120.50'
