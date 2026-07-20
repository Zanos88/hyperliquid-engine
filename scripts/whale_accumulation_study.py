#!/usr/bin/env python3
"""
Whale Accumulation → Forward Return Study
===========================================
Pre-registered 2026-07-20. See `research/output/whale_accumulation_results.json` for full data.

QUESTION: Does a whale-accumulation event (whale_alerts trigger='entry', delta_pct>0)
precede a measurable USD-price gain in the associated token, beyond a random-entry baseline?

METHOD (pre-registered before any return computation):
  1) EVENT: alert with trigger='entry', delta_pct>0, price_usd not null
  2) ENTRY PRICE: price_usd at alert time
  3) HOLDING WINDOW: 1h, 6h, 24h fixed forward
  4) EXIT PRICE: price_usd of the nearest alert whose timestamp >= entry_time + horizon
  5) BASELINE: random timestamps within each token's date range, same entry/exit logic
  6) SIGNIFICANCE: Welch's t-test + permutation test (10K reps), Bonferroni (3 horizons)
  7) EVENT DEDUP: events with same token, same±5min, same±1% price grouped → one trade
"""
import json, os, random, math, urllib.request, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────────────────
HORIZONS  = [3600, 21600, 86400]  # 1h, 6h, 24h
H_LABEL   = {3600:'1h', 21600:'6h', 86400:'24h'}
CACHE_DIR = '/opt/data/repos/btc-signal-bot/research/data/dexscreener_cache'
SEED      = 42
N_PERM    = 10_000
BASELINE_MULT = 20  # 20x per signal event → ~4000 baseline/horizon
API_DELAY = 0.1     # DexScreener rate limit (10/s)

# ── Data ────────────────────────────────────────────────────────────────────
def load_mirror(path):
    with open(path) as f:
        raw = f.read()
    if raw.startswith('{') and '"content"' in raw:
        raw = json.loads(raw)['content']
    return json.loads(raw)

def parse_ts(s):
    return datetime.fromisoformat(s.replace('Z','+00:00'))

# ── DexScreener (cached) ───────────────────────────────────────────────────
DS_CACHE = {}
def ds_fetch(addr):
    if addr in DS_CACHE:
        return DS_CACHE[addr]
    os.makedirs(CACHE_DIR, exist_ok=True)
    cp = os.path.join(CACHE_DIR, f"{addr}.json")
    if os.path.exists(cp):
        with open(cp) as f:
            data = json.load(f)
            DS_CACHE[addr] = data
            return data
    try:
        req = urllib.request.Request(
            f'https://api.dexscreener.com/latest/dex/tokens/{addr}',
            headers={'User-Agent': 'ResearchBot/1.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        with open(cp, 'w') as f:
            json.dump(data, f)
        time.sleep(API_DELAY)
        DS_CACHE[addr] = data
        return data
    except Exception as e:
        print(f"  DS error {addr[:12]}...: {e}")
        DS_CACHE[addr] = None
        return None

# ── Events ──────────────────────────────────────────────────────────────────
def de_alerts(alerts):
    """Sort alerts by token+time. Returns {addr: [sorted alerts]}."""
    by = defaultdict(list)
    for a in alerts:
        if a.get('token_address') and a.get('alerted_at'):
            by[a['token_address']].append(a)
    for k in by:
        by[k].sort(key=lambda x: x['alerted_at'])
    return dict(by)

def find_exit_price(alerts, start_idx, target_dt, max_forward_h=48):
    """Find first alert AT OR AFTER target_dt with a price. O(n) but each token scanned once."""
    for j in range(start_idx, len(alerts)):
        aj = alerts[j]
        if aj.get('price_usd') and aj['price_usd'] > 0:
            ajt = parse_ts(aj['alerted_at'])
            if ajt >= target_dt:
                return j, aj['price_usd'], ajt
            if ajt > target_dt + timedelta(hours=max_forward_h):
                break
    return None, None, None

def build_events(by_token):
    """Extract signal events and build the price index for baseline generation."""
    token_info = {}
    for addr, al in by_token.items():
        sym = al[0].get('token_symbol', addr[:8])
        # signal events: trigger=entry + delta>0 + price
        signals = []
        for i, a in enumerate(al):
            if (a.get('trigger') == 'entry' and a.get('delta_pct', 0) > 0
                and a.get('price_usd') and a['price_usd'] > 0):
                signals.append(i)
        if len(signals) < 3:
            print(f"  {sym}: skip — {len(signals)} signal events")
            continue

        # For each signal, compute forward returns at each horizon
        events = []
        for idx in signals:
            ea = al[idx]
            et = parse_ts(ea['alerted_at'])
            ep = ea['price_usd']
            for h in HORIZONS:
                target = et + timedelta(seconds=h)
                j, xp, xt = find_exit_price(al, idx+1, target)
                if xp is not None:
                    r = (xp / ep) - 1.0
                    events.append(dict(token=addr, symbol=sym,
                        entry_time=et.isoformat(), entry_price=ep,
                        exit_time=xt.isoformat(), exit_price=xp,
                        horizon=h, label=H_LABEL[h],
                        ret=r, actual_h=(xt-et).total_seconds()/3600))

        if events:
            token_info[addr] = dict(symbol=sym, alerts=al, events=events,
                signals=signals)
            print(f"  {sym}: {len(signals)} signals → {len(events)} event-x-horizon")
    return token_info

def deduplicate(events, window_min=5):
    """Group events for same token+horizon within window_min at same price."""
    if not events: return []
    events = sorted(events, key=lambda e: (e['token'], e['label'], e['entry_time']))
    deduped = []
    for e in events:
        if not deduped: deduped.append(e); continue
        p = deduped[-1]
        if (e['token'] == p['token'] and e['label'] == p['label']):
            dt_e = parse_ts(e['entry_time'])
            dt_p = parse_ts(p['entry_time'])
            gap = (dt_e - dt_p).total_seconds() / 60
            pr  = abs(e['entry_price'] - p['entry_price']) / max(e['entry_price'], p['entry_price'])
            if gap < window_min and pr < 0.01:
                deduped[-1] = e  # replace: keep last-in-cluster
                continue
        deduped.append(e)
    return deduped

# ── Baseline ────────────────────────────────────────────────────────────────
def gen_baseline(by_token, token_info):
    """Random timestamps per token, same exit logic. Batch for speed."""
    random.seed(SEED)
    random.seed(SEED)
    baseline = []
    for addr, al in by_token.items():
        if addr not in token_info:
            continue
        ti = token_info[addr]
        n_sig = len(ti['signals'])
        if n_sig < 2:
            continue
        n_bs = n_sig * BASELINE_MULT
        t0 = parse_ts(al[0]['alerted_at'])
        tN = parse_ts(al[-1]['alerted_at'])
        span = (tN - t0).total_seconds()
        if span <= 0: continue

        # Precompute all alert times and prices for fast lookup
        al_times = [parse_ts(a['alerted_at']) for a in al]
        al_prices = [a.get('price_usd') for a in al]

        for _ in range(n_bs):
            rt = t0 + timedelta(seconds=random.random() * span)
            # Find first alert ON OR AFTER rt with price
            entry_idx = -1
            for idx, (at, ap) in enumerate(zip(al_times, al_prices)):
                if at >= rt and ap and ap > 0:
                    entry_idx = idx
                    break
            if entry_idx < 0:
                continue
            ep = al_prices[entry_idx]
            et = al_times[entry_idx]
            # Same exit logic as signals
            for h in HORIZONS:
                target = et + timedelta(seconds=h)
                j = entry_idx + 1
                while j < len(al):
                    if al_prices[j] and al_prices[j] > 0 and al_times[j] >= target:
                        break
                    j += 1
                if j < len(al) and al_prices[j] and al_prices[j] > 0:
                    r = (al_prices[j] / ep) - 1.0
                    baseline.append(dict(token=addr, symbol=ti['symbol'],
                        entry_price=ep, exit_price=al_prices[j],
                        horizon=h, label=H_LABEL[h], ret=r))
    return baseline

# ── Stats ───────────────────────────────────────────────────────────────────
def betainc(a, b, x):
    """Regularized incomplete beta function I_x(a,b). Uses continued fraction."""
    # Lentz's method
    if x < 0 or x > 1: return 0
    if x == 0 or x == 1: return x
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # Continued fraction
    f, c, d = 1.0, 1.0, 1.0 - (a + b) * x / (a + 1)
    if abs(d) < 1e-30: d = 1e-30
    d = 1.0 / d
    f = d
    for m in range(1, 201):
        n = 2 * m
        alpha = m * (b - m) * x / ((a - 1 + n) * (a + n))
        d = 1.0 + alpha * d
        if abs(d) < 1e-30: d = 1e-30
        c = 1.0 + alpha / c
        if abs(c) < 1e-30: c = 1e-30
        d = 1.0 / d
        f *= d * c
        alpha = -(a + m) * (a + b + m) * x / ((a + n) * (a + 1 + n))
        d = 1.0 + alpha * d
        if abs(d) < 1e-30: d = 1e-30
        c = 1.0 + alpha / c
        if abs(c) < 1e-30: c = 1e-30
        d = 1.0 / d
        delta = d * c
        f *= delta
        if abs(delta - 1.0) < 1e-10: break
    return front * f

def t_cdf(t, df):
    """CDF of Student's t-distribution."""
    x = df / (t * t + df)
    p = 0.5 * betainc(df / 2, 0.5, x)
    return 1 - p if t >= 0 else p

def welch(a, b):
    """Welch t-test. Returns (t, df, p_value)."""
    n1, n2 = len(a), len(b)
    m1 = sum(a)/n1 if n1 else 0
    m2 = sum(b)/n2 if n2 else 0
    v1 = sum((x-m1)**2 for x in a)/(n1-1) if n1>1 else 0
    v2 = sum((x-m2)**2 for x in b)/(n2-1) if n2>1 else 0
    se = math.sqrt(v1/n1 + v2/n2) if (v1/n1+v2/n2)>0 else 0.0001
    t = (m1 - m2) / se
    num = (v1/n1 + v2/n2)**2
    den = (v1/n1)**2/(n1-1) + (v2/n2)**2/(n2-1)
    df = num/den if den>0 else 1
    p = t_cdf(-abs(t), df) * 2  # two-tailed
    return t, df, p

def permutation_test(a, b, n_perm=10000):
    """One-sided permutation test: mean(a) > mean(b)."""
    import random
    random.seed(SEED)
    pooled = list(a) + list(b)
    na = len(a)
    obs = sum(a)/na - sum(b)/len(b)
    extreme = 0
    for _ in range(n_perm):
        random.shuffle(pooled)
        pa = sum(pooled[:na])/na
        pb = sum(pooled[na:])/len(b)
        if (pa - pb) >= obs:
            extreme += 1
    return (extreme + 1) / (n_perm + 1)

def cohens_d(a, b):
    n1, n2 = len(a), len(b)
    m1 = sum(a)/n1; m2 = sum(b)/n2
    v1 = sum((x-m1)**2 for x in a)/(n1-1) if n1>1 else 0
    v2 = sum((x-m2)**2 for x in b)/(n2-1) if n2>1 else 0
    sp = math.sqrt(((n1-1)*v1 + (n2-1)*v2) / (n1+n2-2))
    return (m1-m2)/sp if sp>0 else 0

def ci_mean_diff(a, b):
    n1, n2 = len(a), len(b)
    m1, m2 = sum(a)/n1, sum(b)/n2
    v1 = sum((x-m1)**2 for x in a)/(n1-1) if n1>1 else 0
    v2 = sum((x-m2)**2 for x in b)/(n2-1) if n2>1 else 0
    se = math.sqrt(v1/n1 + v2/n2)
    d = m1 - m2
    return d - 1.96*se, d + 1.96*se

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("  WHALE ACCUMULATION → FORWARD RETURN STUDY")
    print("  Pre-registered: 2026-07-20")
    print("=" * 70)

    # 1. Load
    print("\n[1] Loading data...")
    wa = load_mirror('/opt/data/mirror-bullphoric/whale_alerts.json')
    dt = load_mirror('/opt/data/mirror-bullphoric/discovered_tokens.json')
    dt_map = {t['token_address']:t for t in dt if 'token_address' in t}
    wt_set = set(a.get('token_address') for a in wa if a.get('token_address'))
    overlap = wt_set & set(dt_map.keys())
    print(f"  whale_alerts: {len(wa)} rows, {len(wt_set)} tokens")
    print(f"  discovered_tokens: {len(dt)} rows, {len(dt_map)} tokens")
    print(f"  Join (token_address): {len(overlap)} events — {'ZERO' if not overlap else 'OK'}")

    # 2. Signal events
    print("\n[2] Extracting whale-accumulation events...")
    by_token = de_alerts(wa)
    token_info = build_events(by_token)

    # 3. Baseline
    print("\n[3] Generating random-entry baseline...")
    baseline = gen_baseline(by_token, token_info)

    # 4. Analysis per horizon
    print("\n[4] Analysis")
    results = {}
    for h in HORIZONS:
        lbl = H_LABEL[h]
        # Signal
        sig_raw = [e for ti in token_info.values() for e in ti['events'] if e['horizon'] == h]
        sig     = [e['ret'] for e in sig_raw]
        sig_deduped = deduplicate(sig_raw, window_min=5)
        sig_dv      = [e['ret'] for e in sig_deduped]
        # Baseline
        bs = [e['ret'] for e in baseline if e['horizon'] == h]

        print(f"\n  ── {lbl} ──")
        print(f"  Raw signal events: {len(sig)}")
        print(f"  Deduped signals:   {len(sig_dv)}")
        print(f"  Baseline events:   {len(bs)}")

        if len(sig_dv) < 10:
            print(f"  ⚠ Insufficient events. Skip.")
            results[lbl] = {'status':'insufficient','n_raw':len(sig),'n_deduped':len(sig_dv)}
            continue

        # Per-token breakdown
        by_sym = defaultdict(list)
        for e in sig_deduped:
            by_sym[e['symbol']].append(e['ret'])

        # Stats: signal vs baseline (use deduped signal)
        m_s = sum(sig_dv)/len(sig_dv)
        m_b = sum(bs)/len(bs)
        t_st, df_st, p_welch = welch(sig_dv, bs)
        p_perm = permutation_test(sig_dv, bs, N_PERM)
        d = cohens_d(sig_dv, bs)
        cil, cih = ci_mean_diff(sig_dv, bs)
        wr_s = sum(1 for r in sig_dv if r>0)/len(sig_dv)
        wr_b = sum(1 for r in bs if r>0)/len(bs)
        bonf = 0.05 / len(HORIZONS)

        print(f"  Signal mean ret: {m_s*100:+.2f}%")
        print(f"  Baseline mean ret: {m_b*100:+.2f}%")
        print(f"  Δ = {(m_s-m_b)*100:+.2f}%  [{cil*100:+.2f}%, {cih*100:+.2f}%]")
        print(f"  Cohen's d = {d:.3f}")
        print(f"  Welch t({df_st:.1f}) = {t_st:.3f}, p={p_welch:.4f}")
        print(f"  Permutation p = {p_perm:.4f}  (Bonf α = {bonf:.4f})")
        print(f"  Significant? {'YES ✓' if p_perm < bonf else 'NO ✗'}")
        print(f"  Win rate: {wr_s*100:.0f}% signal vs {wr_b*100:.0f}% baseline")
        print(f"\n  Per token (deduped):")
        for sym, rv in sorted(by_sym.items()):
            m = sum(rv)/len(rv)
            w = sum(1 for r in rv if r>0)/len(rv)
            print(f"    {sym}: {len(rv)} events, mean={m*100:+.2f}%, win={w*100:.0f}%")

        results[lbl] = dict(status='complete',
            n_raw=len(sig), n_deduped=len(sig_dv), n_baseline=len(bs),
            signal_mean=m_s, baseline_mean=m_b, signal_std=math.sqrt(sum((x-m_s)**2 for x in sig_dv)/(len(sig_dv)-1)) if len(sig_dv)>1 else 0,
            baseline_std=math.sqrt(sum((x-m_b)**2 for x in bs)/(len(bs)-1)) if len(bs)>1 else 0,
            mean_diff=m_s-m_b, ci_95=[cil, cih],
            cohens_d=d, welch_t=t_st, welch_df=df_st, welch_p=p_welch,
            perm_p=p_perm, bonf_alpha=bonf, significant=p_perm < bonf,
            signal_win_rate=wr_s, baseline_win_rate=wr_b,
            token_breakdown={sym:{'n':len(rv),'mean':sum(rv)/len(rv),'win':sum(1 for r in rv if r>0)/len(rv)} for sym,rv in by_sym.items()})

    # 5. DexScreener current state
    print("\n[5] DexScreener current data...")
    ds_whale = {addr: ds_fetch(addr) for addr in wt_set}
    # Sample discovered_tokens
    dt_addrs = list(set(t['token_address'] for t in dt[:200] if 'token_address' in t))
    ds_dt = {}
    for i, addr in enumerate(dt_addrs[:30]):
        if i % 10 == 0: print(f"  DS discovered_tokens: {i}/30")
        ds_dt[addr] = ds_fetch(addr)

    # Print DS summary
    print("\n  Whale tokens current state:")
    for addr, dd in ds_whale.items():
        if dd and dd.get('pairs'):
            p = dd['pairs'][0]
            print(f"    {addr[:12]}...: ${p.get('priceUsd','N/A')}, 24hΔ={p.get('priceChange',{}).get('h24','N/A')}%, "
                  f"liq=${p.get('liquidity',{}).get('usd',0)}, fdv={p.get('fdv','N/A')}")
        else:
            sym = next((ti['symbol'] for ad,ti in token_info.items() if ad==addr), addr[:12])
            print(f"    {sym} ({addr[:12]}...): no pairs on DexScreener")

    # DS stats for discovered_tokens sample
    ds_stats = []
    for addr, dd in ds_dt.items():
        if dd and dd.get('pairs'):
            p = dd['pairs'][0]
            ds_stats.append(float(p.get('priceChange',{}).get('h24',0) or 0))
    if ds_stats:
        print(f"\n  Discovered_tokens sample (n={len(ds_stats)}):")
        print(f"    Mean 24h Δ: {sum(ds_stats)/len(ds_stats):+.2f}%")
        print(f"    Tokens with pairs: {len(ds_stats)}/{len(ds_dt)}")

    # ── Output ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  FINAL RESULTS")
    print("=" * 70)
    for lbl, r in sorted(results.items()):
        if r.get('status') != 'complete':
            print(f"\n  {lbl}: INSUFFICIENT — {r.get('n_deduped',0)} events")
            continue
        print(f"\n  ── {lbl} ──")
        print(f"  Events: {r['n_deduped']} signal (from {r['n_raw']} raw) vs {r['n_baseline']} baseline")
        print(f"  Signal:   {r['signal_mean']*100:+7.2f}% ± {r['signal_std']*100:.2f}%   win={r['signal_win_rate']*100:.0f}%")
        print(f"  Baseline: {r['baseline_mean']*100:+7.2f}% ± {r['baseline_std']*100:.2f}%   win={r['baseline_win_rate']*100:.0f}%")
        sig = "SIGNIFICANT ✓" if r['significant'] else "NOT SIGNIFICANT ✗"
        print(f"  Δ = {r['mean_diff']*100:+7.2f}%  CI95=[{r['ci_95'][0]*100:+.2f}%,{r['ci_95'][1]*100:+.2f}%]")
        print(f"  d = {r['cohens_d']:.3f}  |  welch t = {r['welch_t']:.3f}  |  perm p = {r['perm_p']:.4f}")
        print(f"  → {sig} (α_Bonf={r['bonf_alpha']:.4f})")

    # Save
    print("\n[6] Saving results...")
    out = dict(
        metadata=dict(
            study='Whale Accumulation → Forward Return',
            preregistered='2026-07-20',
            source_whale='/opt/data/mirror-bullphoric/whale_alerts.json',
            source_tokens='/opt/data/mirror-bullphoric/discovered_tokens.json',
            whale_tokens=len(wt_set), discovered_tokens=len(dt_map),
            token_overlap=len(overlap), n_permutations=N_PERM,
            baseline_multiplier=BASELINE_MULT, horizons_tested=[H_LABEL[h] for h in HORIZONS]),
        caveats=[
            "whale_alerts capped at 1000 rows (PostgREST server-side limit); recent-window sample.",
            "filter_rejections table EMPTY — all tokens passed bot filter; survivorship bias.",
            "DexScreener gives current/recent pair data, not historical OHLCV. Forward returns measured from alert-to-alert prices (irregular sampling).",
            "Only 4 unique tokens; results heavily token-idiosyncratic (ANSEM drives most signal)."],
        results={},
        dexscreener={})
    for lbl, r in results.items():
        out['results'][lbl] = {k:v for k,v in r.items() if k not in ('__all__',)}
    # DexScreener summary
    for addr, dd in ds_whale.items():
        if dd and dd.get('pairs'):
            p = dd['pairs'][0]
            out['dexscreener'][addr] = {
                'price_usd': p.get('priceUsd'),
                'change_24h': p.get('priceChange',{}).get('h24'),
                'liquidity_usd': p.get('liquidity',{}).get('usd'),
                'fdv': p.get('fdv')}
    op = '/opt/data/repos/btc-signal-bot/research/output/whale_accumulation_results.json'
    os.makedirs(os.path.dirname(op), exist_ok=True)
    with open(op, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  → {op}")

if __name__ == '__main__':
    main()
