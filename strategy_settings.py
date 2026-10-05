"""Money-only configuration. Entry rules, payout and 3x4 structure remain frozen."""
import copy
import math
from bisect import bisect_left
from decimal import Decimal, ROUND_HALF_UP
from core_config import STAKE_TIERS, START_BANKROLL

MULTIPLIERS = [[1,2,3,6],[12.5,25,50,100],[200,400,800,1600]]
MONEY_DEFAULTS = {
 'l1': {'bankroll':100000,'base':500,'tp':5000,'sl':50000,'multipliers':MULTIPLIERS,'withdrawal':50000},
 'twelve': {'bankroll':START_BANKROLL,'base':STAKE_TIERS[0][0],'tp':0,'sl':0,'multipliers':MULTIPLIERS},
}
STRATEGY_INFO = {
 'l1': {'name':'L1 CAPITAL','description':'RSI confirmation with frozen skip rules. Three tiers of four steps. Manual signals continue after TP / SL; the risk banner switches to observe only.',
        'rules':['RSI period 14 · Oversold 32 · Overbought 68','Previous RSI ≤32 + BIG confirmation → BIG; ≥68 + SMALL → SMALL',
                 'R02: RSI bucket 70–79 at step 1 → skip 3 rounds','R03: RSI rising at step 2 → skip 2 rounds',
                 'R05: RSI falling at step 1 → skip 3 rounds','R06: RSI rising at step 1 → skip 1 round',
                 'Win → Tier 1 reset; tier failure → next tier with a fresh signal; 12-step bust → reset','Payout 1.96 · 12 steps · No automatic betting']},
 'twelve': {'name':'12-STEP','description':'RSI confirmation with a three-tier, four-step ladder. Losses advance the current ladder; tier failure waits for a fresh signal. Money limits are manual risk guidance and never change signal rules.',
            'rules':['RSI period 14 · Oversold 32 · Overbought 68','Previous RSI ≤32 + BIG confirmation → BIG; ≥68 + SMALL → SMALL',
                     'Step loss → next step; win → Tier 1 / Step 1 reset','Four losses in a tier → pause until the next valid signal',
                     'Tier 3 failure → reset Tier 1 / Step 1','Payout 1.96 · 12 steps · No automatic betting',
                     'Original 12-Step has no dedicated TP / SL limit; default 0 leaves each limit disabled']},
}

def validate_money(engine, value):
    if engine not in MONEY_DEFAULTS or not isinstance(value,dict) or set(value)!=set(MONEY_DEFAULTS[engine]):
        raise ValueError('Only money fields can be changed. Strategy rules are read only.')
    for key in ('bankroll','base','tp','sl') + (('withdrawal',) if engine=='l1' else ()):
        minimum=0 if key in ('tp','sl') else 1
        if type(value[key]) is not int or not minimum<=value[key]<=1000000000:
            raise ValueError(key+' must be a whole MMK amount within the supported range.')
    if value['base']>value['bankroll']:
        raise ValueError('Base bet cannot exceed bankroll.')
    if value['sl']>value['bankroll']:
        raise ValueError('Stop loss cannot exceed bankroll; 0 disables the limit.')
    matrix=value['multipliers']
    if not isinstance(matrix,list) or len(matrix)!=3 or any(not isinstance(row,list) or len(row)!=4 for row in matrix):
        raise ValueError('Keep exactly three tiers and four steps.')
    flat=[x for row in matrix for x in row]
    if any(type(x) not in (int,float) or not math.isfinite(x) or not 1<=x<=10000 or round(x,4)!=x for x in flat):
        raise ValueError('Multipliers must be finite numbers from 1 to 10000, with at most four decimals.')
    if flat[0]!=1 or any(a>b for a,b in zip(flat,flat[1:])):
        raise ValueError('Step 1 must be 1× base. The ladder must not decrease.')
    if any(stake(value,t,s)>1000000000 for t in range(3) for s in range(4)):
        raise ValueError('A ladder stake exceeds the supported MMK limit.')
    return copy.deepcopy(value)

def stake(money,tier,step):
    return int((Decimal(str(money['base']))*Decimal(str(money['multipliers'][tier][step]))).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def ladder(money):
    return [[stake(money,t,s) for s in range(4)] for t in range(3)]

class MoneySchedule:
    def __init__(self,engine,changes=()):
        self.default=copy.deepcopy(MONEY_DEFAULTS[engine])
        by_issue={}
        for change in changes:
            by_issue[int(change['after_issue'])]=change['settings']
        self.boundaries=sorted(by_issue)
        self.values=[by_issue[i] for i in self.boundaries]
        self.ladders=[ladder(v) for v in self.values]
        self.default_ladder=ladder(self.default)
    def at(self,source_issue):
        i=bisect_left(self.boundaries,int(source_issue))-1
        return self.values[i] if i>=0 else self.default

    def ladder_at(self,source_issue):
        i=bisect_left(self.boundaries,int(source_issue))-1
        return self.ladders[i] if i>=0 else self.default_ladder

def risk_status(money,pnl,pending_stake=0):
    if money['tp'] and pnl>=money['tp']:return 'OBSERVE ONLY — DAILY TP REACHED'
    if money['sl'] and pnl<=-money['sl']:return 'OBSERVE ONLY — DAILY SL REACHED'
    if money['bankroll']+pnl<=0:return 'OBSERVE ONLY — BANKROLL EXHAUSTED'
    if pending_stake>max(0,money['bankroll']+pnl):return 'OBSERVE ONLY — STAKE EXCEEDS AVAILABLE BANKROLL'
    return 'TRADE ALLOWED'
